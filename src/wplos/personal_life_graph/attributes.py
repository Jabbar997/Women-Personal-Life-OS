from collections.abc import Mapping
from datetime import date, datetime
from enum import StrEnum
from typing import ClassVar, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from wplos.core.identifiers import EntityId
from wplos.core.money import Money
from wplos.core.sensitivity import SensitivityLevel
from wplos.core.temporal import ZonedInstant, ensure_utc
from wplos.personal_life_graph.entity_types import EntityType, LifeDomain
from wplos.shared.errors import InvariantViolation


class EntityAttributes(BaseModel):
    """Base for the typed payload of an entity.

    Every :class:`EntityType` must register a model here, so adding a life
    domain is a deliberate schema decision rather than another untyped bag.
    Record-level ``metadata`` remains the escape hatch for incidental values.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    SENSITIVE_FIELDS: ClassVar[Mapping[str, SensitivityLevel]] = {}
    """Fields sharper than their type's default, and how sharp.

    Record-level sensitivity alone forces a choice between over-classifying a
    whole record and dropping the one field that is genuinely sensitive. An
    address makes a place S3; the city in the same record is not S3, and a mind
    that only needs the city should still get it.
    """

    def sensitivity_floor(self) -> SensitivityLevel | None:
        """The floor the *populated* sensitive fields impose on this record."""
        levels = [
            level
            for field, level in self.SENSITIVE_FIELDS.items()
            if getattr(self, field, None) is not None
        ]
        return max(levels, key=lambda level: level.rank) if levels else None

    def redacted_to(self, ceiling: SensitivityLevel) -> tuple[Self, frozenset[str]]:
        """Drop the fields above ``ceiling``, keeping the rest of the record.

        Returns the surviving attributes and the names withheld — never their
        values.
        """
        dropped = frozenset(
            field
            for field, level in self.SENSITIVE_FIELDS.items()
            if getattr(self, field, None) is not None and not ceiling.dominates(level)
        )
        if not dropped:
            return self, frozenset()
        return self.model_copy(update=dict.fromkeys(dropped)), dropped


class Kinship(StrEnum):
    SELF = "SELF"
    PARTNER = "PARTNER"
    PARENT = "PARENT"
    CHILD = "CHILD"
    SIBLING = "SIBLING"
    EXTENDED_FAMILY = "EXTENDED_FAMILY"
    FRIEND = "FRIEND"
    COLLEAGUE = "COLLEAGUE"
    PROFESSIONAL = "PROFESSIONAL"
    OTHER = "OTHER"


class PersonAttributes(EntityAttributes):
    display_name: str
    kinship: Kinship
    is_self: bool = False
    birth_date: date | None = None
    household_member: bool = False


class GoalHorizon(StrEnum):
    NOW = "NOW"
    QUARTER = "QUARTER"
    YEAR = "YEAR"
    LONG_TERM = "LONG_TERM"


class GoalAttributes(EntityAttributes):
    horizon: GoalHorizon
    domain: LifeDomain
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    measurable_outcome: str | None = None


class PriorityClassValue(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class PriorityAttributes(EntityAttributes):
    priority_class: PriorityClassValue
    rationale: str
    subject_entity_id: EntityId | None = None


class MilestoneAttributes(EntityAttributes):
    goal_entity_id: EntityId
    achieved: bool = False


class OpenLoopState(StrEnum):
    """Life Admin owns every open loop from capture to close."""

    CAPTURED = "CAPTURED"
    CLARIFIED = "CLARIFIED"
    SCHEDULED = "SCHEDULED"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    DUE = "DUE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

    @property
    def is_open(self) -> bool:
        return self not in {OpenLoopState.COMPLETED, OpenLoopState.CANCELLED}


class TaskAttributes(EntityAttributes):
    state: OpenLoopState
    effort_minutes: int | None = Field(default=None, ge=0)
    blocked_by_entity_id: EntityId | None = None


class CommitmentKind(StrEnum):
    PROMISE_MADE = "PROMISE_MADE"
    PROMISE_RECEIVED = "PROMISE_RECEIVED"
    APPOINTMENT = "APPOINTMENT"
    RETURN = "RETURN"
    REFUND = "REFUND"
    RENEWAL = "RENEWAL"
    BILL = "BILL"
    FOLLOW_UP = "FOLLOW_UP"
    WAITING_FOR = "WAITING_FOR"


class CommitmentAttributes(EntityAttributes):
    kind: CommitmentKind
    state: OpenLoopState
    counterparty_entity_id: EntityId | None = None


class DeadlineAttributes(EntityAttributes):
    hard: bool
    subject_entity_id: EntityId | None = None
    consequence: str | None = None


class CalendarEventAttributes(EntityAttributes):
    """Start time lives in the entity's ``scheduled_for`` marker; only the end
    of the interval is an attribute.

    ``time_zone`` is what the event is anchored to. An appointment at 09:00 in
    Riyadh stays at 09:00 in Riyadh when she lands in London, so the zone has to
    travel with the event rather than be read from wherever she happens to be.
    """

    time_zone: str | None = None
    ends_at: datetime | None = None
    all_day: bool = False
    place_entity_id: EntityId | None = None
    calendar_ref: str | None = None
    cancelled: bool = False

    @field_validator("ends_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)

    @field_validator("time_zone")
    @classmethod
    def _known_zone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown IANA time zone: {value}") from error
        return value

    def anchored(self, instant: datetime | None) -> ZonedInstant:
        """The start as the event's own zone reads it."""
        if instant is None:
            raise InvariantViolation("this event has no scheduled start")
        return ZonedInstant(instant=instant, time_zone=self.time_zone or "UTC")


