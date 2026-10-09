"""API-assisted editorial reranking and whole-script source reservation.

The wrapped local search remains authoritative for evidence and media policy.
This layer may only prefer/reorder already-legal candidates.  On the first
rough-cut query for a script it prefetches sentence-level local candidates,
optionally sends the complete candidate snapshot through one API rerank call,
and then runs deterministic global source assignment.  This avoids the classic
greedy failure where an early generic sentence consumes the only S evidence
needed by a later sentence.

It also owns sparse per-segment generic b-roll overrides. A single clean empty
shot inside a normal source video can therefore be used as ``generic`` without
reclassifying the entire video.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any
from uuid import UUID

from clipatlas.catalog.segment_roles import SegmentFallbackRoleStore
from clipatlas.director.requirements import parse_script_visual_requirements
from clipatlas.director.reranker import CandidateReranker, RerankCandidate
from clipatlas.domain.models import AnnotationOrigin, SemanticAnnotation
from clipatlas.domain.visual_protocol import normalize_match_level
from clipatlas.retrieval.local_rough_cut import LocalRoughCutHit
from clipatlas.roughcut.global_assignment import AssignmentCandidate, assign_requirements


_LEVEL_RANK = {
    "DIRECT": 0,
    "SUPPORT": 1,
    "RELATED": 2,
    "GENERIC": 3,
    "SOURCE": 4,
    "REUSE": 5,
    "UNKNOWN": 6,
}
_IMPORTANCE_RANK = {"B": 0, "A": 1, "S": 2}


class RerankedRoughCutSearch:
    def __init__(self, search: Any, *, reranker: CandidateReranker | None = None) -> None:
        self._inner = search
        self._reranker = reranker
        self._rank_cache: dict[str, list[str]] = {}
        # script/scope hash -> aliases(sentence_id and exact sentence text) ->
        # (video_id, start_ms, end_ms).  The cache is process-local on purpose;
        # the permanent catalog remains the source of truth.
        self._global_reservation_cache: dict[
            str, dict[str, tuple[UUID, int, int]]
        ] = {}
        catalog = getattr(search, "_catalog", None)
        self._segment_roles = SegmentFallbackRoleStore(catalog) if catalog is not None else None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def set_segment_fallback_role(self, segment_id: UUID, role: str) -> None:
        """Explicitly mark one source segment as normal/generic/never."""
        if self._segment_roles is None:
            raise RuntimeError("segment fallback roles require a local catalog")
        self._segment_roles.set_role(segment_id, role)  # type: ignore[arg-type]

    async def search(
        self,
        query: str,
        limit: int = 12,
        video_ids: list[UUID] | None = None,
    ) -> list[Any]:
        return await self.search_with_context(
            query, context=None, limit=limit, video_ids=video_ids,
        )

    async def search_with_context(
        self,
        query: str,
        *,
        context: dict[str, object] | None = None,
        limit: int = 12,
        video_ids: list[UUID] | None = None,
    ) -> list[Any]:
        hits = await self._inner.search_with_context(
            query, context=context, limit=limit, video_ids=video_ids,
        )
        context_dict = dict(context or {})

        # If local semantic recall reached source/reuse fallback, an explicitly
        # approved clean segment-level b-roll is a better honest generic shot.
        if not hits or all(
            str(getattr(hit, "schedule_level", "source")) in {"source", "reuse"}
            for hit in hits
        ):
            generic = self._segment_generic_candidates(
                context=context_dict, limit=limit, video_ids=video_ids,
            )
            if generic:
                hits = generic

        global_used = False
        if context_dict.get("rough_cut") and context_dict.get("narration_context"):
            reservations = await self._whole_script_reservations(
                context=context_dict,
                video_ids=video_ids,
                limit=limit,
            )
            global_used = True
            reservation = self._reservation_for_query(query, context_dict, reservations)
            if reservation is not None:
                hits = self._apply_reservation(hits, reservation)

        if self._reranker is None or len(hits) < 2:
            return hits
        if not context_dict.get("rough_cut"):
            return hits
        if str(context_dict.get("director_importance") or "") == "B":
            return hits
        # Whole-script preparation already used one candidate-rerank request.
        # Do not fall back to one API call per sentence afterward.
        if global_used:
            return hits

        requirement_id, source_quote, semantic = self._requirement_context(query, context_dict)
        candidates = [
            self._to_candidate(
                hit,
                requirement_id=requirement_id,
                source_quote=source_quote,
                semantic=semantic,
            )
            for hit in hits
        ]
        candidates = [candidate for candidate in candidates if candidate is not None]
        if len(candidates) < 2:
            return hits

        snapshot = self._snapshot_key(query, candidates)
        ordered_ids = self._rank_cache.get(snapshot)
        if ordered_ids is None:
            ranking = await self._reranker.rank(candidates)
            ordered_ids = ranking.get(requirement_id, [])
            self._rank_cache[snapshot] = list(ordered_ids)
        return self._apply_rank(hits, ordered_ids)

    async def _whole_script_reservations(
        self,
        *,
        context: dict[str, object],
        video_ids: list[UUID] | None,
        limit: int,
    ) -> dict[str, tuple[UUID, int, int]]:
        narration = str(context.get("narration_context") or "").strip()
        if not narration:
            return {}
        scope = ",".join(sorted(str(video_id) for video_id in (video_ids or [])))
        cache_key = sha256(f"{scope}\n{narration}".encode("utf-8")).hexdigest()
        if cache_key in self._global_reservation_cache:
            return self._global_reservation_cache[cache_key]

        requirements = parse_script_visual_requirements(narration)
        grouped: dict[str, list[Any]] = {}
        for requirement in requirements:
            grouped.setdefault(requirement.sentence_id, []).append(requirement)
        if len(grouped) < 2:
            # A one-sentence script has no cross-sentence source conflict; let
            # the normal single-query reranker handle it.
            self._global_reservation_cache[cache_key] = {}
            return {}

        hits_by_sentence: dict[str, list[Any]] = {}
        text_by_sentence: dict[str, str] = {}
        all_api_candidates: list[RerankCandidate] = []
        semantics_by_sentence: dict[str, dict[str, object]] = {}
        importance_by_sentence: dict[str, str] = {}
        required_duration_ms: dict[str, int] = {}

        for sentence_id, sentence_requirements in grouped.items():
            sentence_text = "".join(item.source_quote for item in sentence_requirements).strip()
            if not sentence_text:
                continue
            importance = max(
                (item.importance for item in sentence_requirements),
                key=lambda value: _IMPORTANCE_RANK.get(value, 0),
            )
            sentence_context = dict(context)
            sentence_context["excluded_ranges"] = []
            sentence_context["director_importance"] = importance
            sentence_context["retrieval_intent"] = {
                "visual_requirements": [
                    item.model_dump(mode="json") for item in sentence_requirements
                ]
            }
            # The local inner search is used deliberately: preparation must not
            # recursively invoke this wrapper or call the API per sentence.
            sentence_hits = await self._inner.search_with_context(
                sentence_text,
                context=sentence_context,
                limit=max(limit, 12),
                video_ids=video_ids,
            )
            if not sentence_hits:
                continue
            hits_by_sentence[sentence_id] = list(sentence_hits)
            text_by_sentence[sentence_id] = sentence_text
            semantics = self._semantic_from_requirements(sentence_requirements)
            semantics_by_sentence[sentence_id] = semantics
            importance_by_sentence[sentence_id] = importance
            # Only an estimate is needed during reservation; the planner later
            # uses the real narration timeline.  The estimate prevents a 3s
            # snippet with slightly higher score from consuming a sentence that
            # has an available continuous 8–12s source window.
            content_chars = len("".join(ch for ch in sentence_text if not ch.isspace()))
            required_duration_ms[sentence_id] = min(12_000, max(2_500, content_chars * 220))
            all_api_candidates.extend(
                candidate
                for hit in sentence_hits
                if (candidate := self._to_candidate(
                    hit,
                    requirement_id=sentence_id,
                    source_quote=sentence_text,
                    semantic=semantics,
                )) is not None
            )

        api_rankings: dict[str, list[str]] = {}
        if self._reranker is not None and len(all_api_candidates) >= 2:
            api_rankings = await self._reranker.rank(all_api_candidates)

        candidate_groups: dict[str, list[AssignmentCandidate]] = {}
        for sentence_id, sentence_hits in hits_by_sentence.items():
            ranking = api_rankings.get(sentence_id, [])
            rank_map = {candidate_id: index for index, candidate_id in enumerate(ranking)}
            values: list[AssignmentCandidate] = []
            for hit in sentence_hits:
                match_level = str(
                    getattr(hit, "match_level", None)
                    or normalize_match_level(getattr(hit, "schedule_level", None))
                )
                local_score = float(
                    getattr(hit, "hybrid_score", 0.0)
                    or getattr(hit, "score", 0.0)
                    or 0.0
                )
                candidate_id = self._candidate_id(hit)
                if candidate_id in rank_map:
                    # API preference is deliberately modest and stays below
                    # the hard evidence-level comparison in global_assignment.
                    score = max(local_score, max(0.0, 0.98 - 0.01 * rank_map[candidate_id]))
                else:
                    score = local_score
                values.append(AssignmentCandidate(
                    requirement_id=sentence_id,
                    sentence_id=sentence_id,
                    importance=importance_by_sentence[sentence_id],  # type: ignore[arg-type]
                    video_id=hit.video_id,
                    start_ms=int(hit.source_start_ms),
                    end_ms=int(hit.source_end_ms),
                    score=score,
                    match_level=match_level,
                    anchor_start_ms=getattr(hit, "anchor_start_ms", None),
                    anchor_end_ms=getattr(hit, "anchor_end_ms", None),
                    pollution_level=getattr(hit, "pollution_level", None),
                    schedule_level=getattr(hit, "schedule_level", None),
                ))
            candidate_groups[sentence_id] = values

        selected = assign_requirements(
            candidate_groups,
            required_duration_ms=required_duration_ms,
        )
        reservations: dict[str, tuple[UUID, int, int]] = {}
        for sentence_id, candidate in selected.items():
            source = (candidate.video_id, candidate.start_ms, candidate.end_ms)
            reservations[sentence_id] = source
            sentence_text = text_by_sentence.get(sentence_id)
            if sentence_text:
                reservations[sentence_text] = source

        self._global_reservation_cache[cache_key] = reservations
        return reservations

    @staticmethod
    def _semantic_from_requirements(requirements: list[Any]) -> dict[str, object]:
        def first(field: str) -> object | None:
            return next((getattr(item, field, None) for item in requirements if getattr(item, field, None)), None)

        def merged(field: str) -> list[str]:
            values: list[str] = []
            for item in requirements:
                raw = getattr(item, field, None)
                if isinstance(raw, str) and raw:
                    values.append(raw)
                elif isinstance(raw, (list, tuple)):
                    values.extend(str(value) for value in raw if value)
            return list(dict.fromkeys(values))

        return {
            "subject": first("subject"),
            "action": first("action"),
            "scene": first("scene"),
            "environment": first("environment"),
            "objects": merged("objects"),
            "configurations": merged("configurations"),
            "quantities": merged("quantities"),
            "relations": merged("relations"),
        }

    @staticmethod
    def _reservation_for_query(
        query: str,
        context: dict[str, object],
        reservations: dict[str, tuple[UUID, int, int]],
    ) -> tuple[UUID, int, int] | None:
        if query.strip() in reservations:
            return reservations[query.strip()]
        intent = context.get("retrieval_intent") or {}
        requirements = intent.get("visual_requirements", []) if isinstance(intent, dict) else []
        sentence_ids = {
            str(item.get("sentence_id"))
            for item in requirements
            if isinstance(item, dict) and item.get("sentence_id")
        }
        if len(sentence_ids) == 1:
            return reservations.get(next(iter(sentence_ids)))
        return None

    @classmethod
    def _apply_reservation(
        cls,
        hits: list[Any],
        reservation: tuple[UUID, int, int],
    ) -> list[Any]:
        video_id, start_ms, end_ms = reservation

        def reserved(hit: Any) -> bool:
            return (
                hit.video_id == video_id
                and int(hit.source_start_ms) == start_ms
                and int(hit.source_end_ms) == end_ms
            )

        indexed = list(enumerate(hits))
        indexed.sort(key=lambda item: (
            _LEVEL_RANK.get(str(
                getattr(item[1], "match_level", None)
                or normalize_match_level(getattr(item[1], "schedule_level", None))
            ), 6),
            0 if reserved(item[1]) else 1,
            item[0],
        ))
        result: list[Any] = []
        for _, hit in indexed:
            if reserved(hit):
                update = {
                    "score": max(float(getattr(hit, "score", 0.0) or 0.0), 0.995),
                    "hybrid_score": max(float(getattr(hit, "hybrid_score", 0.0) or 0.0), 0.995),
                    "query_relevance_reason": (
                        (getattr(hit, "query_relevance_reason", "") or "")
                        + "；全局素材预留：避免抢占后文稀缺证据/重复源片段"
                    ).lstrip("；"),
                }
                if hasattr(hit, "model_copy"):
                    hit = hit.model_copy(update=update)
                else:
                    for key, value in update.items():
                        setattr(hit, key, value)
            result.append(hit)
        return result

    async def neutral_candidates(
        self,
        *,
        limit: int = 12,
        video_ids: list[UUID] | None = None,
        needed_duration_ms: int | None = None,
    ) -> list[Any]:
        context: dict[str, object] = {
            "rough_cut": True,
            "minimum_shot_ms": min(needed_duration_ms or 2_000, 2_000),
            "needed_duration_ms": needed_duration_ms or 0,
        }
        generic = self._segment_generic_candidates(
            context=context, limit=limit, video_ids=video_ids,
        )
        if generic:
            return generic
        neutral = getattr(self._inner, "neutral_candidates")
        try:
            return await neutral(
                limit=limit,
                video_ids=video_ids,
                needed_duration_ms=needed_duration_ms,
            )
        except TypeError:
            return await neutral(limit=limit, video_ids=video_ids)

    def _segment_generic_candidates(
        self,
        *,
        context: dict[str, object],
        limit: int,
        video_ids: list[UUID] | None,
    ) -> list[LocalRoughCutHit]:
        if self._segment_roles is None or limit <= 0:
            return []
        catalog = getattr(self._inner, "_catalog", None)
        if catalog is None:
            return []
        try:
            minimum_ms = int(context.get("minimum_shot_ms") or 2_000)
        except (TypeError, ValueError):
            minimum_ms = 2_000
        excluded: list[tuple[str, int, int]] = []
        raw_excluded = context.get("excluded_ranges") or []
        if isinstance(raw_excluded, list):
            for item in raw_excluded:
                if not isinstance(item, dict):
                    continue
                try:
                    excluded.append((
                        str(item.get("video_id")),
                        int(item.get("start_ms", 0)),
                        int(item.get("end_ms", 0)),
                    ))
                except (TypeError, ValueError):
                    continue

        hits: list[LocalRoughCutHit] = []
        for item in self._segment_roles.list_ranges(
            "generic", video_ids=video_ids, limit=max(limit * 4, 40),
        ):
            if item.end_ms - item.start_ms < minimum_ms:
                continue
            if any(
                video_key == str(item.video_id)
                and item.start_ms < excluded_end and item.end_ms > excluded_start
                for video_key, excluded_start, excluded_end in excluded
            ):
                continue
            video = catalog.get_video(item.video_id)
            if video is None or getattr(video, "fallback_role", "normal") == "never":
                continue
            annotation = catalog.get_effective_annotation(item.segment_id)
            if annotation is None:
                annotation = SemanticAnnotation(
                    segment_id=item.segment_id,
                    origin=AnnotationOrigin.AI,
                    provider="catalog",
                    description="人工标记通用镜头/空镜，用于干净中性兜底。",
                    confidence=0.0,
                )
            hits.append(LocalRoughCutHit(
                segment_id=item.segment_id,
                video_id=item.video_id,
                filename=video.filename,
                source_uri=video.source_uri,
                source_start_ms=item.start_ms,
                source_end_ms=item.end_ms,
                score=0.0,
                hybrid_score=0.0,
                annotation=annotation,
                query_relevance_reason="人工标记通用镜头/空镜",
                schedule_level="generic",
                match_level="GENERIC",
            ))

        # Reuse the exact same media-admission gate as normal/source fallbacks;
        # an explicit generic label never legalises title cards/PPT/dense text.
        filter_media = getattr(self._inner, "_filter_non_editable", None)
        if callable(filter_media):
            hits = filter_media(hits, context)
        hits.sort(key=lambda hit: (
            -(hit.source_end_ms - hit.source_start_ms),
            str(hit.video_id),
            hit.source_start_ms,
        ))
        return hits[:limit]

    @staticmethod
    def _requirement_context(
        query: str,
        context: dict[str, object],
    ) -> tuple[str, str, dict[str, object]]:
        intent = context.get("retrieval_intent") or {}
        requirements = intent.get("visual_requirements", []) if isinstance(intent, dict) else []
        valid = [item for item in requirements if isinstance(item, dict)]
        sentence_ids = [str(item.get("sentence_id")) for item in valid if item.get("sentence_id")]
        source_quotes = [str(item.get("source_quote")) for item in valid if item.get("source_quote")]
        requirement_id = (
            sentence_ids[0]
            if sentence_ids and len(set(sentence_ids)) == 1
            else "beat:" + sha256(query.encode("utf-8")).hexdigest()[:20]
        )
        source_quote = "".join(source_quotes) or query

        def first(field: str) -> object | None:
            return next((item.get(field) for item in valid if item.get(field)), None)

        def merged(field: str) -> list[str]:
            values: list[str] = []
            for item in valid:
                raw = item.get(field)
                if isinstance(raw, str) and raw:
                    values.append(raw)
                elif isinstance(raw, (list, tuple)):
                    values.extend(str(value) for value in raw if value)
            return list(dict.fromkeys(values))

        semantic: dict[str, object] = {
            "subject": first("subject"),
            "action": first("action"),
            "scene": first("scene"),
            "environment": first("environment"),
            "objects": merged("objects"),
            "configurations": merged("configurations"),
            "quantities": merged("quantities"),
            "relations": merged("relations"),
        }
        return requirement_id, source_quote, semantic

    @staticmethod
    def _candidate_id(hit: Any) -> str:
        protocol_id = getattr(hit, "protocol_id", None)
        if protocol_id:
            return str(protocol_id)
        return (
            f"{getattr(hit, 'segment_id', 'unknown')}:"
            f"{getattr(hit, 'source_start_ms', 0)}:"
            f"{getattr(hit, 'source_end_ms', 0)}"
        )

    @classmethod
    def _to_candidate(
        cls,
        hit: Any,
        *,
        requirement_id: str,
        source_quote: str,
        semantic: dict[str, object],
    ) -> RerankCandidate | None:
        start = int(getattr(hit, "source_start_ms", 0) or 0)
        end = int(getattr(hit, "source_end_ms", 0) or 0)
        if end <= start:
            return None
        annotation = getattr(hit, "annotation", None)
        if annotation is None:
            return None
        match_level = str(
            getattr(hit, "match_level", None)
            or normalize_match_level(getattr(hit, "schedule_level", None))
        )
        return RerankCandidate(
            candidate_id=cls._candidate_id(hit),
            requirement_id=requirement_id,
            source_quote=source_quote,
            match_level=match_level,
            local_score=float(
                getattr(hit, "hybrid_score", 0.0)
                or getattr(hit, "score", 0.0)
                or 0.0
            ),
            subject=str(semantic.get("subject")) if semantic.get("subject") else (
                annotation.characters[0] if annotation.characters else None
            ),
            action=str(semantic.get("action")) if semantic.get("action") else (
                annotation.actions[0] if annotation.actions else None
            ),
            scene=str(semantic.get("scene")) if semantic.get("scene") else (
                annotation.scene[0] if annotation.scene else None
            ),
            environment=(
                str(semantic.get("environment")) if semantic.get("environment") else None
            ),
            objects=list(semantic.get("objects") or annotation.objects),
            configurations=list(semantic.get("configurations") or []),
            quantities=list(semantic.get("quantities") or []),
            relations=list(semantic.get("relations") or []),
            evidence_summary=str(getattr(annotation, "description", "") or ""),
            source_start_ms=start,
            source_end_ms=end,
            pollution_level=getattr(hit, "pollution_level", None),
            presentation_type=getattr(hit, "presentation_type", None),
        )

    @staticmethod
    def _snapshot_key(query: str, candidates: list[RerankCandidate]) -> str:
        raw = "|".join([
            query,
            *(
                f"{candidate.candidate_id}:{candidate.match_level}:"
                f"{candidate.local_score:.6f}:{candidate.pollution_level}"
                for candidate in candidates
            ),
        ])
        return sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def _apply_rank(cls, hits: list[Any], ordered_ids: list[str]) -> list[Any]:
        if not ordered_ids:
            return hits
        api_rank = {candidate_id: index for index, candidate_id in enumerate(ordered_ids)}
        indexed = list(enumerate(hits))
        indexed.sort(key=lambda item: (
            _LEVEL_RANK.get(str(
                getattr(item[1], "match_level", None)
                or normalize_match_level(getattr(item[1], "schedule_level", None))
            ), 6),
            api_rank.get(cls._candidate_id(item[1]), 10_000),
            item[0],
        ))
        result: list[Any] = []
        for _, hit in indexed:
            candidate_id = cls._candidate_id(hit)
            if candidate_id in api_rank:
                preferred_score = max(0.0, 0.98 - 0.01 * api_rank[candidate_id])
                update = {
                    "score": max(float(getattr(hit, "score", 0.0) or 0.0), preferred_score),
                    "hybrid_score": max(
                        float(getattr(hit, "hybrid_score", 0.0) or 0.0), preferred_score
                    ),
                    "query_relevance_reason": (
                        (getattr(hit, "query_relevance_reason", "") or "")
                        + f"；API导演候选重排第{api_rank[candidate_id] + 1}"
                    ).lstrip("；"),
                }
                if hasattr(hit, "model_copy"):
                    hit = hit.model_copy(update=update)
                else:
                    for key, value in update.items():
                        setattr(hit, key, value)
            result.append(hit)
        return result
