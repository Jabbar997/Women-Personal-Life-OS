from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import field_validator

from wlos.agents.contracts import AgentContract, DecisionState, PriorityClass
from wlos.core.base import DomainModel
from wlos.core.minds import Mind
from wlos.events.catalog import EventType
from wlos.personal_life_graph.domains import LifeDomain
from wlos.policy.permissions import PermissionLevel
from wlos.shared.clock import ensure_utc
from wlos.shared.identifiers import EntityId

CONTRACT = AgentContract(
    mind=Mind.LIFE_ADMIN,
    mission="Own the user's open loops.",
    reads=frozenset(
        {
            LifeDomain.COMMITMENTS,
            LifeDomain.TASKS,
            LifeDomain.CALENDAR,
            LifeDomain.PURCHASES,
            LifeDomain.SUBSCRIPTIONS,
            LifeDomain.MONEY,
            LifeDomain.DOCUMENTS,
            LifeDomain.PEOPLE,
        }
    ),
    writes=frozenset(
        {
            LifeDomain.COMMITMENTS,
            LifeDomain.TASKS,
            LifeDomain.CALENDAR,
            LifeDomain.SUBSCRIPTIONS,
            LifeDomain.DOCUMENTS,
        }
    ),
    decision_authority=frozenset(
        {DecisionState.IGNORE, DecisionState.SURFACE, DecisionState.RECOMMEND}
    ),
    max_permission_level=PermissionLevel.A1,
    forbidden_actions=(
        "turn every piece of information into a task",
        "execute external actions directly",
        "override a Guardian verdict",
    ),
    events_consumed=frozenset(
        {
            EventType.CAPTURE_PARSED,
            EventType.CAPTURE_ROUTED,
            EventType.EVENT_CREATED,
            EventType.EVENT_CANCELLED,
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
    required_policies=("sensitivity.need-to-know.v1",),
)


class OpenLoopState(StrEnum):
    CAPTURED = "CAPTURED"
    CLARIFIED = "CLARIFIED"
    SCHEDULED = "SCHEDULED"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    DUE = "DUE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in (OpenLoopState.COMPLETED, OpenLoopState.CANCELLED)


ALLOWED_TRANSITIONS: dict[OpenLoopState, frozenset[OpenLoopState]] = {
    OpenLoopState.CAPTURED: frozenset(
        {OpenLoopState.CLARIFIED, OpenLoopState.SCHEDULED, OpenLoopState.CANCELLED}
    ),
    OpenLoopState.CLARIFIED: frozenset(
        {
            OpenLoopState.SCHEDULED,
            OpenLoopState.WAITING,
            OpenLoopState.BLOCKED,
            OpenLoopState.DUE,
            OpenLoopState.CANCELLED,
        }
    ),
    OpenLoopState.SCHEDULED: frozenset(
        {
            OpenLoopState.WAITING,
            OpenLoopState.BLOCKED,
            OpenLoopState.DUE,
            OpenLoopState.COMPLETED,
            OpenLoopState.CANCELLED,
        }
    ),
    OpenLoopState.WAITING: frozenset(
        {OpenLoopState.SCHEDULED, OpenLoopState.DUE, OpenLoopState.BLOCKED, OpenLoopState.CANCELLED}
    ),
    OpenLoopState.BLOCKED: frozenset(
        {OpenLoopState.SCHEDULED, OpenLoopState.WAITING, OpenLoopState.CANCELLED}
    ),
    OpenLoopState.DUE: frozenset(
        {OpenLoopState.COMPLETED, OpenLoopState.BLOCKED, OpenLoopState.CANCELLED}
    ),
    OpenLoopState.COMPLETED: frozenset(),
    OpenLoopState.CANCELLED: frozenset(),
}


def can_transition(current: OpenLoopState, target: OpenLoopState) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


class OpenLoop(DomainModel):
    """A commitment, task, deadline, return, renewal or follow-up in flight."""

    entity_id: EntityId
    title: str
    state: OpenLoopState
    priority: PriorityClass = PriorityClass.P2
    due_at: datetime | None = None
    scheduled_for: datetime | None = None
    waiting_on: str | None = None
    completed_at: datetime | None = None

    @field_validator("due_at", "scheduled_for", "completed_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)
