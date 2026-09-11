"""ADV-04, 05, 23, 24, 29 — replays, races, causation and volume."""

from datetime import datetime, timedelta

import pytest

from scenario_helpers import declare, emit
from wplos.agents.contracts import DecisionState, PriorityClass
from wplos.core.client import ClientEventId, ClientRef, DeviceId, EventOrigin
from wplos.core.confidence import Confidence
from wplos.core.identifiers import EntityId, UserId
from wplos.core.provenance import SourceRef, SourceType
from wplos.core.roles import ActorRole, AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.core.temporal import TemporalMarkers
from wplos.events.bus import InMemoryEventBus
from wplos.events.envelope import Actor, DomainEvent, Subject
from wplos.events.payloads import (
    CaptureKind,
    CaptureParsedPayload,
    CapturePayload,
    DeadlineApproachingPayload,
    DeadlinePayload,
    OpenLoopPayload,
    ReadinessPlanPayload,
)
from wplos.events.types import EventType
from wplos.orchestration.conflict import DEFAULT_CONFLICT_POLICY, Claim, ClaimNature
from wplos.personal_life_graph.attributes import (
    CommitmentAttributes,
    CommitmentKind,
    OpenLoopState,
)
from wplos.personal_life_graph.entity_types import EntityType
from wplos.personal_life_graph.graph import PersonalLifeGraph
from wplos.shared.errors import ConcurrentModification, InvariantViolation


def _from_device(
    owner: UserId, at: datetime, client_event_id: str, capture_id: str = "cap_1"
) -> DomainEvent:
    return DomainEvent.emit(
        event_type=EventType.CAPTURE_RECEIVED,
        payload=CapturePayload(capture_id=capture_id, kind=CaptureKind.VOICE),
        actor=Actor.user(owner),
        subject=Subject(owner_id=owner),
        source=SourceRef(source_type=SourceType.USER_ACTION, captured_at=at),
        sensitivity=SensitivityLevel.S1,
        occurred_at=at,
        origin=EventOrigin.MOBILE_DEVICE,
        client=ClientRef(
            client_event_id=ClientEventId(client_event_id),
            device_id=DeviceId("dev_a"),
            submitted_at=at,
        ),
    )


# --- ADV-04 — the same thing sent twice -----------------------------------


def test_a_replayed_submission_is_recognised_by_its_client_id(owner: UserId, now: datetime) -> None:
    bus = InMemoryEventBus()
    first = bus.publish(_from_device(owner, now, "cev_1"))
    retry = _from_device(owner, now + timedelta(seconds=30), "cev_1")

    assert bus.duplicate_of(retry) == first.event_id
    assert bus.accept(retry).event_id == first.event_id
    assert len(bus.log) == 1
    with pytest.raises(InvariantViolation, match="already accepted"):
        bus.publish(retry)


def test_two_genuinely_separate_captures_are_not_collapsed(owner: UserId, now: datetime) -> None:
    """Identical-looking text can be two real commitments; only the id decides."""
    bus = InMemoryEventBus()
    bus.publish(_from_device(owner, now, "cev_1", capture_id="cap_same"))
    bus.publish(_from_device(owner, now + timedelta(minutes=5), "cev_2", capture_id="cap_same"))

    assert len(bus.log) == 2


def test_the_same_event_id_is_never_published_twice(owner: UserId, now: datetime) -> None:
    bus = InMemoryEventBus()
    event = bus.publish(
        emit(
            EventType.CAPTURE_RECEIVED,
            CapturePayload(capture_id="cap_1", kind=CaptureKind.TEXT),
            owner,
            now,
        )
    )

    with pytest.raises(InvariantViolation, match="already been published"):
        bus.publish(event)


def test_an_event_from_a_device_must_be_identifiable(owner: UserId, now: datetime) -> None:
    with pytest.raises(ValueError, match="must carry a ClientRef"):
        DomainEvent.emit(
            event_type=EventType.CAPTURE_RECEIVED,
            payload=CapturePayload(capture_id="cap_1", kind=CaptureKind.TEXT),
            actor=Actor.user(owner),
            subject=Subject(owner_id=owner),
            source=SourceRef(source_type=SourceType.USER_ACTION, captured_at=now),
            sensitivity=SensitivityLevel.S1,
            occurred_at=now,
            origin=EventOrigin.MOBILE_DEVICE,
        )


# --- ADV-05 — two devices, one open loop ----------------------------------


