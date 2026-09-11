# ADR-004 — Domain events, immutability, and an in-process bus

- Status: accepted
- Date: 2026-09-11
- Phase: 01 — Foundation Layer

## Context

The architecture requires an event-driven core: every meaningful change must be
representable as a domain event, with correlation and causation, versioned
schemas and serializable payloads. It does not require, at this phase, a
distributed log.

## Decision

- One uniform `DomainEvent` envelope for every event.
- Events are immutable (frozen models) and the store is append-only, with no
  update or delete operation to misuse.
- `EventType` is an enum; event names are never bare strings.
- Important events have typed payloads resolved through a registry, so
  `to_dict()` / `from_dict()` round-trips restore the concrete payload class.
- `correlation_id` ties a flow together; `causation_id` records the direct cause;
  `caused_by()` builds the next link.
- Transport is an in-process `EventBus` protocol with an in-memory
  implementation. No external broker.

## Alternatives considered

**Kafka, Redis Streams or NATS now.** Rejected: "event-driven" describes the
domain model, not the infrastructure. A broker would add deployment, delivery
semantics and testing complexity while the event catalog is still being shaped.

**Untyped `dict` payloads.** Simpler to write, but it would push payload
validation into every consumer and make the catalog undiscoverable.

**One event class per event type, no shared envelope.** Rejected: correlation,
causation, provenance and sensitivity would drift per class, and cross-cutting
consumers (audit, projection) would need to special-case each.

**Full event sourcing as the primary write model.** Rejected for now: the graph
is the system of record and the event log is the change record. Promoting the log
to the source of truth is a decision for a later phase, and the append-only store
keeps that door open.

## Consequences

Positive:

- Any change is auditable, replayable and traceable back to its cause.
- Serialization is tested, so a future transport or persistence layer inherits a
  stable wire format.
- `schema_version` on every event makes payload evolution explicit.

Negative / accepted trade-offs:

- The in-memory bus dispatches synchronously in-process: a slow handler blocks
  the publisher, and nothing survives a restart. Both are acceptable for a domain
  phase and are exactly what the protocol boundary exists to replace.
- A payload registry must be kept in step with the catalog; the envelope
  validates the pairing, so a mismatch fails loudly at construction.
