from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from wplos.core.identifiers import EntityId, MemoryId, RelationshipId, UserId
from wplos.core.records import RecordStatus
from wplos.personal_life_graph.entity import Entity
from wplos.personal_life_graph.entity_types import EntityType
from wplos.personal_life_graph.memory import MemoryRecord, MemoryType
from wplos.personal_life_graph.relationship import (
    Relationship,
    RelationshipType,
    relationship_spec,
)
from wplos.shared.errors import ConcurrentModification, InvariantViolation, RecordNotFound


class GraphStore(Protocol):
    """The port every storage engine implements.

    Domain logic talks to this, never to a table or a Cypher query, so the graph
    can move to PostgreSQL or a graph database without a domain rewrite.
    """

    def put_entity(self, entity: Entity) -> Entity: ...

    def get_entity(self, entity_id: EntityId) -> Entity: ...

    def entity_versions(self, entity_id: EntityId) -> tuple[Entity, ...]: ...

    def put_relationship(self, relationship: Relationship) -> Relationship: ...

    def get_relationship(self, relationship_id: RelationshipId) -> Relationship: ...

    def put_memory(self, memory: MemoryRecord) -> MemoryRecord: ...

    def get_memory(self, memory_id: MemoryId) -> MemoryRecord: ...


class PersonalLifeGraph:
    """In-memory system of record for one deployment.

    Append-only by construction: revisions and expiries keep the previous
    version, so history is never lost to an update.
    """

    def __init__(self) -> None:
        self._entities: dict[EntityId, Entity] = {}
        self._entity_history: dict[EntityId, list[Entity]] = {}
        self._relationships: dict[RelationshipId, Relationship] = {}
        self._memories: dict[MemoryId, MemoryRecord] = {}

    # entities ---------------------------------------------------------------

    def put_entity(self, entity: Entity) -> Entity:
        existing = self._entities.get(entity.id)
        if existing is not None:
            self._entity_history.setdefault(entity.id, []).append(existing)
        self._entities[entity.id] = entity
        return entity

    def get_entity(self, entity_id: EntityId) -> Entity:
        entity = self._entities.get(entity_id)
        if entity is None:
            raise RecordNotFound(f"entity {entity_id} is not in the graph")
        return entity

    def entity_versions(self, entity_id: EntityId) -> tuple[Entity, ...]:
        history = tuple(self._entity_history.get(entity_id, ()))
        current = self._entities.get(entity_id)
        return history if current is None else (*history, current)

    def revise_entity(
        self,
        entity_id: EntityId,
        revision: Entity,
        *,
        expected_revision: int | None = None,
    ) -> Entity:
        """Store the next version, optionally refusing a write built on a stale read.

        Two devices editing the same open loop must not resolve by whichever
        packet arrives last: the second write is rejected so the conflict can be
        represented rather than lost.
        """
        if revision.id != entity_id:
            raise InvariantViolation("a revision must keep the entity id")
        current = self.get_entity(entity_id)
        if expected_revision is not None and current.revision != expected_revision:
            raise ConcurrentModification(
                f"{entity_id} is at revision {current.revision}, "
                f"the write was built on revision {expected_revision}"
            )
        return self.put_entity(revision)

    def close_entity(self, entity_id: EntityId, *, at: datetime, status: RecordStatus) -> Entity:
        return self.put_entity(self.get_entity(entity_id).closed(at=at, status=status))

    def entities(
        self,
        *,
        owner_id: UserId,
        entity_types: Iterable[EntityType] | None = None,
        at: datetime | None = None,
        include_inactive: bool = False,
    ) -> tuple[Entity, ...]:
        wanted = frozenset(entity_types) if entity_types is not None else None
        return tuple(
            entity
            for entity in self._entities.values()
            if entity.owner_id == owner_id
            and (wanted is None or entity.entity_type in wanted)
            and (include_inactive or at is None or entity.is_active_at(at))
        )

    # relationships ----------------------------------------------------------

    def put_relationship(self, relationship: Relationship) -> Relationship:
        self._require_endpoints(relationship)
        self._relationships[relationship.id] = relationship
        return relationship

    def get_relationship(self, relationship_id: RelationshipId) -> Relationship:
        relationship = self._relationships.get(relationship_id)
        if relationship is None:
            raise RecordNotFound(f"relationship {relationship_id} is not in the graph")
        return relationship

    def expire_relationship(self, relationship_id: RelationshipId, *, at: datetime) -> Relationship:
        expired = self.get_relationship(relationship_id).expired(at=at)
        self._relationships[expired.id] = expired
        return expired

    def relationships(
        self,
        *,
        owner_id: UserId,
        from_entity_id: EntityId | None = None,
        to_entity_id: EntityId | None = None,
        relationship_type: RelationshipType | None = None,
        at: datetime | None = None,
        include_expired: bool = False,
    ) -> tuple[Relationship, ...]:
        return tuple(
            relationship
            for relationship in self._relationships.values()
            if relationship.owner_id == owner_id
            and (from_entity_id is None or relationship.from_entity_id == from_entity_id)
            and (to_entity_id is None or relationship.to_entity_id == to_entity_id)
            and (relationship_type is None or relationship.relationship_type is relationship_type)
            and (include_expired or at is None or relationship.temporal.is_valid_at(at))
        )

    def _require_endpoints(self, relationship: Relationship) -> None:
        source = self.get_entity(relationship.from_entity_id)
        target = self.get_entity(relationship.to_entity_id)
        spec = relationship_spec(relationship.relationship_type)
        if not spec.permits(source.entity_type, target.entity_type):
            raise InvariantViolation(
                f"{relationship.relationship_type} cannot connect "
                f"{source.entity_type} to {target.entity_type}"
            )

    # memory -----------------------------------------------------------------

    def put_memory(self, memory: MemoryRecord) -> MemoryRecord:
        self._memories[memory.id] = memory
        return memory

    def get_memory(self, memory_id: MemoryId) -> MemoryRecord:
        memory = self._memories.get(memory_id)
        if memory is None:
            raise RecordNotFound(f"memory {memory_id} is not in the graph")
        return memory

    def supersede_memory(self, memory_id: MemoryId, *, at: datetime, reason: str) -> MemoryRecord:
        """The memory stopped being true. History before ``at`` is unaffected."""
        return self.put_memory(self.get_memory(memory_id).superseded(at=at, reason=reason))

    def invalidate_memory(self, memory_id: MemoryId, *, at: datetime, reason: str) -> MemoryRecord:
        """The memory was wrong. It is retained but never read back as history."""
        return self.put_memory(self.get_memory(memory_id).invalidated(at=at, reason=reason))

    def memories(
        self,
        *,
        owner_id: UserId,
        memory_types: Iterable[MemoryType] | None = None,
        at: datetime | None = None,
        include_inactive: bool = False,
    ) -> tuple[MemoryRecord, ...]:
        wanted = frozenset(memory_types) if memory_types is not None else None
        return tuple(
            memory
            for memory in self._memories.values()
            if memory.owner_id == owner_id
            and (wanted is None or memory.memory_type in wanted)
            and (include_inactive or at is None or memory.is_usable_at(at))
        )
