"""The authority matrix and the handoff map are checked against the contracts.

A boundary that lives only in a document is a boundary that drifts.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from wplos.agents.contracts import DecisionState
from wplos.agents.registry import AGENT_CONTRACTS
from wplos.core.roles import AgentName
from wplos.events.types import EventType
from wplos.orchestration.contract import ROUTING_TABLE
from wplos.orchestration.handoffs import (
    AGENT_HANDOFFS,
    HANDOFFS_INTO_GUARDIAN,
    handoffs_from,
    handoffs_into,
)
from wplos.personal_life_graph.entity_types import EntityType

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs" / "domain" / "agent-authority-matrix.md"
GENERATOR = ROOT / "scripts" / "generate_authority_matrix.py"


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("authority_matrix", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_committed_matrix_matches_the_contracts_in_code() -> None:
    """The document is derived. If a contract changes and the file does not,
    this fails rather than letting the two tell different stories."""
    rendered = _generator().render()

    assert MATRIX.exists(), "the authority matrix has not been generated"
    assert MATRIX.read_text(encoding="utf-8") == rendered, (
        "the authority matrix is stale; run scripts/generate_authority_matrix.py"
    )


def test_every_object_a_mind_writes_it_may_also_read() -> None:
    for agent, contract in AGENT_CONTRACTS.items():
        assert contract.writes <= contract.reads, f"{agent} writes what it cannot read"


def test_no_mind_writes_an_object_outside_its_contract() -> None:
    for agent, contract in AGENT_CONTRACTS.items():
        for entity_type in EntityType:
            if entity_type not in contract.writes:
                assert not contract.may_write(entity_type), f"{agent} may write {entity_type}"


def test_guardian_is_the_only_veto_and_writes_nothing() -> None:
    vetoes = [agent for agent, contract in AGENT_CONTRACTS.items() if contract.holds_veto]
    assert vetoes == [AgentName.GUARDIAN]
    assert AGENT_CONTRACTS[AgentName.GUARDIAN].writes == frozenset()
    assert not AGENT_CONTRACTS[AgentName.GUARDIAN].may_decide(DecisionState.RECOMMEND)


def test_the_operator_is_the_only_executor() -> None:
    executors = [
        agent
        for agent, contract in AGENT_CONTRACTS.items()
        if contract.max_permission_level.is_executable
    ]
    actors = [
        agent
        for agent, contract in AGENT_CONTRACTS.items()
        if contract.may_decide(DecisionState.ACT)
    ]
    assert executors == [AgentName.OPERATOR]
    assert actors == [AgentName.OPERATOR]


def test_radar_and_navigator_cannot_reach_body_or_money_context() -> None:
    forbidden = {
        EntityType.CYCLE_STATE,
        EntityType.PREGNANCY_STATE,
        EntityType.HEALTH_CONDITION,
        EntityType.BODY_SIGNAL,
        EntityType.MONEY_CONTEXT,
    }
    for agent in (AgentName.RADAR, AgentName.NAVIGATOR):
        assert not (AGENT_CONTRACTS[agent].reads & forbidden)


def test_every_declared_handoff_actually_connects() -> None:
    broken = {
        f"{handoff.source} -> {handoff.target}": sorted(
            event.value for event in handoff.disconnected_events()
        )
        for handoff in AGENT_HANDOFFS
        if handoff.disconnected_events()
    }
    assert not broken, broken


def test_every_proposing_mind_can_hand_off_to_guardian() -> None:
    sources = {handoff.source for handoff in HANDOFFS_INTO_GUARDIAN}
    assert {AgentName.RADAR, AgentName.LIFE_ADMIN, AgentName.READINESS} <= sources
    assert AgentName.OPERATOR in sources


def test_work_reaches_the_operator_only_through_guardian_or_the_orchestrator() -> None:
    for handoff in handoffs_into(AgentName.OPERATOR):
        assert handoff.source in (AgentName.GUARDIAN, None)
    assert any(handoff.is_orchestrated for handoff in handoffs_into(AgentName.OPERATOR))


def test_guardian_hands_on_a_verdict_and_never_authority() -> None:
    for handoff in handoffs_from(AgentName.GUARDIAN):
        assert handoff.carries <= {
            EventType.GUARDIAN_BLOCKED_ACTION,
            EventType.GUARDIAN_CAUTION_RAISED,
        }


def test_no_handoff_bypasses_guardian_in_an_executing_route() -> None:
    for route in ROUTING_TABLE.values():
        if AgentName.OPERATOR in route:
            assert AgentName.GUARDIAN in route
            assert route.index(AgentName.GUARDIAN) < route.index(AgentName.OPERATOR)
