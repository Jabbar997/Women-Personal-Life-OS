from datetime import datetime
from typing import Self

from pydantic import Field, SerializeAsAny, model_validator

from wplos.core.attribution import Attribution
from wplos.core.identifiers import EntityId, UserId, new_entity_id
from wplos.core.records import ProvenancedRecord, RecordStatus
from wplos.core.temporal import TemporalMarkers, TemporalValidity
from wplos.personal_life_graph.attributes import EntityAttributes, attributes_model_for
from wplos.personal_life_graph.entity_types import EntityType
from wplos.shared.errors import InvariantViolation
from wplos.shared.json import JsonValue


class Entity(ProvenancedRecord):
    """A node in the Personal Life Graph.

    Three kinds of time are kept apart: ``created_at``/``updated_at`` are record
    time, ``temporal`` is when the fact is true of the world, and
    ``markers`` is when the world actually does the thing.
    """

    id: EntityId
    entity_type: EntityType
    owner_id: UserId
    label: str
    attributes: SerializeAsAny[EntityAttributes]
    markers: TemporalMarkers = Field(default_factory=TemporalMarkers.none)

    @model_validator(mode="before")
    @classmethod
    def _coerce_attributes(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        raw = data.get("attributes")
        if not isinstance(raw, dict):
            return data
        entity_type = data.get("entity_type")
        if entity_type is None:
            return data
        model = attributes_model_for(EntityType(entity_type))
        return {**data, "attributes": model.model_validate(raw)}

    @model_validator(mode="after")
    def _attributes_match_type(self) -> Self:
        expected = attributes_model_for(self.entity_type)
        if not isinstance(self.attributes, expected):
            raise ValueError(
                f"{self.entity_type} requires {expected.__name__}, "
                f"got {type(self.attributes).__name__}"
            )
        return self

    @classmethod
    def create(
        cls,
        *,
        owner_id: UserId,
        entity_type: EntityType,
        label: str,
        attributes: EntityAttributes,
        attribution: Attribution,
        at: datetime,
        valid_from: datetime | None = None,
        markers: TemporalMarkers | None = None,
        metadata: dict[str, JsonValue] | None = None,
    ) -> "Entity":
        return cls(
            id=new_entity_id(),
            entity_type=entity_type,
            owner_id=owner_id,
            label=label,
            attributes=attributes,
            attribution=attribution,
            temporal=TemporalValidity.open_from(valid_from or at),
            markers=markers or TemporalMarkers.none(),
            created_at=at,
            updated_at=at,
            metadata=metadata or {},
        )

    def revised(
        self,
        *,
        at: datetime,
        attributes: EntityAttributes | None = None,
        label: str | None = None,
        markers: TemporalMarkers | None = None,
        attribution: Attribution | None = None,
    ) -> "Entity":
        """Return the next version of this entity. The caller keeps the old one."""
        if self.status is not RecordStatus.ACTIVE:
            raise InvariantViolation(f"{self.id} is {self.status} and cannot be revised")
        return self.model_copy(
            update={
                "attributes": attributes or self.attributes,
                "label": label or self.label,
                "markers": markers or self.markers,
                "attribution": attribution or self.attribution,
                "updated_at": at,
            }
        )

    def closed(self, *, at: datetime, status: RecordStatus) -> "Entity":
        return self.model_copy(
            update={"temporal": self.temporal.closed_at(at), "status": status, "updated_at": at}
        )

    def attributes_as[T: EntityAttributes](self, model: type[T]) -> T:
        if not isinstance(self.attributes, model):
            raise InvariantViolation(
                f"{self.id} carries {type(self.attributes).__name__}, not {model.__name__}"
            )
        return self.attributes
