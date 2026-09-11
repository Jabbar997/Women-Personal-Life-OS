"""Test 3: expiry closes a record in time; it never erases it."""

from datetime import datetime

from wplos.core.attribution import Attribution
from wplos.core.identifiers import UserId
from wplos.core.records import RecordStatus
from wplos.core.sensitivity import SensitivityLevel
from wplos.personal_life_graph.attributes import GoalAttributes, GoalHorizon
from wplos.personal_life_graph.entity import Entity
from wplos.personal_life_graph.entity_types import EntityType, LifeDomain
from wplos.personal_life_graph.graph import PersonalLifeGraph
from wplos.personal_life_graph.relationship import Relationship, RelationshipType


def _has_goal(
    graph: PersonalLifeGraph, owner: UserId, person: Entity, goal: Entity, at: datetime
) -> Relationship:
    return graph.put_relationship(
        Relationship.create(
            owner_id=owner,
            from_entity_id=person.id,
            relationship_type=RelationshipType.HAS_GOAL,
            to_entity_id=goal.id,
            attribution=Attribution.declared(at, SensitivityLevel.S1),
            at=at,
        )
    )


def test_expired_relationship_keeps_its_history(
    graph: PersonalLifeGraph,
    owner: UserId,
    self_person: Entity,
    goal: Entity,
    now: datetime,
    later: datetime,
) -> None:
    relationship = _has_goal(graph, owner, self_person, goal, now)

    expired = graph.expire_relationship(relationship.id, at=later)

    assert expired.status is RecordStatus.EXPIRED
    assert expired.temporal.valid_from == now
    assert expired.temporal.valid_until == later

    assert graph.relationships(owner_id=owner, at=later) == ()
    assert graph.relationships(owner_id=owner, at=now) == (expired,)
    assert graph.relationships(owner_id=owner, at=later, include_expired=True) == (expired,)
    assert graph.get_relationship(relationship.id).id == relationship.id


def test_entity_revision_keeps_every_previous_version(
    graph: PersonalLifeGraph, goal: Entity, now: datetime, later: datetime
) -> None:
    revision = goal.revised(
        at=later,
        attributes=GoalAttributes(
            horizon=GoalHorizon.YEAR, domain=LifeDomain.LEARNING, progress=0.5
        ),
    )
    graph.revise_entity(goal.id, revision)

    versions = graph.entity_versions(goal.id)

    assert len(versions) == 2
    assert versions[0].attributes_as(GoalAttributes).progress == 0.0
    assert versions[1].attributes_as(GoalAttributes).progress == 0.5
    assert versions[0].created_at == versions[1].created_at
    assert versions[1].updated_at == later


def test_closing_an_entity_leaves_it_readable_in_the_past(
    graph: PersonalLifeGraph, owner: UserId, goal: Entity, now: datetime, later: datetime
) -> None:
    graph.close_entity(goal.id, at=later, status=RecordStatus.SUPERSEDED)

    assert graph.entities(owner_id=owner, entity_types=[EntityType.GOAL], at=later) == ()
    assert graph.get_entity(goal.id).temporal.valid_until == later
    assert graph.get_entity(goal.id).temporal.is_valid_at(now)


def test_record_time_validity_and_domain_time_are_distinct(goal: Entity, now: datetime) -> None:
    assert goal.created_at == now
    assert goal.temporal.valid_from == now
    assert goal.markers.due_at is None
    assert goal.markers.completed_at is None
