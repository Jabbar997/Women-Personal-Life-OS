import uuid
from typing import NewType

UserId = NewType("UserId", str)
EntityId = NewType("EntityId", str)
RelationshipId = NewType("RelationshipId", str)
MemoryId = NewType("MemoryId", str)
EventId = NewType("EventId", str)
CorrelationId = NewType("CorrelationId", str)
RequestId = NewType("RequestId", str)
ActionId = NewType("ActionId", str)
AuthorizationId = NewType("AuthorizationId", str)
AssessmentId = NewType("AssessmentId", str)
AttemptId = NewType("AttemptId", str)
NotificationId = NewType("NotificationId", str)
IdempotencyKeyLike = NewType("IdempotencyKeyLike", str)


def _mint(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def new_user_id() -> UserId:
    return UserId(_mint("usr"))


def new_entity_id() -> EntityId:
    return EntityId(_mint("ent"))


def new_relationship_id() -> RelationshipId:
    return RelationshipId(_mint("rel"))


def new_memory_id() -> MemoryId:
    return MemoryId(_mint("mem"))


def new_event_id() -> EventId:
    return EventId(_mint("evt"))


def new_correlation_id() -> CorrelationId:
    return CorrelationId(_mint("cor"))


def new_request_id() -> RequestId:
    return RequestId(_mint("req"))


def new_action_id() -> ActionId:
    return ActionId(_mint("act"))


def new_authorization_id() -> AuthorizationId:
    return AuthorizationId(_mint("aut"))


def new_assessment_id() -> AssessmentId:
    return AssessmentId(_mint("asm"))


def new_attempt_id() -> AttemptId:
    return AttemptId(_mint("att"))


def new_notification_id() -> NotificationId:
    return NotificationId(_mint("ntf"))
