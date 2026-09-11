"""Builders shared by the life-simulation scenarios."""

from datetime import datetime

from wplos.core.attribution import Attribution
from wplos.core.identifiers import EntityId, UserId
from wplos.core.provenance import SourceRef, SourceType
from wplos.core.roles import ActorRole, AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.core.temporal import TemporalMarkers
from wplos.events.envelope import Actor, DomainEvent, Subject
from wplos.events.payloads import EventPayload
from wplos.events.types import EventType
from wplos.personal_life_graph.attributes import EntityAttributes
from wplos.personal_life_graph.entity import Entity
from wplos.personal_life_graph.entity_types import EntityType, default_sensitivity
from wplos.personal_life_graph.graph import PersonalLifeGraph
from wplos.personal_life_graph.relationship import Relationship, RelationshipType


def declare(
    graph: PersonalLifeGraph,
    owner: UserId,
    at: datetime,
    entity_type: EntityType,
    label: str,
    attributes: EntityAttributes,
    *,
    markers: TemporalMarkers | None = None,
    sensitivity: SensitivityLevel | None = None,
) -> Entity:
    """An entity the user stated herself: certain, and attributed to her."""
    return graph.put_entity(
        Entity.create(
            owner_id=owner,
            entity_type=entity_type,
            label=label,
            attributes=attributes,
            attribution=Attribution.declared(at, sensitivity or default_sensitivity(entity_type)),
            at=at,
            markers=markers,
        )
    )


def link(
    graph: PersonalLifeGraph,
    owner: UserId,
    at: datetime,
    source: Entity,
    relationship_type: RelationshipType,
    target: Entity,
    *,
    sensitivity: SensitivityLevel = SensitivityLevel.S1,
) -> Relationship:
    return graph.put_relationship(
        Relationship.create(
            owner_id=owner,
            from_entity_id=source.id,
            relationship_type=relationship_type,
            to_entity_id=target.id,
            attribution=Attribution.declared(at, sensitivity),
            at=at,
        )
    )


def emit(
    event_type: EventType,
    payload: EventPayload,
    owner: UserId,
    at: datetime,
    *,
    agent: AgentName | None = None,
    entity_id: EntityId | None = None,
    sensitivity: SensitivityLevel = SensitivityLevel.S1,
    source_type: SourceType = SourceType.SYSTEM_DERIVED,
) -> DomainEvent:
    actor = (
        Actor.agent_actor(agent, owner)
        if agent is not None
        else Actor(role=ActorRole.ORCHESTRATOR, user_id=owner)
    )
    return DomainEvent.emit(
        event_type=event_type,
        payload=payload,
        actor=actor,
        subject=Subject(owner_id=owner, entity_id=entity_id),
        source=SourceRef(source_type=source_type, captured_at=at),
        sensitivity=sensitivity,
        occurred_at=at,
    )
