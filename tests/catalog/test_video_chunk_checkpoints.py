from pathlib import Path
from uuid import UUID, uuid4

from clipatlas.catalog.checkpoints import (
    PreparedMediaCheckpointStore,
    VideoChunkCheckpointStatus,
    VideoChunkCheckpointStore,
)


def _key() -> tuple[UUID, int, int, str, str]:
    return uuid4(), 0, 30_000, "qwen-vl-video", "qwen3-vl-embedding"


def test_missing_video_chunk_checkpoint_is_not_completed(tmp_path: Path) -> None:
    store = VideoChunkCheckpointStore(tmp_path / "clipatlas.sqlite3")
    video_id, start_ms, end_ms, provider, model = _key()

    assert store.get(video_id, start_ms, end_ms, provider, model) is None
    assert not store.is_completed(video_id, start_ms, end_ms, provider, model)


def test_processing_increments_attempt_count(tmp_path: Path) -> None:
    store = VideoChunkCheckpointStore(tmp_path / "clipatlas.sqlite3")
    video_id, start_ms, end_ms, provider, model = _key()

    store.mark_processing(video_id, start_ms, end_ms, provider, model)
    first = store.get(video_id, start_ms, end_ms, provider, model)
    store.mark_processing(video_id, start_ms, end_ms, provider, model)
    second = store.get(video_id, start_ms, end_ms, provider, model)

    assert first is not None
    assert first.status is VideoChunkCheckpointStatus.PROCESSING
    assert first.attempt_count == 1
    assert second is not None
    assert second.status is VideoChunkCheckpointStatus.PROCESSING
    assert second.attempt_count == 2


def test_completed_checkpoint_is_reusable(tmp_path: Path) -> None:
    store = VideoChunkCheckpointStore(tmp_path / "clipatlas.sqlite3")
    video_id, start_ms, end_ms, provider, model = _key()

    store.mark_processing(video_id, start_ms, end_ms, provider, model)
    store.mark_completed(video_id, start_ms, end_ms, provider, model)
    checkpoint = store.get(video_id, start_ms, end_ms, provider, model)

    assert checkpoint is not None
    assert checkpoint.status is VideoChunkCheckpointStatus.COMPLETED
    assert checkpoint.attempt_count == 1
    assert checkpoint.last_error is None
    assert store.is_completed(video_id, start_ms, end_ms, provider, model)


def test_failed_checkpoint_can_retry_without_losing_attempt_history(tmp_path: Path) -> None:
    store = VideoChunkCheckpointStore(tmp_path / "clipatlas.sqlite3")
    video_id, start_ms, end_ms, provider, model = _key()

    store.mark_processing(video_id, start_ms, end_ms, provider, model)
    store.mark_failed(video_id, start_ms, end_ms, provider, model, error="connection reset")
    failed = store.get(video_id, start_ms, end_ms, provider, model)

    assert failed is not None
    assert failed.status is VideoChunkCheckpointStatus.FAILED
    assert failed.attempt_count == 1
    assert failed.last_error == "connection reset"
    assert not store.is_completed(video_id, start_ms, end_ms, provider, model)

    store.mark_processing(video_id, start_ms, end_ms, provider, model)
    retrying = store.get(video_id, start_ms, end_ms, provider, model)

    assert retrying is not None
    assert retrying.status is VideoChunkCheckpointStatus.PROCESSING
    assert retrying.attempt_count == 2
    assert retrying.last_error is None


def test_5s_and_30s_checkpoint_state_is_isolated(tmp_path: Path) -> None:
    store = VideoChunkCheckpointStore(tmp_path / "clipatlas.sqlite3")
    video_id = uuid4()
    provider = "qwen-vl-video"
    model = "qwen3-vl-embedding"

    store.mark_processing(
        video_id,
        0,
        5_000,
        provider,
        model,
        chunk_duration_ms=5_000,
        overlap_ms=1_000,
    )
    store.mark_completed(
        video_id,
        0,
        5_000,
        provider,
        model,
        chunk_duration_ms=5_000,
        overlap_ms=1_000,
    )
    store.mark_processing(
        video_id,
        0,
        5_000,
        provider,
        model,
        chunk_duration_ms=30_000,
        overlap_ms=5_000,
    )
    store.mark_failed(
        video_id,
        0,
        5_000,
        provider,
        model,
        chunk_duration_ms=30_000,
        overlap_ms=5_000,
        error="coarse failed",
    )

    assert store.is_completed(
        video_id,
        0,
        5_000,
        provider,
        model,
        chunk_duration_ms=5_000,
        overlap_ms=1_000,
    )
    assert not store.is_completed(
        video_id,
        0,
        5_000,
        provider,
        model,
        chunk_duration_ms=30_000,
        overlap_ms=5_000,
    )


def test_video_chunk_checkpoints_do_not_change_prepared_media_checkpoints(tmp_path: Path) -> None:
    db_path = tmp_path / "clipatlas.sqlite3"
    prepared_store = PreparedMediaCheckpointStore(db_path)
    chunk_store = VideoChunkCheckpointStore(db_path)
    library_item_id = uuid4()
    prepared_video_id = uuid4()
    chunk_video_id = uuid4()

    prepared_store.save(library_item_id, "fingerprint-v1", prepared_video_id)
    chunk_store.mark_processing(
        chunk_video_id,
        0,
        30_000,
        "qwen-vl-video",
        "qwen3-vl-embedding",
    )
    chunk_store.mark_completed(
        chunk_video_id,
        0,
        30_000,
        "qwen-vl-video",
        "qwen3-vl-embedding",
    )

    assert prepared_store.get_video_id(library_item_id, "fingerprint-v1") == prepared_video_id
