"""Fifteen end-to-end runs.

The question these answer: can six independent minds produce one safe, coherent,
bounded decision without a language model anywhere in the loop?
"""

from datetime import datetime, timedelta

from runtime_harness import build_harness
from scenario_helpers import declare
from wplos.agents.contracts import Intent, PriorityClass
from wplos.application.composer import (
    DEFAULT_BUDGET,
    HighImpactAuthorizationRequest,
    SuppressionReason,
)
from wplos.application.idempotency import InMemoryRuntimeLedger
from wplos.application.reference_agents import reference_pilates
from wplos.application.request import ClientContext, RuntimeRequest, TriggerRef, TriggerType
from wplos.application.result import RuntimeStatus
from wplos.core.client import ClientEventId, DeviceId, EventOrigin
from wplos.core.identifiers import AuthorizationId, UserId, new_correlation_id, new_request_id
from wplos.core.money import Money
from wplos.core.roles import AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.core.temporal import TemporalMarkers
from wplos.events.types import EventType
from wplos.personal_life_graph.attributes import (
    CalendarEventAttributes,
    CommitmentAttributes,
    CommitmentKind,
    EngagementLevel,
    GoalAttributes,
    GoalHorizon,
    InterestAttributes,
    OpenLoopState,
    PlaceAttributes,
    RadarCategory,
    RadarItemAttributes,
    RequirementAttributes,
    RequirementKind,
    RequirementStatus,
)
from wplos.personal_life_graph.entity_types import EntityType, LifeDomain
from wplos.personal_life_graph.graph import PersonalLifeGraph
from wplos.policy.decisions import PolicyOutcome, ReasonCode
from wplos.policy.execution import AuthorizationMethod, ExecutionAuthorization, ProposedAction
from wplos.policy.permissions import ActionDomain, PermissionLevel, ReversibilityClass


def _user_request(owner: UserId, at: datetime, utterance: str) -> RuntimeRequest:
    return RuntimeRequest.from_user(user_id=owner, at=at, utterance=utterance)


def _mobile_request(
    owner: UserId, occurred_at: datetime, received_at: datetime, client_request_id: str
) -> RuntimeRequest:
    return RuntimeRequest(
        request_id=new_request_id(),
        user_id=owner,
        trigger=TriggerType.MOBILE_ACTION,
        trigger_ref=TriggerRef(label="confirm"),
        occurred_at=occurred_at,
        received_at=received_at,
        correlation_id=new_correlation_id(),
        client=ClientContext(
            origin=EventOrigin.MOBILE_DEVICE,
            client_request_id=ClientEventId(client_request_id),
            device_id=DeviceId("dev_1"),
        ),
    )


def _long_day(graph: PersonalLifeGraph, owner: UserId, now: datetime) -> None:
    morning = now + timedelta(days=1, hours=1)
    clinic = now + timedelta(days=1, hours=7)
    shop_closes = now + timedelta(days=1, hours=13)

    declare(
        graph,
        owner,
        now,
        EntityType.CALENDAR_EVENT,
        "Morning meeting",
        CalendarEventAttributes(ends_at=morning + timedelta(hours=1)),
        markers=TemporalMarkers(scheduled_for=morning),
    )
    declare(
        graph,
        owner,
        now,
        EntityType.CALENDAR_EVENT,
        "Daughter's appointment",
        CalendarEventAttributes(ends_at=clinic + timedelta(hours=1)),
        markers=TemporalMarkers(scheduled_for=clinic),
    )
    declare(
        graph,
        owner,
        now,
        EntityType.COMMITMENT,
        "Return the dress before the shop closes",
        CommitmentAttributes(kind=CommitmentKind.RETURN, state=OpenLoopState.DUE),
        markers=TemporalMarkers(due_at=shop_closes),
    )


# --- E2E-01 ---------------------------------------------------------------


def test_e2e_01_a_long_day_becomes_one_plan(owner: UserId, now: datetime) -> None:
    harness = build_harness()
    _long_day(harness.graph, owner, now)

    result = harness.runtime.run(
        _user_request(owner, now, "tomorrow is long"),
        graph=harness.graph,
        intent=Intent.PLAN_DAY,
        now=now,
    )

    assert result.status is RuntimeStatus.COMPLETED
    assert result.plan.items
    assert len(result.plan.items) <= DEFAULT_BUDGET.max_total
    assert {AgentName.LIFE_ADMIN, AgentName.READINESS} <= set(result.trace.routed_agents)
    assert AgentName.GUARDIAN in result.trace.execution_order
    # One coordinated answer, not four separate replies.
    assert result.correlation_id == result.emitted_events[0].correlation_id
    assert len({event.correlation_id for event in result.emitted_events}) == 1


