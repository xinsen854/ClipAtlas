from uuid import uuid4

from clipatlas.asr.models import ASRChunkRecord, ASRChunkStatus, ASRSentence
from clipatlas.asr.store import ASRStore


def _record(
    video_id,
    *,
    start_ms: int,
    end_ms: int,
    revision: int,
    status: ASRChunkStatus,
    text: str,
) -> ASRChunkRecord:
    sentences = []
    if text:
        sentences = [
            ASRSentence(
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
            )
        ]
    return ASRChunkRecord(
        video_id=video_id,
        start_ms=start_ms,
        end_ms=end_ms,
        provider="bailian-asr",
        model="qwen-audio-3.0-asr-flash",
        revision=revision,
        status=status,
        attempt_count=1,
        sentences=sentences,
    )


def test_asr_search_text_uses_latest_success_per_span_and_ignores_failed_revision(
    tmp_path,
) -> None:
    store = ASRStore(tmp_path / "library.sqlite3")
    video_id = uuid4()
    store.save_asr_chunk(
        _record(
            video_id,
            start_ms=0,
            end_ms=5_000,
            revision=1,
            status=ASRChunkStatus.COMPLETED,
            text="我们现在开始越野测试",
        )
    )
    store.save_asr_chunk(
        _record(
            video_id,
            start_ms=0,
            end_ms=5_000,
            revision=2,
            status=ASRChunkStatus.FAILED,
            text="",
        )
    )
    store.save_asr_chunk(
        _record(
            video_id,
            start_ms=5_000,
            end_ms=10_000,
            revision=1,
            status=ASRChunkStatus.COMPLETED,
            text="普通公路行驶",
        )
    )

    hits = store.search_text(
        "越野测试",
        "bailian-asr",
        "qwen-audio-3.0-asr-flash",
        limit=10,
    )

    assert [(hit.video_id, hit.start_ms, hit.end_ms, hit.text, hit.revision) for hit in hits] == [
        (video_id, 0, 5_000, "我们现在开始越野测试", 1)
    ]


def test_asr_search_text_filters_video_ids_and_limits_results(tmp_path) -> None:
    store = ASRStore(tmp_path / "library.sqlite3")
    first = uuid4()
    second = uuid4()
    for video_id, start_ms in ((first, 0), (second, 5_000)):
        store.save_asr_chunk(
            _record(
                video_id,
                start_ms=start_ms,
                end_ms=start_ms + 5_000,
                revision=1,
                status=ASRChunkStatus.COMPLETED,
                text="越野测试现场",
            )
        )

    hits = store.search_text(
        "越野测试",
        "bailian-asr",
        "qwen-audio-3.0-asr-flash",
        limit=1,
        video_ids=[second],
    )

    assert len(hits) == 1
    assert hits[0].video_id == second


def test_asr_search_text_returns_empty_for_blank_query_or_nonpositive_limit(tmp_path) -> None:
    store = ASRStore(tmp_path / "library.sqlite3")

    assert store.search_text("   ", "bailian-asr", "qwen-audio-3.0-asr-flash", limit=10) == []
    assert store.search_text("越野", "bailian-asr", "qwen-audio-3.0-asr-flash", limit=0) == []
