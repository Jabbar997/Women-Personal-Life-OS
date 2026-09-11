from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from wplos.core.identifiers import ActionId, AuthorizationId, EntityId, MemoryId
from wplos.core.roles import AgentName
from wplos.core.temporal import ensure_utc
from wplos.events.types import EventType
from wplos.personal_life_graph.attributes import (
    AvailabilityState,
    BodySignalKind,
    CyclePhase,
    OpenLoopState,
    RadarCategory,
)
from wplos.personal_life_graph.entity_types import EntityType
from wplos.personal_life_graph.memory import MemoryType
from wplos.policy.guardian import GuardianCheck, GuardianVerdict
from wplos.policy.permissions import ActionDomain, PermissionLevel
from wplos.shared.errors import UnknownEventType


class EventPayload(BaseModel):
    """Base for every event body. Payloads are plain data and must serialize."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class EntityRefPayload(EventPayload):
    entity_id: EntityId
    entity_type: EntityType


class UserProfileUpdatedPayload(EventPayload):
    changed_fields: tuple[str, ...]


class GoalProgressUpdatedPayload(EventPayload):
    goal_entity_id: EntityId
    previous_progress: float = Field(ge=0.0, le=1.0)
    current_progress: float = Field(ge=0.0, le=1.0)


class OpenLoopPayload(EventPayload):
    entity_id: EntityId
    entity_type: EntityType
    state: OpenLoopState
    due_at: datetime | None = None

    @field_validator("due_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)


class DeadlinePayload(EventPayload):
    deadline_entity_id: EntityId
    due_at: datetime
    hard: bool

    @field_validator("due_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class DeadlineApproachingPayload(DeadlinePayload):
    minutes_remaining: int = Field(ge=0)


class CalendarEventPayload(EventPayload):
    event_entity_id: EntityId
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)


class CalendarConflictPayload(EventPayload):
    first_event_entity_id: EntityId
    second_event_entity_id: EntityId
    overlap_minutes: int = Field(ge=1)


class CapturePayload(EventPayload):
    capture_id: str
    channel: str


class CaptureParsedPayload(EventPayload):
    capture_id: str
    extracted_count: int = Field(ge=0)


class CaptureRoutedPayload(EventPayload):
    capture_id: str
    routed_to: tuple[AgentName, ...]


class MemoryPayload(EventPayload):
    memory_id: MemoryId
    memory_type: MemoryType


class MemoryInvalidatedPayload(MemoryPayload):
    reason: str


class RecommendationPayload(EventPayload):
    """The raw signal behind behavioural learning.

    Without a record of what was offered and what happened to it, a derived
    preference has no evidence and cannot be revised against the facts.
    """

    recommendation_id: str
    offered_by: AgentName
    title: str
    subject_entity_id: EntityId | None = None


class PurchaseRecordedPayload(EventPayload):
    purchase_entity_id: EntityId
    returnable_until: datetime | None = None

    @field_validator("returnable_until")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)


class ReturnWindowClosingPayload(EventPayload):
    purchase_entity_id: EntityId
    returnable_until: datetime
    days_remaining: int = Field(ge=0)

    @field_validator("returnable_until")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class PreferenceObservedPayload(EventPayload):
    memory_id: MemoryId
    statement: str
    inferred: bool


class BehaviorPatternPayload(EventPayload):
    entity_id: EntityId
    pattern: str
    observations: int = Field(ge=1)


class ProductPayload(EventPayload):
    product_entity_id: EntityId


class ProductStockPayload(ProductPayload):
    remaining_ratio: float = Field(ge=0.0, le=1.0)


class WardrobeItemPayload(EventPayload):
    item_entity_id: EntityId


class WardrobeItemStatusPayload(WardrobeItemPayload):
    previous_state: AvailabilityState
    current_state: AvailabilityState


class CycleStateChangedPayload(EventPayload):
    """Emitted by cycle rules, never by a language model."""

    previous_phase: CyclePhase
    current_phase: CyclePhase
    cycle_day: int | None = Field(default=None, ge=1, le=90)
    predicted: bool


class BodySignalPayload(EventPayload):
    signal: BodySignalKind
    scale_value: float | None = Field(default=None, ge=0.0, le=10.0)


class WeatherContextPayload(EventPayload):
    place_entity_id: EntityId
    temperature_c: float
    condition: str


class RadarItemPayload(EventPayload):
    radar_entity_id: EntityId
    category: RadarCategory


class GuardianPayload(EventPayload):
    verdict: GuardianVerdict
    checks: tuple[GuardianCheck, ...]
    explanation: str
    subject_action_id: ActionId | None = None


class ReadinessPlanPayload(EventPayload):
    plan_id: str
    target_event_entity_id: EntityId | None = None
    item_count: int = Field(ge=0)


class ReadyCheckPayload(EventPayload):
    plan_id: str
    missing_item_count: int = Field(ge=0)


class OperatorActionPayload(EventPayload):
    action_id: ActionId
    domain: ActionDomain
    permission_level: PermissionLevel


class OperatorAuthorizationPayload(EventPayload):
    action_id: ActionId
    authorization_id: AuthorizationId
    permission_level: PermissionLevel


class OperatorActionResultPayload(EventPayload):
    action_id: ActionId
    detail: str | None = None


PAYLOAD_BY_EVENT: dict[EventType, type[EventPayload]] = {
    EventType.USER_PROFILE_UPDATED: UserProfileUpdatedPayload,
    EventType.GOAL_CREATED: EntityRefPayload,
    EventType.GOAL_UPDATED: EntityRefPayload,
    EventType.GOAL_PROGRESS_UPDATED: GoalProgressUpdatedPayload,
    EventType.COMMITMENT_CAPTURED: OpenLoopPayload,
    EventType.COMMITMENT_UPDATED: OpenLoopPayload,
    EventType.COMMITMENT_COMPLETED: OpenLoopPayload,
    EventType.TASK_CREATED: OpenLoopPayload,
    EventType.TASK_COMPLETED: OpenLoopPayload,
    EventType.DEADLINE_CREATED: DeadlinePayload,
    EventType.DEADLINE_APPROACHING: DeadlineApproachingPayload,
    EventType.DEADLINE_MISSED: DeadlinePayload,
    EventType.EVENT_CREATED: CalendarEventPayload,
    EventType.EVENT_UPDATED: CalendarEventPayload,
    EventType.EVENT_CANCELLED: CalendarEventPayload,
    EventType.CALENDAR_CONFLICT_DETECTED: CalendarConflictPayload,
    EventType.CAPTURE_RECEIVED: CapturePayload,
    EventType.CAPTURE_PARSED: CaptureParsedPayload,
    EventType.CAPTURE_ROUTED: CaptureRoutedPayload,
    EventType.MEMORY_CREATED: MemoryPayload,
    EventType.MEMORY_UPDATED: MemoryPayload,
    EventType.MEMORY_INVALIDATED: MemoryInvalidatedPayload,
    EventType.RECOMMENDATION_SURFACED: RecommendationPayload,
    EventType.RECOMMENDATION_ACCEPTED: RecommendationPayload,
    EventType.RECOMMENDATION_DISMISSED: RecommendationPayload,
    EventType.RECOMMENDATION_IGNORED: RecommendationPayload,
    EventType.PURCHASE_RECORDED: PurchaseRecordedPayload,
    EventType.RETURN_WINDOW_CLOSING: ReturnWindowClosingPayload,
    EventType.PREFERENCE_OBSERVED: PreferenceObservedPayload,
    EventType.BEHAVIOR_PATTERN_UPDATED: BehaviorPatternPayload,
    EventType.PRODUCT_ADDED: ProductPayload,
    EventType.PRODUCT_LOW: ProductStockPayload,
    EventType.PRODUCT_EXPIRED: ProductPayload,
    EventType.WARDROBE_ITEM_ADDED: WardrobeItemPayload,
    EventType.WARDROBE_ITEM_STATUS_CHANGED: WardrobeItemStatusPayload,
    EventType.CYCLE_STATE_CHANGED: CycleStateChangedPayload,
    EventType.MOOD_UPDATED: BodySignalPayload,
    EventType.ENERGY_UPDATED: BodySignalPayload,
    EventType.SLEEP_UPDATED: BodySignalPayload,
    EventType.WEATHER_CONTEXT_CHANGED: WeatherContextPayload,
    EventType.RADAR_ITEM_DISCOVERED: RadarItemPayload,
    EventType.RADAR_ITEM_SAVED: RadarItemPayload,
    EventType.RADAR_ITEM_DISMISSED: RadarItemPayload,
    EventType.RADAR_ITEM_ACTED_ON: RadarItemPayload,
    EventType.GUARDIAN_CAUTION_RAISED: GuardianPayload,
    EventType.GUARDIAN_BLOCKED_ACTION: GuardianPayload,
    EventType.READINESS_PLAN_CREATED: ReadinessPlanPayload,
    EventType.READINESS_PLAN_UPDATED: ReadinessPlanPayload,
    EventType.READY_CHECK_COMPLETED: ReadyCheckPayload,
    EventType.OPERATOR_ACTION_PROPOSED: OperatorActionPayload,
    EventType.OPERATOR_ACTION_AUTHORIZED: OperatorAuthorizationPayload,
    EventType.OPERATOR_ACTION_REJECTED: OperatorActionResultPayload,
    EventType.OPERATOR_ACTION_STARTED: OperatorActionResultPayload,
    EventType.OPERATOR_ACTION_SUCCEEDED: OperatorActionResultPayload,
    EventType.OPERATOR_ACTION_FAILED: OperatorActionResultPayload,
    EventType.OPERATOR_ACTION_REVERSED: OperatorActionResultPayload,
}


def payload_model_for(event_type: EventType) -> type[EventPayload]:
    model = PAYLOAD_BY_EVENT.get(event_type)
    if model is None:
        raise UnknownEventType(f"no payload schema registered for {event_type}")
    return model
