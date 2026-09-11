from __future__ import annotations

from typing import NewType
from uuid import uuid4

OwnerId = NewType("OwnerId", str)
EntityId = NewType("EntityId", str)
RelationshipId = NewType("RelationshipId", str)
MemoryId = NewType("MemoryId", str)
EventId = NewType("EventId", str)
CorrelationId = NewType("CorrelationId", str)
CausationId = NewType("CausationId", str)
RequestId = NewType("RequestId", str)
ActionId = NewType("ActionId", str)
RecommendationId = NewType("RecommendationId", str)


def _new(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def new_owner_id() -> OwnerId:
    return OwnerId(_new("own"))


def new_entity_id() -> EntityId:
    return EntityId(_new("ent"))


def new_relationship_id() -> RelationshipId:
    return RelationshipId(_new("rel"))


def new_memory_id() -> MemoryId:
    return MemoryId(_new("mem"))


def new_event_id() -> EventId:
    return EventId(_new("evt"))


def new_correlation_id() -> CorrelationId:
    return CorrelationId(_new("cor"))


def new_request_id() -> RequestId:
    return RequestId(_new("req"))


def new_action_id() -> ActionId:
    return ActionId(_new("act"))


def new_recommendation_id() -> RecommendationId:
    return RecommendationId(_new("rec"))
