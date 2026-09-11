from wplos.agents.contracts import AgentContract, DecisionState
from wplos.core.roles import AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.events.types import EventType
from wplos.personal_life_graph.attributes import OpenLoopState
from wplos.personal_life_graph.entity_types import EntityType
from wplos.personal_life_graph.memory import MemoryType
from wplos.policy.permissions import PermissionLevel

OPEN_LOOP_STATES = tuple(OpenLoopState)

LIFE_ADMIN_CONTRACT = AgentContract(
    agent=AgentName.LIFE_ADMIN,
    mission="Own the user's open loops.",
    reads=frozenset(
        {
            EntityType.COMMITMENT,
            EntityType.TASK,
            EntityType.DEADLINE,
            EntityType.CALENDAR_EVENT,
            EntityType.SUBSCRIPTION,
            EntityType.PURCHASE,
            EntityType.DOCUMENT,
            EntityType.PERSON,
            EntityType.PRODUCT,
            EntityType.GOAL,
        }
    ),
    writes=frozenset(
        {
            EntityType.COMMITMENT,
            EntityType.TASK,
            EntityType.DEADLINE,
            EntityType.DOCUMENT,
        }
    ),
    reads_memory=frozenset({MemoryType.FACT, MemoryType.TEMPORAL, MemoryType.DECISION}),
    decision_authority=frozenset(
        {DecisionState.IGNORE, DecisionState.SURFACE, DecisionState.RECOMMEND}
    ),
    max_permission_level=PermissionLevel.A0,
    max_sensitivity=SensitivityLevel.S3,
    events_consumed=frozenset(
        {
            EventType.CAPTURE_PARSED,
            EventType.CAPTURE_ROUTED,
            EventType.EVENT_CREATED,
            EventType.EVENT_CANCELLED,
            EventType.PRODUCT_LOW,
        }
    ),
    events_produced=frozenset(
        {
            EventType.COMMITMENT_CAPTURED,
            EventType.COMMITMENT_UPDATED,
            EventType.COMMITMENT_COMPLETED,
            EventType.TASK_CREATED,
            EventType.TASK_COMPLETED,
            EventType.DEADLINE_CREATED,
            EventType.DEADLINE_APPROACHING,
            EventType.DEADLINE_MISSED,
            EventType.CALENDAR_CONFLICT_DETECTED,
        }
    ),
    required_policies=("sensitivity.need_to_know",),
    forbidden=(
        "Turn every piece of information into a task.",
        "Execute an external action directly.",
        "Compute a deadline with a language model instead of date arithmetic.",
    ),
)
