from __future__ import annotations

import pytest

from wlos.agents.contracts import (
    AgentConfidence,
    AgentDecision,
    AgentOutput,
    AgentRecommendation,
    DecisionState,
    PriorityClass,
    assert_within_contract,
)
from wlos.agents.life_admin import OpenLoopState, can_transition
from wlos.agents.readiness import ReadinessMode, ReadinessPlan
from wlos.core.errors import ContractViolationError
from wlos.core.minds import SIX_MINDS, Mind
from wlos.events.catalog import EventType
from wlos.orchestration.registry import MIND_CONTRACTS, contract_for
from wlos.policy.guardian_verdict import GuardianVerdict
from wlos.policy.permissions import PermissionLevel
from wlos.shared.identifiers import RequestId


def _output(mind: Mind, state: DecisionState, **recommendation_overrides) -> AgentOutput:
    confidence = AgentConfidence(value=0.8)
    recommendation = AgentRecommendation(
        title="do the thing",
        decision_state=state,
        priority=PriorityClass.P2,
        confidence=confidence,
        **recommendation_overrides,
    )
    return AgentOutput(
        mind=mind,
        request_id=RequestId("req_1"),
        decision=AgentDecision(
            decision_state=state, priority=PriorityClass.P2, rationale="test", confidence=confidence
        ),
        recommendations=(recommendation,),
    )


def test_every_mind_has_a_contract():
    assert set(MIND_CONTRACTS) == set(SIX_MINDS)
    for mind in SIX_MINDS:
        contract = contract_for(mind)
        assert contract.mind is mind
        assert contract.mission
        assert contract.reads
        assert contract.decision_authority


def test_only_the_operator_may_act():
    for mind in SIX_MINDS:
        contract = contract_for(mind)
        may_act = DecisionState.ACT in contract.decision_authority
        assert may_act is (mind is Mind.OPERATOR)


def test_only_the_operator_may_reach_external_permission_levels():
    for mind in SIX_MINDS:
        contract = contract_for(mind)
        if mind is Mind.OPERATOR:
            assert contract.max_permission_level is PermissionLevel.A3
        else:
            assert contract.max_permission_level <= PermissionLevel.A1


def test_contract_rejects_a_decision_state_the_mind_does_not_hold():
    with pytest.raises(ContractViolationError):
        assert_within_contract(contract_for(Mind.RADAR), _output(Mind.RADAR, DecisionState.ACT))


def test_contract_rejects_permission_above_the_ceiling():
    output = _output(
        Mind.NAVIGATOR, DecisionState.RECOMMEND, requires_permission=PermissionLevel.A2
    )
    with pytest.raises(ContractViolationError):
        assert_within_contract(contract_for(Mind.NAVIGATOR), output)


def test_contract_rejects_events_the_mind_does_not_produce():
    output = _output(Mind.NAVIGATOR, DecisionState.RECOMMEND).model_copy(
        update={"emitted_event_types": (EventType.OPERATOR_ACTION_AUTHORIZED,)}
    )
    with pytest.raises(ContractViolationError):
        assert_within_contract(contract_for(Mind.NAVIGATOR), output)


def test_a_valid_output_passes_its_contract():
    assert_within_contract(
        contract_for(Mind.NAVIGATOR), _output(Mind.NAVIGATOR, DecisionState.RECOMMEND)
    )


def test_guardian_vocabulary_is_exactly_four_verdicts():
    assert [verdict.value for verdict in GuardianVerdict] == [
        "ALLOW",
        "CAUTION",
        "BLOCK",
        "ESCALATE",
    ]
    assert GuardianVerdict.BLOCK.permits_execution is False
    assert GuardianVerdict.ESCALATE.permits_execution is False


def test_open_loop_transitions_are_constrained():
    assert can_transition(OpenLoopState.CAPTURED, OpenLoopState.SCHEDULED) is True
    assert can_transition(OpenLoopState.COMPLETED, OpenLoopState.SCHEDULED) is False
    assert OpenLoopState.CANCELLED.is_terminal is True


def test_quick_ready_mode_keeps_the_same_sections(now):
    plan = ReadinessPlan(
        wear=("linen dress", "flat sandals"),
        get_ready=("shower", "SPF", "hair"),
        carry=("keys", "card", "water", "umbrella"),
        prepare=("charge the power bank",),
        leave_at=now,
    )
    quick = plan.quick()

    assert quick.mode is ReadinessMode.QUICK
    assert quick.wear == ("linen dress",)
    assert quick.get_ready == ("shower", "SPF")
    assert quick.carry == ("keys", "card", "water")
    assert quick.prepare == ()
    assert quick.leave_at == plan.leave_at
