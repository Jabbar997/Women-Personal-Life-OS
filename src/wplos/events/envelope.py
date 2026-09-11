from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny, field_validator, model_validator

from wplos.core.identifiers import (
    CorrelationId,
    EntityId,
    EventId,
    UserId,
    new_correlation_id,
    new_event_id,
)
from wplos.core.provenance import SourceRef
from wplos.core.roles import ActorRole, AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.core.temporal import ensure_utc
from wplos.events.payloads import EventPayload, payload_model_for
from wplos.events.types import EventType
from wplos.shared.json import JsonValue

CURRENT_SCHEMA_VERSION = 1


class Actor(BaseModel):
    """Who acted. An agent actor names which of the six minds it was."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: ActorRole
    user_id: UserId | None = None
    agent: AgentName | None = None

    @model_validator(mode="after")
    def _role_matches_identity(self) -> Self:
        if self.role is ActorRole.AGENT and self.agent is None:
            raise ValueError("an AGENT actor must name the agent")
        if self.role is ActorRole.USER and self.user_id is None:
            raise ValueError("a USER actor must carry a user_id")
        return self

    @classmethod
    def user(cls, user_id: UserId) -> "Actor":
        return cls(role=ActorRole.USER, user_id=user_id)

    @classmethod
    def agent_actor(cls, agent: AgentName, user_id: UserId | None = None) -> "Actor":
        return cls(role=ActorRole.AGENT, agent=agent, user_id=user_id)

    @classmethod
    def orchestrator(cls, user_id: UserId | None = None) -> "Actor":
        return cls(role=ActorRole.ORCHESTRATOR, user_id=user_id)


class Subject(BaseModel):
    """What the event is about."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    owner_id: UserId
    entity_id: EntityId | None = None


class DomainEvent(BaseModel):
    """The one envelope every change in the system is expressed in.

    Frozen on purpose: a recorded event is history. Corrections are new events,
    never edits, and ``schema_version`` lets payload shapes evolve without
    rewriting what has already happened.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: EventId
    event_type: EventType
    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION, ge=1)
    occurred_at: datetime
    recorded_at: datetime
    actor: Actor
    subject: Subject
    correlation_id: CorrelationId
    causation_id: EventId | None = None
    source: SourceRef
    sensitivity: SensitivityLevel
    payload: SerializeAsAny[EventPayload]
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("occurred_at", "recorded_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @model_validator(mode="before")
    @classmethod
    def _coerce_payload(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        raw = data.get("payload")
        event_type = data.get("event_type")
        if not isinstance(raw, dict) or event_type is None:
            return data
        model = payload_model_for(EventType(event_type))
        return {**data, "payload": model.model_validate(raw)}

    @model_validator(mode="after")
    def _payload_matches_type(self) -> Self:
        expected = payload_model_for(self.event_type)
        if not isinstance(self.payload, expected):
            raise ValueError(
                f"{self.event_type} requires {expected.__name__}, got {type(self.payload).__name__}"
            )
        return self

    @classmethod
    def emit(
        cls,
        *,
        event_type: EventType,
        payload: EventPayload,
        actor: Actor,
        subject: Subject,
        source: SourceRef,
        sensitivity: SensitivityLevel,
        occurred_at: datetime,
        recorded_at: datetime | None = None,
        correlation_id: CorrelationId | None = None,
        causation_id: EventId | None = None,
        metadata: dict[str, JsonValue] | None = None,
    ) -> "DomainEvent":
        return cls(
            event_id=new_event_id(),
            event_type=event_type,
            occurred_at=occurred_at,
            recorded_at=recorded_at or occurred_at,
            actor=actor,
            subject=subject,
            correlation_id=correlation_id or new_correlation_id(),
            causation_id=causation_id,
            source=source,
            sensitivity=sensitivity,
            payload=payload,
            metadata=metadata or {},
        )

    def caused(
        self,
        *,
        event_type: EventType,
        payload: EventPayload,
        actor: Actor,
        source: SourceRef,
        sensitivity: SensitivityLevel,
        occurred_at: datetime,
        subject: Subject | None = None,
        metadata: dict[str, JsonValue] | None = None,
    ) -> "DomainEvent":
        """Derive a consequence of this event, carrying the correlation forward."""
        return DomainEvent.emit(
            event_type=event_type,
            payload=payload,
            actor=actor,
            subject=subject or self.subject,
            source=source,
            sensitivity=sensitivity,
            occurred_at=occurred_at,
            correlation_id=self.correlation_id,
            causation_id=self.event_id,
            metadata=metadata,
        )

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: str) -> "DomainEvent":
        return cls.model_validate_json(raw)
