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

    def __init__(self) -> None:
        self._log: list[DomainEvent] = []
        self._seen: set[EventId] = set()
        self._typed: dict[EventType, list[EventHandler]] = {}
        self._catch_all: list[EventHandler] = []

    def publish(self, event: DomainEvent) -> DomainEvent:
        if event.event_id in self._seen:
            raise InvariantViolation(f"{event.event_id} has already been published")
        self._seen.add(event.event_id)
        self._log.append(event)
        for handler in (*self._typed.get(event.event_type, ()), *self._catch_all):
            handler(event)
        return event

    def publish_all(self, events: Iterable[DomainEvent]) -> tuple[DomainEvent, ...]:
        return tuple(self.publish(event) for event in events)

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
        cursor: EventId | None = event_id
        while cursor is not None:
            event = by_id.get(cursor)
            if event is None:
                break
            chain.append(event)
            cursor = event.causation_id
        return tuple(reversed(chain))
