from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from clipatlas.domain.models import utc_now


class Project(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
