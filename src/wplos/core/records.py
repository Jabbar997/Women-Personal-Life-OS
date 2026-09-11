from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from wplos.core.attribution import Attribution
from wplos.core.confidence import Confidence
from wplos.core.provenance import SourceRef
from wplos.core.sensitivity import SensitivityLevel
from wplos.core.temporal import TemporalValidity, ensure_utc
from wplos.shared.json import JsonValue


class RecordStatus(StrEnum):
    """Lifecycle of a stored record. Nothing is ever hard-deleted."""

    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    ARCHIVED = "ARCHIVED"


class ProvenancedRecord(BaseModel):
    """Shared shape of everything stored in the Personal Life Graph."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    attribution: Attribution
    temporal: TemporalValidity
    status: RecordStatus = RecordStatus.ACTIVE
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("created_at", "updated_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @property
    def source(self) -> SourceRef:
        return self.attribution.source

    @property
    def confidence(self) -> Confidence:
        return self.attribution.confidence

    @property
    def sensitivity(self) -> SensitivityLevel:
        return self.attribution.sensitivity

    def is_active_at(self, at: datetime) -> bool:
        return self.status is RecordStatus.ACTIVE and self.temporal.is_valid_at(at)
