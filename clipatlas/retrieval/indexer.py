from uuid import UUID

from clipatlas.catalog.store import CatalogStore
from clipatlas.embeddings.contracts import EmbeddingProvider
from clipatlas.providers.errors import ProviderRequestError
from clipatlas.retrieval.models import SegmentEmbedding
from clipatlas.retrieval.semantics import build_retrieval_text


class SemanticIndexer:
    def __init__(self, *, store: CatalogStore, provider: EmbeddingProvider) -> None:
        self._store = store
        self._provider = provider

    async def index_segment(self, segment_id: UUID) -> bool:
        annotation = self._store.get_effective_annotation(segment_id)
        if annotation is None:
            return False

        current = self._store.get_effective_embedding(
            segment_id,
            provider=self._provider.name,
            model=self._provider.model,
            dimensions=self._provider.dimensions,
        )
        if (
            current is not None
            and current.annotation_id == annotation.id
            and current.annotation_revision == annotation.revision
        ):
            return False

        vectors = await self._provider.embed_documents([build_retrieval_text(annotation)])
        if len(vectors) != 1:
            raise ProviderRequestError("Embedding provider must return exactly one vector")

        self._store.save_embedding(
            SegmentEmbedding(
                segment_id=segment_id,
                annotation_id=annotation.id,
                annotation_revision=annotation.revision,
                provider=self._provider.name,
                model=self._provider.model,
                dimensions=self._provider.dimensions,
                vector=vectors[0].values,
            )
        )
        return True

    async def index_pending(self, limit: int | None = None) -> int:
        generated = 0
        for segment_id in self._store.list_segment_ids(limit=limit):
            if await self.index_segment(segment_id):
                generated += 1
        return generated
