from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator

from wlos.core.base import DomainModel
from wlos.shared.clock import ensure_utc, utc_now


class SourceType(StrEnum):
    USER_DECLARED = "USER_DECLARED"
    USER_ACTION = "USER_ACTION"
    SYSTEM_DERIVED = "SYSTEM_DERIVED"
    AI_INFERRED = "AI_INFERRED"
    CALENDAR = "CALENDAR"
    EXTERNAL_CONNECTOR = "EXTERNAL_CONNECTOR"
    RADAR = "RADAR"
    OPERATOR_RESULT = "OPERATOR_RESULT"


INFERENTIAL_SOURCES: frozenset[SourceType] = frozenset({SourceType.AI_INFERRED, SourceType.RADAR})
"""Sources that produce claims, not facts. They must carry a confidence below 1.0."""

DETERMINISTIC_SOURCES: frozenset[SourceType] = frozenset(
    {
        SourceType.USER_DECLARED,
        SourceType.USER_ACTION,
        SourceType.SYSTEM_DERIVED,
        SourceType.CALENDAR,
        SourceType.EXTERNAL_CONNECTOR,
        SourceType.OPERATOR_RESULT,
    }
)


class SourceRef(DomainModel):
    """Where a fact, relationship or memory came from."""

    source_type: SourceType
    reference: str | None = None
    connector: str | None = None
    observed_at: datetime = Field(default_factory=utc_now)
    note: str | None = None

    @field_validator("observed_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @property
    def is_inferential(self) -> bool:
        return self.source_type in INFERENTIAL_SOURCES

    @classmethod
    def user_declared(cls, *, note: str | None = None) -> SourceRef:
        return cls(source_type=SourceType.USER_DECLARED, note=note)

    @classmethod
    def ai_inferred(cls, *, reference: str | None = None, note: str | None = None) -> SourceRef:
        return cls(source_type=SourceType.AI_INFERRED, reference=reference, note=note)
