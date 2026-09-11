from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from wplos.core.temporal import ensure_utc


class SourceType(StrEnum):
    """Where a fact came from. Every stored fact must be able to answer this."""

    USER_DECLARED = "USER_DECLARED"
    USER_ACTION = "USER_ACTION"
    SYSTEM_DERIVED = "SYSTEM_DERIVED"
    AI_INFERRED = "AI_INFERRED"
    BEHAVIORAL_INFERENCE = "BEHAVIORAL_INFERENCE"
    CALENDAR = "CALENDAR"
    EXTERNAL_CONNECTOR = "EXTERNAL_CONNECTOR"
    RADAR = "RADAR"
    OPERATOR_RESULT = "OPERATOR_RESULT"

    @property
    def is_inferential(self) -> bool:
        """True when the source produces beliefs rather than observations."""
        return self in _INFERENTIAL

    @property
    def is_authoritative(self) -> bool:
        return not self.is_inferential


_INFERENTIAL: frozenset[SourceType] = frozenset(
    {
        SourceType.AI_INFERRED,
        SourceType.BEHAVIORAL_INFERENCE,
        SourceType.RADAR,
    }
)


class SourceRef(BaseModel):
    """A single, uniform provenance reference used by entities, relationships,
    memories and events alike."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_type: SourceType
    captured_at: datetime
    reference: str | None = Field(
        default=None,
        description="Opaque id of the originating artefact (message, calendar item, row).",
    )
    detail: str | None = None

    @field_validator("captured_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @classmethod
    def user_declared(cls, captured_at: datetime, detail: str | None = None) -> "SourceRef":
        return cls(source_type=SourceType.USER_DECLARED, captured_at=captured_at, detail=detail)

    @classmethod
    def ai_inferred(cls, captured_at: datetime, detail: str | None = None) -> "SourceRef":
        return cls(source_type=SourceType.AI_INFERRED, captured_at=captured_at, detail=detail)

    @property
    def is_inferential(self) -> bool:
        return self.source_type.is_inferential
