from uuid import uuid4

from finecut.models import Clip, TimelineDocument, Track
from finecut.store import TimelineStore


def make_document() -> TimelineDocument:
    return TimelineDocument(
        project_id=uuid4(),
        source_plan_id=uuid4(),
        width=1920,
        height=1080,
        fps=30.0,
        duration_ms=4_000,
        tracks=[
            Track(
                kind="video",
                clips=[
                    Clip(
                        source_id="segment-1",
                        source_path="D:/media/source.mp4",
                        timeline_start_ms=1_000,
                        duration_ms=2_000,
                        source_in_ms=5_000,
                        source_out_ms=7_000,
                    )
                ],
            )
        ],
    )


def test_timeline_store_survives_reopen(tmp_path) -> None:
    db_path = tmp_path / "finecut.sqlite3"
    document = make_document()

    TimelineStore(db_path).save(document)
    loaded = TimelineStore(db_path).get(document.project_id, document.source_plan_id)

    assert loaded == document


def test_timeline_store_replaces_same_document_key(tmp_path) -> None:
    db_path = tmp_path / "finecut.sqlite3"
    document = make_document()
    store = TimelineStore(db_path)
    store.save(document)

    edited = document.model_copy(update={"width": 1280, "height": 720})
    store.save(edited)

    loaded = store.get(document.project_id, document.source_plan_id)
    assert loaded == edited
