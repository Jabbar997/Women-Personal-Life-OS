from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from wplos.agents.contracts import Intent
from wplos.core.roles import AgentName


class OrchestratorResponsibility(StrEnum):
    INTENT_CLASSIFICATION = "INTENT_CLASSIFICATION"
    CONTEXT_RETRIEVAL = "CONTEXT_RETRIEVAL"
    AGENT_SELECTION = "AGENT_SELECTION"
    ORDERING = "ORDERING"
    CONFLICT_HANDLING = "CONFLICT_HANDLING"
    GUARDIAN_ENFORCEMENT = "GUARDIAN_ENFORCEMENT"
    PRIORITY_AGGREGATION = "PRIORITY_AGGREGATION"
    ACTION_COMPOSITION = "ACTION_COMPOSITION"
    AUTHORIZATION_ROUTING = "AUTHORIZATION_ROUTING"
    EVENT_EMISSION = "EVENT_EMISSION"


ROUTING_TABLE: dict[Intent, tuple[AgentName, ...]] = {
    Intent.CAPTURE: (AgentName.LIFE_ADMIN, AgentName.GUARDIAN),
    Intent.PLAN_DAY: (
        AgentName.NAVIGATOR,
        AgentName.LIFE_ADMIN,
        AgentName.READINESS,
        AgentName.GUARDIAN,
    ),
    Intent.DIRECTION_CHECK: (AgentName.NAVIGATOR, AgentName.GUARDIAN),
    Intent.GET_READY: (AgentName.READINESS, AgentName.GUARDIAN),
    Intent.OPEN_LOOPS: (AgentName.LIFE_ADMIN, AgentName.NAVIGATOR, AgentName.GUARDIAN),
    Intent.DISCOVER: (AgentName.RADAR, AgentName.NAVIGATOR, AgentName.GUARDIAN),
    Intent.EXECUTE: (AgentName.LIFE_ADMIN, AgentName.GUARDIAN, AgentName.OPERATOR),
    Intent.REFLECT: (AgentName.NAVIGATOR, AgentName.GUARDIAN),
    Intent.UNKNOWN: (AgentName.GUARDIAN,),
}


class OrchestratorContract(BaseModel):
    """The coordinator, not a seventh mind.

    It owns routing, ordering, conflict handling and authorization routing, and
    owns no business domain of its own. Guardian runs before the Operator in
    every route that can execute.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    responsibilities: frozenset[OrchestratorResponsibility]
    owns_business_domain: bool = False
    may_override_guardian: bool = False
    forbidden: tuple[str, ...] = ()

    def agents_for(self, intent: Intent) -> tuple[AgentName, ...]:
        return ROUTING_TABLE[intent]


ORCHESTRATOR_CONTRACT = OrchestratorContract(
    responsibilities=frozenset(OrchestratorResponsibility),
    forbidden=(
        "Hold a business domain of its own.",
        "Override or soften a Guardian verdict.",
        "Let the user pick which mind answers.",
        "Execute an action itself instead of routing it to the Operator.",
    ),
)


def guardian_precedes_operator(route: tuple[AgentName, ...]) -> bool:
    if AgentName.OPERATOR not in route:
        return True
    if AgentName.GUARDIAN not in route:
        return False
    return route.index(AgentName.GUARDIAN) < route.index(AgentName.OPERATOR)
