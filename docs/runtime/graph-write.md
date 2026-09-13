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

It **carries** the `SanctionedWrite` rather than restating it: the agent, the
operation, the entity type and the target are read from it, so there is no field
in which a resolver could put a different mind or a different target. Alongside
it are the owner and — depending on the operation — the concrete `Entity`, the
revision the write was built on, or the closure to apply.

Its validators guarantee *shape*: a `CREATE` carries a first-revision entity and
no expected revision; a `REVISE` carries the next version and the revision it
follows; a `CLOSE` names an entity, a closure, a time **and the revision it was
built on**, and carries no entity, because the closed version is derived from
what is stored.

Agreement with the graph is not the model's job. Whether the stored entity is
the type the intent claims, whether the owner owns it, whether it is still open
and whether it is still at the revision the write saw are questions about stored
state, and the service answers them against the store.

### Resolution

`GraphWriteResolver` is a port. Knowing that "the dentist moved to Thursday"
means revising *this* commitment is domain knowledge; applying the revision
safely is not, and the two do not belong in the same object. No resolver ships
in `src/` yet — the deterministic resolvers used by the tests are the only
implementations, and a real one arrives with Universal Capture.

**A resolver resolves data; it does not decide who authorized the write.**
`apply_runtime_result` binds each resolved write back to the `SanctionedWrite`
the runtime handed the resolver, and a mismatch is a `ContractViolation`. Two
things make substitution worth guarding against rather than trusting: the
substituted agent might well be allowed to write that entity type, so the
contract check alone would wave it through; and swapping the target of a
`REVISE` would change a record nobody asked about.

## Write semantics

**CREATE** — the entity must not already exist, must be owned by the command's
owner, and must be the type the intent declared. Revision 1 is inserted.

**REVISE** — the entity must exist, be owned by the same person, be the same
type, and still be `ACTIVE`. The new version is appended; the previous one stays
queryable.

Two things a revision may never do. It may not **change the owner**: the
replacement's `owner_id` must equal the stored owner and the command's owner, so
a record cannot be moved between people by rewriting a field. And it may not
**reopen a closed record**: `Entity.revised` has always refused that, and the
service enforces the same rule against a fully constructed `ACTIVE` replacement
that went around the helper. There is no reopen operation in this phase.

**CLOSE** — the entity must exist, be owned by the same person, still be
`ACTIVE`, and be at the revision the write was built on. Closing something
already closed is refused rather than resolved into another state. The closed
version is `stored.closed(at=…, status=…)`, which sets `temporal.valid_until`
and bumps the revision, so the record leaves the active view without leaving the
history.

## Concurrency

`revision N → device A writes N+1 → device B, still holding N, is refused.`

Every write against an existing record names the version it saw —
`REVISE` **and** `CLOSE`. A close prepared against what she read a minute ago
must not quietly close what someone else has written since.

The refusal is `ConcurrentModification`, the same exception the in-memory graph
has raised since Phase 01. It is raised in two places for two reasons:

- the service compares the stored revision to `expected_revision`, which gives a
  clear message;
- the insert itself names the predecessor —
  `WHERE (SELECT MAX(revision) …) IS ?` — with
  `PRIMARY KEY(entity_id, revision)` behind it, which is what actually holds
  when two workers both got past the check.

The adapter requires the **exact** predecessor rather than merely refusing to go
backwards. "Nothing at or beyond revision N" would also accept revision 4
written onto an empty entity, leaving a history with a hole in it that no as-of
query could read honestly. A successor that is not `expected + 1` is a caller
bug and raises `InvariantViolation`.

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

Two things identify a request, and the database enforces both:
`(owner_id, idempotency_key)` as a primary key, and `request_id` as a unique
index over the same table.

- same key, same fingerprint → the first attempt's receipt, marked `DUPLICATE`,
  with the same entity ids and the same event ids;
- same key, different fingerprint → `CONFLICT`, and nothing is written;
- same `request_id` under a different key, same fingerprint → `DUPLICATE`; it is
  the same run arriving again;
