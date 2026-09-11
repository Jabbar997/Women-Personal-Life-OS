from __future__ import annotations

from enum import StrEnum

from wlos.shared.sensitivity import Sensitivity


class LifeDomain(StrEnum):
    """Areas of life the graph covers. Minds declare their reads and writes in these terms."""

    IDENTITY = "IDENTITY"
    GOALS = "GOALS"
    PRIORITIES = "PRIORITIES"
    PEOPLE = "PEOPLE"
    FAMILY = "FAMILY"
    RELATIONSHIPS = "RELATIONSHIPS"
    CAREER = "CAREER"
    EDUCATION = "EDUCATION"
    CALENDAR = "CALENDAR"
    COMMITMENTS = "COMMITMENTS"
    TASKS = "TASKS"
    HEALTH = "HEALTH"
    CYCLE = "CYCLE"
    PREGNANCY = "PREGNANCY"
    MOOD = "MOOD"
    ENERGY = "ENERGY"
    SLEEP = "SLEEP"
    SKIN = "SKIN"
    HAIR = "HAIR"
    WARDROBE = "WARDROBE"
    BEAUTY_INVENTORY = "BEAUTY_INVENTORY"
    ESSENTIALS = "ESSENTIALS"
    PURCHASES = "PURCHASES"
    SUBSCRIPTIONS = "SUBSCRIPTIONS"
    PLACES = "PLACES"
    INTERESTS = "INTERESTS"
    HOBBIES = "HOBBIES"
    MONEY = "MONEY"
    ROUTINES = "ROUTINES"
    PREFERENCES = "PREFERENCES"
    HABITS = "HABITS"
    LIFE_EVENTS = "LIFE_EVENTS"
    BEHAVIORAL_HISTORY = "BEHAVIORAL_HISTORY"
    RADAR = "RADAR"
    DOCUMENTS = "DOCUMENTS"


class EntityType(StrEnum):
    """Concrete node kinds. Kept as extensible primitives, not one table per life area."""

    IDENTITY = "IDENTITY"
    GOAL = "GOAL"
    PRIORITY = "PRIORITY"
    PERSON = "PERSON"
    FAMILY_CONTEXT = "FAMILY_CONTEXT"
    CAREER_ROLE = "CAREER_ROLE"
    EDUCATION_PROGRAM = "EDUCATION_PROGRAM"
    COURSE = "COURSE"
    CALENDAR_EVENT = "CALENDAR_EVENT"
    COMMITMENT = "COMMITMENT"
    TASK = "TASK"
    DEADLINE = "DEADLINE"
    HEALTH_OBSERVATION = "HEALTH_OBSERVATION"
    CYCLE_STATE = "CYCLE_STATE"
    PREGNANCY_CONTEXT = "PREGNANCY_CONTEXT"
    MOOD_OBSERVATION = "MOOD_OBSERVATION"
    ENERGY_OBSERVATION = "ENERGY_OBSERVATION"
    SLEEP_OBSERVATION = "SLEEP_OBSERVATION"
    SKIN_OBSERVATION = "SKIN_OBSERVATION"
    HAIR_OBSERVATION = "HAIR_OBSERVATION"
    WARDROBE_ITEM = "WARDROBE_ITEM"
    BEAUTY_PRODUCT = "BEAUTY_PRODUCT"
    INGREDIENT = "INGREDIENT"
    ESSENTIAL_ITEM = "ESSENTIAL_ITEM"
    PURCHASE = "PURCHASE"
    SUBSCRIPTION = "SUBSCRIPTION"
    PLACE = "PLACE"
    INTEREST = "INTEREST"
    HOBBY = "HOBBY"
    MONEY_CONTEXT = "MONEY_CONTEXT"
    ROUTINE = "ROUTINE"
    PREFERENCE = "PREFERENCE"
    HABIT = "HABIT"
    LIFE_EVENT = "LIFE_EVENT"
    BEHAVIOR_PATTERN = "BEHAVIOR_PATTERN"
    RADAR_ITEM = "RADAR_ITEM"
    DOCUMENT = "DOCUMENT"
    AVAILABILITY_STATE = "AVAILABILITY_STATE"


