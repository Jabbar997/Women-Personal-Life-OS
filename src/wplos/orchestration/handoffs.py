from pydantic import BaseModel, ConfigDict, Field

from wplos.agents.registry import contract_for
from wplos.core.roles import AgentName
from wplos.events.types import EventType


class Handoff(BaseModel):
    """One permitted pass of work between minds.

    ``carries`` is what makes a handoff real rather than a diagram: the source
    must actually produce those events and the target must actually consume
    them, so a declared flow cannot quietly fail to connect.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: AgentName | None
    target: AgentName
    purpose: str
    carries: frozenset[EventType] = Field(default_factory=frozenset)

    @property
    def is_orchestrated(self) -> bool:
        """A handoff with no source agent is issued by the Orchestrator itself."""
        return self.source is None

    def disconnected_events(self) -> frozenset[EventType]:
        """Events this handoff claims to carry that the contracts do not support."""
        consumed = contract_for(self.target).events_consumed
        produced = (
            frozenset(EventType)
            if self.source is None
            else contract_for(self.source).events_produced
        )
        return frozenset(
            event for event in self.carries if event not in produced or event not in consumed
        )


AGENT_HANDOFFS: tuple[Handoff, ...] = (
    Handoff(
        source=AgentName.RADAR,
        target=AgentName.NAVIGATOR,
        purpose="Opportunity evaluation against the user's direction.",
        carries=frozenset({EventType.RADAR_ITEM_DISCOVERED}),
    ),
    Handoff(
        source=AgentName.NAVIGATOR,
        target=AgentName.LIFE_ADMIN,
        purpose="An accepted milestone becomes a commitment candidate.",
        carries=frozenset({EventType.GOAL_UPDATED, EventType.GOAL_PROGRESS_UPDATED}),
    ),
    Handoff(
        source=AgentName.LIFE_ADMIN,
        target=AgentName.READINESS,
        purpose="An upcoming commitment requires preparation.",
        carries=frozenset({EventType.COMMITMENT_CAPTURED, EventType.DEADLINE_APPROACHING}),
    ),
    Handoff(
        source=AgentName.READINESS,
        target=AgentName.GUARDIAN,
        purpose="A safety-sensitive preparation step needs a verdict.",
        carries=frozenset({EventType.READINESS_PLAN_CREATED}),
    ),
    Handoff(
        source=AgentName.RADAR,
        target=AgentName.GUARDIAN,
        purpose="A discovered item is checked before it is ever recommended.",
        carries=frozenset({EventType.RADAR_ITEM_DISCOVERED}),
    ),
    Handoff(
        source=AgentName.LIFE_ADMIN,
        target=AgentName.GUARDIAN,
        purpose="A scheduling clash is checked for real-world consequence.",
        carries=frozenset({EventType.CALENDAR_CONFLICT_DETECTED}),
    ),
    Handoff(
        source=AgentName.OPERATOR,
        target=AgentName.GUARDIAN,
        purpose="Every proposed action is assessed before authorization is sought.",
        carries=frozenset({EventType.OPERATOR_ACTION_PROPOSED}),
    ),
    Handoff(
        source=AgentName.GUARDIAN,
        target=AgentName.OPERATOR,
        purpose="A verdict reaches the only mind that can execute.",
        carries=frozenset({EventType.GUARDIAN_BLOCKED_ACTION, EventType.GUARDIAN_CAUTION_RAISED}),
    ),
    Handoff(
        source=None,
        target=AgentName.OPERATOR,
        purpose="The Orchestrator routes an authorized decision to execution.",
        carries=frozenset({EventType.OPERATOR_ACTION_AUTHORIZED}),
    ),
)

HANDOFFS_INTO_GUARDIAN: tuple[Handoff, ...] = tuple(
    handoff for handoff in AGENT_HANDOFFS if handoff.target is AgentName.GUARDIAN
)


def handoffs_from(agent: AgentName) -> tuple[Handoff, ...]:
    return tuple(handoff for handoff in AGENT_HANDOFFS if handoff.source is agent)


def handoffs_into(agent: AgentName) -> tuple[Handoff, ...]:
    return tuple(handoff for handoff in AGENT_HANDOFFS if handoff.target is agent)