# --- E2E-02 ---------------------------------------------------------------


def test_e2e_02_a_radar_find_reaches_navigator(owner: UserId, now: datetime) -> None:
    harness = build_harness()
    declare(
        harness.graph,
        owner,
        now,
        EntityType.GOAL,
        "Move into UX within six months",
        GoalAttributes(horizon=GoalHorizon.QUARTER, domain=LifeDomain.WORK),
    )
    declare(
        harness.graph,
        owner,
        now,
        EntityType.RADAR_ITEM,
        "UX Portfolio Workshop",
        RadarItemAttributes(
            category=RadarCategory.LEARNING,
            headline="UX Portfolio Workshop",
            price=Money.of(35000, "SAR"),
        ),
        markers=TemporalMarkers(scheduled_for=now + timedelta(days=4)),
    )

    result = harness.runtime.run(
        RuntimeRequest.from_event(
            user_id=owner, event_type=EventType.RADAR_ITEM_DISCOVERED, at=now
        ),
        graph=harness.graph,
        now=now,
    )

    order = result.trace.execution_order
    assert order.index(AgentName.RADAR) < order.index(AgentName.NAVIGATOR)
    assert result.plan.opportunities
    assert result.plan.opportunities[0].origin_agent is AgentName.RADAR
    assert result.status.produced_a_plan


# --- E2E-03 ---------------------------------------------------------------


def test_e2e_03_an_opportunity_does_not_displace_an_appointment(
    owner: UserId, now: datetime
) -> None:
    harness = build_harness()
    thursday = now + timedelta(days=4)
    declare(
        harness.graph,
        owner,
        now,
        EntityType.CALENDAR_EVENT,
        "Thursday evening",
        CalendarEventAttributes(),
        markers=TemporalMarkers(scheduled_for=thursday),
        sensitivity=SensitivityLevel.S2,
    )
    declare(
        harness.graph,
        owner,
        now,
        EntityType.RADAR_ITEM,
        "Thursday evening",
        RadarItemAttributes(category=RadarCategory.EVENT, headline="Thursday evening"),
        markers=TemporalMarkers(scheduled_for=thursday),
    )

    result = harness.runtime.run(
        _user_request(owner, now, "anything on?"),
        graph=harness.graph,
        intent=Intent.DISCOVER,
        now=now,
    )

    titles = {item.title for item in result.plan.items}
    assert "Thursday evening" in titles
    # The two claims share a subject; the commitment survives and the find does not
    # silently take its place.
    kept = next(item for item in result.plan.items if item.title == "Thursday evening")
    assert kept.origin_agent is AgentName.LIFE_ADMIN
    assert result.plan.suppressed_for(SuppressionReason.DUPLICATE) or result.plan.suppressed_for(
        SuppressionReason.CONFLICT
    )


# --- E2E-04 ---------------------------------------------------------------


def test_e2e_04_guardian_removes_an_unsafe_candidate(owner: UserId, now: datetime) -> None:
    harness = build_harness(readiness_unsafe=True)
    declare(
        harness.graph,
        owner,
        now,
        EntityType.CALENDAR_EVENT,
        "Tonight",
        CalendarEventAttributes(),
        markers=TemporalMarkers(scheduled_for=now + timedelta(hours=8)),
    )
    # Readiness proposes; Guardian is told to block that proposal.
    first = harness.runtime.run(
        _user_request(owner, now, "get me ready"),
        graph=harness.graph,
        intent=Intent.GET_READY,
        now=now,
    )
    unsafe = harness.readiness.unsafe_action_id

    harness.guardian.block = frozenset({unsafe})
    second = harness.runtime.run(
        _user_request(owner, now, "get me ready"),
        graph=harness.graph,
        intent=Intent.GET_READY,
        now=now,
    )

    assert first.status.produced_a_plan
    blocked_ids = {
        item.candidate_id for item in second.plan.suppressed_for(SuppressionReason.GUARDIAN_BLOCK)
    }
    assert blocked_ids
    assert all(item.action_id != unsafe for item in second.plan.items)
    assert second.plan.warnings


