from __future__ import annotations

from datetime import timedelta

import pytest

from wlos.core.errors import EventIntegrityError, TemporalError
from wlos.core.minds import Mind
from wlos.events.bus import InMemoryEventBus
from wlos.events.catalog import EventType
from wlos.events.envelope import Actor, DomainEvent, Subject, caused_by, make_event
from wlos.events.payloads import (
    CommitmentCapturedPayload,
    GoalCreatedPayload,
    TaskCreatedPayload,
)
from wlos.personal_life_graph.domains import EntityType
from wlos.shared.identifiers import CorrelationId, EntityId
from wlos.shared.provenance import SourceRef, SourceType
from wlos.shared.sensitivity import Sensitivity


def _goal_created(owner_id, now) -> DomainEvent:
    return make_event(
        event_type=EventType.GOAL_CREATED,
        actor=Actor.user(owner_id),
        subject=Subject.entity("ent_goal_1", EntityType.GOAL),
        source=SourceRef.user_declared(),
        payload=GoalCreatedPayload(
            goal_id=EntityId("ent_goal_1"), title="Launch the studio", target_at=now
        ),
        occurred_at=now,
        sensitivity=Sensitivity.S1,
    )


def test_event_round_trips_without_losing_its_typed_payload(owner_id, now):
    """Test 4: serialize then deserialize and get the same event and payload type back."""
    event = _goal_created(owner_id, now)
    raw = event.to_dict()

    assert isinstance(raw["occurred_at"], str)
    restored = DomainEvent.from_dict(raw)

    assert restored == event
    assert isinstance(restored.payload, GoalCreatedPayload)
    assert restored.payload.title == "Launch the studio"
    assert restored.schema_version == 1
    assert restored.to_dict() == raw


def test_payload_type_must_match_the_event_type(owner_id, now):
    with pytest.raises(EventIntegrityError):
        make_event(
            event_type=EventType.GOAL_CREATED,
            actor=Actor.user(owner_id),
            subject=Subject.entity("ent_goal_1", EntityType.GOAL),
            source=SourceRef.user_declared(),
            payload=TaskCreatedPayload(task_id=EntityId("ent_task_1"), title="wrong payload"),
            occurred_at=now,
        )


def test_correlation_and_causation_chain(owner_id, now, bus: InMemoryEventBus):
    """Test 5: a chain shares one correlation id and records each step's cause."""
    capture = bus.publish(
        make_event(
            event_type=EventType.CAPTURE_RECEIVED,
            actor=Actor.user(owner_id),
            subject=Subject.entity("ent_capture_1", EntityType.DOCUMENT),
            source=SourceRef.user_declared(),
            occurred_at=now,
        )
    )
    commitment = bus.publish(
        caused_by(
            capture,
            event_type=EventType.COMMITMENT_CAPTURED,
            actor=Actor.of_mind(Mind.LIFE_ADMIN),
            subject=Subject.entity("ent_commitment_1", EntityType.COMMITMENT),
            source=SourceRef(source_type=SourceType.SYSTEM_DERIVED),
            payload=CommitmentCapturedPayload(
                commitment_id=EntityId("ent_commitment_1"),
                title="Return the parcel",
                due_at=now + timedelta(days=3),
            ),
            occurred_at=now + timedelta(seconds=1),
        )
    )
    task = bus.publish(
        caused_by(
            commitment,
            event_type=EventType.TASK_CREATED,
            actor=Actor.of_mind(Mind.LIFE_ADMIN),
            subject=Subject.entity("ent_task_1", EntityType.TASK),
            source=SourceRef(source_type=SourceType.SYSTEM_DERIVED),
            payload=TaskCreatedPayload(
                task_id=EntityId("ent_task_1"), title="Print the return label"
            ),
            occurred_at=now + timedelta(seconds=2),
        )
    )

    assert commitment.correlation_id == capture.correlation_id
    assert task.correlation_id == capture.correlation_id
    assert task.causation_id == str(commitment.event_id)
    assert commitment.causation_id == str(capture.event_id)

    chain = bus.store.causal_chain(task.event_id)
    assert [event.event_type for event in chain] == [
        EventType.CAPTURE_RECEIVED,
        EventType.COMMITMENT_CAPTURED,
        EventType.TASK_CREATED,
    ]
    assert len(bus.store.by_correlation(capture.correlation_id)) == 3


def test_recorded_events_are_immutable_and_append_only(owner_id, now, bus: InMemoryEventBus):
    event = bus.publish(_goal_created(owner_id, now))

    with pytest.raises(ValueError, match="frozen"):
        event.event_type = EventType.GOAL_UPDATED

    with pytest.raises(EventIntegrityError):
        bus.publish(event)

    assert not hasattr(bus.store, "update")
    assert not hasattr(bus.store, "delete")
    assert bus.published() == (event,)


def test_bus_dispatches_to_typed_and_global_subscribers(owner_id, now, bus: InMemoryEventBus):
    seen: list[EventType] = []
    everything: list[EventType] = []
    bus.subscribe(EventType.GOAL_CREATED, lambda event: seen.append(event.event_type))
    bus.subscribe_all(lambda event: everything.append(event.event_type))

    bus.publish(_goal_created(owner_id, now))

    assert seen == [EventType.GOAL_CREATED]
    assert everything == [EventType.GOAL_CREATED]


def test_recorded_at_may_not_precede_occurred_at(owner_id, now):
    with pytest.raises(TemporalError):
        DomainEvent(
            event_type=EventType.MOOD_UPDATED,
            occurred_at=now,
            recorded_at=now - timedelta(minutes=5),
            actor=Actor.user(owner_id),
            subject=Subject.entity("ent_mood_1", EntityType.MOOD_OBSERVATION),
            correlation_id=CorrelationId("cor_1"),
            source=SourceRef.user_declared(),
        )
