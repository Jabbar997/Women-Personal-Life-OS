from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from wlos.core.base import DomainModel
from wlos.core.errors import TemporalError
from wlos.core.invariants import resolve_confidence
from wlos.personal_life_graph.domains import LifeDomain
from wlos.shared.attributes import Attributes
from wlos.shared.clock import ensure_utc, utc_now
from wlos.shared.confidence import Confidence
from wlos.shared.identifiers import EntityId, MemoryId, OwnerId, new_memory_id
from wlos.shared.provenance import SourceRef
from wlos.shared.sensitivity import Sensitivity


class MemoryType(StrEnum):
    FACT = "FACT"
    PREFERENCE = "PREFERENCE"
    BEHAVIOR = "BEHAVIOR"
    DECISION = "DECISION"
    RELATIONSHIP = "RELATIONSHIP"
    TEMPORAL = "TEMPORAL"


class MemoryStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class MemoryRecord(DomainModel):
    """A durable statement about the user, always carrying where it came from.

    Memory lives in the graph, not in a per-mind silo: every mind reads and
    writes the same records.
    """

    id: MemoryId = Field(default_factory=new_memory_id)
    owner_id: OwnerId
    memory_type: MemoryType
    domain: LifeDomain
    statement: str
    subject_entity_id: EntityId | None = None
    attributes: Attributes = Field(default_factory=dict)
    status: MemoryStatus = MemoryStatus.ACTIVE
    source: SourceRef
    confidence: Confidence = 1.0
    sensitivity: Sensitivity = Sensitivity.S1
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_confirmed_at: datetime | None = None
    review_after: datetime | None = None
    expires_at: datetime | None = None

    @field_validator("created_at", "updated_at", "last_confirmed_at", "review_after", "expires_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)

    @model_validator(mode="after")
    def _consistent(self) -> MemoryRecord:
        if self.expires_at is not None and self.expires_at < self.created_at:
            raise TemporalError(f"memory {self.id}: expires_at precedes created_at")
        resolve_confidence(self.source, self.confidence)
        return self

    def is_live_at(self, moment: datetime) -> bool:
        if self.status is not MemoryStatus.ACTIVE:
            return False
        return self.expires_at is None or ensure_utc(moment) < self.expires_at

    def needs_review_at(self, moment: datetime) -> bool:
        return self.review_after is not None and ensure_utc(moment) >= self.review_after

    def confirmed_at(self, moment: datetime) -> MemoryRecord:
        confirmed = ensure_utc(moment)
        return self.model_copy(update={"last_confirmed_at": confirmed, "updated_at": confirmed})

    def invalidated_at(self, moment: datetime) -> MemoryRecord:
        closed = ensure_utc(moment)
        return self.model_copy(
            update={"status": MemoryStatus.INVALIDATED, "updated_at": closed, "expires_at": closed}
        )


def make_memory(
    *,
    owner_id: OwnerId,
    memory_type: MemoryType,
    domain: LifeDomain,
    statement: str,
    source: SourceRef,
    subject_entity_id: EntityId | None = None,
    attributes: Attributes | None = None,
    confidence: float | None = None,
    sensitivity: Sensitivity = Sensitivity.S1,
    review_after: datetime | None = None,
    expires_at: datetime | None = None,
    at: datetime | None = None,
) -> MemoryRecord:
    moment = ensure_utc(at) if at is not None else utc_now()
    return MemoryRecord(
        owner_id=owner_id,
        memory_type=memory_type,
        domain=domain,
        statement=statement,
        subject_entity_id=subject_entity_id,
        attributes=dict(attributes or {}),
        source=source,
        confidence=resolve_confidence(source, confidence),
        sensitivity=sensitivity,
        created_at=moment,
        updated_at=moment,
        last_confirmed_at=moment if not source.is_inferential else None,
        review_after=review_after,
        expires_at=expires_at,
    )