# --- E2E-05 ---------------------------------------------------------------


def test_e2e_05_an_external_action_asks_before_it_acts(owner: UserId, now: datetime) -> None:
    harness = build_harness()
    action = ProposedAction(
        action_id=reference_pilates(owner, now, Money.of(10000, "SAR")).action_id,
        owner_id=owner,
        proposed_by=AgentName.OPERATOR,
        proposed_at=now,
        domain=ActionDomain.COMMUNICATION,
        permission_level=PermissionLevel.A2,
        summary="Message the studio",
        reversibility=ReversibilityClass.IRREVERSIBLE,
        material_terms={"recipient": "the studio"},
    )
    harness.operator.proposal = action

    result = harness.runtime.run(
        _user_request(owner, now, "book it"),
        graph=harness.graph,
        intent=Intent.EXECUTE,
        now=now,
    )

    assert result.status is RuntimeStatus.NEEDS_AUTHORIZATION
    assert len(result.required_authorizations) == 1
    request = result.required_authorizations[0]
    assert request.permission_level is PermissionLevel.A2
    assert not request.is_high_impact
    assert harness.operator.executed == []
    assert any(
        event.event_type is EventType.AUTHORIZATION_REQUESTED for event in result.emitted_events
    )


def test_e2e_05b_a_high_impact_action_carries_its_terms(owner: UserId, now: datetime) -> None:
    harness = build_harness()
    action = reference_pilates(owner, now, Money.of(10000, "SAR"))
    harness.operator.proposal = action

    result = harness.runtime.run(
        _user_request(owner, now, "book it"),
        graph=harness.graph,
        intent=Intent.EXECUTE,
        now=now,
    )

    request = result.required_authorizations[0]
    assert isinstance(request, HighImpactAuthorizationRequest)
    assert request.is_high_impact
    assert request.audit_required
    assert request.action.material_terms["price"] == Money.of(10000, "SAR").as_terms()
    assert harness.operator.executed == []


# --- E2E-06 ---------------------------------------------------------------


def test_e2e_06_an_internal_action_runs_and_says_so(owner: UserId, now: datetime) -> None:
    harness = build_harness()
    action = ProposedAction(
        action_id=reference_pilates(owner, now, Money.of(1, "SAR")).action_id,
        owner_id=owner,
        proposed_by=AgentName.OPERATOR,
        proposed_at=now,
        domain=ActionDomain.INTERNAL,
        permission_level=PermissionLevel.A1,
        summary="Reschedule an internal reminder",
        reversibility=ReversibilityClass.REVERSIBLE,
    )
    harness.operator.proposal = action

    result = harness.runtime.run(
        _user_request(owner, now, "sort my reminders"),
        graph=harness.graph,
        intent=Intent.EXECUTE,
        now=now,
    )

    assert harness.operator.executed == [action.action_id]
    assert result.required_authorizations == ()
    emitted = {event.event_type for event in result.emitted_events}
    assert EventType.OPERATOR_ACTION_STARTED in emitted
    assert EventType.OPERATOR_ACTION_SUCCEEDED in emitted


# --- E2E-07 ---------------------------------------------------------------


def test_e2e_07_a_stale_confirmation_is_refused(owner: UserId, now: datetime) -> None:
    harness = build_harness()
    shown = reference_pilates(owner, now, Money.of(10000, "SAR"))
    harness.operator.proposal = shown
    harness.guardian.subject = shown

    first = harness.runtime.run(
        _user_request(owner, now, "book it"),
        graph=harness.graph,
        intent=Intent.EXECUTE,
        now=now,
    )
    consent = ExecutionAuthorization.for_action(
        first.required_authorizations[0].action,
        authorization_id=AuthorizationId("aut_1"),
        granted_at=now,
        method=AuthorizationMethod.EXPLICIT_CONFIRMATION,
        expires_at=now + timedelta(hours=6),
        audit_ref="audit_1",
    )

    two_hours_later = now + timedelta(hours=2)
    repriced = shown.with_terms(price=Money.of(18000, "SAR").as_terms())
    verdict = harness.authority.allow(
        action_id=repriced.action_id,
        fingerprint=repriced.terms_fingerprint,
        at=two_hours_later,
    )

    decision = harness.runtime.execution_policy.authorize(
        repriced, verdict, consent, two_hours_later
    )

    assert decision.outcome is PolicyOutcome.DENY
    assert decision.has_reason(ReasonCode.MATERIAL_TERMS_CHANGED)


