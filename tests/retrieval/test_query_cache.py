from pathlib import Path
from uuid import uuid4

import pytest

from clipatlas.catalog.store import CatalogStore
from clipatlas.director.requirements import parse_script_visual_requirements
from clipatlas.embeddings.contracts import EmbeddingVector
from clipatlas.retrieval.query_cache import RequirementQueryEmbeddingService


class FakeEmbeddingProvider:
    name = "fake-text"
    model = "fake-v1"
    dimensions = 3

    def __init__(self) -> None:
        self.calls = 0

    async def embed_documents(self, texts: list[str]) -> list[EmbeddingVector]:
        self.calls += 1
        return [EmbeddingVector(values=[float(index + 1), 0.0, 1.0]) for index, _ in enumerate(texts)]

    async def embed_query(self, text: str) -> EmbeddingVector:
        raise AssertionError("query vectors must be prepared in the upload stage")


@pytest.mark.asyncio
async def test_requirement_query_vectors_are_prepared_once(tmp_path: Path):
    catalog = CatalogStore(tmp_path / "library.sqlite3")
    provider = FakeEmbeddingProvider()
    requirements = parse_script_visual_requirements("\u6cf0\u94bd700\u5728\u6c99\u783e\u8def\u9762\u884c\u9a76\u3002")
    service = RequirementQueryEmbeddingService(
        catalog=catalog,
        provider=provider,
        protocol_version="visual-retrieval-v2",
        event_index_revision="events-test-1",
    )

    assert await service.prepare(requirements) == 1
    assert await service.prepare(requirements) == 0
    assert provider.calls == 1
    cached = catalog.get_query_embedding(
        requirements[0].id,
        source_text_hash=requirements[0].source_text_hash,
        provider=provider.name,
        model=provider.model,
        dimensions=provider.dimensions,
        protocol_version="visual-retrieval-v2",
        event_index_revision="events-test-1",
    )
    assert cached is not None and cached.vector == [1.0, 0.0, 1.0]
