from datetime import datetime, timedelta
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from wplos.core.capabilities import CapabilitySet
from wplos.core.client import ClientEventId, ClientSessionId, DeviceId, EventOrigin
from wplos.core.identifiers import (
    ActionId,
    CorrelationId,
    EntityId,
    EventId,
    RequestId,
    UserId,
    new_correlation_id,
    new_request_id,
)
from wplos.core.temporal import ensure_utc
from wplos.events.types import EventType

DELAYED_AFTER = timedelta(minutes=2)


class TriggerType(StrEnum):
    USER_REQUEST = "USER_REQUEST"
    DOMAIN_EVENT = "DOMAIN_EVENT"
    SCHEDULED = "SCHEDULED"
    MOBILE_ACTION = "MOBILE_ACTION"
    SYSTEM_REEVALUATION = "SYSTEM_REEVALUATION"


class TriggerRef(BaseModel):
    """What the run is about, by reference rather than by payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: EventType | None = None
    event_id: EventId | None = None
    entity_id: EntityId | None = None
    action_id: ActionId | None = None
    label: str | None = None


class ClientContext(BaseModel):
    """What the server needs to know about the client, and nothing more.

    Device identity stays here: it is transport, used for idempotency and
    debugging. It never reaches the Personal Life Graph.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    origin: EventOrigin
    client_request_id: ClientEventId | None = None
    device_id: DeviceId | None = None
    session_id: ClientSessionId | None = None
    capabilities: CapabilitySet = CapabilitySet()
    time_zone: str | None = None


class RuntimeRequest(BaseModel):
    """One run of the Orchestrator.

    ``occurred_at`` is when she did it; ``received_at`` is when the server heard
    about it. An intent formed offline two hours ago is not an instruction to
    act as though it were formed now.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: RequestId
    user_id: UserId
    trigger: TriggerType
    trigger_ref: TriggerRef
    occurred_at: datetime
    received_at: datetime
    correlation_id: CorrelationId
    client: ClientContext | None = None
    utterance: str | None = None

    @field_validator("occurred_at", "received_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @model_validator(mode="after")
    def _trigger_carries_what_it_needs(self) -> Self:
        if self.trigger is TriggerType.DOMAIN_EVENT and self.trigger_ref.event_type is None:
            raise ValueError("a DOMAIN_EVENT run must name the event type")
        if self.trigger is TriggerType.MOBILE_ACTION and (
            self.client is None or self.client.client_request_id is None
        ):
            raise ValueError("a MOBILE_ACTION run must carry a client request id")
        if self.received_at < self.occurred_at:
            raise ValueError("a request cannot be received before it happened")
        return self

    @classmethod
    def from_user(
        cls,
        *,
        user_id: UserId,
        at: datetime,
        utterance: str | None = None,
        client: ClientContext | None = None,
        correlation_id: CorrelationId | None = None,
    ) -> "RuntimeRequest":
        return cls(
            request_id=new_request_id(),
            user_id=user_id,
            trigger=TriggerType.USER_REQUEST,
            trigger_ref=TriggerRef(label=utterance),
            occurred_at=at,
            received_at=at,
            correlation_id=correlation_id or new_correlation_id(),
            client=client,
            utterance=utterance,
        )

    @classmethod
    def from_event(
        cls,
        *,
        user_id: UserId,
        event_type: EventType,
        at: datetime,
        entity_id: EntityId | None = None,
        action_id: ActionId | None = None,
        correlation_id: CorrelationId | None = None,
    ) -> "RuntimeRequest":
        return cls(
            request_id=new_request_id(),
            user_id=user_id,
            trigger=TriggerType.DOMAIN_EVENT,
            trigger_ref=TriggerRef(event_type=event_type, entity_id=entity_id, action_id=action_id),
            occurred_at=at,
            received_at=at,
            correlation_id=correlation_id or new_correlation_id(),
        )

    @property
    def delay(self) -> timedelta:
        return self.received_at - self.occurred_at

    @property
    def arrived_late(self) -> bool:
        """Formed on a device that could not reach us at the time."""
        return self.delay > DELAYED_AFTER

    @property
    def client_request_id(self) -> ClientEventId | None:
        return None if self.client is None else self.client.client_request_id

    def capabilities(self) -> CapabilitySet:
        return CapabilitySet() if self.client is None else self.client.capabilities