# --- E2E-08 ---------------------------------------------------------------


def test_e2e_08_a_delayed_intent_is_re_evaluated_against_now(owner: UserId, now: datetime) -> None:
    harness = build_harness()
    _long_day(harness.graph, owner, now)
    two_hours_later = now + timedelta(hours=2)

    request = _mobile_request(owner, now, two_hours_later, "cev_offline")
    result = harness.runtime.run(
        request,
        graph=harness.graph,
        intent=Intent.PLAN_DAY,
        now=two_hours_later,
    )

    assert request.arrived_late
    assert request.occurred_at == now
    assert request.received_at == two_hours_later
    # Evaluated against the state at arrival, not at the moment she tapped.
    assert all(event.occurred_at == two_hours_later for event in result.emitted_events)
    assert result.status.produced_a_plan


# --- E2E-09 ---------------------------------------------------------------


def test_e2e_09_losing_radar_still_produces_a_plan(owner: UserId, now: datetime) -> None:
    harness = build_harness(radar_available=False)
    declare(
        harness.graph,
        owner,
        now,
        EntityType.INTEREST,
        "Pottery",
        InterestAttributes(engagement=EngagementLevel.ACTIVE),
    )
    declare(
        harness.graph,
        owner,
        now,
        EntityType.PLACE,
        "Riyadh",
        PlaceAttributes(city="Riyadh", area="Al Nakheel"),
    )
    _long_day(harness.graph, owner, now)

    result = harness.runtime.run(
        _user_request(owner, now, "what's on?"),
        graph=harness.graph,
        intent=Intent.DISCOVER,
        now=now,
    )

    assert result.status is RuntimeStatus.PARTIAL
    assert any(failure.agent is AgentName.RADAR for failure in result.failures)
    assert all(not failure.blocks_action for failure in result.failures)
    assert result.warnings


# --- E2E-10 ---------------------------------------------------------------


def test_e2e_10_losing_guardian_fails_closed(owner: UserId, now: datetime) -> None:
    harness = build_harness(guardian_available=False)
    action = reference_pilates(owner, now, Money.of(10000, "SAR"))
    harness.operator.proposal = action

    result = harness.runtime.run(
        _user_request(owner, now, "book it"),
        graph=harness.graph,
        intent=Intent.EXECUTE,
        now=now,
    )

    assert result.status is RuntimeStatus.BLOCKED
    assert harness.operator.executed == []
    assert result.required_authorizations == ()
    assert any(warning.code == "FAIL_CLOSED" for warning in result.warnings)
    assert result.plan.suppressed_for(SuppressionReason.GUARDIAN_BLOCK)


# --- E2E-11 ---------------------------------------------------------------


def test_e2e_11_a_flood_still_produces_a_small_plan(owner: UserId, now: datetime) -> None:
    harness = build_harness()
    for index in range(300):
        declare(
            harness.graph,
            owner,
            now,
            EntityType.RADAR_ITEM,
            f"Find {index}",
            RadarItemAttributes(category=RadarCategory.EVENT, headline=f"Find {index}"),
        )
    for index in range(14):
        declare(
            harness.graph,
            owner,
            now,
            EntityType.COMMITMENT,
            f"Open loop {index}",
            CommitmentAttributes(kind=CommitmentKind.FOLLOW_UP, state=OpenLoopState.DUE),
            markers=TemporalMarkers(due_at=now + timedelta(days=1)),
        )
    for index in range(8):
        declare(
            harness.graph,
            owner,
            now,
            EntityType.REQUIREMENT,
            f"Requirement {index}",
            RequirementAttributes(
                kind=RequirementKind.BRING_ITEM, status=RequirementStatus.UNSATISFIED
            ),
        )
    for index in range(4):
        declare(
            harness.graph,
            owner,
            now,
            EntityType.GOAL,
            f"Goal {index}",
            GoalAttributes(horizon=GoalHorizon.YEAR, domain=LifeDomain.LEARNING),
        )

    result = harness.runtime.run(
        _user_request(owner, now, "what should I do?"),
        graph=harness.graph,
        intent=Intent.DISCOVER,
        now=now,
    )

    assert result.trace.candidates_considered > 200
    assert len(result.plan.items) <= DEFAULT_BUDGET.max_total
    assert len(result.plan.opportunities) <= DEFAULT_BUDGET.max_opportunities
    assert result.plan.suppressed
    # Nothing was thrown away without a reason.
    assert all(item.reason for item in result.plan.suppressed)