class RecurrenceUnit(StrEnum):
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"


class RoutineAttributes(EntityAttributes):
    every: int = Field(ge=1)
    unit: RecurrenceUnit
    preferred_time_of_day: str | None = None


class HabitAttributes(EntityAttributes):
    target_per_week: int = Field(ge=0, le=21)
    current_streak: int = Field(default=0, ge=0)


class CyclePhase(StrEnum):
    MENSTRUAL = "MENSTRUAL"
    FOLLICULAR = "FOLLICULAR"
    OVULATORY = "OVULATORY"
    LUTEAL = "LUTEAL"
    UNKNOWN = "UNKNOWN"


class CycleStateAttributes(EntityAttributes):
    """Cycle arithmetic is a rules concern. A model may report an observation;
    it may not compute the phase."""

    phase: CyclePhase
    cycle_day: int | None = Field(default=None, ge=1, le=90)
    predicted: bool = False


class PregnancyStage(StrEnum):
    NOT_PREGNANT = "NOT_PREGNANT"
    FIRST_TRIMESTER = "FIRST_TRIMESTER"
    SECOND_TRIMESTER = "SECOND_TRIMESTER"
    THIRD_TRIMESTER = "THIRD_TRIMESTER"
    POSTPARTUM = "POSTPARTUM"


class PregnancyStateAttributes(EntityAttributes):
    stage: PregnancyStage
    week: int | None = Field(default=None, ge=0, le=45)
    confirmed_by_user: bool = False


class BodySignalKind(StrEnum):
    MOOD = "MOOD"
    ENERGY = "ENERGY"
    SLEEP = "SLEEP"
    SKIN = "SKIN"
    HAIR = "HAIR"
    PAIN = "PAIN"
    STRESS = "STRESS"


class BodySignalAttributes(EntityAttributes):
    signal: BodySignalKind
    scale_value: float | None = Field(default=None, ge=0.0, le=10.0)
    note: str | None = None


class HealthConditionAttributes(EntityAttributes):
    condition_label: str
    self_reported: bool = True
    active: bool = True


class AvailabilityState(StrEnum):
    AVAILABLE = "AVAILABLE"
    IN_USE = "IN_USE"
    LOW = "LOW"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    EXPIRED = "EXPIRED"
    IN_LAUNDRY = "IN_LAUNDRY"
    NEEDS_REPAIR = "NEEDS_REPAIR"
    LENT_OUT = "LENT_OUT"
    DISCARDED = "DISCARDED"


class AvailabilityStateAttributes(EntityAttributes):
    state: AvailabilityState


class WardrobeCategory(StrEnum):
    TOP = "TOP"
    BOTTOM = "BOTTOM"
    DRESS = "DRESS"
    OUTERWEAR = "OUTERWEAR"
    SHOES = "SHOES"
    BAG = "BAG"
    ACCESSORY = "ACCESSORY"
    MODEST_LAYER = "MODEST_LAYER"
    ACTIVEWEAR = "ACTIVEWEAR"


class WardrobeItemAttributes(EntityAttributes):
    category: WardrobeCategory
    colors: tuple[str, ...] = Field(default_factory=tuple)
    formality: int = Field(default=2, ge=1, le=5)
    weather_min_c: float | None = None
    weather_max_c: float | None = None


