from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from wplos.core.attribution import Attribution
from wplos.core.identifiers import EntityId, RelationshipId, UserId, new_relationship_id
from wplos.core.records import ProvenancedRecord, RecordStatus
from wplos.core.temporal import TemporalValidity
from wplos.personal_life_graph.entity_types import EntityType
from wplos.shared.json import JsonValue


class RelationshipType(StrEnum):
    HAS_GOAL = "HAS_GOAL"
    LIKES = "LIKES"
    USES = "USES"
    CONTAINS = "CONTAINS"
    REQUIRES = "REQUIRES"
    SUPPORTED_BY = "SUPPORTED_BY"
    RELATED_TO = "RELATED_TO"
    HAS_STATUS = "HAS_STATUS"
    OWNS = "OWNS"
    LOCATED_AT = "LOCATED_AT"
    PREPARES_FOR = "PREPARES_FOR"
    BLOCKS = "BLOCKS"
    CONFLICTS_WITH = "CONFLICTS_WITH"
    DERIVED_FROM = "DERIVED_FROM"
    WORKS_AS = "WORKS_AS"
    ENROLLED_IN = "ENROLLED_IN"
    ATTENDS = "ATTENDS"
    PURCHASED = "PURCHASED"
    SUBSCRIBED_TO = "SUBSCRIBED_TO"
    ASSIGNED_TO = "ASSIGNED_TO"


