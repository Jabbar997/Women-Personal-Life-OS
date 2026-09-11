from __future__ import annotations

from typing import Protocol

from wlos.core.errors import EventIntegrityError
from wlos.events.catalog import EventType
from wlos.events.envelope import DomainEvent
from wlos.shared.identifiers import CorrelationId, EventId


class EventStore(Protocol):
    def append(self, event: DomainEvent) -> DomainEvent: ...

    def get(self, event_id: EventId) -> DomainEvent | None: ...

    def all_events(self) -> tuple[DomainEvent, ...]: ...

    def by_correlation(self, correlation_id: CorrelationId) -> tuple[DomainEvent, ...]: ...


class InMemoryEventStore:
    """Append-only log. There is deliberately no update or delete."""

    def __init__(self) -> None:
        self._events: list[DomainEvent] = []
        self._by_id: dict[EventId, DomainEvent] = {}

    def append(self, event: DomainEvent) -> DomainEvent:
        if event.event_id in self._by_id:
            raise EventIntegrityError(f"event {event.event_id} is already recorded")
        self._events.append(event)
        self._by_id[event.event_id] = event
        return event

    def get(self, event_id: EventId) -> DomainEvent | None:
        return self._by_id.get(event_id)

    def all_events(self) -> tuple[DomainEvent, ...]:
        return tuple(self._events)

    def by_type(self, event_type: EventType) -> tuple[DomainEvent, ...]:
        return tuple(event for event in self._events if event.event_type is event_type)

    def by_correlation(self, correlation_id: CorrelationId) -> tuple[DomainEvent, ...]:
        return tuple(event for event in self._events if event.correlation_id == correlation_id)

    def causal_chain(self, event_id: EventId) -> tuple[DomainEvent, ...]:
        """Walk back from an event to its root cause, oldest first."""
        chain: list[DomainEvent] = []
        current = self._by_id.get(event_id)
        seen: set[EventId] = set()
        while current is not None:
            if current.event_id in seen:
                raise EventIntegrityError(f"causation cycle at {current.event_id}")
            seen.add(current.event_id)
            chain.append(current)
            if current.causation_id is None:
                break
            current = self._by_id.get(EventId(str(current.causation_id)))
        return tuple(reversed(chain))
