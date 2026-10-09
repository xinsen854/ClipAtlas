from uuid import uuid4

from clipatlas.ocr.models import OCRSampleRecord, OCRSampleStatus, OCRSpan
from clipatlas.ocr.store import OCRStore


def _save_sample(store: OCRStore, *, video_id, text: str) -> None:
    store.save_sample(
        OCRSampleRecord(
            video_id=video_id,
            start_ms=0,
            end_ms=5_000,
            interval_ms=5_000,
            provider="bailian-ocr",
            model="qwen3.5-ocr",
            revision=1,
            status=OCRSampleStatus.COMPLETED,
            attempt_count=1,
            text=text,
        )
    )


def test_ocr_html_is_preserved_raw_but_cleaned_for_spans_and_search(tmp_path) -> None:
    store = OCRStore(tmp_path / "library.sqlite3")
    video_id = uuid4()
    raw_text = (
        "<html><body><p>北京越野董事长</p>"
        "<div>泰钽700&nbsp;上市发布会</div>"
        "<div class=\"image\"><img></div>"
        "</body></html>"
    )
    _save_sample(store, video_id=video_id, text=raw_text)

    samples = store.list_samples(video_id, "bailian-ocr", "qwen3.5-ocr")
    assert samples[0].text == raw_text

    assert store.list_spans(
        video_id,
        "bailian-ocr",
        "qwen3.5-ocr",
        revision=1,
        interval_ms=5_000,
    ) == [
        OCRSpan(
            start_ms=0,
            end_ms=5_000,
            text="北京越野董事长 泰钽700 上市发布会",
        )
    ]

    matches = store.search_text(
        "北京越野",
        "bailian-ocr",
        "qwen3.5-ocr",
        limit=10,
        video_ids=[video_id],
    )
    assert len(matches) == 1
    assert matches[0].text == "北京越野董事长"


def test_ocr_plain_multiline_search_returns_only_matching_line(tmp_path) -> None:
    store = OCRStore(tmp_path / "library.sqlite3")
    video_id = uuid4()
    raw_text = "中国越野车发明者\n北京越野董事长\n直播平台：央视新闻客户端"
    _save_sample(store, video_id=video_id, text=raw_text)

    samples = store.list_samples(video_id, "bailian-ocr", "qwen3.5-ocr")
    assert samples[0].text == raw_text

    matches = store.search_text(
        "北京越野",
        "bailian-ocr",
        "qwen3.5-ocr",
        limit=10,
        video_ids=[video_id],
    )
    assert len(matches) == 1
    assert matches[0].text == "北京越野董事长"
