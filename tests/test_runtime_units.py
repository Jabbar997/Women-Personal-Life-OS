"""The machinery itself: routing, planning, scope, enforcement, budget."""

from datetime import datetime, timedelta

import pytest

from wplos.agents.contracts import (
    AgentOutput,
    AgentRecommendation,
    DecisionState,
    GraphWriteIntent,
    Intent,
    PriorityClass,
    WriteOperation,
)
from wplos.agents.registry import contract_for
from wplos.application.candidates import CandidateKind, PlanCandidate
from wplos.application.composer import (
    DEFAULT_BUDGET,
    ActionComposer,
    CompositionBudget,
    SuppressionReason,
)
from wplos.application.enforcement import ContractViolation, enforce_output
from wplos.application.failure import DEFAULT_FAILURE_POLICY, FailureDisposition
from wplos.application.planning import (
    DEFAULT_PLANNER,
    AgentCriticality,
    CyclicPlan,
    ExecutionPlan,
    PlanNode,
)
from wplos.application.purpose_scopes import PURPOSE_SCOPES, PurposeScope, scope_for
from wplos.application.request import RuntimeRequest, TriggerType
from wplos.application.routing import DEFAULT_ROUTER, ROUTING_RULES
from wplos.core.confidence import Confidence
from wplos.core.identifiers import ActionId, UserId
from wplos.core.purpose import Purpose
from wplos.core.roles import AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.events.types import EventType
from wplos.personal_life_graph.entity_types import EntityType
from wplos.policy.execution import ProposedAction
from wplos.policy.guardian import GuardianAssessment, GuardianVerdict
from wplos.policy.permissions import ActionDomain, PermissionLevel, ReversibilityClass

# --- routing --------------------------------------------------------------


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        (EventType.DEADLINE_APPROACHING, (AgentName.LIFE_ADMIN, AgentName.READINESS)),
        (EventType.RADAR_ITEM_DISCOVERED, (AgentName.RADAR, AgentName.LIFE_ADMIN)),
        (EventType.OPERATOR_ACTION_PROPOSED, (AgentName.GUARDIAN, AgentName.OPERATOR)),
    ],
)
def test_events_route_to_the_minds_that_own_them(
    owner: UserId, now: datetime, event_type: EventType, expected: tuple[AgentName, ...]
) -> None:
    request = RuntimeRequest.from_event(user_id=owner, event_type=event_type, at=now)

    decision = DEFAULT_ROUTER.route(request, Intent.UNKNOWN)

    assert decision.agents[: len(expected)] == expected
    assert decision.matched_rules


def test_routing_is_a_table_not_a_chain_of_conditionals() -> None:
    assert len({rule.name for rule in ROUTING_RULES}) == len(ROUTING_RULES)
    for rule in ROUTING_RULES:
        assert rule.agents
        assert rule.triggers or rule.event_types or rule.intents


def test_an_unroutable_request_produces_no_agents(owner: UserId, now: datetime) -> None:
    request = RuntimeRequest.from_event(user_id=owner, event_type=EventType.MOOD_UPDATED, at=now)

    assert DEFAULT_ROUTER.route(request, Intent.REFLECT).is_empty


# --- planning -------------------------------------------------------------


def test_guardian_runs_last_because_it_judges_what_the_others_proposed() -> None:
    """Proposing and acting are different. The Operator speaks before Guardian;
    it acts only in the authorization phase, after Guardian has answered."""
    plan = DEFAULT_PLANNER.plan(
        (AgentName.LIFE_ADMIN, AgentName.GUARDIAN, AgentName.OPERATOR),
        Purpose.EXECUTE_ACTION,
    )

    order = plan.execution_order()
    assert order[-1] is AgentName.GUARDIAN
    assert order.index(AgentName.OPERATOR) < order.index(AgentName.GUARDIAN)
    assert order.index(AgentName.LIFE_ADMIN) < order.index(AgentName.GUARDIAN)


def test_independent_minds_land_in_the_same_wave() -> None:
    plan = DEFAULT_PLANNER.plan((AgentName.NAVIGATOR, AgentName.RADAR), Purpose.PLAN_DAY)

    waves = plan.waves()
    assert waves[0] == (AgentName.RADAR,)
    assert waves[1] == (AgentName.NAVIGATOR,)


