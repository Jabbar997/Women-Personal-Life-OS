from wplos.agents.contracts import AgentContract, DecisionState
from wplos.core.roles import AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.events.types import EventType
from wplos.personal_life_graph.entity_types import EntityType
from wplos.personal_life_graph.memory import MemoryType
from wplos.policy.permissions import PermissionLevel

NAVIGATOR_CONTRACT = AgentContract(
    agent=AgentName.NAVIGATOR,
    mission="Determine what matters and where the user is going.",
    reads=frozenset(
        {
            EntityType.GOAL,
            EntityType.PRIORITY,
            EntityType.MILESTONE,
            EntityType.COMMITMENT,
            EntityType.TASK,
            EntityType.DEADLINE,
            EntityType.CALENDAR_EVENT,
            EntityType.CAREER_ROLE,
            EntityType.EDUCATION_PROGRAM,
            EntityType.COURSE,
            EntityType.SKILL,
            EntityType.PERSON,
            EntityType.BEHAVIOR_PATTERN,
            EntityType.RADAR_ITEM,
        }
    ),
    writes=frozenset({EntityType.PRIORITY, EntityType.MILESTONE}),
    reads_memory=frozenset({MemoryType.PREFERENCE, MemoryType.BEHAVIOR, MemoryType.DECISION}),
    decision_authority=frozenset(
        {DecisionState.IGNORE, DecisionState.SURFACE, DecisionState.RECOMMEND}
    ),
    max_permission_level=PermissionLevel.A0,
    max_sensitivity=SensitivityLevel.S2,
    events_consumed=frozenset(
        {
            EventType.GOAL_CREATED,
            EventType.GOAL_UPDATED,
            EventType.GOAL_PROGRESS_UPDATED,
            EventType.COMMITMENT_CAPTURED,
            EventType.COMMITMENT_COMPLETED,
            EventType.DEADLINE_APPROACHING,
            EventType.DEADLINE_MISSED,
            EventType.BEHAVIOR_PATTERN_UPDATED,
            EventType.RADAR_ITEM_DISCOVERED,
        }
    ),
    events_produced=frozenset({EventType.GOAL_PROGRESS_UPDATED, EventType.GOAL_UPDATED}),
    required_policies=("sensitivity.need_to_know",),
    forbidden=(
        "Execute external actions.",
        "Override a Guardian verdict.",
        "Invent a commitment the user never made.",
    ),
)

NAVIGATOR_OUTPUT_KINDS = (
    "Priority",
    "Next milestone",
    "Focus recommendation",
    "Deprioritization",
    "Goal risk",
    "Progress assessment",
)