class ProductCategory(StrEnum):
    SKINCARE = "SKINCARE"
    HAIRCARE = "HAIRCARE"
    MAKEUP = "MAKEUP"
    FRAGRANCE = "FRAGRANCE"
    SUPPLEMENT = "SUPPLEMENT"
    HOUSEHOLD_ESSENTIAL = "HOUSEHOLD_ESSENTIAL"
    PERSONAL_ESSENTIAL = "PERSONAL_ESSENTIAL"


class ProductAttributes(EntityAttributes):
    category: ProductCategory
    brand: str | None = None
    opened_at: datetime | None = None
    remaining_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    restock_threshold: float = Field(default=0.2, ge=0.0, le=1.0)

    @field_validator("opened_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)


class IngredientFlag(StrEnum):
    PREGNANCY_CAUTION = "PREGNANCY_CAUTION"
    PHOTOSENSITISING = "PHOTOSENSITISING"
    KNOWN_IRRITANT = "KNOWN_IRRITANT"
    USER_AVOIDS = "USER_AVOIDS"


class IngredientAttributes(EntityAttributes):
    inci_name: str | None = None
    flags: frozenset[IngredientFlag] = Field(default_factory=frozenset)


class PurchaseAttributes(EntityAttributes):
    """A purchase captured in conversation often has no price attached yet;
    ``None`` says unknown rather than free."""

    amount: Money | None = None
    merchant: str | None = None
    returnable_until: datetime | None = None

    @field_validator("returnable_until")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)


class SubscriptionAttributes(EntityAttributes):
    amount: Money
    renews_at: datetime | None = None
    cancellable_until: datetime | None = None
    auto_renew: bool = True

    @field_validator("renews_at", "cancellable_until")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)


class MoneyContextAttributes(EntityAttributes):
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    monthly_discretionary: Money | None = None
    spending_caution_threshold: Money | None = None


class EngagementLevel(StrEnum):
    CURIOUS = "CURIOUS"
    ACTIVE = "ACTIVE"
    COMMITTED = "COMMITTED"
    LAPSED = "LAPSED"


class InterestAttributes(EntityAttributes):
    engagement: EngagementLevel
    category: str | None = None


class LocationPrecision(StrEnum):
    AREA = "AREA"
    PRECISE = "PRECISE"


class PlaceAttributes(EntityAttributes):
    """City and area are what a recommendation needs; a street address is not.

    The precise fields are classified individually, so a mind cleared to S2
    receives the city and area of the same record with the address and
    coordinates withheld, rather than losing the place entirely.
    """

    SENSITIVE_FIELDS: ClassVar[Mapping[str, SensitivityLevel]] = {
        "street_address": SensitivityLevel.S3,
        "latitude": SensitivityLevel.S3,
        "longitude": SensitivityLevel.S3,
    }

    city: str | None = None
    area: str | None = None
    street_address: str | None = None
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    is_home: bool = False
    typical_travel_minutes: int | None = Field(default=None, ge=0)

    @property
    def precision(self) -> LocationPrecision:
        return (
            LocationPrecision.PRECISE
            if self.street_address is not None or self.latitude is not None
            else LocationPrecision.AREA
        )


class RadarCategory(StrEnum):
    EVENT = "EVENT"
    DEAL = "DEAL"
    OPPORTUNITY = "OPPORTUNITY"
    LOCAL_CHANGE = "LOCAL_CHANGE"
    LEARNING = "LEARNING"


class RadarItemAttributes(EntityAttributes):
    """What Radar found. Radar never stores an advertisement as a fact; the
    claim stays a claim until something authoritative confirms it."""

    category: RadarCategory
    headline: str
    price: Money | None = None
    starts_at_is_claimed: bool = True
    place_entity_id: EntityId | None = None
    claimed_by_source: bool = True


class RequirementKind(StrEnum):
    """What an event needs in order to go well."""

    BRING_ITEM = "BRING_ITEM"
    WEAR = "WEAR"
    DOCUMENT = "DOCUMENT"
    CARRY_CASH = "CARRY_CASH"
    PAY_BEFORE = "PAY_BEFORE"
    ENTRY_FEE = "ENTRY_FEE"
    PURCHASE = "PURCHASE"

    @property
    def is_monetary(self) -> bool:
        return self in {
            RequirementKind.CARRY_CASH,
            RequirementKind.PAY_BEFORE,
            RequirementKind.ENTRY_FEE,
            RequirementKind.PURCHASE,
        }

    @property
    def settled_before_the_event(self) -> bool:
        """Cash carried on the day is not the same obligation as paying ahead."""
        return self in {RequirementKind.PAY_BEFORE, RequirementKind.PURCHASE}


class RequirementStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    SATISFIED = "SATISFIED"
    AT_RISK = "AT_RISK"
    UNSATISFIED = "UNSATISFIED"
    WAIVED = "WAIVED"

    @property
    def blocks_readiness(self) -> bool:
        return self in {RequirementStatus.AT_RISK, RequirementStatus.UNSATISFIED}


class RequirementAttributes(EntityAttributes):
    """One thing an event needs: an item, an outfit, a document or money.

    Money is a first-class amount rather than a task whose title happens to
    contain a number, and the kind distinguishes carrying cash on the day from
    paying ahead of it.
    """

    kind: RequirementKind
    status: RequirementStatus = RequirementStatus.UNKNOWN
    amount: Money | None = None
    item_entity_id: EntityId | None = None
    quantity: int | None = Field(default=None, ge=1)
    note: str | None = None

    @model_validator(mode="after")
    def _shape_matches_kind(self) -> Self:
        if self.kind.is_monetary and self.amount is None:
            raise ValueError(f"{self.kind} requires an amount")
        if not self.kind.is_monetary and self.amount is not None:
            raise ValueError(f"{self.kind} is not a monetary requirement")
        return self


class CareerRoleAttributes(EntityAttributes):
    title: str
    organisation: str | None = None
    is_current: bool = True


class EducationProgramAttributes(EntityAttributes):
    institution: str | None = None
    field_of_study: str | None = None
    completed: bool = False


class CourseAttributes(EntityAttributes):
    provider: str | None = None
    progress: float = Field(default=0.0, ge=0.0, le=1.0)


class SkillAttributes(EntityAttributes):
    level: int = Field(default=1, ge=1, le=5)


class DocumentAttributes(EntityAttributes):
    document_kind: str
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)


class BehaviorPatternAttributes(EntityAttributes):
    """An observed regularity. Always inferred, therefore always probabilistic."""

    pattern: str
    observations: int = Field(ge=1)


ATTRIBUTES_BY_TYPE: dict[EntityType, type[EntityAttributes]] = {
    EntityType.PERSON: PersonAttributes,
    EntityType.GOAL: GoalAttributes,
    EntityType.PRIORITY: PriorityAttributes,
    EntityType.MILESTONE: MilestoneAttributes,
    EntityType.CAREER_ROLE: CareerRoleAttributes,
    EntityType.EDUCATION_PROGRAM: EducationProgramAttributes,
    EntityType.COURSE: CourseAttributes,
    EntityType.SKILL: SkillAttributes,
    EntityType.CALENDAR_EVENT: CalendarEventAttributes,
    EntityType.COMMITMENT: CommitmentAttributes,
    EntityType.TASK: TaskAttributes,
    EntityType.DEADLINE: DeadlineAttributes,
    EntityType.ROUTINE: RoutineAttributes,
    EntityType.HABIT: HabitAttributes,
    EntityType.HEALTH_CONDITION: HealthConditionAttributes,
    EntityType.CYCLE_STATE: CycleStateAttributes,
    EntityType.PREGNANCY_STATE: PregnancyStateAttributes,
    EntityType.BODY_SIGNAL: BodySignalAttributes,
    EntityType.WARDROBE_ITEM: WardrobeItemAttributes,
    EntityType.PRODUCT: ProductAttributes,
    EntityType.INGREDIENT: IngredientAttributes,
    EntityType.PURCHASE: PurchaseAttributes,
    EntityType.SUBSCRIPTION: SubscriptionAttributes,
    EntityType.AVAILABILITY_STATE: AvailabilityStateAttributes,
    EntityType.PLACE: PlaceAttributes,
    EntityType.INTEREST: InterestAttributes,
    EntityType.MONEY_CONTEXT: MoneyContextAttributes,
    EntityType.DOCUMENT: DocumentAttributes,
    EntityType.RADAR_ITEM: RadarItemAttributes,
    EntityType.BEHAVIOR_PATTERN: BehaviorPatternAttributes,
    EntityType.REQUIREMENT: RequirementAttributes,
}


def attributes_model_for(entity_type: EntityType) -> type[EntityAttributes]:
    model = ATTRIBUTES_BY_TYPE.get(entity_type)
    if model is None:
        raise InvariantViolation(f"no attributes schema registered for {entity_type}")
    return model
