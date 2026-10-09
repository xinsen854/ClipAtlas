import logging
from uuid import UUID

from clipatlas.retrieval.hybrid import HybridSearchHit, HybridSearchLike
from clipatlas.retrieval.intent import RetrievalIntentBuilder
from clipatlas.retrieval.storyboard import ShotIntent
from clipatlas.roughcut.models import ScriptBeat

_MAX_VISUAL_QUERIES = 4
logger = logging.getLogger(__name__)


class ShotSearchHit(HybridSearchHit):
    """Internal rough-cut candidate provenance; the public Hybrid result stays unchanged."""
    visual_query: str


class IntentAwareHybridSearch:
    """Expand one narration query into a few retrieval queries before local recall."""

    def __init__(
        self,
        *,
        search: HybridSearchLike,
        builder: RetrievalIntentBuilder,
    ) -> None:
        self._search = search
        self._builder = builder

    def project_video_ids(self, project_id: UUID) -> list[UUID]:
        lookup = getattr(self._search, "project_video_ids", None)
        if not callable(lookup):
            raise ValueError("Project library scope is not configured")
        return list(lookup(project_id))

    async def prepare_beats(self, beats: list[ScriptBeat], context: dict[str, object]) -> list[ScriptBeat]:
        prepare = getattr(self._builder, "prepare_beats", None)
        return await prepare(beats, context) if callable(prepare) else beats

    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
    ) -> list[HybridSearchHit]:
        return await self.search_with_context(
            query,
            context=None,
            limit=limit,
            video_ids=video_ids,
        )

    async def search_with_context(
        self,
        query: str,
        *,
        context: dict[str, object] | None = None,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
    ) -> list[HybridSearchHit]:
        retrieval_query = self._base_retrieval_query(query, context)

        # Preserve the downstream search service's existing edge-case behaviour.
        if not query.strip() or limit <= 0 or (video_ids is not None and not video_ids):
            return await self._search.search(
                retrieval_query,
                limit=limit,
                video_ids=video_ids,
            )

        plan = context.get("retrieval_intent") if context else None
        legacy_keys = {
            "start_sequence", "end_sequence", "subject", "purpose",
            "evidence", "match_type", "visual_queries",
        }
        if isinstance(plan, dict) and legacy_keys <= set(plan):
            shot = ShotIntent.model_validate(plan)
            routed_search = getattr(self._search, "search_evidence", None)
            if callable(routed_search):
                broaden = bool(context and context.get("broaden_search"))
                visuals = shot.visual_queries[:1]
                if broaden:
                    visuals = shot.alternatives[:1] or shot.visual_queries[1:2] or shot.visual_queries[:1]
                if context and context.get("auto_support"):
                    visuals = shot.supporting_queries[:1] or [f"{shot.subject} 场景 展示 使用"]
                logger.info("roughcut planned recall evidence=%s match=%s visual=%s keywords=%s broaden=%s",
                            shot.evidence, shot.match_type, visuals, shot.keywords, broaden)
                routed_hits = await routed_search(visual_queries=visuals, keywords=shot.keywords,
                                                  evidence=shot.evidence, limit=limit, video_ids=video_ids)
                return [ShotSearchHit(**h.model_dump(), visual_query=visuals[0]) for h in routed_hits]

        builder_context = dict(context) if context is not None else None
        if builder_context is not None and isinstance(plan, dict) and not legacy_keys <= set(plan):
            # visual_requirements belongs to the new local evidence protocol,
            # not the retired ShotIntent schema consumed by this adapter.
            builder_context.pop("retrieval_intent", None)
        try:
            if context is None:
                intent = await self._builder.build(query)
            else:
                intent = await self._builder.build(query, context=builder_context)
        except Exception:
            # Intent generation is an optional recall enhancement. The already-proven
            # retrieval path remains authoritative when it is unavailable.
            return await self._search.search(
                retrieval_query,
                limit=limit,
                video_ids=video_ids,
            )

        queries = self._queries(retrieval_query, intent.visual_queries)
        rough_cut = bool(context and context.get("rough_cut"))
        if rough_cut and len(queries) > 1:
            queries = queries[1:]
        if rough_cut:
            logger.info("roughcut visual queries=%s", queries)
        if len(queries) == 1:
            hits = await self._search.search(
                queries[0],
                limit=limit,
                video_ids=video_ids,
            )

            if rough_cut and intent.visual_queries:
                return [ShotSearchHit(**h.model_dump(), visual_query=queries[0]) for h in hits]
            return hits

        best_by_range: dict[tuple[UUID, int, int], HybridSearchHit] = {}
        query_results: list[list[HybridSearchHit]] = []
        for expanded_query in queries:
            hits = await self._search.search(
                expanded_query,
                limit=limit,
                video_ids=video_ids,
            )
            if rough_cut:
                hits = [ShotSearchHit(**h.model_dump(), visual_query=expanded_query) for h in hits]
            query_results.append(hits)
            for hit in hits:
                key = (
                    hit.video_id,
                    hit.source_start_ms,
                    hit.source_end_ms,
                )
                current = best_by_range.get(key)
                if current is None or hit.score > current.score:
                    best_by_range[key] = hit

        if context and context.get("rough_cut"):
            # Preserve each shot intent instead of comparing scores from different queries.
            lists = query_results
            ranked = []
            seen_ranges = set()
            for index in range(max((len(hits) for hits in lists), default=0)):
                for hits in lists:
                    if index >= len(hits):
                        continue
                    hit = hits[index]
                    key = (hit.video_id, hit.source_start_ms, hit.source_end_ms)
                    if key not in seen_ranges:
                        seen_ranges.add(key)
                        ranked.append(hit)
            return ranked[:limit]

        ranked = sorted(
            best_by_range.values(),
            key=lambda hit: (
                -hit.score,
                str(hit.video_id),
                hit.source_start_ms,
                hit.source_end_ms,
            ),
        )
        return ranked[:limit]

    @staticmethod
    def _base_retrieval_query(
        source_text: str,
        context: dict[str, object] | None,
    ) -> str:
        if context is not None:
            candidate = context.get("base_retrieval_query")
            if isinstance(candidate, str) and candidate.strip():
                return candidate
        return source_text

    @staticmethod
    def _queries(source_text: str, visual_queries: list[str]) -> list[str]:
        queries = [source_text]
        seen = {source_text.strip()}
        for value in visual_queries[:_MAX_VISUAL_QUERIES]:
            query = value.strip()
            if not query or query in seen:
                continue
            seen.add(query)
            queries.append(query)
        return queries
