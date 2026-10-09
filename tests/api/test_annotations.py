from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.routes.library import router as library_router
from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.models import (
    AnnotationOrigin,
    SegmentSource,
    SemanticAnnotation,
    VideoAsset,
    VideoSegment,
)
from clipatlas.embeddings.contracts import EmbeddingVector
from clipatlas.retrieval.indexer import SemanticIndexer
from clipatlas.retrieval.semantics import build_retrieval_text
from clipatlas.video.models import IngestedVideo, MediaMetadata


class RecordingEmbeddingProvider:
    name = "fake-embedding"
    model = "embed-v1"
    dimensions = 3

    def __init__(self) -> None:
        self.document_calls: list[list[str]] = []

    async def embed_documents(self, texts: list[str]) -> list[EmbeddingVector]:
        self.document_calls.append(list(texts))
        return [EmbeddingVector(values=[1.0, 0.0, 0.0]) for _ in texts]

    async def embed_query(self, text: str) -> EmbeddingVector:
        del text
        return EmbeddingVector(values=[1.0, 0.0, 0.0])


def _catalog_with_ai_annotation(tmp_path: Path) -> tuple[CatalogStore, VideoSegment, SemanticAnnotation]:
    store = CatalogStore(tmp_path / "catalog.sqlite3")
    video = VideoAsset(
        filename="movie.mp4",
        source_uri="file:///media/movie.mp4",
        duration_ms=10_000,
        width=1920,
        height=1080,
        fps=25.0,
    )
    segment = VideoSegment(
        video_id=video.id,
        start_ms=1_000,
        end_ms=5_000,
        source=SegmentSource.SCENE_DETECTION,
    )
    store.save_prepared_video(
        IngestedVideo(
            video=video,
            metadata=MediaMetadata(
                duration_ms=10_000,
                width=1920,
                height=1080,
                fps=25.0,
                video_codec="h264",
                has_audio=True,
            ),
            segments=[segment],
            frames_by_segment={segment.id: []},
        )
    )
    ai = SemanticAnnotation(
        segment_id=segment.id,
        origin=AnnotationOrigin.AI,
        provider="qwen",
        model="qwen3.7-flash",
        description="A woman walks into a building at night",
        characters=["woman"],
        actions=["walking"],
        scene=["night", "building entrance"],
        emotions=["tense"],
        objects=["umbrella"],
        ocr=["EXIT"],
        shot_type="medium",
        camera_motion="static",
        confidence=0.91,
        revision=1,
    )
    store.save_annotation(ai)
    return store, segment, ai


def _app(store: CatalogStore, indexer: SemanticIndexer | None) -> FastAPI:
    app = FastAPI()
    app.include_router(library_router)
    app.state.library_catalog = store
    app.state.semantic_indexer = indexer
    return app


@pytest.mark.asyncio
async def test_human_correction_creates_revision_and_reindexes_effective_annotation(
    tmp_path: Path,
) -> None:
    store, segment, ai = _catalog_with_ai_annotation(tmp_path)
    provider = RecordingEmbeddingProvider()
    indexer = SemanticIndexer(store=store, provider=provider)
    assert await indexer.index_segment(segment.id) is True
    client = TestClient(_app(store, indexer))

    before = client.get(f"/api/v1/library/segments/{segment.id}/annotation")
    assert before.status_code == 200
    assert before.json()["id"] == str(ai.id)
    assert before.json()["origin"] == "ai"

    response = client.patch(
        f"/api/v1/library/segments/{segment.id}/annotation",
        json={
            "description": "一个女人在雨夜走进建筑入口",
            "characters": ["成年女性"],
            "actions": ["撑伞", "走进入口"],
            "emotions": ["紧张", "犹豫"],
            "locked": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    annotation = body["annotation"]
    assert body["embedding_updated"] is True
    assert annotation["origin"] == "human"
    assert annotation["provider"] is None
    assert annotation["model"] is None
    assert annotation["revision"] == 2
    assert annotation["verified"] is True
    assert annotation["locked"] is True
    assert annotation["description"] == "一个女人在雨夜走进建筑入口"
    assert annotation["characters"] == ["成年女性"]
    assert annotation["actions"] == ["撑伞", "走进入口"]
    assert annotation["emotions"] == ["紧张", "犹豫"]
    assert annotation["scene"] == ["night", "building entrance"]
    assert annotation["objects"] == ["umbrella"]
    assert annotation["ocr"] == ["EXIT"]
    assert annotation["shot_type"] == "medium"
    assert annotation["camera_motion"] == "static"

    history = store.list_annotations(segment.id)
    assert [item.origin for item in history] == [AnnotationOrigin.AI, AnnotationOrigin.HUMAN]
    assert history[0].id == ai.id
    assert history[1].id != ai.id

    effective_embedding = store.get_effective_embedding(
        segment.id,
        provider=provider.name,
        model=provider.model,
        dimensions=provider.dimensions,
    )
    assert effective_embedding is not None
    assert effective_embedding.annotation_id == history[1].id
    assert effective_embedding.annotation_revision == 2
    assert provider.document_calls == [
        [build_retrieval_text(ai)],
        [build_retrieval_text(history[1])],
    ]

    second = client.patch(
        f"/api/v1/library/segments/{segment.id}/annotation",
        json={"emotions": ["警觉"], "locked": True},
    )
    assert second.status_code == 200
    assert second.json()["annotation"]["revision"] == 3
    assert second.json()["annotation"]["description"] == "一个女人在雨夜走进建筑入口"
    assert second.json()["annotation"]["emotions"] == ["警觉"]
    assert len(store.list_annotations(segment.id)) == 3


@pytest.mark.asyncio
async def test_correction_requires_embedding_runtime_before_mutating_history(tmp_path: Path) -> None:
    store, segment, ai = _catalog_with_ai_annotation(tmp_path)
    client = TestClient(_app(store, None))

    response = client.patch(
        f"/api/v1/library/segments/{segment.id}/annotation",
        json={"description": "人工修正", "locked": True},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "semantic indexer is not configured"}
    annotations = store.list_annotations(segment.id)
    assert len(annotations) == 1
    assert annotations[0].id == ai.id