def test_two_devices_editing_one_loop_do_not_resolve_by_last_write(
    graph: PersonalLifeGraph, owner: UserId, now: datetime
) -> None:
    loop = declare(
        graph,
        owner,
        now,
        EntityType.COMMITMENT,
        "Return the dress",
        CommitmentAttributes(kind=CommitmentKind.RETURN, state=OpenLoopState.DUE),
        markers=TemporalMarkers(due_at=now + timedelta(days=2)),
    )
    both_read = loop.revision

    device_a = loop.revised(
        at=now + timedelta(minutes=1),
        attributes=CommitmentAttributes(kind=CommitmentKind.RETURN, state=OpenLoopState.COMPLETED),
    )
    graph.revise_entity(loop.id, device_a, expected_revision=both_read)

    device_b = loop.revised(
        at=now + timedelta(minutes=2),
        attributes=CommitmentAttributes(kind=CommitmentKind.RETURN, state=OpenLoopState.CANCELLED),
    )

    # The second write was built on a stale read and is refused, not applied.
    with pytest.raises(ConcurrentModification, match="revision"):
        graph.revise_entity(loop.id, device_b, expected_revision=both_read)

    current = graph.get_entity(loop.id)
    assert current.attributes_as(CommitmentAttributes).state is OpenLoopState.COMPLETED
    assert current.revision == both_read + 1


def test_the_losing_update_can_be_represented_as_a_conflict(owner: UserId, now: datetime) -> None:
    completed = Claim(
        claim_id="claim_device_a",
        agent=AgentName.LIFE_ADMIN,
        subject="return-the-dress",
        nature=ClaimNature.COMMITMENT,
        decision_state=DecisionState.SURFACE,
        priority=PriorityClass.P1,
        statement="marked completed on her phone",
        confidence=Confidence.certain(),
    )
    cancelled = completed.model_copy(
        update={"claim_id": "claim_device_b", "statement": "marked cancelled on her tablet"}
    )

    resolution = DEFAULT_CONFLICT_POLICY.resolve((completed, cancelled))

    # No rule can choose between "completed" and "cancelled", and the model says
    # so rather than quietly keeping whichever arrived last.
    assert resolution.needs_the_user
    assert len(resolution.unresolved) == 1
    contention = resolution.unresolved[0]
    assert contention.subject == "return-the-dress"
    assert set(contention.claim_ids) == {"claim_device_a", "claim_device_b"}
    assert {claim.claim_id for claim in resolution.surviving} == {
        "claim_device_a",
        "claim_device_b",
    }


# --- ADV-23 / ADV-24 — causation -----------------------------------------


def test_a_six_step_chain_reconstructs_to_one_root(owner: UserId, now: datetime) -> None:
    bus = InMemoryEventBus()
    entity_id = EntityId("ent_x")
    due = now + timedelta(days=2)

    received = bus.publish(
        emit(
            EventType.CAPTURE_RECEIVED,
            CapturePayload(capture_id="cap_1", kind=CaptureKind.SCREENSHOT),
            owner,
            now,
        )
    )
    steps: list[tuple[EventType, object]] = [
        (EventType.CAPTURE_PARSED, CaptureParsedPayload(capture_id="cap_1", extracted_count=2)),
        (
            EventType.COMMITMENT_CAPTURED,
            OpenLoopPayload(
                entity_id=entity_id,
                entity_type=EntityType.COMMITMENT,
                state=OpenLoopState.SCHEDULED,
                due_at=due,
            ),
        ),
        (
            EventType.DEADLINE_CREATED,
            DeadlinePayload(deadline_entity_id=entity_id, due_at=due, hard=True),
        ),
        (
            EventType.DEADLINE_APPROACHING,
            DeadlineApproachingPayload(
                deadline_entity_id=entity_id, due_at=due, hard=True, minutes_remaining=120
            ),
        ),
        (
            EventType.READINESS_PLAN_UPDATED,
            ReadinessPlanPayload(plan_id="plan_1", target_event_entity_id=entity_id, item_count=3),
        ),
    ]

    cursor = received
    for index, (event_type, payload) in enumerate(steps, start=1):
        cursor = bus.publish(
            cursor.caused(
                event_type=event_type,
                payload=payload,  # type: ignore[arg-type]
                actor=received.actor,
                source=received.source,
                sensitivity=SensitivityLevel.S2,
                occurred_at=now + timedelta(minutes=index),
            )
        )

    chain = bus.causation_chain(cursor.event_id)
    assert [event.event_type for event in chain] == [
        EventType.CAPTURE_RECEIVED,
        EventType.CAPTURE_PARSED,
        EventType.COMMITMENT_CAPTURED,
        EventType.DEADLINE_CREATED,
        EventType.DEADLINE_APPROACHING,
        EventType.READINESS_PLAN_UPDATED,
    ]
    assert len({event.correlation_id for event in chain}) == 1
    assert chain[0].causation_id is None


