"""What event a graph mutation announces, and what that event may carry.

Two rules decide the mapping, and both matter:

1. If the catalog already names this mutation, that event is used. Inventing a
   generic name next to an existing ``COMMITMENT_CAPTURED`` would leave two
   vocabularies for one fact and consumers subscribed to the wrong one.
2. If it does not, the mutation is announced with the small graph-mutation
   vocabulary rather than by overloading an event that means something else.
   ``PRODUCT_LOW`` is a rules observation about stock, not a statement that a
   product record was revised, and using it here would make a write look like a
   detection.

A canonical event applies only when its payload can be derived from the entity
itself (plus, for a revision, the version before it). A deadline with no due
date cannot fill ``DeadlinePayload``, so it falls back rather than inventing a
date.
"""

from wplos.agents.contracts import WriteOperation
from wplos.events.payloads import (
    BehaviorPatternPayload,
    BodySignalPayload,
    CalendarEventPayload,
    DeadlinePayload,
    EntityRefPayload,
    EventPayload,
    GraphMutationPayload,
    OpenLoopPayload,
    ProductPayload,
    PurchaseRecordedPayload,
    RadarItemPayload,
    RequirementPayload,
    RequirementStatusChangedPayload,
    WardrobeItemPayload,
)
from wplos.events.types import EventType
from wplos.personal_life_graph.attributes import (
    BehaviorPatternAttributes,
    BodySignalAttributes,
    BodySignalKind,
    CalendarEventAttributes,
    CommitmentAttributes,
    DeadlineAttributes,
    OpenLoopState,
    PurchaseAttributes,
    RadarItemAttributes,
    RequirementAttributes,
    TaskAttributes,
)
from wplos.personal_life_graph.entity import Entity
from wplos.personal_life_graph.entity_types import EntityType

GENERIC_EVENT: dict[WriteOperation, EventType] = {
    WriteOperation.CREATE: EventType.GRAPH_ENTITY_CREATED,
    WriteOperation.REVISE: EventType.GRAPH_ENTITY_REVISED,
    WriteOperation.CLOSE: EventType.GRAPH_ENTITY_CLOSED,
}

_BODY_SIGNAL_EVENT: dict[BodySignalKind, EventType] = {
    BodySignalKind.MOOD: EventType.MOOD_UPDATED,
    BodySignalKind.ENERGY: EventType.ENERGY_UPDATED,
    BodySignalKind.SLEEP: EventType.SLEEP_UPDATED,
}


class GraphEventResolution:
    """The event a mutation announces, together with its payload."""

    __slots__ = ("event_type", "payload")

    def __init__(self, event_type: EventType, payload: EventPayload) -> None:
        self.event_type = event_type
        self.payload = payload


def resolve_graph_event(
    *,
    operation: WriteOperation,
    entity: Entity,
    previous: Entity | None,
) -> GraphEventResolution:
    """The domain event that announces this mutation.

    ``previous`` is the version being replaced, and is what lets a revision say
    *what changed* — a commitment reaching ``COMPLETED`` is a completion, while
    a commitment whose note was corrected is an update.
    """
    canonical = _canonical(operation, entity, previous)
    if canonical is not None:
        return canonical
    return GraphEventResolution(
        GENERIC_EVENT[operation],
        GraphMutationPayload(
            entity_id=entity.id,
            entity_type=entity.entity_type,
            revision=entity.revision,
            status=entity.status,
        ),
    )


def _canonical(
    operation: WriteOperation, entity: Entity, previous: Entity | None
) -> GraphEventResolution | None:
    match entity.entity_type:
        case EntityType.GOAL:
            return _goal(operation, entity)
        case EntityType.COMMITMENT:
            return _commitment(operation, entity, previous)
        case EntityType.TASK:
            return _task(operation, entity, previous)
        case EntityType.CALENDAR_EVENT:
            return _calendar_event(operation, entity)
        case EntityType.DEADLINE:
            return _deadline(operation, entity)
        case EntityType.REQUIREMENT:
            return _requirement(operation, entity, previous)
        case EntityType.PRODUCT:
            return _created_only(
                operation, EventType.PRODUCT_ADDED, ProductPayload(product_entity_id=entity.id)
            )
        case EntityType.WARDROBE_ITEM:
            return _created_only(
                operation,
                EventType.WARDROBE_ITEM_ADDED,
                WardrobeItemPayload(item_entity_id=entity.id),
            )
        case EntityType.PURCHASE:
            return _created_only(
                operation,
                EventType.PURCHASE_RECORDED,
                PurchaseRecordedPayload(
                    purchase_entity_id=entity.id,
                    returnable_until=entity.attributes_as(PurchaseAttributes).returnable_until,
                ),
            )
        case EntityType.RADAR_ITEM:
            return _created_only(
                operation,
                EventType.RADAR_ITEM_DISCOVERED,
                RadarItemPayload(
                    radar_entity_id=entity.id,
                    category=entity.attributes_as(RadarItemAttributes).category,
                ),
            )
        case EntityType.BEHAVIOR_PATTERN:
            return _behavior_pattern(operation, entity)
        case EntityType.BODY_SIGNAL:
            return _body_signal(operation, entity)
        case _:
            return None


def _created_only(
    operation: WriteOperation, event_type: EventType, payload: EventPayload
) -> GraphEventResolution | None:
    """Types whose catalog entry names the arrival of the record and nothing else."""
    if operation is not WriteOperation.CREATE:
        return None
    return GraphEventResolution(event_type, payload)


