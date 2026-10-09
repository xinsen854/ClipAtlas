from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class RuleKind(StrEnum):
    PRONUNCIATION = "pronunciation"
    SPEECH_SUPPRESS = "speech_suppress"
    SPEECH_REPLACE = "speech_replace"
    SUBTITLE_REPLACE = "subtitle_replace"
    ENTITY_ALIAS = "entity_alias"
    SEMANTIC_HINT = "semantic_hint"


class RulePackStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"


class ProjectRule(BaseModel):
    kind: RuleKind
    match: str | None = None
    replacement: str | None = None
    hint: str | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def validate_by_kind(self) -> "ProjectRule":
        replacement_kinds = {
            RuleKind.PRONUNCIATION,
            RuleKind.SPEECH_REPLACE,
            RuleKind.SUBTITLE_REPLACE,
            RuleKind.ENTITY_ALIAS,
        }

        if self.kind in replacement_kinds:
            if not self.match or self.replacement is None:
                raise ValueError(f"{self.kind.value} requires match and replacement")
            # replacement == "" is a deletion: e.g. broadcast-norm wording that
            # must not appear in subtitles is removed entirely.
            if self.hint is not None:
                raise ValueError(f"{self.kind.value} does not accept hint")
            return self

        if self.kind == RuleKind.SPEECH_SUPPRESS:
            if not self.match:
                raise ValueError("speech_suppress requires match")
            if self.replacement is not None or self.hint is not None:
                raise ValueError("speech_suppress accepts only match")
            return self

        if self.kind == RuleKind.SEMANTIC_HINT:
            if not self.hint:
                raise ValueError("semantic_hint requires hint")
            if self.match is not None or self.replacement is not None:
                raise ValueError("semantic_hint accepts only hint")
            return self

        raise ValueError(f"unsupported rule kind: {self.kind}")


class ProjectRulePack(BaseModel):
    project_id: UUID
    revision: int = Field(ge=1)
    status: RulePackStatus
    rules: list[ProjectRule] = Field(default_factory=list)


class ProjectedText(BaseModel):
    canonical_text: str
    speech_text: str
    subtitle_text: str
    retrieval_text: str
    semantic_hints: list[str] = Field(default_factory=list)