def test_a_plan_that_waits_on_itself_is_refused() -> None:
    with pytest.raises(CyclicPlan, match="dependency cycle"):
        ExecutionPlan(
            nodes=(
                PlanNode(
                    agent=AgentName.RADAR,
                    purpose=Purpose.PLAN_DAY,
                    depends_on=frozenset({AgentName.NAVIGATOR}),
                    criticality=AgentCriticality.OPTIONAL,
                ),
                PlanNode(
                    agent=AgentName.NAVIGATOR,
                    purpose=Purpose.PLAN_DAY,
                    depends_on=frozenset({AgentName.RADAR}),
                    criticality=AgentCriticality.OPTIONAL,
                ),
            )
        )


def test_a_plan_cannot_depend_on_a_mind_that_is_not_running() -> None:
    with pytest.raises(ValueError, match="is not planned"):
        ExecutionPlan(
            nodes=(
                PlanNode(
                    agent=AgentName.NAVIGATOR,
                    purpose=Purpose.PLAN_DAY,
                    depends_on=frozenset({AgentName.RADAR}),
                    criticality=AgentCriticality.OPTIONAL,
                ),
            )
        )


# --- purpose-bound context ------------------------------------------------


def test_the_same_mind_gets_different_context_for_different_jobs() -> None:
    local = scope_for(AgentName.RADAR, Purpose.FIND_LOCAL_EVENT)
    wellness = scope_for(AgentName.RADAR, Purpose.WELLNESS_OPPORTUNITY)

    assert EntityType.PLACE in local.required_entity_types
    assert EntityType.PLACE not in wellness.required_entity_types
    assert local.purpose is Purpose.FIND_LOCAL_EVENT
    assert wellness.max_sensitivity.rank < local.max_sensitivity.rank


def test_radar_looking_for_a_local_event_is_not_given_body_context() -> None:
    scope = scope_for(AgentName.RADAR, Purpose.FIND_LOCAL_EVENT)

    for forbidden in (
        EntityType.CYCLE_STATE,
        EntityType.PREGNANCY_STATE,
        EntityType.BODY_SIGNAL,
        EntityType.HEALTH_CONDITION,
    ):
        assert forbidden not in scope.required_entity_types


def test_a_purpose_can_narrow_a_contract_but_never_widen_it() -> None:
    with pytest.raises(ValueError, match="does not allow"):
        PurposeScope(
            agent=AgentName.RADAR,
            purpose=Purpose.FIND_LOCAL_EVENT,
            entity_types=frozenset({EntityType.CYCLE_STATE}),
        )

    with pytest.raises(ValueError, match="above its ceiling"):
        PurposeScope(
            agent=AgentName.RADAR,
            purpose=Purpose.FIND_LOCAL_EVENT,
            entity_types=frozenset({EntityType.PLACE}),
            max_sensitivity=SensitivityLevel.S3,
        )


def test_every_declared_purpose_scope_stays_inside_its_contract() -> None:
    for (agent, _purpose), scope in PURPOSE_SCOPES.items():
        contract = contract_for(agent)
        assert scope.entity_types <= contract.reads
        assert scope.memory_types <= contract.reads_memory


def test_a_job_with_no_declared_scope_falls_back_to_the_contract() -> None:
    scope = scope_for(AgentName.GUARDIAN, Purpose.SAFETY_REVIEW)

    assert scope.required_entity_types == contract_for(AgentName.GUARDIAN).reads


# --- contract enforcement -------------------------------------------------


def _action(
    owner: UserId, now: datetime, agent: AgentName, level: PermissionLevel
) -> ProposedAction:
    return ProposedAction(
        action_id=ActionId("act_x"),
        owner_id=owner,
        proposed_by=agent,
        proposed_at=now,
        domain=ActionDomain.COMMUNICATION if level.is_executable else ActionDomain.INTERNAL,
        permission_level=level,
        summary="something",
        reversibility=ReversibilityClass.REVERSIBLE,
    )


def test_radar_returning_a_guardian_assessment_is_rejected(owner: UserId, now: datetime) -> None:
    output = AgentOutput(
        agent=AgentName.RADAR,
        request_id="req_1",  # type: ignore[arg-type]
        assessments=(
            GuardianAssessment(subject_action_id=ActionId("act_x"), verdict=GuardianVerdict.ALLOW),
        ),
    )

    with pytest.raises(ContractViolation, match="returned a Guardian assessment"):
        enforce_output(contract_for(AgentName.RADAR), output)


def test_readiness_returning_an_act_decision_is_rejected(owner: UserId, now: datetime) -> None:
    output = AgentOutput(
        agent=AgentName.READINESS,
        request_id="req_1",  # type: ignore[arg-type]
        recommendations=(
            AgentRecommendation(
                title="do it",
                rationale="because",
                decision_state=DecisionState.ACT,
                priority=PriorityClass.P2,
                confidence=Confidence.certain(),
                proposed_action=_action(owner, now, AgentName.READINESS, PermissionLevel.A0),
            ),
        ),
    )

    with pytest.raises(ContractViolation, match="not permitted to decide"):
        enforce_output(contract_for(AgentName.READINESS), output)


