# Persistent GraphWrite

How a mind's request to change the Personal Life Graph becomes a durable,
typed mutation that is still there after a restart. This describes what is
implemented, not what is planned.

```
AgentOutput.writes
  -> enforce_output            (the mind's contract decides what it may write)
  -> RuntimeResult.sanctioned_writes
  -> GraphWriteResolver        (intent -> concrete typed mutation)
  -> GraphWriteService.apply   (validate, resolve versions, build events)
  -> GraphWriteStore.commit    (one transaction: versions + events + run record)
  -> outbox                    (consumers observe it)
```

## The pieces

| Concern | Where |
| --- | --- |
| A mind asking for a change | `GraphWriteIntent` (`agents/contracts.py`, unchanged) |
| That request, with its author | `SanctionedWrite` (`application/writes.py`) |
| The concrete typed mutation | `ResolvedGraphWrite` (`application/graph_write.py`) |
| Which event announces it | `application/graph_events.py` |
| Validation and assembly | `GraphWriteService` (`application/graph_write_service.py`) |
| The durable side | `SQLiteGraphStore` (`integration/graph_store.py`) |

### `GraphWriteIntent` is an intent

It carries an entity type, an operation, an optional entity id and a `summary`.
The summary is prose describing the request; it is never read as data. The
intent deliberately cannot construct an `Entity`, and it was not widened to be
able to: a `payload: dict` on an agent contract would make every typed
attributes model optional the moment a mind chose to bypass it.

### `ResolvedGraphWrite` is the intent after resolution

It carries the intent unchanged, the owner, the mind that proposed it, and —
depending on the operation — the concrete `Entity`, the revision the write was
built on, or the closure to apply. Its validators guarantee *shape*: a `CREATE`
carries a first-revision entity and no expected revision; a `REVISE` carries the
next version and the revision it follows; a `CLOSE` names an entity, a closure
and a time, and carries no entity, because the closed version is derived from
what is stored.

Agreement with the graph is not the model's job. Whether the stored entity is
the type the intent claims, whether the owner owns it and whether it is still
open are questions about stored state, and the service answers them against the
store.

### Resolution

`GraphWriteResolver` is a port. Knowing that "the dentist moved to Thursday"
means revising *this* commitment is domain knowledge; applying the revision
safely is not, and the two do not belong in the same object. No resolver ships
in `src/` yet — the deterministic resolvers used by the tests are the only
implementations, and a real one arrives with Universal Capture.

## Write semantics

**CREATE** — the entity must not already exist, must be owned by the command's
owner, and must be the type the intent declared. Revision 1 is inserted.

**REVISE** — the entity must exist, be owned by the same person, and be the same
type; an entity's type never changes. The new version is appended; the previous
one stays queryable.

**CLOSE** — the entity must exist, be owned by the same person, and still be
`ACTIVE`. Closing something already closed is refused rather than resolved into
another state. The closed version is `stored.closed(at=…, status=…)`, which sets
`temporal.valid_until` and bumps the revision, so the record leaves the active
view without leaving the history.

## Concurrency

`revision N → device A writes N+1 → device B, still holding N, is refused.`

The refusal is `ConcurrentModification`, the same exception the in-memory graph
has raised since Phase 01. It is raised in two places for two reasons:

- the service compares the stored revision to `expected_revision`, which gives a
  clear message;
- the insert itself carries `WHERE NOT EXISTS (… revision >= ?)`, with
  `PRIMARY KEY(entity_id, revision)` behind it, which is what actually holds
  when two workers both got past the check.

There is no last-write-wins path.

## Restart

The store keeps one row per `(entity_id, revision)` holding the canonical
`Entity` document. The current version is the highest revision; there is no
separate current row to fall out of step with history. Reconstruction is
`Entity.model_validate_json`, so what comes back is the domain model with its
validators, typed attributes, provenance, confidence, sensitivity and temporal
state intact. See ADR-012.

## The transaction

```
BEGIN IMMEDIATE
  claim the idempotency key
  for each write: append the entity version
                  insert the domain event into the outbox
  record the run
COMMIT
```

A crash before `COMMIT` leaves no entity version, no event and no request row. A
crash after it leaves all of them, with the event still `PENDING` for delivery.
There is no ordering in which the graph moved and nothing announced it.

