"""ADV-01, 02, 08, 18, 19, 20, 21, 22, 30 — when what is true keeps changing."""

from datetime import datetime, timedelta

from scenario_helpers import declare, emit
from wplos.agents.radar import RADAR_CONTRACT
from wplos.core.attribution import Attribution
from wplos.core.identifiers import UserId
from wplos.core.provenance import SourceType
from wplos.core.records import RecordStatus
from wplos.core.sensitivity import SensitivityLevel
from wplos.core.temporal import TemporalMarkers
from wplos.events.bus import InMemoryEventBus
from wplos.events.payloads import (
    CaptureInvalidatedPayload,
    CaptureKind,
    CapturePayload,
    SourceConflictPayload,
)
from wplos.events.types import EventType
from wplos.personal_life_graph.attributes import CalendarEventAttributes
from wplos.personal_life_graph.context import project_context
from wplos.personal_life_graph.entity_types import EntityType
from wplos.personal_life_graph.graph import PersonalLifeGraph
from wplos.personal_life_graph.memory import MemoryRecord, MemoryType
from wplos.policy.decisions import ReasonCode
from wplos.policy.source_authority import (
    DEFAULT_SOURCE_AUTHORITY_POLICY,
    OverrideRequest,
    SourceAuthority,
    authority_of,
)


def _preference(
    owner: UserId, at: datetime, statement: str, attribution: Attribution
) -> MemoryRecord:
    return MemoryRecord.create(
        owner_id=owner,
        memory_type=MemoryType.PREFERENCE,
        statement=statement,
        attribution=attribution,
        at=at,
    )


# --- ADV-01 — she liked it, then did not, then did again ------------------


def test_a_preference_can_reverse_and_reverse_again_without_losing_history(
    graph: PersonalLifeGraph, owner: UserId, now: datetime
) -> None:
    month_later = now + timedelta(days=30)
    year_later = now + timedelta(days=365)

    liked = graph.put_memory(
        _preference(owner, now, "Loves Pilates", Attribution.declared(now, SensitivityLevel.S1))
    )
    graph.supersede_memory(liked.id, at=month_later, reason="she said she no longer wants it")
    disliked = graph.put_memory(
        _preference(
            owner,
            month_later,
            "Does not want Pilates suggestions",
            Attribution.declared(month_later, SensitivityLevel.S1),
        )
    )
    graph.supersede_memory(disliked.id, at=year_later, reason="she took it up again")
    liked_again = graph.put_memory(
        _preference(
            owner,
            year_later,
            "Loves Pilates",
            Attribution.declared(year_later, SensitivityLevel.S1),
        )
    )

    # Each statement is true of its own stretch of time, and none was erased.
    assert graph.get_memory(liked.id).is_usable_at(now + timedelta(days=1))
    assert not graph.get_memory(liked.id).is_usable_at(month_later + timedelta(days=1))
    assert graph.get_memory(disliked.id).is_usable_at(month_later + timedelta(days=1))
    assert not graph.get_memory(disliked.id).is_usable_at(year_later + timedelta(days=1))
    assert liked_again.is_usable_at(year_later + timedelta(days=1))

    active_then = graph.memories(owner_id=owner, at=month_later + timedelta(days=1))
    assert [memory.id for memory in active_then] == [disliked.id]
    assert len(graph.memories(owner_id=owner, include_inactive=True)) == 3


def test_radar_stops_seeing_a_withdrawn_preference_but_the_record_survives(
    graph: PersonalLifeGraph, owner: UserId, now: datetime
) -> None:
    month_later = now + timedelta(days=30)
    liked = graph.put_memory(
        _preference(owner, now, "Loves Pilates", Attribution.declared(now, SensitivityLevel.S1))
    )
    graph.supersede_memory(liked.id, at=month_later, reason="she asked us to stop suggesting it")

    scope = RADAR_CONTRACT.context_scope("suggest classes nearby")
    view = project_context(graph, owner_id=owner, scope=scope, at=month_later + timedelta(days=1))

    assert all(memory.id != liked.id for memory in view.memories)
    assert graph.get_memory(liked.id).statement == "Loves Pilates"
    assert graph.get_memory(liked.id).status is RecordStatus.SUPERSEDED


