from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from wplos.core.purpose import Purpose
from wplos.core.roles import AgentName
from wplos.orchestration.handoffs import AGENT_HANDOFFS
from wplos.shared.errors import DomainError


class CyclicPlan(DomainError):
    """A plan in which a mind waits, directly or indirectly, on itself."""


class AgentCriticality(StrEnum):
    """What it means for this mind to fail on this run."""

    OPTIONAL = "OPTIONAL"
    REQUIRED = "REQUIRED"
    SAFETY_CRITICAL = "SAFETY_CRITICAL"


CRITICALITY: dict[AgentName, AgentCriticality] = {
    AgentName.GUARDIAN: AgentCriticality.SAFETY_CRITICAL,
    AgentName.OPERATOR: AgentCriticality.REQUIRED,
    AgentName.LIFE_ADMIN: AgentCriticality.REQUIRED,
    AgentName.READINESS: AgentCriticality.REQUIRED,
    AgentName.NAVIGATOR: AgentCriticality.OPTIONAL,
    AgentName.RADAR: AgentCriticality.OPTIONAL,
}


class PlanNode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: AgentName
    purpose: Purpose
    depends_on: frozenset[AgentName] = frozenset()
    criticality: AgentCriticality


class ExecutionPlan(BaseModel):
    """Who runs, in what order, and what may be run at the same time.

    Dependencies are derived from the declared handoffs rather than invented
    here, so the plan cannot disagree with the map of how work is allowed to
    pass between minds.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    nodes: tuple[PlanNode, ...]

    @model_validator(mode="after")
    def _dependencies_exist_and_do_not_loop(self) -> Self:
        present = {node.agent for node in self.nodes}
        for node in self.nodes:
            missing = node.depends_on - present
            if missing:
                raise ValueError(f"{node.agent} depends on {sorted(missing)}, which is not planned")
        self._topological_order()
        return self

    def _topological_order(self) -> tuple[tuple[AgentName, ...], ...]:
        remaining = {node.agent: set(node.depends_on) for node in self.nodes}
        waves: list[tuple[AgentName, ...]] = []
        while remaining:
            ready = tuple(
                sorted(
                    (agent for agent, deps in remaining.items() if not deps),
                    key=lambda item: item.value,
                )
            )
            if not ready:
                raise CyclicPlan(
                    f"the plan has a dependency cycle among {sorted(remaining, key=str)}"
                )
            waves.append(ready)
            for agent in ready:
                del remaining[agent]
            for deps in remaining.values():
                deps.difference_update(ready)
        return tuple(waves)

    def waves(self) -> tuple[tuple[AgentName, ...], ...]:
        """Groups that may run in parallel, in the order they must run."""
        return self._topological_order()

    def execution_order(self) -> tuple[AgentName, ...]:
        return tuple(agent for wave in self.waves() for agent in wave)

    def node_for(self, agent: AgentName) -> PlanNode:
        return next(node for node in self.nodes if node.agent is agent)

    @property
    def agents(self) -> frozenset[AgentName]:
        return frozenset(node.agent for node in self.nodes)


ACROSS_RUNS: frozenset[tuple[AgentName, AgentName]] = frozenset(
    {(AgentName.GUARDIAN, AgentName.OPERATOR)}
)
"""Handoffs that connect one run to the next rather than ordering a single run.

The handoff map is cyclic on purpose: the Operator proposes an action, Guardian
assesses it, and the verdict returns to the Operator. Inside one run that would
deadlock, so the loop is cut at the verdict.

Which half to cut matters. Proposing and executing are different acts: a mind
has to say what it would do before Guardian can judge it, so the Operator's
*proposal* runs first and Guardian assesses it. Execution is not an agent step
at all — it happens in the authorization phase, after Guardian has answered and
the execution policy has permitted it. "Guardian before the Operator" is a rule
about acting, not about speaking.
"""


def handoff_dependencies(agents: frozenset[AgentName]) -> dict[AgentName, frozenset[AgentName]]:
    """Which of the routed minds each routed mind waits on, within this run."""
    dependencies: dict[AgentName, set[AgentName]] = {agent: set() for agent in agents}
    for handoff in AGENT_HANDOFFS:
        if handoff.source is None:
            continue
        if (handoff.source, handoff.target) in ACROSS_RUNS:
            continue
        if handoff.source in agents and handoff.target in agents:
            dependencies[handoff.target].add(handoff.source)
    return {agent: frozenset(deps) for agent, deps in dependencies.items()}


class Planner:
    """Turns a routing decision into an ordered plan."""

    def plan(self, agents: tuple[AgentName, ...], purpose: Purpose) -> ExecutionPlan:
        chosen = frozenset(agents)
        dependencies = handoff_dependencies(chosen)
        # Guardian judges everything this run proposed, so it waits on all of
        # them. It cannot judge what has not been said yet.
        if AgentName.GUARDIAN in chosen:
            dependencies[AgentName.GUARDIAN] |= chosen - {AgentName.GUARDIAN}

        return ExecutionPlan(
            nodes=tuple(
                PlanNode(
                    agent=agent,
                    purpose=purpose,
                    depends_on=dependencies[agent],
                    criticality=CRITICALITY[agent],
                )
                for agent in agents
            )
        )


DEFAULT_PLANNER = Planner()