## Idempotency

The key is `(owner_id, idempotency_key)`, a primary key in the database.

- same key, same fingerprint → the first attempt's receipt, marked `DUPLICATE`,
  with the same entity ids and the same event ids;
- same key, different fingerprint → `CONFLICT`, and nothing is written.

The fingerprint covers the operation, owner, entity type, target, expected
revision, closure and the entity's content. It excludes the entity id a `CREATE`
mints, `created_at`/`updated_at`, the derived `revision` and the source's
capture bookkeeping — all of which differ between two attempts at one command.
`ResolvedGraphWrite.logical_terms` is the list, with the reasoning.

The service looks the key up before validating, so a retried `CREATE` is not
refused for having already succeeded. That look-up is a fast path, not the
protection: two retries arriving together both find nothing and both reach the
insert, where the constraint decides. See ADR-013.

## Batch semantics

Everything one run asks for is one unit. If any write is rejected, none is
persisted and no event is emitted — not even for the writes that were fine. Two
writes to the same entity in one batch are refused rather than ordered by
guesswork. A run whose status is `BLOCKED` — Guardian could not be reached —
persists nothing at all. See ADR-013.

## Which event a mutation announces

Two rules:

1. If the catalog already names this mutation, that event is used.
   `COMMITMENT_CAPTURED` for a new commitment, `COMMITMENT_COMPLETED` for one
   that has just reached `COMPLETED`, `EVENT_CANCELLED` for a closed calendar
   event. Inventing a generic name beside an existing one would leave two
   vocabularies for one fact and consumers subscribed to the wrong one.
2. If it does not, the mutation is announced with `GRAPH_ENTITY_CREATED`,
   `GRAPH_ENTITY_REVISED` or `GRAPH_ENTITY_CLOSED` rather than by overloading an
   event that means something else. `PRODUCT_LOW` is a rules observation about
   stock, not a statement that a product record was revised.

A canonical event applies only where its payload can be derived from the entity
itself, plus the previous version for a revision. A deadline with no due date
cannot fill `DeadlinePayload`, so it falls back rather than inventing a date.

Derived and detection events — `PRODUCT_LOW`, `DEADLINE_APPROACHING`,
`RETURN_WINDOW_CLOSING`, `CALENDAR_CONFLICT_DETECTED`, `CYCLE_STATE_CHANGED` —
are never emitted here. They are rules observing state, not writes.

Per entity revision there is exactly one event:
`UNIQUE(aggregate_id, aggregate_version)` over `(entity_id, revision)`.

## What an event may carry

`GraphMutationPayload` is `entity_id`, `entity_type`, `revision`, `status`. A
reference and a version; never content. A consumer that needs what the entity
says reads it through `project_context` under its own clearance, which is what
stops the event stream becoming a second, unclassified copy of the graph.

The event's `sensitivity` is the entity's own. An event about an S3 record stays
S3 even though it carries only a reference: what a mutation is *about* is itself
something to withhold. Its `source` is the record's `SourceRef`, so provenance
survives the announcement, and its actor is the mind that asked for the write.

## The run record

`RuntimeRunRecord` is `request_id`, `correlation_id`, `owner_id`, `status`,
`started_at`, `completed_at`, and the entity and event ids the run produced. It
is written in the same transaction as the writes, so a completed run is
recognisable after a restart.

The runtime trace is not persisted. It carries shapes and counts for debugging,
and none of it is worth keeping forever next to a woman's life.

## Delivery

Events land in `graph_outbox` as `PENDING`. Delivery is at-least-once, as in the
Integration Kernel: `apply_once(consumer_name, event_id)` claims an event for one
consumer through `PRIMARY KEY(consumer_name, event_id)`, so a second delivery
claims nothing and each consumer still gets its own first delivery.

## What is not here

- No resolver in `src/`. Nothing yet turns a phrase into a typed entity.
- No projections. The outbox is durable and observable; nothing subscribes.
- No relationships or memory records in the durable store. Only entities.
- No migrations. `Entity.model_dump_json` is now part of the storage contract,
  and the first change to a stored attributes model needs a migration path.
