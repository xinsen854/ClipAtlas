"""Provider-neutral embedding support."""

from clipatlas.embeddings.contracts import (
    EmbeddingProvider,
    EmbeddingVector,
    VideoEmbeddingProvider,
)

__all__ = ["EmbeddingProvider", "EmbeddingVector", "VideoEmbeddingProvider"]
