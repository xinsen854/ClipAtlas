from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class EmbeddingVector(BaseModel):
    values: list[float] = Field(min_length=1)


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    async def embed_documents(self, texts: list[str]) -> list[EmbeddingVector]: ...

    async def embed_query(self, text: str) -> EmbeddingVector: ...


@runtime_checkable
class VideoEmbeddingProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def effective_dimensions(self) -> int: ...

    async def embed_video(self, video_path: Path) -> EmbeddingVector: ...

    async def embed_query(self, text: str) -> EmbeddingVector: ...
