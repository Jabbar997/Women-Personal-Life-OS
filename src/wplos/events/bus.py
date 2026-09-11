from collections.abc import Callable, Iterable
from typing import Protocol

from wplos.core.identifiers import CorrelationId, EventId
from wplos.events.envelope import DomainEvent
from wplos.events.types import EventType
from wplos.shared.errors import InvariantViolation

type EventHandler = Callable[[DomainEvent], None]


class EventBus(Protocol):
    """The port a real broker would implement later.

    Nothing here requires Kafka or Redis; an event-driven core is a modelling
    decision, not an infrastructure purchase.
    """

    def publish(self, event: DomainEvent) -> DomainEvent: ...

    def subscribe(self, event_type: EventType | None, handler: EventHandler) -> None: ...


class InMemoryEventBus:
    """Append-only log plus synchronous fan-out, for tests and the local core."""

    def __init__(self, *, require_known_cause: bool = True) -> None:
        self._log: list[DomainEvent] = []
        self._seen: set[EventId] = set()
        self._client_keys: dict[str, EventId] = {}
        self._typed: dict[EventType, list[EventHandler]] = {}
        self._catch_all: list[EventHandler] = []
        self._require_known_cause = require_known_cause

    def publish(self, event: DomainEvent) -> DomainEvent:
        """Append an event, refusing a replay or a cause that does not exist."""
        if event.event_id in self._seen:
            raise InvariantViolation(f"{event.event_id} has already been published")
        if (
            self._require_known_cause
            and event.causation_id is not None
            and event.causation_id not in self._seen
        ):
            raise InvariantViolation(
                f"{event.event_id} claims a cause that has not been published; "
                "causation must point backwards"
            )
        duplicate = self.duplicate_of(event)
        if duplicate is not None:
            raise InvariantViolation(f"{event.client_event_id} was already accepted as {duplicate}")
        self._seen.add(event.event_id)
        if event.client_event_id is not None:
            self._client_keys[event.client_event_id] = event.event_id
        self._log.append(event)
        for handler in (*self._typed.get(event.event_type, ()), *self._catch_all):
            handler(event)
        return event

    def publish_all(self, events: Iterable[DomainEvent]) -> tuple[DomainEvent, ...]:
        return tuple(self.publish(event) for event in events)

    def duplicate_of(self, event: DomainEvent) -> EventId | None:
        """The event id this submission was already accepted as, if any.

        Deduplication keys off the client's own event id, never off the text of
        a message: two identical-looking captures can be two real commitments.
        """
        key = event.client_event_id
        return None if key is None else self._client_keys.get(key)

    def accept(self, event: DomainEvent) -> DomainEvent:
        """Publish, or return the existing event when this is a replay.

        The shape a mobile sync path needs: retrying is safe and does not create
        a second commitment.
        """
        existing = self.duplicate_of(event)
        if existing is not None:
            return next(item for item in self._log if item.event_id == existing)
        return self.publish(event)

    def subscribe(self, event_type: EventType | None, handler: EventHandler) -> None:
        if event_type is None:
            self._catch_all.append(handler)
        else:
            self._typed.setdefault(event_type, []).append(handler)

    @property
    def log(self) -> tuple[DomainEvent, ...]:
        return tuple(self._log)

    def events_of(self, event_type: EventType) -> tuple[DomainEvent, ...]:
        return tuple(event for event in self._log if event.event_type is event_type)

    def correlation(self, correlation_id: CorrelationId) -> tuple[DomainEvent, ...]:
        return tuple(event for event in self._log if event.correlation_id == correlation_id)

    def causation_chain(self, event_id: EventId) -> tuple[DomainEvent, ...]:
        """Walk back from an event to the root cause, oldest first."""
        by_id = {event.event_id: event for event in self._log}
        chain: list[DomainEvent] = []
        visited: set[EventId] = set()
        cursor: EventId | None = event_id
        while cursor is not None:
            if cursor in visited:
                raise InvariantViolation(f"causation cycle through {cursor}")
            visited.add(cursor)
            event = by_id.get(cursor)
            if event is None:
                break
            chain.append(event)
            cursor = event.causation_id
        return tuple(reversed(chain))

    def in_arrival_order(self) -> tuple[DomainEvent, ...]:
        """The log as recorded. Arrival order is not the order things happened."""
        return tuple(self._log)

    def in_occurrence_order(self) -> tuple[DomainEvent, ...]:
        """The log as the world produced it, for events that arrived late."""
        return tuple(sorted(self._log, key=lambda event: event.occurred_at))
