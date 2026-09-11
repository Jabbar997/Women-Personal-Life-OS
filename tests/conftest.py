from datetime import UTC, datetime, timedelta

import pytest

from wplos.core.attribution import Attribution
from wplos.core.identifiers import UserId
from wplos.core.sensitivity import SensitivityLevel
from wplos.personal_life_graph.attributes import (
    CyclePhase,
    CycleStateAttributes,
    GoalAttributes,
    GoalHorizon,
    Kinship,
    PersonAttributes,
)
from wplos.personal_life_graph.entity import Entity
from wplos.personal_life_graph.entity_types import EntityType, LifeDomain, default_sensitivity
from wplos.personal_life_graph.graph import PersonalLifeGraph

NOW = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def later() -> datetime:
    return NOW + timedelta(days=30)


@pytest.fixture
def owner() -> UserId:
    return UserId("usr_test")


@pytest.fixture
def graph() -> PersonalLifeGraph:
    return PersonalLifeGraph()


@pytest.fixture
def self_person(graph: PersonalLifeGraph, owner: UserId, now: datetime) -> Entity:
    return graph.put_entity(
        Entity.create(
            owner_id=owner,
            entity_type=EntityType.PERSON,
            label="Self",
            attributes=PersonAttributes(display_name="Self", kinship=Kinship.SELF, is_self=True),
            attribution=Attribution.declared(now, default_sensitivity(EntityType.PERSON)),
            at=now,
        )
    )


@pytest.fixture
def goal(graph: PersonalLifeGraph, owner: UserId, now: datetime) -> Entity:
    return graph.put_entity(
        Entity.create(
            owner_id=owner,
            entity_type=EntityType.GOAL,
            label="Finish the master's degree",
            attributes=GoalAttributes(horizon=GoalHorizon.YEAR, domain=LifeDomain.LEARNING),
            attribution=Attribution.declared(now, SensitivityLevel.S1),
            at=now,
        )
    )


@pytest.fixture
def cycle_state(graph: PersonalLifeGraph, owner: UserId, now: datetime) -> Entity:
    return graph.put_entity(
        Entity.create(
            owner_id=owner,
            entity_type=EntityType.CYCLE_STATE,
            label="Cycle state",
            attributes=CycleStateAttributes(phase=CyclePhase.LUTEAL, cycle_day=22),
            attribution=Attribution.declared(now, default_sensitivity(EntityType.CYCLE_STATE)),
            at=now,
        )
    )
