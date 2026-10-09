from uuid import uuid4

from clipatlas.ocr.models import OCRSampleRecord, OCRSampleStatus
from clipatlas.ocr.store import OCRStore


def _sample(
    video_id,
    *,
    start_ms: int,
    end_ms: int,
    interval_ms: int,
    revision: int,
    status: OCRSampleStatus,
    text: str,
) -> OCRSampleRecord:
    return OCRSampleRecord(
        video_id=video_id,
        start_ms=start_ms,
        end_ms=end_ms,
        interval_ms=interval_ms,
        provider="bailian-ocr",
        model="qwen3.5-ocr",
        revision=revision,
        status=status,
        attempt_count=1,
        text=text,
    )


def test_ocr_search_text_uses_latest_success_per_sample_and_ignores_failed_revision(
    tmp_path,
) -> None:
    store = OCRStore(tmp_path / "library.sqlite3")
    video_id = uuid4()
    store.save_sample(
        _sample(
            video_id,
            start_ms=0,
            end_ms=5_000,
            interval_ms=5_000,
            revision=1,
            status=OCRSampleStatus.COMPLETED,
            text="  越野测试  ",
        )
    )
    store.save_sample(
        _sample(
            video_id,
            start_ms=0,
            end_ms=5_000,
            interval_ms=5_000,
            revision=2,
            status=OCRSampleStatus.FAILED,
            text="",
        )
    )
    store.save_sample(
        _sample(
            video_id,
            start_ms=5_000,
            end_ms=10_000,
            interval_ms=5_000,
            revision=1,
            status=OCRSampleStatus.COMPLETED,
            text="普通公路",
        )
    )

    hits = store.search_text(
        "越野测试",
        "bailian-ocr",
        "qwen3.5-ocr",
        limit=10,
    )

    assert [
        (hit.video_id, hit.start_ms, hit.end_ms, hit.text, hit.revision, hit.interval_ms)
        for hit in hits
    ] == [(video_id, 0, 5_000, "越野测试", 1, 5_000)]


def test_ocr_search_text_filters_video_ids_and_ignores_blank_samples(tmp_path) -> None:
    store = OCRStore(tmp_path / "library.sqlite3")
    first = uuid4()
    second = uuid4()
    store.save_sample(
        _sample(
            first,
            start_ms=0,
            end_ms=5_000,
            interval_ms=5_000,
            revision=1,
            status=OCRSampleStatus.COMPLETED,
            text="越野测试",
        )
    )
    store.save_sample(
        _sample(
            second,
            start_ms=5_000,
            end_ms=10_000,
            interval_ms=5_000,
            revision=1,
            status=OCRSampleStatus.COMPLETED,
            text="越野测试现场",
        )
    )
    store.save_sample(
        _sample(
            second,
            start_ms=10_000,
            end_ms=15_000,
            interval_ms=5_000,
            revision=1,
            status=OCRSampleStatus.COMPLETED,
            text="  \n  ",
        )
    )

    hits = store.search_text(
        "越野测试",
        "bailian-ocr",
        "qwen3.5-ocr",
        limit=1,
        video_ids=[second],
    )

    assert len(hits) == 1
    assert hits[0].video_id == second
    assert hits[0].text == "越野测试现场"


def test_ocr_search_text_returns_empty_for_blank_query_or_nonpositive_limit(tmp_path) -> None:
    store = OCRStore(tmp_path / "library.sqlite3")

    assert store.search_text("   ", "bailian-ocr", "qwen3.5-ocr", limit=10) == []
    assert store.search_text("越野", "bailian-ocr", "qwen3.5-ocr", limit=0) == []
