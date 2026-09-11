from __future__ import annotations

from collections import defaultdict
from typing import Protocol

from wlos.events.catalog import EventType
from wlos.events.envelope import DomainEvent
from wlos.events.store import InMemoryEventStore


class EventHandler(Protocol):
    def __call__(self, event: DomainEvent) -> None: ...


class EventBus(Protocol):
    def subscribe(self, event_type: EventType, handler: EventHandler) -> None: ...

    def subscribe_all(self, handler: EventHandler) -> None: ...

    def publish(self, event: DomainEvent) -> DomainEvent: ...


class InMemoryEventBus:
    """Synchronous in-process bus backed by an append-only store.

    Enough to develop and test the domain against. A broker can replace it later
    without the domain noticing.
    """

    def __init__(self, store: InMemoryEventStore | None = None) -> None:
        self.store = store or InMemoryEventStore()
        self._handlers: dict[EventType, list[EventHandler]] = defaultdict(list)
        self._global_handlers: list[EventHandler] = []

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        self._global_handlers.append(handler)

    def publish(self, event: DomainEvent) -> DomainEvent:
        self.store.append(event)
        for handler in (*self._global_handlers, *self._handlers[event.event_type]):
            handler(event)
        return event

    def published(self) -> tuple[DomainEvent, ...]:
        return self.store.all_events()
