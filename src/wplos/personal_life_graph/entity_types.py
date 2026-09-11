from enum import StrEnum

from wplos.core.sensitivity import SensitivityLevel


class EntityType(StrEnum):
    """Primitives, not one table per life topic.

    Mood, energy, sleep, skin and hair are all ``BODY_SIGNAL``; beauty stock and
    household essentials are both ``PRODUCT``. See
    ``docs/domain/personal-life-graph.md`` for the domain coverage table.
    """

    # Identity and people
    PERSON = "PERSON"

    # Direction
    GOAL = "GOAL"
    PRIORITY = "PRIORITY"
    MILESTONE = "MILESTONE"

    # Career and education
    CAREER_ROLE = "CAREER_ROLE"
    EDUCATION_PROGRAM = "EDUCATION_PROGRAM"
    COURSE = "COURSE"
    SKILL = "SKILL"

    # Time and obligations
    CALENDAR_EVENT = "CALENDAR_EVENT"
    COMMITMENT = "COMMITMENT"
    TASK = "TASK"
    DEADLINE = "DEADLINE"
    ROUTINE = "ROUTINE"
    HABIT = "HABIT"

    # Body and health
    HEALTH_CONDITION = "HEALTH_CONDITION"
    CYCLE_STATE = "CYCLE_STATE"
    PREGNANCY_STATE = "PREGNANCY_STATE"
    BODY_SIGNAL = "BODY_SIGNAL"

    # Things owned and consumed
    WARDROBE_ITEM = "WARDROBE_ITEM"
    PRODUCT = "PRODUCT"
    INGREDIENT = "INGREDIENT"
    PURCHASE = "PURCHASE"
    SUBSCRIPTION = "SUBSCRIPTION"
    AVAILABILITY_STATE = "AVAILABILITY_STATE"

    # World and context
    PLACE = "PLACE"
    INTEREST = "INTEREST"
    MONEY_CONTEXT = "MONEY_CONTEXT"
    DOCUMENT = "DOCUMENT"
    RADAR_ITEM = "RADAR_ITEM"
    BEHAVIOR_PATTERN = "BEHAVIOR_PATTERN"


class LifeDomain(StrEnum):
    """Coarse grouping used for prioritisation and context scoping."""

    IDENTITY = "IDENTITY"
    DIRECTION = "DIRECTION"
    WORK = "WORK"
    LEARNING = "LEARNING"
    TIME = "TIME"
    BODY = "BODY"
    APPEARANCE = "APPEARANCE"
    HOME = "HOME"
    MONEY = "MONEY"
    SOCIAL = "SOCIAL"
    WORLD = "WORLD"


DOMAIN_OF: dict[EntityType, LifeDomain] = {
    EntityType.PERSON: LifeDomain.SOCIAL,
    EntityType.GOAL: LifeDomain.DIRECTION,
    EntityType.PRIORITY: LifeDomain.DIRECTION,
    EntityType.MILESTONE: LifeDomain.DIRECTION,
    EntityType.CAREER_ROLE: LifeDomain.WORK,
    EntityType.EDUCATION_PROGRAM: LifeDomain.LEARNING,
    EntityType.COURSE: LifeDomain.LEARNING,
    EntityType.SKILL: LifeDomain.LEARNING,
    EntityType.CALENDAR_EVENT: LifeDomain.TIME,
    EntityType.COMMITMENT: LifeDomain.TIME,
    EntityType.TASK: LifeDomain.TIME,
    EntityType.DEADLINE: LifeDomain.TIME,
    EntityType.ROUTINE: LifeDomain.TIME,
    EntityType.HABIT: LifeDomain.TIME,
    EntityType.HEALTH_CONDITION: LifeDomain.BODY,
    EntityType.CYCLE_STATE: LifeDomain.BODY,
    EntityType.PREGNANCY_STATE: LifeDomain.BODY,
    EntityType.BODY_SIGNAL: LifeDomain.BODY,
    EntityType.WARDROBE_ITEM: LifeDomain.APPEARANCE,
    EntityType.PRODUCT: LifeDomain.HOME,
    EntityType.INGREDIENT: LifeDomain.APPEARANCE,
    EntityType.PURCHASE: LifeDomain.MONEY,
    EntityType.SUBSCRIPTION: LifeDomain.MONEY,
    EntityType.AVAILABILITY_STATE: LifeDomain.HOME,
    EntityType.PLACE: LifeDomain.WORLD,
    EntityType.INTEREST: LifeDomain.IDENTITY,
    EntityType.MONEY_CONTEXT: LifeDomain.MONEY,
    EntityType.DOCUMENT: LifeDomain.HOME,
    EntityType.RADAR_ITEM: LifeDomain.WORLD,
    EntityType.BEHAVIOR_PATTERN: LifeDomain.IDENTITY,
}

DEFAULT_SENSITIVITY: dict[EntityType, SensitivityLevel] = {
    EntityType.PERSON: SensitivityLevel.S2,
    EntityType.GOAL: SensitivityLevel.S1,
    EntityType.PRIORITY: SensitivityLevel.S1,
    EntityType.MILESTONE: SensitivityLevel.S1,
    EntityType.CAREER_ROLE: SensitivityLevel.S2,
    EntityType.EDUCATION_PROGRAM: SensitivityLevel.S1,
    EntityType.COURSE: SensitivityLevel.S1,
    EntityType.SKILL: SensitivityLevel.S1,
    EntityType.CALENDAR_EVENT: SensitivityLevel.S2,
    EntityType.COMMITMENT: SensitivityLevel.S2,
    EntityType.TASK: SensitivityLevel.S1,
    EntityType.DEADLINE: SensitivityLevel.S1,
    EntityType.ROUTINE: SensitivityLevel.S1,
    EntityType.HABIT: SensitivityLevel.S1,
    EntityType.HEALTH_CONDITION: SensitivityLevel.S3,
    EntityType.CYCLE_STATE: SensitivityLevel.S3,
    EntityType.PREGNANCY_STATE: SensitivityLevel.S3,
    EntityType.BODY_SIGNAL: SensitivityLevel.S3,
    EntityType.WARDROBE_ITEM: SensitivityLevel.S1,
    EntityType.PRODUCT: SensitivityLevel.S1,
    EntityType.INGREDIENT: SensitivityLevel.S0,
    EntityType.PURCHASE: SensitivityLevel.S3,
    EntityType.SUBSCRIPTION: SensitivityLevel.S3,
    EntityType.AVAILABILITY_STATE: SensitivityLevel.S0,
    EntityType.PLACE: SensitivityLevel.S2,
    EntityType.INTEREST: SensitivityLevel.S1,
    EntityType.MONEY_CONTEXT: SensitivityLevel.S3,
    EntityType.DOCUMENT: SensitivityLevel.S2,
    EntityType.RADAR_ITEM: SensitivityLevel.S0,
    EntityType.BEHAVIOR_PATTERN: SensitivityLevel.S2,
}


def default_sensitivity(entity_type: EntityType) -> SensitivityLevel:
    return DEFAULT_SENSITIVITY[entity_type]


def life_domain(entity_type: EntityType) -> LifeDomain:
    return DOMAIN_OF[entity_type]
