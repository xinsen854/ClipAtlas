from pathlib import Path
from uuid import uuid4

from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.models import SegmentSource
from clipatlas.retrieval.fallback_roles import SegmentFallbackSearch


class _Inner:
    def __init__(self, catalog: CatalogStore, hits=None):
        self._catalog = catalog
        self.hits = list(hits or [])

    async def search_with_context(self, query, *, context=None, limit=12, video_ids=None):
        return list(self.hits)

    async def search(self, query, limit=12, video_ids=None):
        return list(self.hits)

    async def neutral_candidates(self, *, limit=12, video_ids=None, needed_duration_ms=None):
        return []

    def _filter_non_editable(self, hits, context=None):
        kept = []
        for hit in hits:
            media = self._catalog.get_segment_media_type(hit.segment_id)
            if media is not None and media[0] in {"title_card", "screen_capture", "technical_chart"}:
                continue
            kept.append(hit)
        return kept


def _catalog_with_segment(tmp_path: Path, *, medium: str = "scene"):
    catalog = CatalogStore(tmp_path / "library.sqlite3")
    video_id = uuid4()
    segment_id = uuid4()
    with catalog._connect() as connection:
        connection.execute(
            "INSERT INTO catalog_videos (id,filename,source_uri,duration_ms,width,height,fps,video_codec,has_audio,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(video_id), "clean.mp4", "file:///clean.mp4", 10_000, 1920, 1080, 25.0,
             "h264", 0, "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO catalog_segments (id,video_id,start_ms,end_ms,source,created_at) VALUES (?,?,?,?,?,?)",
            (str(segment_id), str(video_id), 1000, 9000, SegmentSource.AI.value,
             "2026-01-01T00:00:00+00:00"),
        )
    catalog.save_segment_media_type(
        segment_id=segment_id,
        subject_medium=medium,
        text_ratio=0.05,
        text_block_count=1,
        has_real_subject=medium == "scene",
        basis="test",
    )
    return catalog, video_id, segment_id


async def test_review_placeholder_is_used_only_after_normal_neutral_pool_is_empty(tmp_path: Path):
    catalog, video_id, segment_id = _catalog_with_segment(tmp_path)
    search = SegmentFallbackSearch(_Inner(catalog), catalog=catalog)
    search.set_segment_fallback_role(segment_id, "review_placeholder")

    hits = await search.neutral_candidates(
        limit=12, video_ids=[video_id], needed_duration_ms=4000,
    )

    assert len(hits) == 1
    assert hits[0].segment_id == segment_id
    assert hits[0].schedule_level == "generic"
    assert "审片占位" in hits[0].query_relevance_reason


async def test_polluted_review_placeholder_is_never_silently_admitted(tmp_path: Path):
    catalog, video_id, segment_id = _catalog_with_segment(tmp_path, medium="title_card")
    search = SegmentFallbackSearch(_Inner(catalog), catalog=catalog)
    search.set_segment_fallback_role(segment_id, "review_placeholder")

    hits = await search.neutral_candidates(
        limit=12, video_ids=[video_id], needed_duration_ms=4000,
    )

    assert hits == []


async def test_explicit_segment_generic_is_available_without_api_reranker(tmp_path: Path):
    catalog, video_id, segment_id = _catalog_with_segment(tmp_path)
    search = SegmentFallbackSearch(_Inner(catalog), catalog=catalog)
    search.set_segment_fallback_role(segment_id, "generic")

    hits = await search.search_with_context(
        "没有语义命中的句子",
        context={"rough_cut": True, "minimum_shot_ms": 2000},
        limit=12,
        video_ids=[video_id],
    )

    assert len(hits) == 1
    assert hits[0].segment_id == segment_id
    assert hits[0].schedule_level == "generic"
