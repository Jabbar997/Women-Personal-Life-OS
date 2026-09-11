"""Tests 4 and 5: events serialize losslessly and carry their causal chain."""

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from wplos.core.identifiers import EntityId, UserId
from wplos.core.provenance import SourceRef, SourceType
from wplos.core.roles import AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.events.bus import InMemoryEventBus
from wplos.events.envelope import CURRENT_SCHEMA_VERSION, Actor, DomainEvent, Subject
from wplos.events.payloads import (
    PAYLOAD_BY_EVENT,
    CaptureKind,
    CapturePayload,
    DeadlinePayload,
    OpenLoopPayload,
    payload_model_for,
)
from wplos.events.types import EventType
from wplos.personal_life_graph.attributes import OpenLoopState
from wplos.personal_life_graph.entity_types import EntityType
from wplos.shared.errors import InvariantViolation


def _capture(owner: UserId, at: datetime) -> DomainEvent:
    return DomainEvent.emit(
        event_type=EventType.CAPTURE_RECEIVED,
        payload=CapturePayload(capture_id="cap_1", kind=CaptureKind.TEXT),
        actor=Actor.user(owner),
        subject=Subject(owner_id=owner),
        source=SourceRef.user_declared(at),
        sensitivity=SensitivityLevel.S1,
        occurred_at=at,
    )


def test_every_catalogued_event_has_a_payload_schema() -> None:
    assert {event_type: PAYLOAD_BY_EVENT[event_type] for event_type in EventType}
    for event_type in EventType:
        assert payload_model_for(event_type) is PAYLOAD_BY_EVENT[event_type]


def test_event_round_trips_through_json_with_its_typed_payload(
    owner: UserId, now: datetime
) -> None:
    event = DomainEvent.emit(
        event_type=EventType.DEADLINE_CREATED,
        payload=DeadlinePayload(
            deadline_entity_id=EntityId("ent_deadline"),
            due_at=now + timedelta(days=3),
            hard=True,
        ),
        actor=Actor.agent_actor(AgentName.LIFE_ADMIN, owner),
        subject=Subject(owner_id=owner, entity_id=EntityId("ent_deadline")),
        source=SourceRef(source_type=SourceType.SYSTEM_DERIVED, captured_at=now),
        sensitivity=SensitivityLevel.S1,
        occurred_at=now,
    )

    restored = DomainEvent.from_json(event.to_json())

    assert restored == event
    assert isinstance(restored.payload, DeadlinePayload)
    assert restored.payload.hard is True
    assert restored.schema_version == CURRENT_SCHEMA_VERSION
    assert restored.source.source_type is SourceType.SYSTEM_DERIVED


def test_a_recorded_event_cannot_be_edited(owner: UserId, now: datetime) -> None:
    event = _capture(owner, now)

    with pytest.raises(ValidationError):
        event.event_type = EventType.TASK_CREATED  # type: ignore[misc]


def test_payload_must_match_the_event_type(owner: UserId, now: datetime) -> None:
    with pytest.raises(ValidationError, match="requires"):
        DomainEvent.emit(
            event_type=EventType.TASK_CREATED,
            payload=CapturePayload(capture_id="cap_1", kind=CaptureKind.TEXT),
            actor=Actor.user(owner),
            subject=Subject(owner_id=owner),
            source=SourceRef.user_declared(now),
            sensitivity=SensitivityLevel.S1,
            occurred_at=now,
        )


def test_correlation_and_causation_chain_is_reconstructable(owner: UserId, now: datetime) -> None:
    bus = InMemoryEventBus()
    received = bus.publish(_capture(owner, now))
    parsed = bus.publish(
        received.caused(
            event_type=EventType.CAPTURE_PARSED,
            payload=PAYLOAD_BY_EVENT[EventType.CAPTURE_PARSED].model_validate(
                {"capture_id": "cap_1", "extracted_count": 1}
            ),
            actor=Actor.orchestrator(owner),
            source=SourceRef(source_type=SourceType.SYSTEM_DERIVED, captured_at=now),
            sensitivity=SensitivityLevel.S1,
            occurred_at=now,
        )
    )
    created = bus.publish(
        parsed.caused(
            event_type=EventType.TASK_CREATED,
            payload=OpenLoopPayload(
                entity_id=EntityId("ent_task"),
                entity_type=EntityType.TASK,
                state=OpenLoopState.CAPTURED,
            ),
            actor=Actor.agent_actor(AgentName.LIFE_ADMIN, owner),
            source=SourceRef(source_type=SourceType.SYSTEM_DERIVED, captured_at=now),
            sensitivity=SensitivityLevel.S1,
            occurred_at=now,
        )
    )

    assert created.correlation_id == received.correlation_id
    assert created.causation_id == parsed.event_id
    assert parsed.causation_id == received.event_id

    chain = bus.causation_chain(created.event_id)
    assert [event.event_type for event in chain] == [
        EventType.CAPTURE_RECEIVED,
        EventType.CAPTURE_PARSED,
        EventType.TASK_CREATED,
    ]
    assert len(bus.correlation(received.correlation_id)) == 3


def test_the_bus_fans_out_and_refuses_a_replay(owner: UserId, now: datetime) -> None:
    bus = InMemoryEventBus()
    seen: list[EventType] = []
    bus.subscribe(EventType.CAPTURE_RECEIVED, lambda event: seen.append(event.event_type))
    bus.subscribe(None, lambda event: seen.append(event.event_type))

    event = bus.publish(_capture(owner, now))

    assert seen == [EventType.CAPTURE_RECEIVED, EventType.CAPTURE_RECEIVED]
    with pytest.raises(InvariantViolation, match="already been published"):
        bus.publish(event)
