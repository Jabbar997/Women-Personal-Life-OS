from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from wplos.core.identifiers import UserId
from wplos.core.roles import AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.personal_life_graph.entity import Entity
from wplos.personal_life_graph.entity_types import EntityType
from wplos.personal_life_graph.graph import PersonalLifeGraph
from wplos.personal_life_graph.memory import MemoryRecord, MemoryType
from wplos.personal_life_graph.relationship import Relationship
from wplos.policy.decisions import ReasonCode
from wplos.policy.sensitivity_policy import (
    DEFAULT_SENSITIVITY_POLICY,
    ExposureRequest,
    SensitivityPolicy,
)


class ContextScope(BaseModel):
    """What one mind is allowed to see for one purpose.

    A mind declares the entity and memory types its contract needs; anything
    else is not merely unranked, it is not retrieved. Sensitive records reach a
    mind only when that mind explicitly requires them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    consumer: AgentName
    purpose: str
    required_entity_types: frozenset[EntityType] = Field(default_factory=frozenset)
    required_memory_types: frozenset[MemoryType] = Field(default_factory=frozenset)
    max_sensitivity: SensitivityLevel = SensitivityLevel.S1

    def requires(self, entity_type: EntityType) -> bool:
        return entity_type in self.required_entity_types


class RedactionScope(StrEnum):
    ENTITY = "ENTITY"
    RELATIONSHIP = "RELATIONSHIP"
    MEMORY = "MEMORY"


class Redaction(BaseModel):
    """A count and a reason, never the withheld content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: RedactionScope
    sensitivity: SensitivityLevel
    reason_code: ReasonCode
    count: int = Field(ge=1)


class ContextView(BaseModel):
    """The only thing a mind ever reads. Built by projection, never by a query
    the mind writes itself."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: ContextScope
    owner_id: UserId
    as_of: datetime
    entities: tuple[Entity, ...] = Field(default_factory=tuple)
    relationships: tuple[Relationship, ...] = Field(default_factory=tuple)
    memories: tuple[MemoryRecord, ...] = Field(default_factory=tuple)
    redactions: tuple[Redaction, ...] = Field(default_factory=tuple)

    def contains_entity_type(self, entity_type: EntityType) -> bool:
        return any(entity.entity_type is entity_type for entity in self.entities)

    def max_sensitivity_present(self) -> SensitivityLevel:
        return SensitivityLevel.highest(tuple(entity.sensitivity for entity in self.entities))

    @property
    def was_redacted(self) -> bool:
        return bool(self.redactions)


def project_context(
    graph: PersonalLifeGraph,
    *,
    owner_id: UserId,
    scope: ContextScope,
    at: datetime,
    policy: SensitivityPolicy = DEFAULT_SENSITIVITY_POLICY,
) -> ContextView:
    """Build a mind's working context under the sensitivity policy."""
    redactions: dict[tuple[RedactionScope, SensitivityLevel, ReasonCode], int] = {}

    def admit(
        record_scope: RedactionScope, sensitivity: SensitivityLevel, explicitly_required: bool
    ) -> bool:
        decision = policy.evaluate_exposure(
            ExposureRequest(
                consumer=scope.consumer,
                consumer_ceiling=scope.max_sensitivity,
                record_sensitivity=sensitivity,
                explicitly_required=explicitly_required,
                purpose=scope.purpose,
            )
        )
        if decision.is_permitted:
            return True
        code = decision.reasons[0].code if decision.reasons else ReasonCode.ALLOWED
        key = (record_scope, sensitivity, code)
        redactions[key] = redactions.get(key, 0) + 1
        return False

    candidates = graph.entities(
        owner_id=owner_id, entity_types=scope.required_entity_types or None, at=at
    )
    entities = tuple(
        entity
        for entity in candidates
        if admit(RedactionScope.ENTITY, entity.sensitivity, scope.requires(entity.entity_type))
    )

    admitted_ids = {entity.id for entity in entities}
    relationships = tuple(
        relationship
        for relationship in graph.relationships(owner_id=owner_id, at=at)
        if relationship.from_entity_id in admitted_ids
        and relationship.to_entity_id in admitted_ids
        and admit(RedactionScope.RELATIONSHIP, relationship.sensitivity, True)
    )

    memory_candidates = graph.memories(
        owner_id=owner_id, memory_types=scope.required_memory_types or None, at=at
    )
    memories = tuple(
        memory
        for memory in memory_candidates
        if admit(
            RedactionScope.MEMORY,
            memory.sensitivity,
            memory.memory_type in scope.required_memory_types,
        )
    )

    return ContextView(
        scope=scope,
        owner_id=owner_id,
        as_of=at,
        entities=entities,
        relationships=relationships,
        memories=memories,
        redactions=tuple(
            Redaction(scope=key[0], sensitivity=key[1], reason_code=key[2], count=count)
            for key, count in sorted(redactions.items(), key=lambda item: str(item[0]))
        ),
    )
