from enum import StrEnum

from wplos.agents.contracts import AgentContract, DecisionState
from wplos.core.roles import AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.events.types import EventType
from wplos.personal_life_graph.entity_types import EntityType
from wplos.personal_life_graph.memory import MemoryType
from wplos.policy.permissions import PermissionLevel


class ReadinessOutputKind(StrEnum):
    WEAR = "WEAR"
    GET_READY = "GET_READY"
    CARRY = "CARRY"
    PREPARE = "PREPARE"
    LEAVE_AT = "LEAVE_AT"
    AVOID = "AVOID"
    TONIGHT = "TONIGHT"
    TOMORROW = "TOMORROW"


class ReadinessMode(StrEnum):
    FULL = "FULL"
    QUICK = "QUICK"


READINESS_CONTRACT = AgentContract(
    agent=AgentName.READINESS,
    mission="Make the user ready for what comes next.",
    reads=frozenset(
        {
            EntityType.CALENDAR_EVENT,
            EntityType.COMMITMENT,
            EntityType.TASK,
            EntityType.PLACE,
            EntityType.WARDROBE_ITEM,
            EntityType.PRODUCT,
            EntityType.AVAILABILITY_STATE,
            EntityType.CYCLE_STATE,
            EntityType.PREGNANCY_STATE,
            EntityType.BODY_SIGNAL,
            EntityType.ROUTINE,
            EntityType.DOCUMENT,
        }
    ),
    writes=frozenset({EntityType.TASK, EntityType.ROUTINE}),
    reads_memory=frozenset({MemoryType.PREFERENCE, MemoryType.BEHAVIOR, MemoryType.TEMPORAL}),
    decision_authority=frozenset(
        {DecisionState.IGNORE, DecisionState.SURFACE, DecisionState.RECOMMEND}
    ),
    max_permission_level=PermissionLevel.A0,
    max_sensitivity=SensitivityLevel.S3,
    events_consumed=frozenset(
        {
            EventType.EVENT_CREATED,
            EventType.EVENT_UPDATED,
            EventType.WEATHER_CONTEXT_CHANGED,
            EventType.CYCLE_STATE_CHANGED,
            EventType.ENERGY_UPDATED,
            EventType.SLEEP_UPDATED,
            EventType.WARDROBE_ITEM_STATUS_CHANGED,
            EventType.PRODUCT_LOW,
        }
    ),
    events_produced=frozenset(
        {
            EventType.READINESS_PLAN_CREATED,
            EventType.READINESS_PLAN_UPDATED,
            EventType.READY_CHECK_COMPLETED,
        }
    ),
    required_policies=("sensitivity.need_to_know",),
    forbidden=(
        "Execute an external action.",
        "Compute departure time with a language model instead of travel arithmetic.",
        "Surface body or cycle context outside the reason it was read for.",
    ),
)
