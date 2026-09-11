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
from wlos.shared.identifiers import EntityId

CONTRACT = AgentContract(
    mind=Mind.READINESS,
    mission="Make the user ready for what comes next.",
    reads=frozenset(
        {
            LifeDomain.CALENDAR,
            LifeDomain.COMMITMENTS,
            LifeDomain.WARDROBE,
            LifeDomain.BEAUTY_INVENTORY,
            LifeDomain.ESSENTIALS,
            LifeDomain.CYCLE,
            LifeDomain.HEALTH,
            LifeDomain.ENERGY,
            LifeDomain.SLEEP,
            LifeDomain.SKIN,
            LifeDomain.HAIR,
            LifeDomain.PLACES,
            LifeDomain.ROUTINES,
            LifeDomain.BEHAVIORAL_HISTORY,
        }
    ),
    writes=frozenset({LifeDomain.ROUTINES}),
    decision_authority=frozenset(
        {DecisionState.IGNORE, DecisionState.SURFACE, DecisionState.RECOMMEND}
    ),
    max_permission_level=PermissionLevel.A1,
    forbidden_actions=(
        "execute external actions",
        "override a Guardian verdict",
        "surface cycle or health context that the plan does not require",
    ),
    events_consumed=frozenset(
        {
            EventType.EVENT_CREATED,
            EventType.EVENT_UPDATED,
            EventType.CYCLE_STATE_CHANGED,
            EventType.WEATHER_CONTEXT_CHANGED,
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
    required_policies=("sensitivity.need-to-know.v1",),
)


class ReadinessMode(StrEnum):
    FULL = "FULL"
    QUICK = "QUICK"


class ReadinessPlan(DomainModel):
    """What to wear, do, carry and leave by — one plan per upcoming moment.

    ``QUICK`` exists so the same plan can be collapsed to the essentials when
    there is no time; the sections stay the same.
    """

    target_event_id: EntityId | None = None
    mode: ReadinessMode = ReadinessMode.FULL
    wear: tuple[str, ...] = ()
    get_ready: tuple[str, ...] = ()
    carry: tuple[str, ...] = ()
    prepare: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    tonight: tuple[str, ...] = ()
    tomorrow: tuple[str, ...] = ()
    leave_at: datetime | None = None
    estimated_prep_minutes: int | None = None

    @field_validator("leave_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)

    def quick(self) -> ReadinessPlan:
        return self.model_copy(
            update={
                "mode": ReadinessMode.QUICK,
                "wear": self.wear[:1],
                "get_ready": self.get_ready[:2],
                "carry": self.carry[:3],
                "prepare": (),
                "tonight": (),
                "tomorrow": (),
            }
        )