def _goal(operation: WriteOperation, entity: Entity) -> GraphEventResolution | None:
    payload = EntityRefPayload(entity_id=entity.id, entity_type=entity.entity_type)
    match operation:
        case WriteOperation.CREATE:
            return GraphEventResolution(EventType.GOAL_CREATED, payload)
        case WriteOperation.REVISE:
            return GraphEventResolution(EventType.GOAL_UPDATED, payload)
        case WriteOperation.CLOSE:
            return None


def _commitment(
    operation: WriteOperation, entity: Entity, previous: Entity | None
) -> GraphEventResolution | None:
    attributes = entity.attributes_as(CommitmentAttributes)
    payload = OpenLoopPayload(
        entity_id=entity.id,
        entity_type=entity.entity_type,
        state=attributes.state,
        due_at=entity.markers.due_at,
    )
    match operation:
        case WriteOperation.CREATE:
            return GraphEventResolution(EventType.COMMITMENT_CAPTURED, payload)
        case WriteOperation.REVISE:
            if _newly_completed(attributes.state, previous, CommitmentAttributes):
                return GraphEventResolution(EventType.COMMITMENT_COMPLETED, payload)
            return GraphEventResolution(EventType.COMMITMENT_UPDATED, payload)
        case WriteOperation.CLOSE:
            return None


def _task(
    operation: WriteOperation, entity: Entity, previous: Entity | None
) -> GraphEventResolution | None:
    attributes = entity.attributes_as(TaskAttributes)
    payload = OpenLoopPayload(
        entity_id=entity.id,
        entity_type=entity.entity_type,
        state=attributes.state,
        due_at=entity.markers.due_at,
    )
    match operation:
        case WriteOperation.CREATE:
            return GraphEventResolution(EventType.TASK_CREATED, payload)
        case WriteOperation.REVISE:
            # The catalog has no TASK_UPDATED. A revision that is not a
            # completion is announced generically rather than as one.
            if _newly_completed(attributes.state, previous, TaskAttributes):
                return GraphEventResolution(EventType.TASK_COMPLETED, payload)
            return None
        case WriteOperation.CLOSE:
            return None


def _newly_completed[T: (CommitmentAttributes, TaskAttributes)](
    state: OpenLoopState, previous: Entity | None, model: type[T]
) -> bool:
    if state is not OpenLoopState.COMPLETED:
        return False
    if previous is None:
        return False
    return previous.attributes_as(model).state is not OpenLoopState.COMPLETED


def _calendar_event(operation: WriteOperation, entity: Entity) -> GraphEventResolution:
    payload = CalendarEventPayload(
        event_entity_id=entity.id,
        starts_at=entity.markers.scheduled_for,
        ends_at=entity.attributes_as(CalendarEventAttributes).ends_at,
    )
    match operation:
        case WriteOperation.CREATE:
            return GraphEventResolution(EventType.EVENT_CREATED, payload)
        case WriteOperation.REVISE:
            return GraphEventResolution(EventType.EVENT_UPDATED, payload)
        case WriteOperation.CLOSE:
            return GraphEventResolution(EventType.EVENT_CANCELLED, payload)


def _deadline(operation: WriteOperation, entity: Entity) -> GraphEventResolution | None:
    due_at = entity.markers.due_at
    if operation is not WriteOperation.CREATE or due_at is None:
        return None
    return GraphEventResolution(
        EventType.DEADLINE_CREATED,
        DeadlinePayload(
            deadline_entity_id=entity.id,
            due_at=due_at,
            hard=entity.attributes_as(DeadlineAttributes).hard,
        ),
    )


def _requirement(
    operation: WriteOperation, entity: Entity, previous: Entity | None
) -> GraphEventResolution | None:
    attributes = entity.attributes_as(RequirementAttributes)
    if operation is WriteOperation.CREATE:
        return GraphEventResolution(
            EventType.REQUIREMENT_CREATED,
            RequirementPayload(
                requirement_entity_id=entity.id,
                kind=attributes.kind,
                status=attributes.status,
            ),
        )
    if operation is not WriteOperation.REVISE or previous is None:
        return None
    before = previous.attributes_as(RequirementAttributes).status
    if before is attributes.status:
        return None
    return GraphEventResolution(
        EventType.REQUIREMENT_STATUS_CHANGED,
        RequirementStatusChangedPayload(
            requirement_entity_id=entity.id,
            kind=attributes.kind,
            status=attributes.status,
            previous_status=before,
        ),
    )


def _behavior_pattern(operation: WriteOperation, entity: Entity) -> GraphEventResolution | None:
    if operation is not WriteOperation.REVISE:
        return None
    attributes = entity.attributes_as(BehaviorPatternAttributes)
    return GraphEventResolution(
        EventType.BEHAVIOR_PATTERN_UPDATED,
        BehaviorPatternPayload(
            entity_id=entity.id,
            pattern=attributes.pattern,
            observations=attributes.observations,
        ),
    )


def _body_signal(operation: WriteOperation, entity: Entity) -> GraphEventResolution | None:
    if operation is WriteOperation.CLOSE:
        return None
    attributes = entity.attributes_as(BodySignalAttributes)
    event_type = _BODY_SIGNAL_EVENT.get(attributes.signal)
    if event_type is None:
        return None
    return GraphEventResolution(
        event_type,
        BodySignalPayload(signal=attributes.signal, scale_value=attributes.scale_value),
    )
