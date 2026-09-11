from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, SerializeAsAny, field_validator, model_validator

from wlos.core.base import DomainModel
from wlos.core.errors import EventIntegrityError, TemporalError
from wlos.core.minds import Mind
from wlos.events.catalog import EventType
from wlos.events.payloads import EventPayload, GenericPayload, payload_type_for
from wlos.personal_life_graph.domains import EntityType
from wlos.shared.attributes import Attributes
from wlos.shared.clock import ensure_utc, utc_now
from wlos.shared.identifiers import (
    CausationId,
    CorrelationId,
    EventId,
    OwnerId,
    new_correlation_id,
    new_event_id,
)
from wlos.shared.provenance import SourceRef
from wlos.shared.sensitivity import Sensitivity

CURRENT_SCHEMA_VERSION = 1


class ActorType(StrEnum):
    USER = "USER"
    MIND = "MIND"
    ORCHESTRATOR = "ORCHESTRATOR"
    SYSTEM = "SYSTEM"
    CONNECTOR = "CONNECTOR"


class SubjectType(StrEnum):
    ENTITY = "ENTITY"
    RELATIONSHIP = "RELATIONSHIP"
    MEMORY = "MEMORY"
    ACTION = "ACTION"
    USER = "USER"
    SYSTEM = "SYSTEM"


class Actor(DomainModel):
    """Who caused the event."""

    actor_type: ActorType
    actor_id: str
    mind: Mind | None = None

    @model_validator(mode="after")
    def _mind_consistency(self) -> Actor:
        if (self.actor_type is ActorType.MIND) != (self.mind is not None):
            raise EventIntegrityError("actor_type MIND and the mind field must agree")
        return self

    @classmethod
    def user(cls, owner_id: OwnerId) -> Actor:
        return cls(actor_type=ActorType.USER, actor_id=str(owner_id))

    @classmethod
    def of_mind(cls, mind: Mind) -> Actor:
        return cls(actor_type=ActorType.MIND, actor_id=str(mind), mind=mind)

    @classmethod
    def orchestrator(cls) -> Actor:
        return cls(actor_type=ActorType.ORCHESTRATOR, actor_id="orchestrator")


class Subject(DomainModel):
    """What the event is about."""

    subject_type: SubjectType
    subject_id: str
    entity_type: EntityType | None = None

    @classmethod
    def entity(cls, entity_id: str, entity_type: EntityType) -> Subject:
        return cls(subject_type=SubjectType.ENTITY, subject_id=entity_id, entity_type=entity_type)

    @classmethod
    def action(cls, action_id: str) -> Subject:
        return cls(subject_type=SubjectType.ACTION, subject_id=action_id)

    @classmethod
    def memory(cls, memory_id: str) -> Subject:
        return cls(subject_type=SubjectType.MEMORY, subject_id=memory_id)


class DomainEvent(DomainModel):
    """The single envelope every change in the system is recorded in.

    Recorded events are immutable. A correction is a new event, never an edit.
    """

    event_id: EventId = Field(default_factory=new_event_id)
    event_type: EventType
    schema_version: int = CURRENT_SCHEMA_VERSION
    occurred_at: datetime
    recorded_at: datetime = Field(default_factory=utc_now)
    actor: Actor
    subject: Subject
    correlation_id: CorrelationId
    causation_id: CausationId | None = None
    source: SourceRef
    sensitivity: Sensitivity = Sensitivity.S1
    payload: SerializeAsAny[EventPayload] = Field(default_factory=GenericPayload)
    metadata: Attributes = Field(default_factory=dict)

    @field_validator("occurred_at", "recorded_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("schema_version")
    @classmethod
    def _positive(cls, value: int) -> int:
        if value < 1:
            raise EventIntegrityError("schema_version must be >= 1")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> DomainEvent:
        if self.recorded_at < self.occurred_at:
            raise TemporalError(f"event {self.event_id}: recorded_at precedes occurred_at")
        expected = payload_type_for(self.event_type)
        if expected is not GenericPayload and not isinstance(self.payload, expected):
            raise EventIntegrityError(
                f"{self.event_type} requires payload {expected.__name__}, "
                f"got {type(self.payload).__name__}"
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DomainEvent:
        """Rebuild an event, restoring the concrete payload type from the catalog."""
        raw = dict(data)
        event_type = EventType(raw["event_type"])
        payload_cls = payload_type_for(event_type)
        payload = raw.get("payload") or {}
        if not isinstance(payload, EventPayload):
            payload = payload_cls.model_validate(payload)
        return cls.model_validate({**raw, "event_type": event_type, "payload": payload})


def make_event(
    *,
    event_type: EventType,
    actor: Actor,
    subject: Subject,
    source: SourceRef,
    payload: EventPayload | None = None,
    occurred_at: datetime | None = None,
    recorded_at: datetime | None = None,
    correlation_id: CorrelationId | None = None,
    causation_id: CausationId | None = None,
    sensitivity: Sensitivity = Sensitivity.S1,
    metadata: Attributes | None = None,
) -> DomainEvent:
    occurred = ensure_utc(occurred_at) if occurred_at is not None else utc_now()
    recorded = ensure_utc(recorded_at) if recorded_at is not None else max(occurred, utc_now())
    return DomainEvent(
        event_type=event_type,
        occurred_at=occurred,
        recorded_at=recorded,
        actor=actor,
        subject=subject,
        correlation_id=correlation_id or new_correlation_id(),
        causation_id=causation_id,
        source=source,
        sensitivity=sensitivity,
        payload=payload or GenericPayload(),
        metadata=dict(metadata or {}),
    )


def caused_by(
    parent: DomainEvent,
    *,
    event_type: EventType,
    actor: Actor,
    subject: Subject,
    source: SourceRef,
    payload: EventPayload | None = None,
    occurred_at: datetime | None = None,
    sensitivity: Sensitivity | None = None,
    metadata: Attributes | None = None,
) -> DomainEvent:
    """Continue a causal chain: same correlation, this event's cause recorded."""
    return make_event(
        event_type=event_type,
        actor=actor,
        subject=subject,
        source=source,
        payload=payload,
        occurred_at=occurred_at,
        correlation_id=parent.correlation_id,
        causation_id=CausationId(str(parent.event_id)),
        sensitivity=sensitivity if sensitivity is not None else parent.sensitivity,
        metadata=metadata,
    )