# --- ADV-02 — a declaration beats an inference ----------------------------


def test_an_explicit_statement_outranks_a_behavioural_inference(
    owner: UserId, now: datetime
) -> None:
    inferred = Attribution.inferred(
        now,
        SensitivityLevel.S1,
        value=0.8,
        source_type=SourceType.BEHAVIORAL_INFERENCE,
    )
    declared = Attribution.declared(now + timedelta(days=1), SensitivityLevel.S1)

    decision = DEFAULT_SOURCE_AUTHORITY_POLICY.evaluate(
        OverrideRequest(incoming=declared, existing=inferred, subject="workout time of day")
    )

    assert decision.is_permitted
    assert authority_of(SourceType.USER_DECLARED) is SourceAuthority.USER_EXPLICIT
    assert authority_of(SourceType.BEHAVIORAL_INFERENCE) is SourceAuthority.INFERRED


def test_an_inference_never_overwrites_what_she_said_herself(
    graph: PersonalLifeGraph, owner: UserId, now: datetime
) -> None:
    declared = Attribution.declared(now, SensitivityLevel.S1)
    later_inference = Attribution.inferred(
        now + timedelta(days=30),
        SensitivityLevel.S1,
        value=0.9,
        source_type=SourceType.BEHAVIORAL_INFERENCE,
    )

    decision = DEFAULT_SOURCE_AUTHORITY_POLICY.evaluate(
        OverrideRequest(incoming=later_inference, existing=declared, subject="workout time of day")
    )

    assert not decision.is_permitted
    assert decision.has_reason(ReasonCode.SOURCE_AUTHORITY_TOO_LOW)
    assert DEFAULT_SOURCE_AUTHORITY_POLICY.would_conflict(
        OverrideRequest(incoming=later_inference, existing=declared, subject="workout time of day")
    )


def test_the_correction_keeps_the_inference_as_history(
    graph: PersonalLifeGraph, owner: UserId, now: datetime
) -> None:
    inference = graph.put_memory(
        _preference(
            owner,
            now,
            "Prefers evening workouts",
            Attribution.inferred(
                now, SensitivityLevel.S1, value=0.8, source_type=SourceType.BEHAVIORAL_INFERENCE
            ),
        )
    )
    correction_at = now + timedelta(days=1)
    graph.supersede_memory(
        inference.id, at=correction_at, reason="she said mornings, she had simply been busy"
    )
    corrected = graph.put_memory(
        _preference(
            owner,
            correction_at,
            "Prefers morning workouts",
            Attribution.declared(correction_at, SensitivityLevel.S1),
        )
    )

    assert graph.get_memory(inference.id).is_usable_at(now)
    assert not graph.get_memory(inference.id).is_usable_at(correction_at)
    assert corrected.confidence.is_certain
    assert corrected.source.source_type is SourceType.USER_DECLARED
    assert graph.get_memory(inference.id).source.source_type is SourceType.BEHAVIORAL_INFERENCE


# --- ADV-08 / ADV-20 — stale and conflicting sources ----------------------


def test_a_stale_calendar_feed_cannot_undo_what_she_confirmed(
    graph: PersonalLifeGraph, owner: UserId, now: datetime
) -> None:
    connector_first = Attribution.observed(
        now, SensitivityLevel.S2, source_type=SourceType.CALENDAR, reference="cal_1"
    )
    user_moved_it = Attribution.declared(now + timedelta(hours=1), SensitivityLevel.S2)
    connector_replay = Attribution.observed(
        now + timedelta(hours=2),
        SensitivityLevel.S2,
        source_type=SourceType.CALENDAR,
        reference="cal_1",
    )

    accepted = DEFAULT_SOURCE_AUTHORITY_POLICY.evaluate(
        OverrideRequest(incoming=user_moved_it, existing=connector_first, subject="meeting time")
    )
    refused = DEFAULT_SOURCE_AUTHORITY_POLICY.evaluate(
        OverrideRequest(incoming=connector_replay, existing=user_moved_it, subject="meeting time")
    )

    # Newer is not the same as more authoritative.
    assert accepted.is_permitted
    assert not refused.is_permitted
    assert refused.has_reason(ReasonCode.SOURCE_AUTHORITY_TOO_LOW)


