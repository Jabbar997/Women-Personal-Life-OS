from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from wlos.core.base import DomainModel
from wlos.core.errors import TemporalError
from wlos.core.invariants import resolve_confidence
from wlos.shared.attributes import Attributes
from wlos.shared.clock import ensure_utc, utc_now
from wlos.shared.confidence import Confidence
from wlos.shared.identifiers import EntityId, RelationshipId, new_relationship_id
from wlos.shared.provenance import SourceRef
from wlos.shared.temporal import TemporalWindow


class RelationshipType(StrEnum):
    HAS_GOAL = "HAS_GOAL"
    LIKES = "LIKES"
    DISLIKES = "DISLIKES"
    USES = "USES"
    OWNS = "OWNS"
    CONTAINS = "CONTAINS"
    REQUIRES = "REQUIRES"
    SUPPORTED_BY = "SUPPORTED_BY"
    RELATED_TO = "RELATED_TO"
    HAS_STATUS = "HAS_STATUS"
    WORKS_AT = "WORKS_AT"
    ENROLLED_IN = "ENROLLED_IN"
    LOCATED_AT = "LOCATED_AT"
    SCHEDULED_AT = "SCHEDULED_AT"
    COMMITTED_TO = "COMMITTED_TO"
    BLOCKS = "BLOCKS"
    DERIVED_FROM = "DERIVED_FROM"
    SUPERSEDES = "SUPERSEDES"


class Relationship(DomainModel):
    """A directed, time-bounded edge between two entities."""

    id: RelationshipId = Field(default_factory=new_relationship_id)
    from_entity_id: EntityId
    relationship_type: RelationshipType
    to_entity_id: EntityId
    attributes: Attributes = Field(default_factory=dict)
    confidence: Confidence = 1.0
    source: SourceRef
    valid_from: datetime = Field(default_factory=utc_now)
    valid_until: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at", "valid_from", "valid_until")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)

    @model_validator(mode="after")
    def _consistent(self) -> Relationship:
        if self.valid_until is not None and self.valid_until < self.valid_from:
            raise TemporalError(f"relationship {self.id}: valid_until precedes valid_from")
        if self.from_entity_id == self.to_entity_id:
            raise ValueError(f"relationship {self.id}: self-referential edge")
        resolve_confidence(self.source, self.confidence)
        return self

    @property
    def window(self) -> TemporalWindow:
        return TemporalWindow(valid_from=self.valid_from, valid_until=self.valid_until)

    def is_active_at(self, moment: datetime) -> bool:
        return self.window.covers(moment)

    def expired_at(self, moment: datetime) -> Relationship:
        """Close the edge. The row stays; only its validity window ends."""
        closed = ensure_utc(moment)
        if closed < self.valid_from:
            raise TemporalError(f"relationship {self.id}: cannot expire before it began")
        return self.model_copy(update={"valid_until": closed})


def make_relationship(
    *,
    from_entity_id: EntityId,
    relationship_type: RelationshipType,
    to_entity_id: EntityId,
    source: SourceRef,
    attributes: Attributes | None = None,
    confidence: float | None = None,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    at: datetime | None = None,
) -> Relationship:
    moment = ensure_utc(at) if at is not None else utc_now()
    return Relationship(
        from_entity_id=from_entity_id,
        relationship_type=relationship_type,
        to_entity_id=to_entity_id,
        attributes=dict(attributes or {}),
        confidence=resolve_confidence(source, confidence),
        source=source,
        valid_from=ensure_utc(valid_from) if valid_from is not None else moment,
        valid_until=valid_until,
        created_at=moment,
    )
