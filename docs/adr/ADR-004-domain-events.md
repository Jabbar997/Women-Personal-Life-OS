# ADR-004 — Domain events without a broker

- **Status:** Accepted
- **Date:** 2026-09-11
- **Phase:** 01 — Domain Foundation

## Context

The architecture is event-driven: every significant change must be expressible
as a domain event. "Event-driven" is routinely misread as "install Kafka", which
would add operational weight to a system that has no users and no second
process.

## Decision

**A typed, immutable event envelope with a registry-backed payload per event
type, an `EventBus` port, and an in-memory implementation. No external broker.**

1. `DomainEvent` is frozen. A recorded event is history; corrections are new
   events.
2. `EventType` is a `StrEnum` — no string literals for events anywhere.
3. Every `EventType` maps to exactly one payload model in `PAYLOAD_BY_EVENT`,
   enforced by a test. Deserialization rebuilds the typed payload from
   `event_type`.
4. `schema_version` is on the envelope, so payload shapes can evolve without
   rewriting history.
5. `correlation_id` groups a turn; `causation_id` links cause to consequence.
   `event.caused(...)` derives a consequence and carries both correctly.
6. `InMemoryEventBus` is an append-only log with synchronous fan-out that refuses
   a duplicate `event_id` and can reconstruct a causation chain.

## Alternatives considered

- **Kafka, Redis Streams or RabbitMQ now.** Rejected. Infrastructure for a
  single in-process system, chosen on the strength of a word in the architecture
  rather than a requirement.
- **Untyped dictionary payloads.** Rejected. The event log is the audit trail for
  authorization decisions; it is the last place to accept untyped data.
- **Generic payloads with per-type validation at the edges.** Rejected. Validation
  belongs with the schema, not with each consumer.
- **Full event sourcing as the system of record.** Deferred; see ADR-003.

## Consequences

**Positive**

- Events are auditable and reconstructable today, with no operational surface.
- Swapping in a broker later means implementing `EventBus`; publishers and
  handlers do not change.
- Typed payloads mean a consumer cannot silently mis-read an event.

**Negative / trade-offs**

- Synchronous fan-out means a slow handler blocks the publisher. Acceptable
  in-process; it is exactly the constraint a broker would later relieve.
- The in-memory log is not durable. Persistence is a later phase.
- Adding an event type costs a payload model. Deliberate.