def test_an_older_reading_from_the_same_source_is_refused(owner: UserId, now: datetime) -> None:
    fresh = Attribution.observed(
        now + timedelta(hours=1), SensitivityLevel.S2, source_type=SourceType.CALENDAR
    )
    stale = Attribution.observed(now, SensitivityLevel.S2, source_type=SourceType.CALENDAR)

    decision = DEFAULT_SOURCE_AUTHORITY_POLICY.evaluate(
        OverrideRequest(incoming=stale, existing=fresh, subject="meeting time")
    )

    assert not decision.is_permitted
    assert decision.has_reason(ReasonCode.SOURCE_STALE)


def test_a_refused_override_is_recorded_as_a_conflict_not_swallowed(
    graph: PersonalLifeGraph, owner: UserId, now: datetime
) -> None:
    meeting = declare(
        graph,
        owner,
        now,
        EntityType.CALENDAR_EVENT,
        "Meeting",
        CalendarEventAttributes(calendar_ref="cal_1"),
        markers=TemporalMarkers(scheduled_for=now + timedelta(hours=2)),
    )
    bus = InMemoryEventBus()
    conflict = bus.publish(
        emit(
            EventType.SOURCE_CONFLICT_DETECTED,
            SourceConflictPayload(
                subject="meeting time",
                entity_id=meeting.id,
                incoming_source=SourceType.CALENDAR,
                retained_source=SourceType.USER_DECLARED,
                resolution="kept the time the user confirmed",
            ),
            owner,
            now,
            sensitivity=SensitivityLevel.S2,
        )
    )

    assert bus.events_of(EventType.SOURCE_CONFLICT_DETECTED) == (conflict,)
    payload = conflict.payload
    assert isinstance(payload, SourceConflictPayload)
    assert payload.retained_source is SourceType.USER_DECLARED


# --- ADV-18 / ADV-19 — a withdrawn or corrected source --------------------


def test_a_withdrawn_capture_invalidates_what_it_produced_without_erasing_it(
    graph: PersonalLifeGraph, owner: UserId, now: datetime, later: datetime
) -> None:
    appointment = declare(
        graph,
        owner,
        now,
        EntityType.CALENDAR_EVENT,
        "Appointment from a screenshot",
        CalendarEventAttributes(),
        markers=TemporalMarkers(scheduled_for=now + timedelta(days=2)),
    )
    bus = InMemoryEventBus()
    captured = bus.publish(
        emit(
            EventType.CAPTURE_RECEIVED,
            CapturePayload(capture_id="cap_old", kind=CaptureKind.SCREENSHOT),
            owner,
            now,
            source_type=SourceType.USER_ACTION,
        )
    )
    withdrawn = bus.publish(
        captured.caused(
            event_type=EventType.CAPTURE_INVALIDATED,
            payload=CaptureInvalidatedPayload(
                capture_id="cap_old",
                reason="she said the message was old",
                derived_entity_ids=(appointment.id,),
            ),
            actor=captured.actor,
            source=captured.source,
            sensitivity=SensitivityLevel.S2,
            occurred_at=later,
        )
    )
    graph.close_entity(appointment.id, at=later, status=RecordStatus.INVALIDATED)

    payload = withdrawn.payload
    assert isinstance(payload, CaptureInvalidatedPayload)
    assert appointment.id in payload.derived_entity_ids
    # The derived fact stops counting, the audit trail does not.
    assert not graph.get_entity(appointment.id).is_active_at(later)
    assert graph.get_entity(appointment.id).label == "Appointment from a screenshot"
    assert bus.causation_chain(withdrawn.event_id)[0].event_type is EventType.CAPTURE_RECEIVED