# --- E2E-12 ---------------------------------------------------------------


def test_e2e_12_guardian_allowing_it_does_not_make_it_feasible(
    owner: UserId, now: datetime
) -> None:
    harness = build_harness()
    thursday = now + timedelta(days=4)
    declare(
        harness.graph,
        owner,
        now,
        EntityType.COMMITMENT,
        "Thursday 19:00",
        CommitmentAttributes(kind=CommitmentKind.APPOINTMENT, state=OpenLoopState.SCHEDULED),
        markers=TemporalMarkers(due_at=thursday),
    )
    declare(
        harness.graph,
        owner,
        now,
        EntityType.RADAR_ITEM,
        "Thursday 19:00",
        RadarItemAttributes(category=RadarCategory.OPPORTUNITY, headline="Thursday 19:00"),
        markers=TemporalMarkers(scheduled_for=thursday),
    )

    result = harness.runtime.run(
        _user_request(owner, now, "anything worth doing?"),
        graph=harness.graph,
        intent=Intent.DISCOVER,
        now=now,
    )

    surviving = [item for item in result.plan.items if item.title == "Thursday 19:00"]
    assert len(surviving) == 1
    assert surviving[0].origin_agent is AgentName.LIFE_ADMIN
    # Guardian never blocked it; it simply cannot happen, which is a different thing.
    assert not result.plan.suppressed_for(SuppressionReason.GUARDIAN_BLOCK)


# --- E2E-13 ---------------------------------------------------------------


def test_e2e_13_nothing_useful_produces_no_action(owner: UserId, now: datetime) -> None:
    harness = build_harness()

    result = harness.runtime.run(
        _user_request(owner, now, "hmm"),
        graph=harness.graph,
        intent=Intent.PLAN_DAY,
        now=now,
    )

    assert result.status is RuntimeStatus.NO_ACTION
    assert result.plan.is_empty
    assert result.plan.items == ()


def test_e2e_13b_an_unroutable_trigger_produces_no_action(owner: UserId, now: datetime) -> None:
    harness = build_harness()

    result = harness.runtime.run(
        RuntimeRequest.from_event(user_id=owner, event_type=EventType.MOOD_UPDATED, at=now),
        graph=harness.graph,
        intent=Intent.REFLECT,
        now=now,
    )

    assert result.status is RuntimeStatus.NO_ACTION
    assert result.trace.routed_agents == ()


# --- E2E-14 ---------------------------------------------------------------


def test_e2e_14_a_retried_request_is_one_run(owner: UserId, now: datetime) -> None:
    harness = build_harness()
    _long_day(harness.graph, owner, now)
    ledger = InMemoryRuntimeLedger()
    request = _mobile_request(owner, now, now, "cev_retry")

    first = harness.runtime.run(
        request, graph=harness.graph, intent=Intent.PLAN_DAY, now=now, ledger=ledger
    )
    retry = harness.runtime.run(
        _mobile_request(owner, now, now + timedelta(seconds=30), "cev_retry"),
        graph=harness.graph,
        intent=Intent.PLAN_DAY,
        now=now,
        ledger=ledger,
    )

    assert retry.request_id == first.request_id
    assert retry.emitted_events == first.emitted_events
    assert len(ledger) == 1


def test_e2e_14b_two_different_submissions_are_two_runs(owner: UserId, now: datetime) -> None:
    harness = build_harness()
    _long_day(harness.graph, owner, now)
    ledger = InMemoryRuntimeLedger()

    first = harness.runtime.run(
        _mobile_request(owner, now, now, "cev_a"),
        graph=harness.graph,
        intent=Intent.PLAN_DAY,
        now=now,
        ledger=ledger,
    )
    second = harness.runtime.run(
        _mobile_request(owner, now, now, "cev_b"),
        graph=harness.graph,
        intent=Intent.PLAN_DAY,
        now=now,
        ledger=ledger,
    )

    assert first.request_id != second.request_id
    assert len(ledger) == 2


