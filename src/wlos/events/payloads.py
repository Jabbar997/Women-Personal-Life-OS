from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from wlos.core.base import DomainModel
from wlos.events.catalog import EventType
from wlos.personal_life_graph.memory import MemoryType
from wlos.personal_life_graph.schemas import AvailabilityState, CyclePhase
from wlos.policy.decisions import ReasonCode
from wlos.policy.execution import ActionKind
from wlos.policy.guardian_verdict import GuardianCheck
from wlos.policy.permissions import PermissionLevel
from wlos.shared.attributes import Attributes
from wlos.shared.clock import ensure_utc
from wlos.shared.confidence import Confidence
from wlos.shared.identifiers import ActionId, EntityId, MemoryId


class EventPayload(DomainModel):
    """Base for event payloads. Serialization must never lose payload fields."""


class GenericPayload(EventPayload):
    """Fallback for events whose shape is not yet pinned down."""

    data: Attributes = Field(default_factory=dict)


class GoalCreatedPayload(EventPayload):
    goal_id: EntityId
    title: str
    target_at: datetime | None = None

    @field_validator("target_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)


class GoalProgressUpdatedPayload(EventPayload):
    goal_id: EntityId
    previous_progress: float
    progress: float


class CommitmentCapturedPayload(EventPayload):
    commitment_id: EntityId
    title: str
    due_at: datetime | None = None
    counterparty: str | None = None

    @field_validator("due_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)


class TaskCreatedPayload(EventPayload):
    task_id: EntityId
    title: str
    due_at: datetime | None = None
    scheduled_for: datetime | None = None

    @field_validator("due_at", "scheduled_for")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)


class TaskCompletedPayload(EventPayload):
    task_id: EntityId
    completed_at: datetime

    @field_validator("completed_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class DeadlineApproachingPayload(EventPayload):
    subject_id: EntityId
    due_at: datetime
    hours_remaining: float

    @field_validator("due_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class CalendarConflictDetectedPayload(EventPayload):
    first_event_id: EntityId
    second_event_id: EntityId
    overlap_minutes: int


class MemoryCreatedPayload(EventPayload):
    memory_id: MemoryId
    memory_type: MemoryType
    statement: str
    confidence: Confidence = 1.0


class PreferenceObservedPayload(EventPayload):
    memory_id: MemoryId
    statement: str
    confidence: Confidence
    observations: int = 1


class CycleStateChangedPayload(EventPayload):
    previous_phase: CyclePhase
    phase: CyclePhase
    cycle_day: int | None = None
    predicted: bool = False


class ProductLowPayload(EventPayload):
    product_id: EntityId
    name: str
    availability: AvailabilityState


class RadarItemDiscoveredPayload(EventPayload):
    radar_item_id: EntityId
    title: str
    origin: str
    relevance: Confidence
    occurs_at: datetime | None = None

    @field_validator("occurs_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)


class GuardianBlockedActionPayload(EventPayload):
    action_id: ActionId
    checks: tuple[GuardianCheck, ...]
    message: str


class OperatorActionProposedPayload(EventPayload):
    action_id: ActionId
    kind: ActionKind
    permission_level: PermissionLevel
    description: str


class OperatorActionAuthorizedPayload(EventPayload):
    action_id: ActionId
    kind: ActionKind
    permission_level: PermissionLevel


class OperatorActionRejectedPayload(EventPayload):
    action_id: ActionId
    kind: ActionKind
    reason_codes: tuple[ReasonCode, ...]


PAYLOAD_TYPES: dict[EventType, type[EventPayload]] = {
    EventType.GOAL_CREATED: GoalCreatedPayload,
    EventType.GOAL_PROGRESS_UPDATED: GoalProgressUpdatedPayload,
    EventType.COMMITMENT_CAPTURED: CommitmentCapturedPayload,
    EventType.TASK_CREATED: TaskCreatedPayload,
    EventType.TASK_COMPLETED: TaskCompletedPayload,
    EventType.DEADLINE_APPROACHING: DeadlineApproachingPayload,
    EventType.CALENDAR_CONFLICT_DETECTED: CalendarConflictDetectedPayload,
    EventType.MEMORY_CREATED: MemoryCreatedPayload,
    EventType.PREFERENCE_OBSERVED: PreferenceObservedPayload,
    EventType.CYCLE_STATE_CHANGED: CycleStateChangedPayload,
    EventType.PRODUCT_LOW: ProductLowPayload,
    EventType.RADAR_ITEM_DISCOVERED: RadarItemDiscoveredPayload,
    EventType.GUARDIAN_BLOCKED_ACTION: GuardianBlockedActionPayload,
    EventType.OPERATOR_ACTION_PROPOSED: OperatorActionProposedPayload,
    EventType.OPERATOR_ACTION_AUTHORIZED: OperatorActionAuthorizedPayload,
    EventType.OPERATOR_ACTION_REJECTED: OperatorActionRejectedPayload,
}


def payload_type_for(event_type: EventType) -> type[EventPayload]:
    return PAYLOAD_TYPES.get(event_type, GenericPayload)