def test_correcting_a_misread_time_revises_rather_than_overwrites(
    graph: PersonalLifeGraph, owner: UserId, now: datetime, later: datetime
) -> None:
    misread = now + timedelta(days=1, hours=20)
    actual = now + timedelta(days=1, hours=18)
    event = declare(
        graph,
        owner,
        now,
        EntityType.CALENDAR_EVENT,
        "Parents' evening",
        CalendarEventAttributes(),
        markers=TemporalMarkers(scheduled_for=misread),
    )

    corrected = event.revised(
        at=later,
        markers=TemporalMarkers(scheduled_for=actual),
        attribution=Attribution.declared(later, SensitivityLevel.S2),
    )
    graph.revise_entity(event.id, corrected, expected_revision=event.revision)

    versions = graph.entity_versions(event.id)
    assert versions[0].markers.scheduled_for == misread
    assert versions[1].markers.scheduled_for == actual
    assert versions[1].revision == versions[0].revision + 1
    assert versions[1].source.source_type is SourceType.USER_DECLARED
    # Everything hanging off the event can be recomputed because the id is stable.
    assert versions[0].id == versions[1].id


# --- ADV-21 / ADV-22 — what an inference may become -----------------------


def test_a_low_confidence_inference_is_not_a_stable_preference(
    owner: UserId, now: datetime
) -> None:
    hunch = _preference(
        owner,
        now,
        "Might enjoy running",
        Attribution.inferred(now, SensitivityLevel.S1, value=0.2),
    )

    assert not hunch.confidence.is_certain
    assert not hunch.confidence.at_least(0.7)
    assert hunch.last_confirmed_at is None
    assert hunch.attribution.is_inferred


def test_a_sensitive_conclusion_stays_sensitive_whatever_inferred_it(
    owner: UserId, now: datetime
) -> None:
    """Sensitivity follows the information, not the mechanism that produced it."""
    inferred_from_behaviour = MemoryRecord.create(
        owner_id=owner,
        memory_type=MemoryType.FACT,
        statement="a cycle-related observation",
        attribution=Attribution.inferred(
            now,
            SensitivityLevel.S3,
            value=0.6,
            source_type=SourceType.BEHAVIORAL_INFERENCE,
        ),
        at=now,
    )

    assert inferred_from_behaviour.sensitivity is SensitivityLevel.S3
    assert not inferred_from_behaviour.confidence.is_certain

    scope = RADAR_CONTRACT.context_scope("suggest classes nearby")
    assert not scope.max_sensitivity.dominates(SensitivityLevel.S3)


# --- ADV-30 — "forget this" -----------------------------------------------


def test_stop_mentioning_it_is_not_the_same_as_it_was_never_true(
    graph: PersonalLifeGraph, owner: UserId, now: datetime, later: datetime
) -> None:
    memory = graph.put_memory(
        _preference(
            owner,
            now,
            "A thing she would rather not be reminded of",
            Attribution.declared(now, SensitivityLevel.S2),
        )
    )

    graph.put_memory(memory.suppressed(at=later, reason="she asked us not to bring it up"))
    suppressed = graph.get_memory(memory.id)

    # Three different things, kept apart.
    assert suppressed.status is RecordStatus.SUPPRESSED
    assert not suppressed.is_surfaceable
    assert suppressed.is_active_at(later)
    assert suppressed.statement == "A thing she would rather not be reminded of"
    assert suppressed.metadata["suppression_reason"] == "she asked us not to bring it up"

    wrong = graph.put_memory(
        _preference(
            owner, now, "Something we got wrong", Attribution.declared(now, SensitivityLevel.S1)
        )
    )
    graph.invalidate_memory(wrong.id, at=later, reason="it was never true")
    assert not graph.get_memory(wrong.id).is_active_at(now)
    assert graph.get_memory(wrong.id).status.negates_history