def test_a_mind_proposing_above_its_permission_level_is_rejected(
    owner: UserId, now: datetime
) -> None:
    output = AgentOutput(
        agent=AgentName.RADAR,
        request_id="req_1",  # type: ignore[arg-type]
        recommendations=(
            AgentRecommendation(
                title="book it",
                rationale="a deal",
                decision_state=DecisionState.RECOMMEND,
                priority=PriorityClass.P2,
                confidence=Confidence.certain(),
                proposed_action=_action(owner, now, AgentName.RADAR, PermissionLevel.A2),
            ),
        ),
    )

    with pytest.raises(ContractViolation, match="above its A0"):
        enforce_output(contract_for(AgentName.RADAR), output)


def test_a_mind_writing_outside_its_contract_is_rejected() -> None:
    output = AgentOutput(
        agent=AgentName.RADAR,
        request_id="req_1",  # type: ignore[arg-type]
        writes=(
            GraphWriteIntent(
                entity_type=EntityType.HEALTH_CONDITION,
                operation=WriteOperation.CREATE,
                summary="noticed something",
            ),
        ),
    )

    with pytest.raises(ContractViolation, match="does not allow"):
        enforce_output(contract_for(AgentName.RADAR), output)


def test_a_mind_answering_for_another_is_rejected() -> None:
    output = AgentOutput(agent=AgentName.RADAR, request_id="req_1")  # type: ignore[arg-type]

    with pytest.raises(ContractViolation, match="answered for"):
        enforce_output(contract_for(AgentName.NAVIGATOR), output)


def test_a_permitted_write_passes() -> None:
    output = AgentOutput(
        agent=AgentName.RADAR,
        request_id="req_1",  # type: ignore[arg-type]
        writes=(
            GraphWriteIntent(
                entity_type=EntityType.RADAR_ITEM,
                operation=WriteOperation.CREATE,
                summary="a find",
            ),
        ),
    )

    assert enforce_output(contract_for(AgentName.RADAR), output) is output


# --- failure policy -------------------------------------------------------


def test_losing_guardian_fails_closed_and_losing_radar_does_not() -> None:
    guardian = DEFAULT_FAILURE_POLICY.record(
        AgentName.GUARDIAN, AgentCriticality.SAFETY_CRITICAL, "unreachable"
    )
    radar = DEFAULT_FAILURE_POLICY.record(AgentName.RADAR, AgentCriticality.OPTIONAL, "unreachable")
    life_admin = DEFAULT_FAILURE_POLICY.record(
        AgentName.LIFE_ADMIN, AgentCriticality.REQUIRED, "unreachable"
    )

    assert guardian.disposition is FailureDisposition.FAIL_CLOSED
    assert guardian.blocks_action
    assert radar.disposition is FailureDisposition.CONTINUE
    assert not radar.blocks_action
    assert life_admin.disposition is FailureDisposition.CONTINUE_DEGRADED


# --- composition ----------------------------------------------------------


def _candidate(
    index: int,
    kind: CandidateKind,
    priority: PriorityClass,
    *,
    title: str | None = None,
    subject: str | None = None,
    agent: AgentName = AgentName.LIFE_ADMIN,
) -> PlanCandidate:
    name = title or f"item {index}"
    return PlanCandidate(
        candidate_id=f"c{index}",
        origin_agent=agent,
        kind=kind,
        title=name,
        rationale="because",
        priority=priority,
        confidence=Confidence.certain(),
        decision_state=DecisionState.SURFACE,
        subject=subject or f"subject-{index}",
        dedupe_key=name.casefold(),
    )


def test_twenty_candidates_become_a_bounded_plan_with_reasons() -> None:
    candidates = tuple(
        _candidate(index, CandidateKind.COMMITMENT, PriorityClass.P2) for index in range(20)
    )

    plan = ActionComposer().compose(candidates)

    assert len(plan.items) <= DEFAULT_BUDGET.max_total
    assert len(plan.must_handle) + len(plan.next_up) <= DEFAULT_BUDGET.p2
    assert plan.suppressed
    assert all(item.reason for item in plan.suppressed)


def test_safety_is_never_budgeted_away() -> None:
    candidates = tuple(
        _candidate(index, CandidateKind.WARNING, PriorityClass.P0, agent=AgentName.GUARDIAN)
        for index in range(6)
    ) + tuple(
        _candidate(100 + index, CandidateKind.OPPORTUNITY, PriorityClass.P3, agent=AgentName.RADAR)
        for index in range(20)
    )

    plan = ActionComposer().compose(candidates)

    assert len(plan.warnings) == 6
    assert len(plan.opportunities) <= DEFAULT_BUDGET.max_opportunities


