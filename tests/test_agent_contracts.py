"""Authority boundaries are enforced by the contract model, not by convention."""

import pytest
from pydantic import ValidationError

from wplos.agents.contracts import AgentContract, DecisionState, Intent, PriorityClass
from wplos.agents.registry import AGENT_CONTRACTS, contract_for
from wplos.core.purpose import Purpose
from wplos.core.roles import AgentName
from wplos.orchestration.contract import (
    ORCHESTRATOR_CONTRACT,
    ROUTING_TABLE,
    guardian_precedes_operator,
)
from wplos.policy.permissions import PermissionLevel


def test_all_six_minds_have_a_contract() -> None:
    assert set(AGENT_CONTRACTS) == set(AgentName)
    assert len(AGENT_CONTRACTS) == 6


def test_only_guardian_holds_a_veto() -> None:
    for agent, contract in AGENT_CONTRACTS.items():
        assert contract.holds_veto is (agent is AgentName.GUARDIAN)


def test_only_the_operator_may_execute() -> None:
    for agent, contract in AGENT_CONTRACTS.items():
        if agent is AgentName.OPERATOR:
            assert contract.max_permission_level is PermissionLevel.A3
            assert contract.may_decide(DecisionState.ACT)
        else:
            assert contract.max_permission_level is PermissionLevel.A0
            assert not contract.may_decide(DecisionState.ACT)


def test_a_contract_cannot_grant_itself_execution_authority() -> None:
    navigator = contract_for(AgentName.NAVIGATOR)

    with pytest.raises(ValidationError, match="must not hold an executable permission level"):
        AgentContract(**{**navigator.model_dump(), "max_permission_level": PermissionLevel.A2})


def test_a_contract_cannot_grant_itself_a_veto() -> None:
    radar = contract_for(AgentName.RADAR)

    with pytest.raises(ValidationError, match="only Guardian holds veto"):
        AgentContract(**{**radar.model_dump(), "holds_veto": True})


def test_guardian_writes_nothing_to_the_graph() -> None:
    assert contract_for(AgentName.GUARDIAN).writes == frozenset()


def test_a_contract_projects_the_context_scope_it_is_allowed_to_read() -> None:
    readiness = contract_for(AgentName.READINESS)
    scope = readiness.context_scope(Purpose.GET_READY)

    assert scope.consumer is AgentName.READINESS
    assert scope.required_entity_types == readiness.reads
    assert scope.max_sensitivity is readiness.max_sensitivity


def test_every_intent_has_a_route_and_guardian_runs_before_the_operator() -> None:
    assert set(ROUTING_TABLE) == set(Intent)
    for intent in Intent:
        route = ORCHESTRATOR_CONTRACT.agents_for(intent)
        assert route
        assert guardian_precedes_operator(route)


def test_the_orchestrator_owns_no_business_domain() -> None:
    assert ORCHESTRATOR_CONTRACT.owns_business_domain is False
    assert ORCHESTRATOR_CONTRACT.may_override_guardian is False


def test_priority_classes_order_from_safety_downwards() -> None:
    assert PriorityClass.P0.outranks(PriorityClass.P1)
    assert PriorityClass.P1.outranks(PriorityClass.P3)
    assert not PriorityClass.P3.outranks(PriorityClass.P0)


def test_an_act_recommendation_must_carry_a_proposed_action() -> None:
    from wplos.agents.contracts import AgentRecommendation
    from wplos.core.confidence import Confidence

    with pytest.raises(ValidationError, match="must carry a ProposedAction"):
        AgentRecommendation(
            title="book it",
            rationale="the slot is free",
            decision_state=DecisionState.ACT,
            priority=PriorityClass.P2,
            confidence=Confidence.certain(),
        )
