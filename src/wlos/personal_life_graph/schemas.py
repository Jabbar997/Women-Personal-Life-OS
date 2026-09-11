from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

from wlos.personal_life_graph.domains import EntityType
from wlos.shared.attributes import Attributes
from wlos.shared.clock import ensure_utc


class TypedAttributes(BaseModel):
    """Attribute shape for entity types whose fields are known up front.

    Entity types without a schema keep the open attribute bag; that keeps the
    graph extensible without turning the whole system into untyped dictionaries.
    """

    model_config = ConfigDict(frozen=True, extra="allow")


class GoalHorizon(StrEnum):
    SHORT_TERM = "SHORT_TERM"
    MEDIUM_TERM = "MEDIUM_TERM"
    LONG_TERM = "LONG_TERM"


class GoalAttributes(TypedAttributes):
    title: str
    horizon: GoalHorizon = GoalHorizon.MEDIUM_TERM
    progress: float = 0.0
    target_at: datetime | None = None

    @field_validator("target_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)

    @field_validator("progress")
    @classmethod
    def _range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("progress must be within 0.0..1.0")
        return value


class CommitmentAttributes(TypedAttributes):
    title: str
    counterparty: str | None = None
    due_at: datetime | None = None
    scheduled_for: datetime | None = None
    completed_at: datetime | None = None

    @field_validator("due_at", "scheduled_for", "completed_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)


class TaskAttributes(TypedAttributes):
    title: str
    due_at: datetime | None = None
    scheduled_for: datetime | None = None
    completed_at: datetime | None = None
    estimated_minutes: int | None = None

    @field_validator("due_at", "scheduled_for", "completed_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)


class CalendarEventAttributes(TypedAttributes):
    title: str
    starts_at: datetime
    ends_at: datetime
    location: str | None = None
    all_day: bool = False

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class CyclePhase(StrEnum):
    MENSTRUAL = "MENSTRUAL"
    FOLLICULAR = "FOLLICULAR"
    OVULATORY = "OVULATORY"
    LUTEAL = "LUTEAL"
    UNKNOWN = "UNKNOWN"


class CycleStateAttributes(TypedAttributes):
    phase: CyclePhase
    cycle_day: int | None = None
    predicted: bool = False


class AvailabilityState(StrEnum):
    AVAILABLE = "AVAILABLE"
    LOW = "LOW"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    EXPIRED = "EXPIRED"
    IN_LAUNDRY = "IN_LAUNDRY"
    LENT_OUT = "LENT_OUT"
    DISCARDED = "DISCARDED"


class WardrobeItemAttributes(TypedAttributes):
    name: str
    category: str | None = None
    color: str | None = None
    availability: AvailabilityState = AvailabilityState.AVAILABLE


class BeautyProductAttributes(TypedAttributes):
    name: str
    brand: str | None = None
    availability: AvailabilityState = AvailabilityState.AVAILABLE
    opened_at: datetime | None = None
    expires_at: datetime | None = None

    @field_validator("opened_at", "expires_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)


class RadarItemAttributes(TypedAttributes):
    title: str
    origin: str
    url: str | None = None
    occurs_at: datetime | None = None
    expires_at: datetime | None = None

    @field_validator("occurs_at", "expires_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)


ATTRIBUTE_SCHEMAS: dict[EntityType, type[TypedAttributes]] = {
    EntityType.GOAL: GoalAttributes,
    EntityType.COMMITMENT: CommitmentAttributes,
    EntityType.TASK: TaskAttributes,
    EntityType.CALENDAR_EVENT: CalendarEventAttributes,
    EntityType.CYCLE_STATE: CycleStateAttributes,
    EntityType.WARDROBE_ITEM: WardrobeItemAttributes,
    EntityType.BEAUTY_PRODUCT: BeautyProductAttributes,
    EntityType.RADAR_ITEM: RadarItemAttributes,
}


def schema_for(entity_type: EntityType) -> type[TypedAttributes] | None:
    return ATTRIBUTE_SCHEMAS.get(entity_type)


def validate_attributes(entity_type: EntityType, attributes: Attributes) -> None:
    schema = schema_for(entity_type)
    if schema is not None:
        schema.model_validate(attributes)
