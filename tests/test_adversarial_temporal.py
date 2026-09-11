"""ADV-03, 06, 07 — late arrivals, travel, and the edges of a clock change."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from scenario_helpers import declare, emit
from wplos.core.identifiers import UserId
from wplos.core.provenance import SourceType
from wplos.core.sensitivity import SensitivityLevel
from wplos.core.temporal import (
    AmbiguousTimePolicy,
    NonexistentTimePolicy,
    TemporalMarkers,
    ZonedInstant,
)
from wplos.events.bus import InMemoryEventBus
from wplos.events.payloads import OpenLoopPayload
from wplos.events.types import EventType
from wplos.personal_life_graph.attributes import (
    CalendarEventAttributes,
    OpenLoopState,
    TaskAttributes,
)
from wplos.personal_life_graph.entity_types import EntityType
from wplos.personal_life_graph.graph import PersonalLifeGraph
from wplos.shared.errors import InvariantViolation

RIYADH = "Asia/Riyadh"
LONDON = "Europe/London"
NEW_YORK = "America/New_York"


# --- ADV-03 — events that arrive in the wrong order -----------------------


def test_a_late_creation_does_not_rewrite_a_completion(owner: UserId, now: datetime) -> None:
    created_at = now.replace(hour=12)
    completed_at = now.replace(hour=18)
    recorded_at = now.replace(hour=19)

    bus = InMemoryEventBus()
    completion = bus.publish(
        emit(
            EventType.TASK_COMPLETED,
            OpenLoopPayload(
                entity_id="ent_task",  # type: ignore[arg-type]
                entity_type=EntityType.TASK,
                state=OpenLoopState.COMPLETED,
            ),
            owner,
            completed_at,
        )
    )
    late_creation = bus.publish(
        emit(
            EventType.TASK_CREATED,
            OpenLoopPayload(
                entity_id="ent_task",  # type: ignore[arg-type]
                entity_type=EntityType.TASK,
                state=OpenLoopState.CAPTURED,
            ),
            owner,
            created_at,
        ).model_copy(update={"recorded_at": recorded_at})
    )

    # Arrival order and world order are different questions, and both are asked.
    assert [event.event_type for event in bus.in_arrival_order()] == [
        EventType.TASK_COMPLETED,
        EventType.TASK_CREATED,
    ]
    assert [event.event_type for event in bus.in_occurrence_order()] == [
        EventType.TASK_CREATED,
        EventType.TASK_COMPLETED,
    ]
    assert late_creation.arrived_late
    assert not completion.arrived_late
    assert late_creation.occurred_at < completion.occurred_at
    assert late_creation.recorded_at > completion.recorded_at


def test_state_is_read_from_occurrence_not_from_arrival(
    graph: PersonalLifeGraph, owner: UserId, now: datetime
) -> None:
    task = declare(
        graph,
        owner,
        now,
        EntityType.TASK,
        "A task",
        TaskAttributes(state=OpenLoopState.CAPTURED),
        markers=TemporalMarkers(occurred_at=now.replace(hour=12)),
    )

    # Record time says when we wrote it down; domain time says when it happened.
    assert task.markers.occurred_at == now.replace(hour=12)
    assert task.created_at == now
    assert task.markers.occurred_at != task.created_at


# --- ADV-06 — she travels, the event does not ----------------------------


def test_a_riyadh_event_stays_at_nine_in_riyadh_when_she_is_in_london() -> None:
    event = ZonedInstant.from_local(datetime(2026, 9, 20, 9, 0), RIYADH)

    assert event.local.hour == 9
    assert event.local.strftime("%Z") in {"+03", "AST", "+0300"}
    assert event.instant == datetime(2026, 9, 20, 6, 0, tzinfo=UTC)
    # Read from London it is 07:00; the event has not moved.
    assert event.local_in(LONDON).hour == 7
    assert event.local.hour == 9
    assert event.time_zone == RIYADH


def test_the_reminder_is_computed_from_the_instant_not_the_wall_clock() -> None:
    event = ZonedInstant.from_local(datetime(2026, 9, 20, 9, 0), RIYADH)

    remind_at = event.instant - timedelta(hours=1)

    assert remind_at == datetime(2026, 9, 20, 5, 0, tzinfo=UTC)
    assert remind_at.astimezone(ZoneInfo(LONDON)).hour == 6


def test_a_calendar_event_records_the_zone_it_is_anchored_to(
    graph: PersonalLifeGraph, owner: UserId, now: datetime
) -> None:
    anchored = ZonedInstant.from_local(datetime(2026, 9, 20, 9, 0), RIYADH)
    meeting = declare(
        graph,
        owner,
        now,
        EntityType.CALENDAR_EVENT,
        "Morning meeting",
        CalendarEventAttributes(time_zone=RIYADH),
        markers=TemporalMarkers(scheduled_for=anchored.instant),
    )

    attributes = meeting.attributes_as(CalendarEventAttributes)
    assert attributes.time_zone == RIYADH
    assert meeting.markers.scheduled_for == anchored.instant
    assert attributes.anchored(meeting.markers.scheduled_for).local.hour == 9


# --- ADV-07 — the clocks move --------------------------------------------


def test_a_local_time_that_never_happens_is_refused_not_guessed() -> None:
    with pytest.raises(InvariantViolation, match="does not exist"):
        ZonedInstant.from_local(datetime(2026, 3, 29, 1, 30), LONDON)

    with pytest.raises(InvariantViolation, match="does not exist"):
        ZonedInstant.from_local(datetime(2026, 3, 8, 2, 30), NEW_YORK)


def test_a_local_time_that_happens_twice_is_refused_not_guessed() -> None:
    with pytest.raises(InvariantViolation, match="happens twice"):
        ZonedInstant.from_local(datetime(2026, 10, 25, 1, 30), LONDON)

    with pytest.raises(InvariantViolation, match="happens twice"):
        ZonedInstant.from_local(datetime(2026, 11, 1, 1, 30), NEW_YORK)


def test_a_dst_gap_can_be_resolved_forward_when_the_caller_says_so() -> None:
    shifted = ZonedInstant.from_local(
        datetime(2026, 3, 29, 1, 30), LONDON, on_nonexistent=NonexistentTimePolicy.SHIFT_FORWARD
    )

    assert shifted.local.hour == 2
    assert shifted.local.minute == 30
    assert shifted.utc_offset_minutes() == 60


def test_an_ambiguous_hour_resolves_to_whichever_occurrence_was_meant() -> None:
    earlier = ZonedInstant.from_local(
        datetime(2026, 10, 25, 1, 30), LONDON, on_ambiguous=AmbiguousTimePolicy.EARLIER
    )
    later = ZonedInstant.from_local(
        datetime(2026, 10, 25, 1, 30), LONDON, on_ambiguous=AmbiguousTimePolicy.LATER
    )

    assert later.instant - earlier.instant == timedelta(hours=1)
    assert earlier.local.hour == 1
    assert later.local.hour == 1
    assert earlier.utc_offset_minutes() == 60
    assert later.utc_offset_minutes() == 0


def test_a_naive_datetime_is_never_accepted_as_an_instant() -> None:
    with pytest.raises(InvariantViolation, match="without a zone"):
        ZonedInstant.from_local(datetime(2026, 9, 20, 9, 0, tzinfo=UTC), RIYADH)


def test_an_unknown_zone_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown IANA time zone"):
        ZonedInstant(instant=datetime(2026, 9, 20, 6, 0, tzinfo=UTC), time_zone="Mars/Olympus")


def test_travel_preparation_uses_the_events_own_zone(owner: UserId, now: datetime) -> None:
    """Leave-at is arithmetic on the instant, rendered in the zone she is in."""
    event = ZonedInstant.from_local(datetime(2026, 9, 20, 9, 0), RIYADH)
    travel = timedelta(minutes=40)

    leave_at = event.instant - travel

    assert leave_at == datetime(2026, 9, 20, 5, 20, tzinfo=UTC)
    assert event.local_in(RIYADH).hour == 9
    assert leave_at.astimezone(ZoneInfo(RIYADH)).strftime("%H:%M") == "08:20"


def test_source_provenance_survives_a_late_arrival(owner: UserId, now: datetime) -> None:
    late = emit(
        EventType.TASK_CREATED,
        OpenLoopPayload(
            entity_id="ent_task",  # type: ignore[arg-type]
            entity_type=EntityType.TASK,
            state=OpenLoopState.CAPTURED,
        ),
        owner,
        now,
        source_type=SourceType.USER_ACTION,
        sensitivity=SensitivityLevel.S1,
    ).model_copy(update={"recorded_at": now + timedelta(hours=6)})

    assert late.arrived_late
    assert late.source.source_type is SourceType.USER_ACTION
    assert late.occurred_at == now