def test_two_minds_saying_the_same_thing_produce_one_item_citing_both() -> None:
    first = _candidate(1, CandidateKind.COMMITMENT, PriorityClass.P1, title="Return the dress")
    second = _candidate(
        2,
        CandidateKind.COMMITMENT,
        PriorityClass.P2,
        title="Return the dress",
        agent=AgentName.READINESS,
    )

    plan = ActionComposer().compose((first, second))

    assert len(plan.items) == 1
    assert plan.suppressed_for(SuppressionReason.DUPLICATE)


def test_a_commitment_and_an_opportunity_sharing_a_title_are_rivals_not_duplicates() -> None:
    """Merging them would let a find quietly absorb a commitment."""
    commitment = _candidate(
        1,
        CandidateKind.COMMITMENT,
        PriorityClass.P1,
        title="Thursday 19:00",
        subject="thursday",
        agent=AgentName.LIFE_ADMIN,
    )
    opportunity = _candidate(
        2,
        CandidateKind.OPPORTUNITY,
        PriorityClass.P3,
        title="Thursday 19:00",
        subject="thursday",
        agent=AgentName.RADAR,
    )

    plan = ActionComposer().compose((commitment, opportunity))

    assert not plan.suppressed_for(SuppressionReason.DUPLICATE)
    assert plan.suppressed_for(SuppressionReason.CONFLICT)
    assert [item.origin_agent for item in plan.items] == [AgentName.LIFE_ADMIN]


def test_a_blocked_action_never_reaches_the_plan(owner: UserId, now: datetime) -> None:
    action = _action(owner, now, AgentName.OPERATOR, PermissionLevel.A0)
    candidate = _candidate(1, CandidateKind.ACTION, PriorityClass.P2).model_copy(
        update={"proposed_action": action}
    )

    plan = ActionComposer().compose((candidate,), blocked_actions=frozenset({action.action_id}))

    assert plan.items == ()
    assert plan.suppressed_for(SuppressionReason.GUARDIAN_BLOCK)


def test_the_budget_is_configurable() -> None:
    tight = ActionComposer(budget=CompositionBudget(p1=1, p2=1, p3=0, max_total=2))
    candidates = tuple(
        _candidate(index, CandidateKind.COMMITMENT, PriorityClass.P1) for index in range(5)
    )

    plan = tight.compose(candidates)

    assert len(plan.items) == 1


def test_a_delayed_request_knows_it_is_delayed(owner: UserId, now: datetime) -> None:
    request = RuntimeRequest(
        request_id="req_1",  # type: ignore[arg-type]
        user_id=owner,
        trigger=TriggerType.MOBILE_ACTION,
        trigger_ref={},  # type: ignore[arg-type]
        occurred_at=now,
        received_at=now + timedelta(hours=2),
        correlation_id="cor_1",  # type: ignore[arg-type]
        client={  # type: ignore[arg-type]
            "origin": "MOBILE_DEVICE",
            "client_request_id": "cev_1",
        },
    )

    assert request.arrived_late
    assert request.delay == timedelta(hours=2)


def test_a_request_cannot_be_received_before_it_happened(owner: UserId, now: datetime) -> None:
    with pytest.raises(ValueError, match="cannot be received before"):
        RuntimeRequest(
            request_id="req_1",  # type: ignore[arg-type]
            user_id=owner,
            trigger=TriggerType.USER_REQUEST,
            trigger_ref={},  # type: ignore[arg-type]
            occurred_at=now,
            received_at=now - timedelta(minutes=1),
            correlation_id="cor_1",  # type: ignore[arg-type]
        )


def test_conflict_resolution_does_not_blow_up_on_volume() -> None:
    """Arbitration groups by subject and walks each group once.

    No optimisation is claimed here; the test exists so that a change to
    quadratic-or-worse behaviour is caught rather than discovered in production.
    """
    import time

    candidates = tuple(
        _candidate(
            index,
            CandidateKind.OPPORTUNITY,
            PriorityClass.P3,
            title=f"find {index}",
            subject=f"slot-{index % 50}",
            agent=AgentName.RADAR,
        )
        for index in range(1000)
    )

    started = time.perf_counter()
    plan = ActionComposer().compose(candidates)
    elapsed = time.perf_counter() - started

    assert elapsed < 2.0
    assert len(plan.items) <= DEFAULT_BUDGET.max_total
    assert len(plan.suppressed) > 900
