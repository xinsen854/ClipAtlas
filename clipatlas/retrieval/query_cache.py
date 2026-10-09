"""Prepare and persist requirement query vectors before rough-cut planning."""

from collections.abc import Sequence

from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.visual_protocol import ScriptVisualRequirement
from clipatlas.embeddings.contracts import EmbeddingProvider
from clipatlas.retrieval.models import QueryEmbedding


class RequirementQueryEmbeddingService:
    def __init__(
        self,
        *,
        catalog: CatalogStore,
        provider: EmbeddingProvider,
        protocol_version: str,
        event_index_revision: str,
    ) -> None:
        self._catalog = catalog
        self._provider = provider
        self._protocol_version = protocol_version
        self._event_index_revision = event_index_revision

    async def prepare(self, requirements: Sequence[ScriptVisualRequirement]) -> int:
        pending = [requirement for requirement in requirements if self._catalog.get_query_embedding(
            requirement.id,
            source_text_hash=requirement.source_text_hash,
            provider=self._provider.name,
            model=self._provider.model,
            dimensions=self._provider.dimensions,
            protocol_version=self._protocol_version,
            event_index_revision=self._event_index_revision,
        ) is None]
        if not pending:
            return 0
        texts = [
            " ".join(dict.fromkeys((
                requirement.source_quote,
                *requirement.accepted_expressions,
                *requirement.proof_expressions,
                *requirement.related_expressions,
            )))
            for requirement in pending
        ]
        vectors = await self._provider.embed_documents(texts)
        if len(vectors) != len(pending):
            raise ValueError("embedding provider returned an unexpected vector count")
        for index, (requirement, vector) in enumerate(zip(pending, vectors, strict=True)):
            if len(vector.values) != self._provider.dimensions:
                raise ValueError("embedding dimensions do not match provider contract")
            self._catalog.save_query_embedding(QueryEmbedding(
                requirement_id=requirement.id,
                source_text_hash=requirement.source_text_hash,
                provider=self._provider.name,
                model=self._provider.model,
                dimensions=self._provider.dimensions,
                protocol_version=self._protocol_version,
                event_index_revision=self._event_index_revision,
                vector=vector.values,
                api_request_count=1 if index == 0 else 0,
            ))
        return len(pending)
