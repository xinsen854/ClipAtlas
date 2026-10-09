from pathlib import Path

from clipatlas.embeddings.contracts import (
    EmbeddingProvider,
    EmbeddingVector,
    VideoEmbeddingProvider,
)


class FakeEmbeddingProvider:
    @property
    def name(self) -> str:
        return "fake-embedding"

    @property
    def model(self) -> str:
        return "fake-v1"

    @property
    def dimensions(self) -> int:
        return 3

    async def embed_documents(self, texts: list[str]) -> list[EmbeddingVector]:
        return [EmbeddingVector(values=[1.0, 0.0, 0.0]) for _ in texts]

    async def embed_query(self, text: str) -> EmbeddingVector:
        return EmbeddingVector(values=[1.0, 0.0, 0.0])


class FakeVideoEmbeddingProvider:
    @property
    def name(self) -> str:
        return "fake-video-embedding"

    @property
    def model(self) -> str:
        return "fake-video-v1"

    @property
    def effective_dimensions(self) -> int:
        return 2560

    async def embed_video(self, video_path: Path) -> EmbeddingVector:
        return EmbeddingVector(values=[1.0] + [0.0] * 2559)

    async def embed_query(self, text: str) -> EmbeddingVector:
        return EmbeddingVector(values=[1.0] + [0.0] * 2559)


def test_embedding_provider_protocol_is_runtime_checkable() -> None:
    provider = FakeEmbeddingProvider()

    assert isinstance(provider, EmbeddingProvider)
    assert provider.name == "fake-embedding"
    assert provider.model == "fake-v1"
    assert provider.dimensions == 3


def test_video_embedding_provider_protocol_is_runtime_checkable() -> None:
    provider = FakeVideoEmbeddingProvider()

    assert isinstance(provider, VideoEmbeddingProvider)
    assert provider.name == "fake-video-embedding"
    assert provider.model == "fake-video-v1"
    assert provider.effective_dimensions == 2560


def test_embedding_vector_preserves_numeric_values() -> None:
    vector = EmbeddingVector(values=[0.25, -0.5, 1.0])

    assert vector.values == [0.25, -0.5, 1.0]
