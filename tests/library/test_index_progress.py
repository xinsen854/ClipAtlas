import sqlite3
from pathlib import Path
from uuid import uuid4

from clipatlas.asr.models import ASRChunkRecord, ASRChunkStatus
from clipatlas.asr.store import ASRStore
from clipatlas.catalog.checkpoints import VideoChunkCheckpointStore
from clipatlas.catalog.store import CatalogStore
from clipatlas.library.index_progress import LibraryIndexProgressReader
from clipatlas.ocr.models import OCRSampleRecord, OCRSampleStatus
from clipatlas.ocr.store import OCRStore


def _video(db_path: Path, *, duration_ms: int = 12_000, has_audio: bool = True):
    CatalogStore(db_path)
    video_id = uuid4()
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO catalog_videos (
                id, filename, source_uri, duration_ms, width, height, fps,
                video_codec, has_audio, created_at
            ) VALUES (?, ?, ?, ?, 1920, 1080, 25.0, 'h264', ?, '2026-09-05T00:00:00+00:00')
            """,
            (str(video_id), "movie.mp4", "file:///movie.mp4", duration_ms, int(has_audio)),
        )
    return video_id


def test_progress_uses_current_visual_profile_and_latest_text_revisions(tmp_path: Path) -> None:
    db_path = tmp_path / "library.sqlite3"
    video_id = _video(db_path)

    visual = VideoChunkCheckpointStore(db_path)
    visual.mark_completed(
        video_id, 0, 5_000, "qwen-vl-video", "qwen3-vl-embedding",
        chunk_duration_ms=5_000, overlap_ms=1_000,
    )
    visual.mark_completed(
        video_id, 4_000, 9_000, "qwen-vl-video", "qwen3-vl-embedding",
        chunk_duration_ms=5_000, overlap_ms=1_000,
    )
    visual.mark_processing(
        video_id, 8_000, 12_000, "qwen-vl-video", "qwen3-vl-embedding",
        chunk_duration_ms=5_000, overlap_ms=1_000,
    )

    asr = ASRStore(db_path)
    asr.save_asr_chunk(ASRChunkRecord(
        video_id=video_id, start_ms=0, end_ms=12_000,
        provider="bailian-asr", model="qwen-audio-3.0-asr-flash",
        revision=1, status=ASRChunkStatus.COMPLETED, attempt_count=1,
    ))
    asr.save_asr_chunk(ASRChunkRecord(
        video_id=video_id, start_ms=0, end_ms=12_000,
        provider="bailian-asr", model="qwen-audio-3.0-asr-flash",
        revision=2, status=ASRChunkStatus.FAILED, attempt_count=1,
        last_error="retry failed",
    ))

    ocr = OCRStore(db_path)
    for revision, status, start_ms, end_ms in [
        (1, OCRSampleStatus.COMPLETED, 0, 5_000),
        (1, OCRSampleStatus.COMPLETED, 5_000, 10_000),
        (1, OCRSampleStatus.COMPLETED, 10_000, 12_000),
        (2, OCRSampleStatus.COMPLETED, 0, 5_000),
        (2, OCRSampleStatus.PROCESSING, 5_000, 10_000),
    ]:
        ocr.save_sample(OCRSampleRecord(
            video_id=video_id, start_ms=start_ms, end_ms=end_ms, interval_ms=5_000,
            provider="bailian-ocr", model="qwen3.5-ocr", revision=revision,
            status=status, attempt_count=1,
        ))

    progress = LibraryIndexProgressReader(
        db_path,
        visual_enabled=True,
        asr_enabled=True,
        ocr_interval_ms=5_000,
    ).get(video_id)

    assert progress.visual.model_dump() == {
        "enabled": True, "applicable": True,
        "completed": 2, "processing": 1, "failed": 0, "total": 3,
    }
    assert progress.asr.model_dump() == {
        "enabled": True, "applicable": True,
        "completed": 0, "processing": 0, "failed": 1, "total": 1,
    }
    assert progress.ocr.model_dump() == {
        "enabled": True, "applicable": True,
        "completed": 1, "processing": 1, "failed": 0, "total": 3,
    }


def test_progress_distinguishes_disabled_from_no_audio(tmp_path: Path) -> None:
    db_path = tmp_path / "library.sqlite3"
    video_id = _video(db_path, has_audio=False)

    progress = LibraryIndexProgressReader(
        db_path,
        visual_enabled=False,
        asr_enabled=True,
        ocr_interval_ms=None,
    ).get(video_id)

    assert progress.visual.enabled is False
    assert progress.visual.applicable is True
    assert progress.visual.total == 0
    assert progress.asr.enabled is True
    assert progress.asr.applicable is False
    assert progress.asr.total == 0
    assert progress.ocr.enabled is False
    assert progress.ocr.applicable is True
    assert progress.ocr.total == 0
