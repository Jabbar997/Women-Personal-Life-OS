from __future__ import annotations

from datetime import datetime
from typing import Protocol

from wlos.core.errors import GraphIntegrityError
from wlos.personal_life_graph.domains import EntityType, LifeDomain, domain_of
from wlos.personal_life_graph.entities import Entity
from wlos.personal_life_graph.memory import MemoryRecord, MemoryType
from wlos.personal_life_graph.relationships import Relationship, RelationshipType
from wlos.shared.clock import ensure_utc
from wlos.shared.identifiers import EntityId, MemoryId, OwnerId, RelationshipId


class GraphRepository(Protocol):
    """Storage-agnostic contract for the Personal Life Graph.

    The in-memory implementation below is the reference; a PostgreSQL or graph
    database adapter can satisfy the same protocol without touching domain code.
    """

    def add_entity(self, entity: Entity) -> Entity: ...

    def put_entity(self, entity: Entity) -> Entity: ...

    def get_entity(self, entity_id: EntityId) -> Entity | None: ...

    def entity_history(self, entity_id: EntityId) -> tuple[Entity, ...]: ...

    def find_entities(
        self,
        *,
        entity_type: EntityType | None = None,
        domain: LifeDomain | None = None,
        active_at: datetime | None = None,
    ) -> tuple[Entity, ...]: ...

    def add_relationship(self, relationship: Relationship) -> Relationship: ...

    def get_relationship(self, relationship_id: RelationshipId) -> Relationship | None: ...

    def relationship_history(self, relationship_id: RelationshipId) -> tuple[Relationship, ...]: ...

    def expire_relationship(
        self, relationship_id: RelationshipId, at: datetime
    ) -> Relationship: ...

    def find_relationships(
        self,
        *,
        from_entity_id: EntityId | None = None,
        to_entity_id: EntityId | None = None,
        relationship_type: RelationshipType | None = None,
        active_at: datetime | None = None,
    ) -> tuple[Relationship, ...]: ...

    def add_memory(self, memory: MemoryRecord) -> MemoryRecord: ...

    def put_memory(self, memory: MemoryRecord) -> MemoryRecord: ...

    def get_memory(self, memory_id: MemoryId) -> MemoryRecord | None: ...

    def memory_history(self, memory_id: MemoryId) -> tuple[MemoryRecord, ...]: ...

    def find_memories(
        self,
        *,
        memory_type: MemoryType | None = None,
        subject_entity_id: EntityId | None = None,
        live_at: datetime | None = None,
    ) -> tuple[MemoryRecord, ...]: ...


