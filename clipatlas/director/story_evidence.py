from __future__ import annotations

from pathlib import Path
from uuid import UUID

from clipatlas.asr.models import ASRChunkStatus
from clipatlas.asr.store import ASRStore
from clipatlas.catalog.store import CatalogStore
from clipatlas.director.story_errors import StoryEvidenceUnavailableError
from clipatlas.director.story_models import StoryEvidenceItem, StoryEvidencePacket
from clipatlas.library.models import LibraryItemStatus
from clipatlas.library.store import LibraryStore
from clipatlas.ocr.models import OCRSampleStatus
from clipatlas.ocr.store import OCRStore, normalize_ocr_text

_MAX_ITEMS = 4_000
_MAX_TEXT = 1_200


def _clean_text(value: str) -> str:
    return " ".join(value.split())[:_MAX_TEXT]


def _visual_text(annotation) -> str:
    parts: list[str] = []
    if annotation.description.strip():
        parts.append(annotation.description.strip())
    for label, values in (
        ("人物", annotation.characters),
        ("动作", annotation.actions),
        ("场景", annotation.scene),
        ("情绪", annotation.emotions),
        ("物体", annotation.objects),
        ("文字", annotation.ocr),
    ):
        cleaned = [str(item).strip() for item in values if str(item).strip()]
        if cleaned:
            parts.append(f"{label}: {'、'.join(cleaned)}")
    facts = [fact.value.strip() for fact in annotation.facts if fact.value.strip()]
    if facts:
        parts.append(f"事实: {'；'.join(facts[:24])}")
    return _clean_text("；".join(parts))


class StoryEvidenceBuilder:
    def __init__(
        self,
        *,
        library_store: LibraryStore,
        catalog_store: CatalogStore,
        asr_store: ASRStore,
        ocr_store: OCRStore,
    ) -> None:
        self._library_store = library_store
        self._catalog_store = catalog_store
        self._asr_store = asr_store
        self._ocr_store = ocr_store

    def build(self, project_id: UUID) -> StoryEvidencePacket:
        items = self._library_store.list_items(
            project_id=project_id,
            status=LibraryItemStatus.COMPLETED,
            limit=10_000,
            offset=0,
        )
        completed = [item for item in items if item.video_id is not None]
        if not completed:
            raise StoryEvidenceUnavailableError("当前项目没有已完成解析的可用视频素材")

        evidence: list[StoryEvidenceItem] = []
        warnings: list[str] = []

        for library_item in completed:
            assert library_item.video_id is not None
            video_id = library_item.video_id
            ingested = self._catalog_store.get_ingested_video(video_id)
            source_name = (
                ingested.video.filename
                if ingested is not None
                else Path(library_item.source_path).name
            )
            if ingested is None:
                warnings.append(f"素材 {source_name} 缺少目录视频记录，已跳过画面证据")
            else:
                for segment in ingested.segments:
                    annotation = self._catalog_store.get_effective_annotation(segment.id)
                    if annotation is None:
                        continue
                    text = _visual_text(annotation)
                    if not text:
                        continue
                    evidence.append(
                        StoryEvidenceItem(
                            evidence_id=f"visual:{video_id}:{segment.id}",
                            kind="visual",
                            video_id=video_id,
                            segment_id=segment.id,
                            start_ms=segment.start_ms,
                            end_ms=segment.end_ms,
                            text=text,
                            source_name=source_name,
                        )
                    )

            asr_latest: dict[tuple[int, int, str, str], object] = {}
            for record in self._asr_store.list_asr_chunks(video_id):
                if record.status != ASRChunkStatus.COMPLETED:
                    continue
                key = (record.start_ms, record.end_ms, record.provider, record.model)
                previous = asr_latest.get(key)
                if previous is None or record.revision > previous.revision:
                    asr_latest[key] = record
            for record in sorted(asr_latest.values(), key=lambda row: (row.start_ms, row.end_ms)):
                for sentence_index, sentence in enumerate(record.sentences):
                    text = _clean_text(sentence.text)
                    if not text:
                        continue
                    evidence.append(
                        StoryEvidenceItem(
                            evidence_id=(
                                f"asr:{video_id}:{sentence.start_ms}:{sentence.end_ms}:"
                                f"{record.revision}:{sentence_index}"
                            ),
                            kind="asr",
                            video_id=video_id,
                            start_ms=sentence.start_ms,
                            end_ms=sentence.end_ms,
                            text=text,
                            source_name=source_name,
                        )
                    )

            ocr_latest: dict[tuple[int, int, int, str, str], object] = {}
            for record in self._ocr_store.list_samples(video_id):
                if record.status != OCRSampleStatus.COMPLETED:
                    continue
                key = (
                    record.start_ms,
                    record.end_ms,
                    record.interval_ms,
                    record.provider,
                    record.model,
                )
                previous = ocr_latest.get(key)
                if previous is None or record.revision > previous.revision:
                    ocr_latest[key] = record
            for record in sorted(ocr_latest.values(), key=lambda row: (row.start_ms, row.end_ms)):
                text = _clean_text(normalize_ocr_text(record.text))
                if not text:
                    continue
                evidence.append(
                    StoryEvidenceItem(
                        evidence_id=(
                            f"ocr:{video_id}:{record.start_ms}:{record.end_ms}:"
                            f"{record.revision}:{record.interval_ms}"
                        ),
                        kind="ocr",
                        video_id=video_id,
                        start_ms=record.start_ms,
                        end_ms=record.end_ms,
                        text=text,
                        source_name=source_name,
                    )
                )

        if not evidence:
            raise StoryEvidenceUnavailableError(
                "当前项目虽然有已解析视频，但没有可用于故事理解的画面、口播或 OCR 证据"
            )
        if len(evidence) > _MAX_ITEMS:
            raise StoryEvidenceUnavailableError(
                f"当前项目故事证据过多（{len(evidence)} 条），请缩小素材范围后再分析"
            )

        return StoryEvidencePacket(
            project_id=project_id,
            video_count=len(completed),
            items=evidence,
            warnings=warnings,
        )