class RelationshipSpec(BaseModel):
    """What a relationship type is allowed to connect.

    An empty ``from_types``/``to_types`` means the edge is deliberately open;
    the registry constrains the edges whose meaning depends on their endpoints.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    relationship_type: RelationshipType
    from_types: frozenset[EntityType] = Field(default_factory=frozenset)
    to_types: frozenset[EntityType] = Field(default_factory=frozenset)
    symmetric: bool = False

    def permits(self, from_type: EntityType, to_type: EntityType) -> bool:
        from_ok = not self.from_types or from_type in self.from_types
        to_ok = not self.to_types or to_type in self.to_types
        if from_ok and to_ok:
            return True
        if not self.symmetric:
            return False
        return (not self.from_types or to_type in self.from_types) and (
            not self.to_types or from_type in self.to_types
        )


RELATIONSHIP_SPECS: dict[RelationshipType, RelationshipSpec] = {
    spec.relationship_type: spec
    for spec in (
        RelationshipSpec(
            relationship_type=RelationshipType.HAS_GOAL,
            from_types=frozenset({EntityType.PERSON}),
            to_types=frozenset({EntityType.GOAL}),
        ),
        RelationshipSpec(
            relationship_type=RelationshipType.LIKES,
            from_types=frozenset({EntityType.PERSON}),
            to_types=frozenset({EntityType.INTEREST, EntityType.PLACE, EntityType.PRODUCT}),
        ),
        RelationshipSpec(
            relationship_type=RelationshipType.USES,
            from_types=frozenset({EntityType.PERSON}),
            to_types=frozenset({EntityType.PRODUCT, EntityType.WARDROBE_ITEM}),
        ),
        RelationshipSpec(
            relationship_type=RelationshipType.CONTAINS,
            from_types=frozenset({EntityType.PRODUCT}),
            to_types=frozenset({EntityType.INGREDIENT}),
        ),
        RelationshipSpec(
            relationship_type=RelationshipType.REQUIRES,
            from_types=frozenset(
                {
                    EntityType.CALENDAR_EVENT,
                    EntityType.TASK,
                    EntityType.COMMITMENT,
                    EntityType.REQUIREMENT,
                }
            ),
            to_types=frozenset(
                {
                    EntityType.WARDROBE_ITEM,
                    EntityType.PRODUCT,
                    EntityType.DOCUMENT,
                    EntityType.REQUIREMENT,
                }
            ),
        ),
        RelationshipSpec(
            relationship_type=RelationshipType.SUPPORTED_BY,
            from_types=frozenset({EntityType.GOAL, EntityType.MILESTONE}),
            to_types=frozenset(
                {
                    EntityType.COURSE,
                    EntityType.EDUCATION_PROGRAM,
                    EntityType.HABIT,
                    EntityType.ROUTINE,
                    EntityType.SKILL,
                    EntityType.TASK,
                    EntityType.RADAR_ITEM,
                }
            ),
        ),
        RelationshipSpec(
            relationship_type=RelationshipType.RELATED_TO,
            from_types=frozenset({EntityType.PERSON}),
            to_types=frozenset({EntityType.PERSON}),
            symmetric=True,
        ),
        RelationshipSpec(
            relationship_type=RelationshipType.HAS_STATUS,
            from_types=frozenset({EntityType.WARDROBE_ITEM, EntityType.PRODUCT}),
            to_types=frozenset({EntityType.AVAILABILITY_STATE}),
        ),
        RelationshipSpec(
            relationship_type=RelationshipType.WORKS_AS,
            from_types=frozenset({EntityType.PERSON}),
            to_types=frozenset({EntityType.CAREER_ROLE}),
        ),
        RelationshipSpec(
            relationship_type=RelationshipType.ENROLLED_IN,
            from_types=frozenset({EntityType.PERSON}),
            to_types=frozenset({EntityType.EDUCATION_PROGRAM, EntityType.COURSE}),
        ),
        RelationshipSpec(
            relationship_type=RelationshipType.SUBSCRIBED_TO,
            from_types=frozenset({EntityType.PERSON}),
            to_types=frozenset({EntityType.SUBSCRIPTION}),
        ),
        RelationshipSpec(
            relationship_type=RelationshipType.PURCHASED,
            from_types=frozenset({EntityType.PERSON}),
            to_types=frozenset({EntityType.PURCHASE}),
        ),
        RelationshipSpec(
            relationship_type=RelationshipType.CONFLICTS_WITH,
            from_types=frozenset(
                {EntityType.CALENDAR_EVENT, EntityType.COMMITMENT, EntityType.TASK}
            ),
            to_types=frozenset({EntityType.CALENDAR_EVENT, EntityType.COMMITMENT, EntityType.TASK}),
            symmetric=True,
        ),
        RelationshipSpec(relationship_type=RelationshipType.OWNS),
        RelationshipSpec(relationship_type=RelationshipType.LOCATED_AT),
        RelationshipSpec(relationship_type=RelationshipType.PREPARES_FOR),
        RelationshipSpec(relationship_type=RelationshipType.BLOCKS),
        RelationshipSpec(relationship_type=RelationshipType.DERIVED_FROM),
        RelationshipSpec(relationship_type=RelationshipType.ATTENDS),
        RelationshipSpec(relationship_type=RelationshipType.ASSIGNED_TO),
    )
}


def relationship_spec(relationship_type: RelationshipType) -> RelationshipSpec:
    return RELATIONSHIP_SPECS[relationship_type]


class Relationship(ProvenancedRecord):
    """A typed, provenanced, time-bounded edge. Edges are closed, never deleted."""

    id: RelationshipId
    owner_id: UserId
    from_entity_id: EntityId
    relationship_type: RelationshipType
    to_entity_id: EntityId
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        owner_id: UserId,
        from_entity_id: EntityId,
        relationship_type: RelationshipType,
        to_entity_id: EntityId,
        attribution: Attribution,
        at: datetime,
        valid_from: datetime | None = None,
        attributes: dict[str, JsonValue] | None = None,
    ) -> "Relationship":
        return cls(
            id=new_relationship_id(),
            owner_id=owner_id,
            from_entity_id=from_entity_id,
            relationship_type=relationship_type,
            to_entity_id=to_entity_id,
            attributes=attributes or {},
            attribution=attribution,
            temporal=TemporalValidity.open_from(valid_from or at),
            created_at=at,
            updated_at=at,
        )

    def expired(self, *, at: datetime) -> "Relationship":
        """Close the edge in time. The record and its history stay in the graph."""
        return self.model_copy(
            update={
                "temporal": self.temporal.closed_at(at),
                "status": RecordStatus.EXPIRED,
                "updated_at": at,
            }
        )