class InMemoryPersonalLifeGraph:
    """Single-owner, revision-keeping implementation of ``GraphRepository``.

    Nothing is ever destroyed: writes append a revision, and invalidation closes
    a validity window so the record stays queryable as of any past moment.
    """

    def __init__(self, owner_id: OwnerId) -> None:
        self.owner_id = owner_id
        self._entities: dict[EntityId, list[Entity]] = {}
        self._relationships: dict[RelationshipId, list[Relationship]] = {}
        self._memories: dict[MemoryId, list[MemoryRecord]] = {}

    def add_entity(self, entity: Entity) -> Entity:
        self._require_owner(entity.owner_id, f"entity {entity.id}")
        if entity.id in self._entities:
            raise GraphIntegrityError(f"entity {entity.id} already exists")
        self._entities[entity.id] = [entity]
        return entity

    def put_entity(self, entity: Entity) -> Entity:
        self._require_owner(entity.owner_id, f"entity {entity.id}")
        revisions = self._entities.get(entity.id)
        if revisions is None:
            raise GraphIntegrityError(f"unknown entity {entity.id}")
        revisions.append(entity)
        return entity

    def get_entity(self, entity_id: EntityId) -> Entity | None:
        revisions = self._entities.get(entity_id)
        return revisions[-1] if revisions else None

    def entity_history(self, entity_id: EntityId) -> tuple[Entity, ...]:
        return tuple(self._entities.get(entity_id, ()))

    def find_entities(
        self,
        *,
        entity_type: EntityType | None = None,
        domain: LifeDomain | None = None,
        active_at: datetime | None = None,
    ) -> tuple[Entity, ...]:
        moment = ensure_utc(active_at) if active_at is not None else None
        found = []
        for revisions in self._entities.values():
            current = revisions[-1]
            if entity_type is not None and current.entity_type is not entity_type:
                continue
            if domain is not None and domain_of(current.entity_type) is not domain:
                continue
            if moment is not None and not current.is_active_at(moment):
                continue
            found.append(current)
        return tuple(found)

    def add_relationship(self, relationship: Relationship) -> Relationship:
        for endpoint in (relationship.from_entity_id, relationship.to_entity_id):
            if endpoint not in self._entities:
                raise GraphIntegrityError(f"relationship endpoint {endpoint} is not in the graph")
        if relationship.id in self._relationships:
            raise GraphIntegrityError(f"relationship {relationship.id} already exists")
        self._relationships[relationship.id] = [relationship]
        return relationship

    def get_relationship(self, relationship_id: RelationshipId) -> Relationship | None:
        revisions = self._relationships.get(relationship_id)
        return revisions[-1] if revisions else None

    def relationship_history(self, relationship_id: RelationshipId) -> tuple[Relationship, ...]:
        return tuple(self._relationships.get(relationship_id, ()))

    def expire_relationship(self, relationship_id: RelationshipId, at: datetime) -> Relationship:
        revisions = self._relationships.get(relationship_id)
        if not revisions:
            raise GraphIntegrityError(f"unknown relationship {relationship_id}")
        expired = revisions[-1].expired_at(at)
        revisions.append(expired)
        return expired

    def find_relationships(
        self,
        *,
        from_entity_id: EntityId | None = None,
        to_entity_id: EntityId | None = None,
        relationship_type: RelationshipType | None = None,
        active_at: datetime | None = None,
    ) -> tuple[Relationship, ...]:
        moment = ensure_utc(active_at) if active_at is not None else None
        found = []
        for revisions in self._relationships.values():
            current = revisions[-1]
            if from_entity_id is not None and current.from_entity_id != from_entity_id:
                continue
            if to_entity_id is not None and current.to_entity_id != to_entity_id:
                continue
            if relationship_type is not None and current.relationship_type is not relationship_type:
                continue
            if moment is not None and not current.is_active_at(moment):
                continue
            found.append(current)
        return tuple(found)

    def add_memory(self, memory: MemoryRecord) -> MemoryRecord:
        self._require_owner(memory.owner_id, f"memory {memory.id}")
        if memory.id in self._memories:
            raise GraphIntegrityError(f"memory {memory.id} already exists")
        self._memories[memory.id] = [memory]
        return memory

    def put_memory(self, memory: MemoryRecord) -> MemoryRecord:
        self._require_owner(memory.owner_id, f"memory {memory.id}")
        revisions = self._memories.get(memory.id)
        if revisions is None:
            raise GraphIntegrityError(f"unknown memory {memory.id}")
        revisions.append(memory)
        return memory

    def get_memory(self, memory_id: MemoryId) -> MemoryRecord | None:
        revisions = self._memories.get(memory_id)
        return revisions[-1] if revisions else None

    def memory_history(self, memory_id: MemoryId) -> tuple[MemoryRecord, ...]:
        return tuple(self._memories.get(memory_id, ()))

    def find_memories(
        self,
        *,
        memory_type: MemoryType | None = None,
        subject_entity_id: EntityId | None = None,
        live_at: datetime | None = None,
    ) -> tuple[MemoryRecord, ...]:
        moment = ensure_utc(live_at) if live_at is not None else None
        found = []
        for revisions in self._memories.values():
            current = revisions[-1]
            if memory_type is not None and current.memory_type is not memory_type:
                continue
            if subject_entity_id is not None and current.subject_entity_id != subject_entity_id:
                continue
            if moment is not None and not current.is_live_at(moment):
                continue
            found.append(current)
        return tuple(found)

    def _require_owner(self, owner_id: OwnerId, what: str) -> None:
        if owner_id != self.owner_id:
            raise GraphIntegrityError(f"{what} belongs to another owner")
