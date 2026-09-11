from pydantic import BaseModel, ConfigDict, Field

from wplos.agents.contracts import Intent
from wplos.application.request import RuntimeRequest, TriggerType
from wplos.core.purpose import Purpose
from wplos.core.roles import AgentName
from wplos.events.types import EventType


class RoutingRule(BaseModel):
    """One declarative reason to wake some minds.

    Routing is a table, not a chain of conditionals: it has to be readable,
    testable and extendable without anyone editing a function body.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    purpose: Purpose
    agents: tuple[AgentName, ...]
    triggers: frozenset[TriggerType] = Field(default_factory=frozenset)
    event_types: frozenset[EventType] = Field(default_factory=frozenset)
    intents: frozenset[Intent] = Field(default_factory=frozenset)

    def matches(self, request: RuntimeRequest, intent: Intent) -> bool:
        if self.triggers and request.trigger not in self.triggers:
            return False
        if self.event_types and request.trigger_ref.event_type not in self.event_types:
            return False
        return not (self.intents and intent not in self.intents)


ROUTING_RULES: tuple[RoutingRule, ...] = (
    RoutingRule(
        name="deadline_pressure",
        purpose=Purpose.CLOSE_OPEN_LOOPS,
        agents=(AgentName.LIFE_ADMIN, AgentName.READINESS),
        triggers=frozenset({TriggerType.DOMAIN_EVENT}),
        event_types=frozenset(
            {
                EventType.DEADLINE_APPROACHING,
                EventType.DEADLINE_MISSED,
                EventType.RETURN_WINDOW_CLOSING,
            }
        ),
    ),
    RoutingRule(
        name="radar_discovery",
        purpose=Purpose.FIND_LOCAL_EVENT,
        agents=(
            AgentName.RADAR,
            AgentName.LIFE_ADMIN,
            AgentName.NAVIGATOR,
            AgentName.GUARDIAN,
        ),
        triggers=frozenset({TriggerType.DOMAIN_EVENT}),
        event_types=frozenset({EventType.RADAR_ITEM_DISCOVERED}),
    ),
    RoutingRule(
        name="action_proposed",
        purpose=Purpose.EXECUTE_ACTION,
        agents=(AgentName.GUARDIAN, AgentName.OPERATOR),
        triggers=frozenset({TriggerType.DOMAIN_EVENT, TriggerType.MOBILE_ACTION}),
        event_types=frozenset(
            {EventType.OPERATOR_ACTION_PROPOSED, EventType.OPERATOR_ACTION_AUTHORIZED}
        ),
    ),
    RoutingRule(
        name="capture_triage",
        purpose=Purpose.CAPTURE_TRIAGE,
        agents=(AgentName.LIFE_ADMIN, AgentName.GUARDIAN),
        triggers=frozenset({TriggerType.DOMAIN_EVENT}),
        event_types=frozenset({EventType.CAPTURE_PARSED, EventType.CAPTURE_ROUTED}),
    ),
    RoutingRule(
        name="calendar_change",
        purpose=Purpose.GET_READY,
        agents=(AgentName.LIFE_ADMIN, AgentName.READINESS, AgentName.GUARDIAN),
        triggers=frozenset({TriggerType.DOMAIN_EVENT}),
        event_types=frozenset(
            {
                EventType.EVENT_CREATED,
                EventType.EVENT_UPDATED,
                EventType.CALENDAR_CONFLICT_DETECTED,
                EventType.REQUIREMENT_STATUS_CHANGED,
            }
        ),
    ),
    RoutingRule(
        name="plan_the_day",
        purpose=Purpose.PLAN_DAY,
        agents=(
            AgentName.NAVIGATOR,
            AgentName.LIFE_ADMIN,
            AgentName.READINESS,
            AgentName.GUARDIAN,
        ),
        triggers=frozenset(
            {
                TriggerType.USER_REQUEST,
                TriggerType.MOBILE_ACTION,
                TriggerType.SCHEDULED,
                TriggerType.SYSTEM_REEVALUATION,
            }
        ),
        intents=frozenset({Intent.PLAN_DAY}),
    ),
    RoutingRule(
        name="open_loops",
        purpose=Purpose.CLOSE_OPEN_LOOPS,
        agents=(AgentName.LIFE_ADMIN, AgentName.NAVIGATOR, AgentName.GUARDIAN),
        triggers=frozenset({TriggerType.USER_REQUEST, TriggerType.MOBILE_ACTION}),
        intents=frozenset({Intent.OPEN_LOOPS}),
    ),
    RoutingRule(
        name="get_ready",
        purpose=Purpose.GET_READY,
        agents=(AgentName.READINESS, AgentName.GUARDIAN),
        triggers=frozenset(
            {TriggerType.USER_REQUEST, TriggerType.MOBILE_ACTION, TriggerType.SCHEDULED}
        ),
        intents=frozenset({Intent.GET_READY}),
    ),
    RoutingRule(
        name="direction_check",
        purpose=Purpose.DIRECTION_CHECK,
        agents=(AgentName.NAVIGATOR, AgentName.GUARDIAN),
        triggers=frozenset({TriggerType.USER_REQUEST, TriggerType.MOBILE_ACTION}),
        intents=frozenset({Intent.DIRECTION_CHECK, Intent.REFLECT}),
    ),
    RoutingRule(
        name="discover",
        purpose=Purpose.FIND_LOCAL_EVENT,
        agents=(
            AgentName.RADAR,
            AgentName.LIFE_ADMIN,
            AgentName.NAVIGATOR,
            AgentName.GUARDIAN,
        ),
        triggers=frozenset({TriggerType.USER_REQUEST, TriggerType.MOBILE_ACTION}),
        intents=frozenset({Intent.DISCOVER}),
    ),
    RoutingRule(
        name="execute",
        purpose=Purpose.EXECUTE_ACTION,
        agents=(AgentName.LIFE_ADMIN, AgentName.GUARDIAN, AgentName.OPERATOR),
        triggers=frozenset({TriggerType.USER_REQUEST, TriggerType.MOBILE_ACTION}),
        intents=frozenset({Intent.EXECUTE}),
    ),
    RoutingRule(
        name="capture",
        purpose=Purpose.CAPTURE_TRIAGE,
        agents=(AgentName.LIFE_ADMIN, AgentName.GUARDIAN),
        triggers=frozenset({TriggerType.USER_REQUEST, TriggerType.MOBILE_ACTION}),
        intents=frozenset({Intent.CAPTURE}),
    ),
    RoutingRule(
        name="safety_fallback",
        purpose=Purpose.SAFETY_REVIEW,
        agents=(AgentName.GUARDIAN,),
        triggers=frozenset({TriggerType.USER_REQUEST, TriggerType.MOBILE_ACTION}),
        intents=frozenset({Intent.UNKNOWN}),
    ),
)


class RoutingDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    agents: tuple[AgentName, ...]
    purpose: Purpose
    matched_rules: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not self.agents


class Router:
    """Picks the minds and the purpose. It never decides anything about a life."""

    def __init__(self, rules: tuple[RoutingRule, ...] = ROUTING_RULES) -> None:
        self.rules = rules

    def route(self, request: RuntimeRequest, intent: Intent) -> RoutingDecision:
        matched = [rule for rule in self.rules if rule.matches(request, intent)]
        if not matched:
            return RoutingDecision(agents=(), purpose=Purpose.SAFETY_REVIEW, matched_rules=())

        agents: list[AgentName] = []
        for rule in matched:
            for agent in rule.agents:
                if agent not in agents:
                    agents.append(agent)
        return RoutingDecision(
            agents=tuple(agents),
            purpose=matched[0].purpose,
            matched_rules=tuple(rule.name for rule in matched),
        )


DEFAULT_ROUTER = Router()
