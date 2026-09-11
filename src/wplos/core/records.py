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
    """Lifecycle of a stored record. Nothing is ever hard-deleted.

    ``INVALIDATED`` alone is retroactive: it means the record was never true and
    must not be read back as history. A superseded or expired record was true
    once, and an as-of query must still be able to see it.
    """

    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    ARCHIVED = "ARCHIVED"
    SUPPRESSED = "SUPPRESSED"

    @property
    def negates_history(self) -> bool:
        return self is RecordStatus.INVALIDATED

    @property
    def may_be_surfaced(self) -> bool:
        """Suppressed records stay true and stay audited; they are just not
        shown. "Do not mention this" is not "this never happened"."""
        return self is not RecordStatus.SUPPRESSED


class ProvenancedRecord(BaseModel):
    """Shared shape of everything stored in the Personal Life Graph."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    attribution: Attribution
    temporal: TemporalValidity
    status: RecordStatus = RecordStatus.ACTIVE
    revision: int = Field(default=1, ge=1)
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

    @property
    def is_surfaceable(self) -> bool:
        return self.status.may_be_surfaced

    def is_active_at(self, at: datetime) -> bool:
        """Was this record in force at that instant?

        Asking about the past must not depend on the record's status today,
        otherwise closing a record quietly rewrites what the graph says about
        last week.
        """
        return not self.status.negates_history and self.temporal.is_valid_at(at)
