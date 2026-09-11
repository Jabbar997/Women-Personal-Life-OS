from wplos.agents.contracts import AgentContract, DecisionState
from wplos.core.roles import AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.events.types import EventType
from wplos.personal_life_graph.entity_types import EntityType
from wplos.personal_life_graph.memory import MemoryType
from wplos.policy.guardian import (
    GuardianAssessment,
    GuardianCheck,
    GuardianFinding,
    GuardianVerdict,
)
from wplos.policy.permissions import PermissionLevel

GUARDIAN_CHECKS = tuple(GuardianCheck)

GUARDIAN_CONTRACT = AgentContract(
    agent=AgentName.GUARDIAN,
    mission="Protect the user and constrain system behaviour.",
    reads=frozenset(
        {
            EntityType.HEALTH_CONDITION,
            EntityType.CYCLE_STATE,
            EntityType.PREGNANCY_STATE,
            EntityType.BODY_SIGNAL,
            EntityType.MONEY_CONTEXT,
            EntityType.PURCHASE,
            EntityType.SUBSCRIPTION,
            EntityType.CALENDAR_EVENT,
            EntityType.COMMITMENT,
            EntityType.PERSON,
            EntityType.PRODUCT,
            EntityType.INGREDIENT,
            EntityType.DOCUMENT,
        }
    ),
    writes=frozenset(),
    reads_memory=frozenset(
        {MemoryType.FACT, MemoryType.PREFERENCE, MemoryType.DECISION, MemoryType.RELATIONSHIP}
    ),
    decision_authority=frozenset({DecisionState.IGNORE, DecisionState.SURFACE}),
    max_permission_level=PermissionLevel.A0,
    max_sensitivity=SensitivityLevel.S3,
    events_consumed=frozenset(
        {
            EventType.OPERATOR_ACTION_PROPOSED,
            EventType.RADAR_ITEM_DISCOVERED,
            EventType.CALENDAR_CONFLICT_DETECTED,
            EventType.CYCLE_STATE_CHANGED,
        }
    ),
    events_produced=frozenset(
        {EventType.GUARDIAN_CAUTION_RAISED, EventType.GUARDIAN_BLOCKED_ACTION}
    ),
    required_policies=("sensitivity.need_to_know", "execution.authorization"),
    forbidden=(
        "Produce any verdict other than ALLOW, CAUTION, BLOCK or ESCALATE.",
        "Write to the Personal Life Graph.",
        "Be overridden by another mind or by the Orchestrator.",
    ),
    holds_veto=True,
)

__all__ = [
    "GUARDIAN_CHECKS",
    "GUARDIAN_CONTRACT",
    "GuardianAssessment",
    "GuardianCheck",
    "GuardianFinding",
    "GuardianVerdict",
]