- same `request_id`, different fingerprint → `CONFLICT`. One request id is one
  run, and letting a second batch through would leave a durable contradiction:
  both sets of mutations committed, one run record describing only the first.

Because a claimed `request_id` cannot already have a run, the insert into
`graph_runs` is a plain insert. A clash there is a contradiction and is loud.

The fingerprint covers the operation, owner, entity type, target, expected
revision, closure, **the closure time normalised to UTC**, and the entity's
content. It excludes the entity id a `CREATE` mints, `created_at`/`updated_at`,
the derived `revision` and the source's capture bookkeeping — all of which
differ between two attempts at one command. `closed_at` is *not* among the
exclusions: it sets `temporal.valid_until`, so it decides what the graph says
about last Tuesday, and closing at a different time is a different closure.
`ResolvedGraphWrite.logical_terms` is the list, with the reasoning.

### Both identities resolve before anything is checked against the graph

`_resolve_existing_request` reads **both** names — the key and the request id —
before validation begins. This is not an optimisation. A retry that reaches
validation is validated against the state its own first attempt produced, and
then refused for it:

```
CREATE retry  -> "entity already exists"
REVISE retry  -> ConcurrentModification
CLOSE  retry  -> "already ARCHIVED"
```

All three are the first attempt having succeeded, reported as failure. Resolving
the request first is what makes a retry under a new key return the original
receipt instead.

It answers one of four things, in the project's own vocabulary:

| | |
| --- | --- |
| nothing found | validate and commit as normal |
| `DUPLICATE` | the same work under one of its names; the original receipt |
| `CONFLICT` | that name already stands for different work — or for someone else's |
| `RequestIdentityConflict` | the two names disagree about which request this is |

The last one **fails closed**. If the key names one stored request and the run
id names another, answering with either could hand the caller a receipt for work
it did not ask for, so the service raises rather than picking.

A request id is unique across the whole store rather than per owner, so the
owner is checked before any receipt is returned: guessing an id must never be a
way to read what somebody else's run did. An owner mismatch is answered exactly
as a fingerprint mismatch is, and says no more than that.

The look-up is still not the protection. Two retries arriving together both find
nothing and both reach the insert, where the uniqueness constraints decide.

### A retry can also lose the race after its look-up

It finds nothing, the winner commits, and validation then fails against the
state the winner left. Before returning that failure the service resolves the
request again — by both names — and if this exact request has meanwhile been
answered it returns that answer. The re-read is narrow: it only ever converts a
failure into a receipt the database actually holds, so a genuinely stale write,
under its own key and its own request id, still raises `ConcurrentModification`.
See ADR-013.

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
something to withhold. Its actor is the mind that asked for the write.

Provenance travels **without its prose**. `SourceRef.detail` is free text
written when the fact was captured and is frequently her own words, so the
announcement carries `SourceRef.without_free_text()`: the source type, the
capture time and the opaque `reference` survive, and the detail does not. The
canonical entity is untouched — it still holds everything she said, behind
context projection. Only the copy that leaves the record is narrowed.

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

**This is not exactly-once, and nothing here should be read as claiming it.**
The guarantee is at-least-once delivery plus a durable dedupe marker. A consumer
whose effect and whose dedupe marker are not written in the same transaction can
still apply an effect twice — the marker says the event was claimed, not that
the work finished. Closing that gap means committing the consumer's effect and
its marker together, and that belongs with the first real projection rather than
with a general processing framework built ahead of one. Deferred.

## What is not here

- No resolver in `src/`. Nothing yet turns a phrase into a typed entity.
- No projections. The outbox is durable and observable; nothing subscribes, and
  consumer-effect atomicity is deferred with them (see **Delivery**).
- No relationships or memory records in the durable store. Only entities.
- No migrations. `Entity.model_dump_json` is now part of the storage contract,
  and the first change to a stored attributes model needs a migration path.
