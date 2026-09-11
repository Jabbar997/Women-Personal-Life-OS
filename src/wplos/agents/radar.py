from enum import StrEnum

from wplos.agents.contracts import AgentContract, DecisionState
from wplos.core.roles import AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.events.types import EventType
from wplos.personal_life_graph.entity_types import EntityType
from wplos.personal_life_graph.memory import MemoryType
from wplos.policy.permissions import PermissionLevel


class RadarClassification(StrEnum):
    """How strongly Radar rates a find. ACT_NOW is still a proposal, never an act."""

    FYI = "FYI"
    SAVE = "SAVE"
    RECOMMEND = "RECOMMEND"
    ACT_NOW = "ACT_NOW"


RADAR_CONTRACT = AgentContract(
    agent=AgentName.RADAR,
    mission="Detect relevant external opportunities and changes.",
    reads=frozenset(
        {
            EntityType.PLACE,
            EntityType.INTEREST,
            EntityType.GOAL,
            EntityType.CALENDAR_EVENT,
            EntityType.PERSON,
            EntityType.CAREER_ROLE,
            EntityType.RADAR_ITEM,
            EntityType.BEHAVIOR_PATTERN,
        }
    ),
    writes=frozenset({EntityType.RADAR_ITEM}),
    reads_memory=frozenset({MemoryType.PREFERENCE, MemoryType.BEHAVIOR}),
    decision_authority=frozenset(
        {DecisionState.IGNORE, DecisionState.SURFACE, DecisionState.RECOMMEND}
    ),
    max_permission_level=PermissionLevel.A0,
    max_sensitivity=SensitivityLevel.S2,
    events_consumed=frozenset({EventType.WEATHER_CONTEXT_CHANGED, EventType.RADAR_ITEM_DISMISSED}),
    events_produced=frozenset(
        {
            EventType.RADAR_ITEM_DISCOVERED,
            EventType.RADAR_ITEM_SAVED,
            EventType.RADAR_ITEM_DISMISSED,
            EventType.RADAR_ITEM_ACTED_ON,
        }
    ),
    required_policies=("sensitivity.need_to_know",),
    forbidden=(
        "Execute anything.",
        "Treat an advertisement as an established fact.",
        "Override an existing calendar commitment.",
        "Override a Guardian verdict.",
    ),
)
