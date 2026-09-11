from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from wlos.core.base import DomainModel
from wlos.core.errors import TemporalError
from wlos.core.invariants import resolve_confidence
from wlos.personal_life_graph.domains import EntityType, LifeDomain, default_sensitivity, domain_of
from wlos.personal_life_graph.schemas import validate_attributes
from wlos.shared.attributes import Attributes
from wlos.shared.clock import ensure_utc, utc_now
from wlos.shared.confidence import Confidence
from wlos.shared.identifiers import EntityId, OwnerId, new_entity_id
from wlos.shared.provenance import SourceRef
from wlos.shared.sensitivity import Sensitivity
from wlos.shared.temporal import TemporalWindow


class EntityStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ARCHIVED = "ARCHIVED"
    SUPERSEDED = "SUPERSEDED"


class Entity(DomainModel):
    """A node in the Personal Life Graph.

    Immutable: updates return a new value with a bumped ``updated_at``, so a
    superseded state can always be kept alongside the one that replaced it.
    """

    id: EntityId = Field(default_factory=new_entity_id)
    entity_type: EntityType
    owner_id: OwnerId
    attributes: Attributes = Field(default_factory=dict)
    status: EntityStatus = EntityStatus.ACTIVE
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    valid_from: datetime = Field(default_factory=utc_now)
    valid_until: datetime | None = None
    source: SourceRef
    confidence: Confidence = 1.0
    sensitivity: Sensitivity
    metadata: Attributes = Field(default_factory=dict)

    @field_validator("created_at", "updated_at", "valid_from", "valid_until")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)

    @model_validator(mode="after")
    def _consistent(self) -> Entity:
        if self.valid_until is not None and self.valid_until < self.valid_from:
            raise TemporalError(f"entity {self.id}: valid_until precedes valid_from")
        if self.updated_at < self.created_at:
            raise TemporalError(f"entity {self.id}: updated_at precedes created_at")
        if self.sensitivity < default_sensitivity(self.entity_type):
            raise ValueError(
                f"entity {self.id}: {self.entity_type} may not be classified below "
                f"{default_sensitivity(self.entity_type).name}"
            )
        resolve_confidence(self.source, self.confidence)
        return self

    @property
    def domain(self) -> LifeDomain:
        return domain_of(self.entity_type)

    @property
    def window(self) -> TemporalWindow:
        return TemporalWindow(valid_from=self.valid_from, valid_until=self.valid_until)

    def is_active_at(self, moment: datetime) -> bool:
        return self.status is EntityStatus.ACTIVE and self.window.covers(moment)

    def with_attributes(self, attributes: Attributes, *, at: datetime | None = None) -> Entity:
        moment = ensure_utc(at) if at is not None else utc_now()
        return self.model_copy(
            update={"attributes": {**self.attributes, **attributes}, "updated_at": moment}
        )

    def with_status(self, status: EntityStatus, *, at: datetime | None = None) -> Entity:
        moment = ensure_utc(at) if at is not None else utc_now()
        return self.model_copy(update={"status": status, "updated_at": moment})

    def invalidated_at(self, moment: datetime, *, status: EntityStatus | None = None) -> Entity:
        """Close the validity window without deleting anything."""
        closed = ensure_utc(moment)
        return self.model_copy(
            update={
                "valid_until": closed,
                "updated_at": closed,
                "status": status or EntityStatus.SUPERSEDED,
            }
        )


def make_entity(
    *,
    entity_type: EntityType,
    owner_id: OwnerId,
    source: SourceRef,
    attributes: Attributes | None = None,
    confidence: float | None = None,
    sensitivity: Sensitivity | None = None,
    status: EntityStatus = EntityStatus.ACTIVE,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    metadata: Attributes | None = None,
    at: datetime | None = None,
) -> Entity:
    """Build an entity with provenance, confidence and sensitivity resolved by the domain rules."""
    moment = ensure_utc(at) if at is not None else utc_now()
    resolved_attributes = dict(attributes or {})
    validate_attributes(entity_type, resolved_attributes)
    floor = default_sensitivity(entity_type)
    return Entity(
        entity_type=entity_type,
        owner_id=owner_id,
        attributes=resolved_attributes,
        status=status,
        created_at=moment,
        updated_at=moment,
        valid_from=ensure_utc(valid_from) if valid_from is not None else moment,
        valid_until=valid_until,
        source=source,
        confidence=resolve_confidence(source, confidence),
        sensitivity=max(sensitivity, floor) if sensitivity is not None else floor,
        metadata=dict(metadata or {}),
    )
