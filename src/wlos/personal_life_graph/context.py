from __future__ import annotations

from datetime import datetime

from wlos.core.base import DomainModel
from wlos.personal_life_graph.entities import Entity
from wlos.personal_life_graph.graph import GraphRepository
from wlos.personal_life_graph.memory import MemoryRecord
from wlos.personal_life_graph.relationships import Relationship
from wlos.policy.decisions import PolicyDecision
from wlos.policy.sensitivity_policy import ContextConsumer, SensitivityPolicy
from wlos.shared.clock import ensure_utc
from wlos.shared.identifiers import OwnerId


class ContextView(DomainModel):
    """The slice of the graph one consumer may see, as of one moment.

    Minds never read the repository directly; they read a view built for their
    declared needs and clearance.
    """

    owner_id: OwnerId
    consumer: ContextConsumer
    as_of: datetime
    entities: tuple[Entity, ...] = ()
    relationships: tuple[Relationship, ...] = ()
    memories: tuple[MemoryRecord, ...] = ()
    withheld_count: int = 0

    def entity_ids(self) -> frozenset[str]:
        return frozenset(str(entity.id) for entity in self.entities)


class ContextProjection(DomainModel):
    """A view plus the policy trail explaining what was left out.

    The audit stays with the orchestrator; a consumer only ever receives ``view``.
    """

    view: ContextView
    audit: tuple[PolicyDecision, ...] = ()


def project_context(
    graph: GraphRepository,
    *,
    owner_id: OwnerId,
    consumer: ContextConsumer,
    as_of: datetime,
) -> ContextProjection:
    moment = ensure_utc(as_of)
    entities: list[Entity] = []
    memories: list[MemoryRecord] = []
    audit: list[PolicyDecision] = []

    for entity in graph.find_entities(active_at=moment):
        decision = SensitivityPolicy.evaluate_entity(consumer, entity, at=moment)
        if decision.is_permitted:
            entities.append(entity)
        else:
            audit.append(decision)

    for memory in graph.find_memories(live_at=moment):
        decision = SensitivityPolicy.evaluate_memory(
            consumer, memory, domain=memory.domain, at=moment
        )
        if decision.is_permitted:
            memories.append(memory)
        else:
            audit.append(decision)

    visible_ids = {entity.id for entity in entities}
    relationships: list[Relationship] = []
    hidden_edges = 0
    for relationship in graph.find_relationships(active_at=moment):
        endpoints_visible = (
            relationship.from_entity_id in visible_ids and relationship.to_entity_id in visible_ids
        )
        if endpoints_visible:
            relationships.append(relationship)
        else:
            hidden_edges += 1

    view = ContextView(
        owner_id=owner_id,
        consumer=consumer,
        as_of=moment,
        entities=tuple(entities),
        relationships=tuple(relationships),
        memories=tuple(memories),
        withheld_count=len(audit) + hidden_edges,
    )
    return ContextProjection(view=view, audit=tuple(audit))