ENTITY_DOMAIN: dict[EntityType, LifeDomain] = {
    EntityType.IDENTITY: LifeDomain.IDENTITY,
    EntityType.GOAL: LifeDomain.GOALS,
    EntityType.PRIORITY: LifeDomain.PRIORITIES,
    EntityType.PERSON: LifeDomain.PEOPLE,
    EntityType.FAMILY_CONTEXT: LifeDomain.FAMILY,
    EntityType.CAREER_ROLE: LifeDomain.CAREER,
    EntityType.EDUCATION_PROGRAM: LifeDomain.EDUCATION,
    EntityType.COURSE: LifeDomain.EDUCATION,
    EntityType.CALENDAR_EVENT: LifeDomain.CALENDAR,
    EntityType.COMMITMENT: LifeDomain.COMMITMENTS,
    EntityType.TASK: LifeDomain.TASKS,
    EntityType.DEADLINE: LifeDomain.COMMITMENTS,
    EntityType.HEALTH_OBSERVATION: LifeDomain.HEALTH,
    EntityType.CYCLE_STATE: LifeDomain.CYCLE,
    EntityType.PREGNANCY_CONTEXT: LifeDomain.PREGNANCY,
    EntityType.MOOD_OBSERVATION: LifeDomain.MOOD,
    EntityType.ENERGY_OBSERVATION: LifeDomain.ENERGY,
    EntityType.SLEEP_OBSERVATION: LifeDomain.SLEEP,
    EntityType.SKIN_OBSERVATION: LifeDomain.SKIN,
    EntityType.HAIR_OBSERVATION: LifeDomain.HAIR,
    EntityType.WARDROBE_ITEM: LifeDomain.WARDROBE,
    EntityType.BEAUTY_PRODUCT: LifeDomain.BEAUTY_INVENTORY,
    EntityType.INGREDIENT: LifeDomain.BEAUTY_INVENTORY,
    EntityType.ESSENTIAL_ITEM: LifeDomain.ESSENTIALS,
    EntityType.PURCHASE: LifeDomain.PURCHASES,
    EntityType.SUBSCRIPTION: LifeDomain.SUBSCRIPTIONS,
    EntityType.PLACE: LifeDomain.PLACES,
    EntityType.INTEREST: LifeDomain.INTERESTS,
    EntityType.HOBBY: LifeDomain.HOBBIES,
    EntityType.MONEY_CONTEXT: LifeDomain.MONEY,
    EntityType.ROUTINE: LifeDomain.ROUTINES,
    EntityType.PREFERENCE: LifeDomain.PREFERENCES,
    EntityType.HABIT: LifeDomain.HABITS,
    EntityType.LIFE_EVENT: LifeDomain.LIFE_EVENTS,
    EntityType.BEHAVIOR_PATTERN: LifeDomain.BEHAVIORAL_HISTORY,
    EntityType.RADAR_ITEM: LifeDomain.RADAR,
    EntityType.DOCUMENT: LifeDomain.DOCUMENTS,
    EntityType.AVAILABILITY_STATE: LifeDomain.ESSENTIALS,
}

DOMAIN_SENSITIVITY: dict[LifeDomain, Sensitivity] = {
    LifeDomain.IDENTITY: Sensitivity.S1,
    LifeDomain.GOALS: Sensitivity.S1,
    LifeDomain.PRIORITIES: Sensitivity.S1,
    LifeDomain.PEOPLE: Sensitivity.S2,
    LifeDomain.FAMILY: Sensitivity.S2,
    LifeDomain.RELATIONSHIPS: Sensitivity.S2,
    LifeDomain.CAREER: Sensitivity.S2,
    LifeDomain.EDUCATION: Sensitivity.S1,
    LifeDomain.CALENDAR: Sensitivity.S2,
    LifeDomain.COMMITMENTS: Sensitivity.S2,
    LifeDomain.TASKS: Sensitivity.S1,
    LifeDomain.HEALTH: Sensitivity.S3,
    LifeDomain.CYCLE: Sensitivity.S3,
    LifeDomain.PREGNANCY: Sensitivity.S3,
    LifeDomain.MOOD: Sensitivity.S3,
    LifeDomain.ENERGY: Sensitivity.S2,
    LifeDomain.SLEEP: Sensitivity.S2,
    LifeDomain.SKIN: Sensitivity.S2,
    LifeDomain.HAIR: Sensitivity.S1,
    LifeDomain.WARDROBE: Sensitivity.S1,
    LifeDomain.BEAUTY_INVENTORY: Sensitivity.S1,
    LifeDomain.ESSENTIALS: Sensitivity.S1,
    LifeDomain.PURCHASES: Sensitivity.S2,
    LifeDomain.SUBSCRIPTIONS: Sensitivity.S2,
    LifeDomain.PLACES: Sensitivity.S2,
    LifeDomain.INTERESTS: Sensitivity.S1,
    LifeDomain.HOBBIES: Sensitivity.S1,
    LifeDomain.MONEY: Sensitivity.S3,
    LifeDomain.ROUTINES: Sensitivity.S1,
    LifeDomain.PREFERENCES: Sensitivity.S1,
    LifeDomain.HABITS: Sensitivity.S1,
    LifeDomain.LIFE_EVENTS: Sensitivity.S2,
    LifeDomain.BEHAVIORAL_HISTORY: Sensitivity.S2,
    LifeDomain.RADAR: Sensitivity.S1,
    LifeDomain.DOCUMENTS: Sensitivity.S2,
}


def domain_of(entity_type: EntityType) -> LifeDomain:
    return ENTITY_DOMAIN[entity_type]


def default_sensitivity(entity_type: EntityType) -> Sensitivity:
    """Floor for an entity type. Callers may raise it, never silently lower it."""
    return DOMAIN_SENSITIVITY[domain_of(entity_type)]
