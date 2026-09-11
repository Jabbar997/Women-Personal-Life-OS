from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import field_validator

from wlos.agents.contracts import AgentContract, DecisionState
from wlos.core.base import DomainModel
from wlos.core.minds import Mind
from wlos.events.catalog import EventType
from wlos.personal_life_graph.domains import LifeDomain
from wlos.policy.permissions import PermissionLevel
from wlos.shared.clock import ensure_utc
from wlos.shared.confidence import Confidence
from wlos.shared.identifiers import EntityId
from wlos.shared.provenance import SourceRef

CONTRACT = AgentContract(
    mind=Mind.RADAR,
    mission="Detect relevant external opportunities and changes.",
    reads=frozenset(
        {
            LifeDomain.PLACES,
            LifeDomain.INTERESTS,
            LifeDomain.HOBBIES,
            LifeDomain.GOALS,
            LifeDomain.CALENDAR,
            LifeDomain.FAMILY,
            LifeDomain.CAREER,
            LifeDomain.BEHAVIORAL_HISTORY,
            LifeDomain.RADAR,
        }
    ),
    writes=frozenset({LifeDomain.RADAR}),
    decision_authority=frozenset(
        {DecisionState.IGNORE, DecisionState.SURFACE, DecisionState.RECOMMEND}
    ),
    max_permission_level=PermissionLevel.A0,
    forbidden_actions=(
        "execute any action",
        "treat advertising copy as fact",
        "override a calendar commitment",
        "override a Guardian verdict",
    ),
    events_consumed=frozenset({EventType.WEATHER_CONTEXT_CHANGED, EventType.EVENT_CREATED}),
    events_produced=frozenset(
        {
            EventType.RADAR_ITEM_DISCOVERED,
            EventType.RADAR_ITEM_SAVED,
            EventType.RADAR_ITEM_DISMISSED,
            EventType.RADAR_ITEM_ACTED_ON,
        }
    ),
    required_policies=("sensitivity.need-to-know.v1",),
)


class RadarClassification(StrEnum):
    FYI = "FYI"
    SAVE = "SAVE"
    RECOMMEND = "RECOMMEND"
    ACT_NOW = "ACT_NOW"


class RadarKind(StrEnum):
    OPPORTUNITY = "OPPORTUNITY"
    CHANGE = "CHANGE"
    EVENT = "EVENT"
    DEAL = "DEAL"


class RadarCandidate(DomainModel):
    """A finding, not a fact: origin and relevance travel with it."""

    radar_item_id: EntityId
    kind: RadarKind
    classification: RadarClassification
    title: str
    origin: str
    source: SourceRef
    relevance: Confidence
    occurs_at: datetime | None = None
    expires_at: datetime | None = None
    verified: bool = False

    @field_validator("occurs_at", "expires_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)