# --- E2E-15 ---------------------------------------------------------------


def test_e2e_15_changed_terms_invalidate_the_authorization_request(
    owner: UserId, now: datetime
) -> None:
    harness = build_harness()
    action = reference_pilates(owner, now, Money.of(10000, "SAR"))
    harness.operator.proposal = action

    result = harness.runtime.run(
        _user_request(owner, now, "book it"),
        graph=harness.graph,
        intent=Intent.EXECUTE,
        now=now,
    )
    issued = result.required_authorizations[0]
    consent = ExecutionAuthorization.for_action(
        issued.action,
        authorization_id=AuthorizationId("aut_1"),
        granted_at=now,
        method=AuthorizationMethod.EXPLICIT_CONFIRMATION,
        audit_ref="audit_1",
    )

    moved = issued.action.with_terms(starts_at="2026-03-03T20:00:00Z")
    verdict = harness.authority.allow(
        action_id=moved.action_id, fingerprint=moved.terms_fingerprint, at=now
    )

    assert consent.covers(issued.action)
    assert not consent.covers(moved)
    decision = harness.runtime.execution_policy.authorize(moved, verdict, consent, now)
    assert decision.outcome is PolicyOutcome.DENY
    assert decision.has_reason(ReasonCode.MATERIAL_TERMS_CHANGED)


# --- the runtime keeps its own boundaries --------------------------------


def test_the_orchestrator_writes_nothing_to_the_graph(owner: UserId, now: datetime) -> None:
    harness = build_harness()
    _long_day(harness.graph, owner, now)
    before = {entity.id: entity.revision for entity in harness.graph.entities(owner_id=owner)}

    harness.runtime.run(
        _user_request(owner, now, "plan my day"),
        graph=harness.graph,
        intent=Intent.PLAN_DAY,
        now=now,
    )

    after = {entity.id: entity.revision for entity in harness.graph.entities(owner_id=owner)}
    assert after == before


def test_the_trace_records_shape_and_never_values(owner: UserId, now: datetime) -> None:
    harness = build_harness()
    declare(
        harness.graph,
        owner,
        now,
        EntityType.COMMITMENT,
        "Something private about her",
        CommitmentAttributes(kind=CommitmentKind.FOLLOW_UP, state=OpenLoopState.DUE),
        markers=TemporalMarkers(due_at=now + timedelta(days=1)),
    )

    result = harness.runtime.run(
        _user_request(owner, now, "open loops"),
        graph=harness.graph,
        intent=Intent.OPEN_LOOPS,
        now=now,
    )

    dumped = result.trace.model_dump_json()
    assert "Something private about her" not in dumped
    assert result.trace.scopes
    assert all(scope.entities_delivered >= 0 for scope in result.trace.scopes)
    assert result.trace.execution_order


def test_the_runtime_holds_no_state_between_runs(owner: UserId, now: datetime) -> None:
    """Two runs of the same request on the same instance agree, so two instances would."""
    harness = build_harness()
    _long_day(harness.graph, owner, now)

    first = harness.runtime.run(
        _user_request(owner, now, "plan"), graph=harness.graph, intent=Intent.PLAN_DAY, now=now
    )
    second = harness.runtime.run(
        _user_request(owner, now, "plan"), graph=harness.graph, intent=Intent.PLAN_DAY, now=now
    )

    assert [item.title for item in first.plan.items] == [item.title for item in second.plan.items]
    assert first.trace.execution_order == second.trace.execution_order


def test_priorities_survive_composition(owner: UserId, now: datetime) -> None:
    harness = build_harness()
    _long_day(harness.graph, owner, now)

    result = harness.runtime.run(
        _user_request(owner, now, "plan"), graph=harness.graph, intent=Intent.PLAN_DAY, now=now
    )

    assert result.plan.items
    assert all(item.priority in set(PriorityClass) for item in result.plan.items)
    if result.plan.now:
        assert result.plan.now[0].priority.rank <= PriorityClass.P1.rank
