from __future__ import annotations

from enum import StrEnum

from wlos.agents.contracts import AgentContract, DecisionState, PriorityClass
from wlos.core.base import DomainModel
from wlos.core.minds import Mind
from wlos.events.catalog import EventType
from wlos.personal_life_graph.domains import LifeDomain
from wlos.policy.permissions import PermissionLevel
from wlos.shared.confidence import Confidence
from wlos.shared.identifiers import EntityId

CONTRACT = AgentContract(
    mind=Mind.NAVIGATOR,
    mission="Determine what matters and where the user is going.",
    reads=frozenset(
        {
            LifeDomain.GOALS,
            LifeDomain.PRIORITIES,
            LifeDomain.COMMITMENTS,
            LifeDomain.TASKS,
            LifeDomain.CALENDAR,
            LifeDomain.ENERGY,
            LifeDomain.BEHAVIORAL_HISTORY,
            LifeDomain.CAREER,
            LifeDomain.EDUCATION,
            LifeDomain.FAMILY,
            LifeDomain.RADAR,
        }
    ),
    writes=frozenset({LifeDomain.PRIORITIES, LifeDomain.GOALS}),
    decision_authority=frozenset(
        {DecisionState.IGNORE, DecisionState.SURFACE, DecisionState.RECOMMEND}
    ),
    max_permission_level=PermissionLevel.A0,
    forbidden_actions=(
        "execute external actions",
        "override a Guardian verdict",
        "invent commitments the user never made",
    ),
    events_consumed=frozenset(
        {
            EventType.GOAL_CREATED,
            EventType.GOAL_UPDATED,
            EventType.GOAL_PROGRESS_UPDATED,
            EventType.COMMITMENT_CAPTURED,
            EventType.COMMITMENT_COMPLETED,
            EventType.DEADLINE_APPROACHING,
            EventType.BEHAVIOR_PATTERN_UPDATED,
        }
    ),
    events_produced=frozenset({EventType.GOAL_PROGRESS_UPDATED, EventType.GOAL_UPDATED}),
    required_policies=("sensitivity.need-to-know.v1",),
)


class GoalRisk(StrEnum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    STALLED = "STALLED"
    BLOCKED = "BLOCKED"


class FocusRecommendation(DomainModel):
    goal_id: EntityId
    headline: str
    priority: PriorityClass
    next_milestone: str | None = None
    risk: GoalRisk = GoalRisk.ON_TRACK


class ProgressAssessment(DomainModel):
    goal_id: EntityId
    progress: float
    risk: GoalRisk
    confidence: Confidence


class Deprioritization(DomainModel):
    goal_id: EntityId
    reason: str