def test_an_event_cannot_cause_itself(owner: UserId, now: datetime) -> None:
    event = emit(
        EventType.CAPTURE_RECEIVED,
        CapturePayload(capture_id="cap_1", kind=CaptureKind.TEXT),
        owner,
        now,
    )
    self_caused = event.model_dump()
    self_caused["causation_id"] = self_caused["event_id"]

    with pytest.raises(ValueError, match="cannot be its own cause"):
        DomainEvent.model_validate(self_caused)


def test_causation_must_point_at_something_already_recorded(owner: UserId, now: datetime) -> None:
    """A cause that has not happened cannot be a cause; this is what stops a cycle."""
    bus = InMemoryEventBus()
    orphan = emit(
        EventType.CAPTURE_PARSED,
        CaptureParsedPayload(capture_id="cap_1", extracted_count=1),
        owner,
        now,
    ).model_copy(update={"causation_id": "evt_never_published"})

    with pytest.raises(InvariantViolation, match="causation must point backwards"):
        bus.publish(orphan)


def test_a_corrupted_causation_cycle_is_reported_not_walked_forever(
    owner: UserId, now: datetime
) -> None:
    bus = InMemoryEventBus(require_known_cause=False)
    first = emit(
        EventType.CAPTURE_RECEIVED,
        CapturePayload(capture_id="cap_1", kind=CaptureKind.TEXT),
        owner,
        now,
    )
    second = emit(
        EventType.CAPTURE_PARSED,
        CaptureParsedPayload(capture_id="cap_1", extracted_count=1),
        owner,
        now,
    ).model_copy(update={"causation_id": first.event_id})
    bus.publish(second)
    bus.publish(first.model_copy(update={"causation_id": second.event_id}))

    with pytest.raises(InvariantViolation, match="causation cycle"):
        bus.causation_chain(second.event_id)


# --- ADV-29 — three hundred finds, four goals -----------------------------


def test_a_flood_of_claims_still_carries_what_is_needed_to_choose(
    owner: UserId, now: datetime
) -> None:
    opportunities = tuple(
        Claim(
            claim_id=f"claim_radar_{index}",
            agent=AgentName.RADAR,
            subject=f"slot-{index % 7}",
            nature=ClaimNature.OPPORTUNITY,
            decision_state=DecisionState.SURFACE,
            priority=PriorityClass.P3,
            statement=f"opportunity {index}",
            confidence=Confidence.probabilistic(0.3 + (index % 10) / 20),
        )
        for index in range(300)
    )
    commitments = tuple(
        Claim(
            claim_id=f"claim_loop_{index}",
            agent=AgentName.LIFE_ADMIN,
            subject=f"slot-{index}",
            nature=ClaimNature.COMMITMENT,
            decision_state=DecisionState.SURFACE,
            priority=PriorityClass.P1,
            statement=f"open loop {index}",
            confidence=Confidence.certain(),
        )
        for index in range(14)
    )

    resolution = DEFAULT_CONFLICT_POLICY.resolve(commitments + opportunities)

    # Every claim carries priority, confidence and a decision state, so the
    # Orchestrator can rank without the domain having thrown anything away.
    assert all(claim.priority for claim in resolution.surviving)
    assert all(claim.confidence.score >= 0.0 for claim in resolution.surviving)
    assert len(resolution.surviving) + len(resolution.suppressed) == 314
    top = sorted(
        resolution.surviving, key=lambda claim: (claim.priority.rank, -claim.confidence.score)
    )
    assert top[0].priority is PriorityClass.P1
    assert {item.claim.claim_id for item in resolution.suppressed}
    # Nothing is lost: a suppressed claim still says what it was and why it lost.
    for suppressed in resolution.suppressed:
        assert suppressed.claim.statement
        assert suppressed.rule


def test_an_actor_role_is_never_guessed(owner: UserId) -> None:
    with pytest.raises(ValueError, match="must carry a user_id"):
        Actor(role=ActorRole.USER)
    with pytest.raises(ValueError, match="must name the agent"):
        Actor(role=ActorRole.AGENT)
