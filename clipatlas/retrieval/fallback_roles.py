"""Per-segment clean fallback roles for rough-cut search.

This wrapper is independent of the optional API reranker. Editors may mark a
single source segment as ``generic`` (normal b-roll) or ``review_placeholder``
(last-resort local review slate/clean holding shot). Both still pass the same
media-admission function as normal retrieval, so an explicit role never makes
PPT/title-card/dense-text pollution legal.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from clipatlas.catalog.segment_roles import SegmentFallbackRoleStore
from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.models import AnnotationOrigin, SemanticAnnotation
from clipatlas.retrieval.local_rough_cut import LocalRoughCutHit


class SegmentFallbackSearch:
    def __init__(self, search: Any, *, catalog: CatalogStore) -> None:
        self._inner = search
        self._catalog = catalog
        self._roles = SegmentFallbackRoleStore(catalog)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def set_segment_fallback_role(self, segment_id: UUID, role: str) -> None:
        self._roles.set_role(segment_id, role)  # type: ignore[arg-type]

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
        context_dict = dict(context or {})
        hits = await self._inner.search_with_context(
            query, context=context, limit=limit, video_ids=video_ids,
        )
        # exact/related remain authoritative. Segment-level generic only replaces
        # source/reuse quality fallbacks, matching exact→related→generic→source.
        if hits and not all(
            str(getattr(hit, "schedule_level", "source")) in {"source", "reuse"}
            for hit in hits
        ):
            return hits
        generic = self._segment_candidates(
            "generic",
            context=context_dict,
            limit=limit,
            video_ids=video_ids,
        )
        return generic or hits

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
        generic = self._segment_candidates(
            "generic", context=context, limit=limit, video_ids=video_ids,
        )
        if generic:
            return generic

        neutral = getattr(self._inner, "neutral_candidates")
        try:
            hits = await neutral(
                limit=limit,
                video_ids=video_ids,
                needed_duration_ms=needed_duration_ms,
            )
        except TypeError:
            hits = await neutral(limit=limit, video_ids=video_ids)
        if hits:
            return hits

        # Only after legal generic/source candidates are exhausted may a
        # pre-approved clean local review placeholder be used. It is still
        # represented as GENERIC, never DIRECT/SUPPORT evidence.
        return self._segment_candidates(
            "review_placeholder",
            context=context,
            limit=limit,
            video_ids=video_ids,
        )

    def _segment_candidates(
        self,
        role: Literal["generic", "review_placeholder"],
        *,
        context: dict[str, object],
        limit: int,
        video_ids: list[UUID] | None,
    ) -> list[LocalRoughCutHit]:
        if limit <= 0:
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
        for item in self._roles.list_ranges(
            role, video_ids=video_ids, limit=max(limit * 4, 40),
        ):
            if item.end_ms - item.start_ms < minimum_ms:
                continue
            if any(
                video_key == str(item.video_id)
                and item.start_ms < excluded_end
                and item.end_ms > excluded_start
                for video_key, excluded_start, excluded_end in excluded
            ):
                continue
            video = self._catalog.get_video(item.video_id)
            if video is None or getattr(video, "fallback_role", "normal") == "never":
                continue
            annotation = self._catalog.get_effective_annotation(item.segment_id)
            if annotation is None:
                annotation = SemanticAnnotation(
                    segment_id=item.segment_id,
                    origin=AnnotationOrigin.AI,
                    provider="catalog",
                    description=(
                        "本地审片占位：无可用合法正文素材时使用预先认可的干净占位镜头。"
                        if role == "review_placeholder"
                        else "人工标记通用镜头/空镜，用于干净中性兜底。"
                    ),
                    confidence=0.0,
                )
            reason = (
                "本地审片占位：无可用合法正文素材，使用预先认可的干净占位镜头"
                if role == "review_placeholder"
                else "人工标记通用镜头/空镜"
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
                query_relevance_reason=reason,
                schedule_level="generic",
                match_level="GENERIC",
            ))

        # Critical invariant: manual role assignment does not bypass the same
        # pollution gate used by exact/related/generic/source fallbacks.
        filter_media = getattr(self._inner, "_filter_non_editable", None)
        if callable(filter_media):
            try:
                hits = filter_media(hits, context)
            except TypeError:
                hits = filter_media(hits)
        hits.sort(key=lambda hit: (
            -(hit.source_end_ms - hit.source_start_ms),
            str(hit.video_id),
            hit.source_start_ms,
        ))
        return hits[:limit]
