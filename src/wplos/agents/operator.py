from wplos.agents.contracts import AgentContract, DecisionState
from wplos.core.roles import AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.events.types import EventType
from wplos.personal_life_graph.entity_types import EntityType
from wplos.personal_life_graph.memory import MemoryType
from wplos.policy.execution import (
    AuthorizationMethod,
    ExecutionAuthorization,
    ProposedAction,
    require_execution_authorization,
)
from wplos.policy.permissions import NEVER_SILENT, ActionDomain, PermissionLevel

OPERATOR_CONTRACT = AgentContract(
    agent=AgentName.OPERATOR,
    mission="Turn authorized intent into real-world action.",
    reads=frozenset(
        {
            EntityType.COMMITMENT,
            EntityType.TASK,
            EntityType.CALENDAR_EVENT,
            EntityType.PURCHASE,
            EntityType.SUBSCRIPTION,
            EntityType.DOCUMENT,
            EntityType.PERSON,
            EntityType.PRODUCT,
        }
    ),
    writes=frozenset({EntityType.TASK, EntityType.COMMITMENT, EntityType.CALENDAR_EVENT}),
    reads_memory=frozenset({MemoryType.DECISION, MemoryType.FACT}),
    decision_authority=frozenset(
        {DecisionState.IGNORE, DecisionState.SURFACE, DecisionState.RECOMMEND, DecisionState.ACT}
    ),
    max_permission_level=PermissionLevel.A3,
    max_sensitivity=SensitivityLevel.S3,
    events_consumed=frozenset(
        {
            EventType.GUARDIAN_BLOCKED_ACTION,
            EventType.GUARDIAN_CAUTION_RAISED,
            EventType.OPERATOR_ACTION_AUTHORIZED,
        }
    ),
    events_produced=frozenset(
        {
            EventType.OPERATOR_ACTION_PROPOSED,
            EventType.OPERATOR_ACTION_AUTHORIZED,
            EventType.OPERATOR_ACTION_REJECTED,
            EventType.OPERATOR_ACTION_STARTED,
            EventType.OPERATOR_ACTION_SUCCEEDED,
            EventType.OPERATOR_ACTION_FAILED,
            EventType.OPERATOR_ACTION_REVERSED,
        }
    ),
    required_policies=("execution.authorization", "sensitivity.need_to_know"),
    forbidden=(
        "Execute an A2 or A3 action without a valid authorization.",
        "Execute silently in a domain that is never silent.",
        "Proceed against a Guardian BLOCK.",
        "Widen its own permission level.",
    ),
)


def is_never_silent(domain: ActionDomain) -> bool:
    return domain in NEVER_SILENT


__all__ = [
    "OPERATOR_CONTRACT",
    "ActionDomain",
    "AuthorizationMethod",
    "ExecutionAuthorization",
    "PermissionLevel",
    "ProposedAction",
    "is_never_silent",
    "require_execution_authorization",
]
