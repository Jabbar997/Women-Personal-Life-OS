# Event Model

Every significant change in the system must be expressible as a domain event.
That is a modelling commitment, not an infrastructure purchase: this phase ships
an interface and an in-memory bus, and no broker.

## 1. Envelope

`DomainEvent` is frozen. A recorded event is history.

| Field | Meaning |
| --- | --- |
| `event_id` | identity of this event |
| `event_type` | a value from the `EventType` catalog, never a string literal |
| `schema_version` | payload shape version, so payloads can evolve |
| `occurred_at` | when it happened in the world |
| `recorded_at` | when the system wrote it down |
| `actor` | who acted: `USER`, `AGENT` (naming the mind), `ORCHESTRATOR`, `CONNECTOR`, `SYSTEM` |
| `subject` | who and what it is about |
| `correlation_id` | the turn or workflow this belongs to |
| `causation_id` | the event that caused this one |
| `origin` | which part of the system produced it: server, device, connector, system or AI |
| `client` | for a device submission, the client event id used for idempotency |
| `source` | the same `SourceRef` used by the graph |
| `sensitivity` | the same `SensitivityLevel` used by the graph |
| `payload` | a typed model chosen by `event_type` |
| `metadata` | incidental `JsonValue` data |

## 2. Rules

1. A recorded event is never modified. The model is frozen; a mutation raises.
2. A change is a new event, never an edit. A correction is an event too.
3. Every event carries `schema_version`.
4. Every event carries `correlation_id`.
5. Every consequence carries `causation_id`. `event.caused(...)` derives a
   consequence, carrying the correlation forward and setting causation.
6. Payloads serialize. `to_json()` / `from_json()` round-trip losslessly and
   rebuild the typed payload from the registry.
7. Event definitions never depend on a language model.
8. An event cannot be its own cause, and the bus refuses a cause it has not
   already seen. Causation points backwards, which is what makes a cycle
   impossible rather than merely unlikely.
9. A submission from a device carries a `ClientRef`. A retry over a flaky
   network is recognised by its client event id and returns the event already
   accepted, so retrying does not create a second commitment. Deduplication
   never keys on message text: two identical-looking captures can be two real
   commitments.

Arrival order is not the order things happened. `occurred_at` and `recorded_at`
stay separate, `arrived_late` says when they differ, and the log can be read in
either `in_arrival_order()` or `in_occurrence_order()`.

## 3. Payloads

`PAYLOAD_BY_EVENT` maps every `EventType` to a payload model; a test fails if
any event type is unmapped. Payload fields use domain enums
(`OpenLoopState`, `CyclePhase`, `AvailabilityState`, `GuardianVerdict`,
`PermissionLevel`, `ActionDomain`, …) rather than loose strings.

Reused shapes keep the catalog small: `EntityRefPayload` for simple
created/updated events, `OpenLoopPayload` for tasks and commitments,
`OperatorActionResultPayload` for the Operator's lifecycle outcomes.

`GraphMutationPayload` carries `entity_id`, `entity_type`, `revision` and
`status` — a reference and a version, never content. A consumer that needs what
the entity says reads it through `project_context` under its own clearance,
which is what keeps an event stream from becoming a second, unclassified copy
of the graph.

## 4. Catalog

Profile · Graph mutations · Goals · Commitments · Tasks · Deadlines · Calendar
events · Calendar conflict · Capture · Memory · Recommendations · Preference and
behaviour · Purchases and return windows · Products · Wardrobe · Cycle · Mood,
energy, sleep · Weather · Radar · Guardian · Readiness · Operator.

The recommendation lifecycle exists because behavioural learning needs the raw
signal:

```
RECOMMENDATION_SURFACED
RECOMMENDATION_ACCEPTED | RECOMMENDATION_DISMISSED | RECOMMENDATION_IGNORED
```

Without a record of what was offered and what became of it, a derived
preference has no evidence behind it and cannot be revised against the facts.

Capture is not a text box. `CaptureKind` covers text, voice, photo, screenshot,
files, shared links and the share sheet, and `MediaRef` points at media held
outside the domain — an id, a media type, a size, a checksum and a storage
reference. No domain model ever holds bytes.

The Operator's lifecycle is explicit because authorization has to be auditable:

```
OPERATOR_ACTION_PROPOSED
OPERATOR_ACTION_AUTHORIZED | OPERATOR_ACTION_REJECTED
OPERATOR_ACTION_STARTED
OPERATOR_ACTION_SUCCEEDED | OPERATOR_ACTION_FAILED
OPERATOR_ACTION_REVERSED
```

The full list lives in `src/wplos/events/types.py` and is the single source of
truth.

## 5. Announcing a graph mutation

`GRAPH_ENTITY_CREATED`, `GRAPH_ENTITY_REVISED` and `GRAPH_ENTITY_CLOSED` exist
for changes the catalog does not otherwise name. They are a fallback, not a
default: where an event already names the mutation — `COMMITMENT_CAPTURED` for a
new commitment, `EVENT_CANCELLED` for a closed calendar event — that event is
used, because two vocabularies for one fact means consumers subscribed to the
wrong one.

Equally, an event that means something else is never borrowed to avoid adding
the right one. `PRODUCT_LOW` is a rules observation about stock, not a statement
that a product record was revised, so a `PRODUCT` revision falls back rather
than pretending to be a detection. The mapping and its two rules live in
`application/graph_events.py`; the write path that uses it is documented in
`docs/runtime/graph-write.md`.

## 6. Bus

`EventBus` is the port a real broker would implement later.
`InMemoryEventBus` is an append-only log with synchronous fan-out. It refuses to
publish the same `event_id` twice, and offers `correlation()` and
`causation_chain()` so a turn can be reconstructed from its root cause forward.

Nothing here requires Kafka or Redis, and neither should be added until a real
need appears in an ADR.
