"""Structural guarantees of the Personal Life Graph."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from wplos.core.attribution import Attribution
from wplos.core.identifiers import UserId
from wplos.core.sensitivity import SensitivityLevel
from wplos.personal_life_graph.attributes import (
    ATTRIBUTES_BY_TYPE,
    GoalAttributes,
    Kinship,
    PersonAttributes,
    attributes_model_for,
)
from wplos.personal_life_graph.entity import Entity
from wplos.personal_life_graph.entity_types import (
    DEFAULT_SENSITIVITY,
    DOMAIN_OF,
    EntityType,
    default_sensitivity,
)
from wplos.personal_life_graph.graph import PersonalLifeGraph
from wplos.personal_life_graph.relationship import (
    RELATIONSHIP_SPECS,
    Relationship,
    RelationshipType,
)
from wplos.shared.errors import InvariantViolation


def test_every_entity_type_has_a_typed_attribute_schema() -> None:
    for entity_type in EntityType:
        assert attributes_model_for(entity_type) is ATTRIBUTES_BY_TYPE[entity_type]


def test_every_entity_type_has_a_sensitivity_and_a_life_domain() -> None:
    for entity_type in EntityType:
        assert entity_type in DEFAULT_SENSITIVITY
        assert entity_type in DOMAIN_OF


def test_every_relationship_type_has_a_spec() -> None:
    for relationship_type in RelationshipType:
        assert relationship_type in RELATIONSHIP_SPECS


def test_body_and_money_domains_default_to_the_highest_sensitivity() -> None:
    for entity_type in (
        EntityType.CYCLE_STATE,
        EntityType.PREGNANCY_STATE,
        EntityType.HEALTH_CONDITION,
        EntityType.BODY_SIGNAL,
        EntityType.PURCHASE,
        EntityType.MONEY_CONTEXT,
    ):
        assert default_sensitivity(entity_type) is SensitivityLevel.S3

    assert default_sensitivity(EntityType.INTEREST) is SensitivityLevel.S1
    assert default_sensitivity(EntityType.CALENDAR_EVENT) is SensitivityLevel.S2


def test_attributes_must_match_the_entity_type(owner: UserId, now: datetime) -> None:
    with pytest.raises(ValidationError, match="requires"):
        Entity.create(
            owner_id=owner,
            entity_type=EntityType.GOAL,
            label="mismatched",
            attributes=PersonAttributes(display_name="x", kinship=Kinship.SELF),
            attribution=Attribution.declared(now, SensitivityLevel.S1),
            at=now,
        )


def test_reading_attributes_as_the_wrong_model_is_refused(goal: Entity) -> None:
    with pytest.raises(InvariantViolation, match="not PersonAttributes"):
        goal.attributes_as(PersonAttributes)

    assert isinstance(goal.attributes_as(GoalAttributes), GoalAttributes)


def test_a_relationship_cannot_connect_endpoints_its_spec_forbids(
    graph: PersonalLifeGraph, owner: UserId, self_person: Entity, goal: Entity, now: datetime
) -> None:
    with pytest.raises(InvariantViolation, match="cannot connect"):
        graph.put_relationship(
            Relationship.create(
                owner_id=owner,
                from_entity_id=goal.id,
                relationship_type=RelationshipType.HAS_GOAL,
                to_entity_id=self_person.id,
                attribution=Attribution.declared(now, SensitivityLevel.S1),
                at=now,
            )
        )


def test_a_symmetric_relationship_accepts_either_direction(
    graph: PersonalLifeGraph, owner: UserId, self_person: Entity, now: datetime
) -> None:
    sister = graph.put_entity(
        Entity.create(
            owner_id=owner,
            entity_type=EntityType.PERSON,
            label="Sister",
            attributes=PersonAttributes(display_name="Sister", kinship=Kinship.SIBLING),
            attribution=Attribution.declared(now, SensitivityLevel.S2),
            at=now,
        )
    )

    relationship = graph.put_relationship(
        Relationship.create(
            owner_id=owner,
            from_entity_id=sister.id,
            relationship_type=RelationshipType.RELATED_TO,
            to_entity_id=self_person.id,
            attribution=Attribution.declared(now, SensitivityLevel.S2),
            at=now,
        )
    )

    assert relationship.relationship_type is RelationshipType.RELATED_TO


def test_a_naive_datetime_is_refused_at_the_boundary(owner: UserId) -> None:
    with pytest.raises(InvariantViolation, match="naive datetime"):
        Entity.create(
            owner_id=owner,
            entity_type=EntityType.GOAL,
            label="naive",
            attributes=GoalAttributes.model_validate({"horizon": "YEAR", "domain": "LEARNING"}),
            attribution=Attribution.declared(datetime(2026, 1, 1), SensitivityLevel.S1),
            at=datetime(2026, 1, 1),
        )
