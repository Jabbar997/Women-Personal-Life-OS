"""A runnable runtime for the end-to-end tests."""

from dataclasses import dataclass, field
from datetime import datetime

from wplos.application.orchestrator import OrchestratorRuntime
from wplos.application.reference_agents import (
    DeterministicGuardian,
    DeterministicLifeAdmin,
    DeterministicNavigator,
    DeterministicOperator,
    DeterministicRadar,
    DeterministicReadiness,
)
from wplos.core.roles import AgentName
from wplos.personal_life_graph.graph import PersonalLifeGraph
from wplos.policy.execution import ExecutionPolicy
from wplos.policy.guardian_authority import GuardianAuthority


@dataclass
class Harness:
    authority: GuardianAuthority
    navigator: DeterministicNavigator
    radar: DeterministicRadar
    life_admin: DeterministicLifeAdmin
    readiness: DeterministicReadiness
    guardian: DeterministicGuardian
    operator: DeterministicOperator
    runtime: OrchestratorRuntime
    graph: PersonalLifeGraph = field(default_factory=PersonalLifeGraph)


def build_harness(
    *,
    graph: PersonalLifeGraph | None = None,
    radar_available: bool = True,
    guardian_available: bool = True,
    readiness_unsafe: bool = False,
    now: datetime | None = None,
) -> Harness:
    authority = GuardianAuthority()
    navigator = DeterministicNavigator()
    radar = DeterministicRadar(available=radar_available)
    life_admin = DeterministicLifeAdmin()
    readiness = DeterministicReadiness(propose_unsafe=readiness_unsafe)
    guardian = DeterministicGuardian(authority, available=guardian_available)
    operator = DeterministicOperator()

    runtime = OrchestratorRuntime(
        agents={
            AgentName.NAVIGATOR: navigator,
            AgentName.RADAR: radar,
            AgentName.LIFE_ADMIN: life_admin,
            AgentName.READINESS: readiness,
            AgentName.GUARDIAN: guardian,
            AgentName.OPERATOR: operator,
        },
        execution_policy=ExecutionPolicy(authority),
        executor=operator,
    )
    return Harness(
        authority=authority,
        navigator=navigator,
        radar=radar,
        life_admin=life_admin,
        readiness=readiness,
        guardian=guardian,
        operator=operator,
        runtime=runtime,
        graph=graph or PersonalLifeGraph(),
    )
