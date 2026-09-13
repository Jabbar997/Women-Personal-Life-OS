# ADR-012 — The Personal Life Graph is stored as its own canonical document, append-only, on SQLite

- **Status:** Accepted
- **Date:** 2026-09-13
- **Phase:** 05 — Persistent GraphWrite

## Context

Through Phase 04 the graph lived in a dictionary. Every invariant the domain
built — append-only history, revisions, provenance travelling with the record,
field-level sensitivity — held for exactly as long as the process did. A system
whose memory ends at the end of a request is not a Personal Life OS; it is a
calculator with opinions.

Two things usually go wrong when a domain model meets a database, and both are
worse than having no database yet.

The first is the **shadow model**: a `PersistentEntity(title, body, data_json)`
appears next to `Entity`, mapping is written between them, and within a phase
the storage shape is the one people reach for. It has no attributes registry, no
sensitivity floor and no temporal semantics, so every rule the domain enforces
becomes optional the moment something is read back.

The second is **history by convention**. A `current` row updated in place, with
a `history` table written alongside it by whoever remembers, gives an
append-only promise that holds until one code path forgets.

The Integration Kernel already runs on stdlib `sqlite3` with a transactional
outbox, per-aggregate versioning and DB-enforced idempotency, all reviewed.

## Decision

**One canonical document per entity version, in one append-only table, read back
only through the domain model.**

1. `graph_entity_versions` holds one row per `(entity_id, revision)`. The row
   carries `entity_json`, the output of `Entity.model_dump_json()`, and nothing
   else that is ever read back into a model.
2. The other columns — `owner_id`, `entity_type`, `status`, `recorded_at` — are
   an **index over that document**, so the database can answer "whose" and
   "which version" without parsing every row. Reconstruction goes through
   `Entity.model_validate_json` alone. There is no second shape of an entity in
   the system.
3. **There is no current-version row.** The current version of an entity is its
   highest revision. A write is an insert; nothing is updated and nothing is
   deleted. History cannot drift out of step with the present because it is the
   same table.
4. Whether a record is *active* is answered by `Entity.is_active_at`, not by a
   SQL predicate. An invalidated record was never true and an expired one was
   true once; re-encoding that distinction in a `WHERE` clause would be a second
   implementation of a rule that already exists.
5. Optimistic concurrency is enforced **by the write itself**: the insert names
   the predecessor — `WHERE (SELECT MAX(revision) …) IS ?` — and
   `PRIMARY KEY(entity_id, revision)` stands behind it. A check performed before
   the write is a check two workers can both pass.
6. The predecessor must be **exact**, not merely older. "Nothing at or beyond
   revision N" would accept revision 4 written onto an empty entity, leaving a
   history with a hole in it; an as-of query over that history cannot answer
   honestly, and nothing would ever tell us the hole is there. A successor that
   is not `expected + 1` is a caller bug and raises `InvariantViolation`.
7. The adapter is `wplos.integration.graph_store`, behind the `GraphWriteStore`
   port in `wplos.application.graph_write`. The application depends on the port;
   the outer layer implements it. Layering is unchanged and still tested.
8. Both durable stores share one connection and transaction mechanism in
   `wplos.integration.sqlite_support`: `BEGIN IMMEDIATE`, WAL, a busy timeout,
   rollback on any exit that is not clean.

## Alternatives considered

- **A relational schema with a column per domain field.** Rejected. Thirty-one
  entity types with their own typed attributes means either thirty-one tables or
  a wide sparse one, and every schema change becomes a migration of the domain
  rather than of the storage. The attributes registry already is the schema.
- **A `current` table plus a `history` table.** Rejected. Two places to keep in
  agreement, and the append-only promise then depends on every code path
  remembering to write both.
- **PostgreSQL now.** Rejected as premature. Nothing in this phase needs a
  server, and the port means the decision can be revisited without touching the
  domain. Adding an external database would also add the first runtime
  dependency this project has managed to avoid.
- **SQLAlchemy.** Rejected. An ORM's job is mapping between a domain model and a
  storage model. There is no storage model here, so it would only add a
  dependency and a second way to spell a query.
- **Storing a pickled model.** Rejected. Not portable, not inspectable, and it
  would tie stored history to a Python class layout.

## Consequences

**Positive**

- What comes out of the database is the model that went in, with its validators,
  its sensitivity floor and its typed attributes intact.
- History is structural. There is no code path that can quietly overwrite a
  version, because there is no update statement to write.
- A stale write loses in the database, so it still loses when the two writers are
  two processes.
- No new runtime dependency. `pydantic` remains the only one.

**Negative / trade-offs**

- Querying inside an entity's attributes means either adding an index column or
  reading rows and filtering in Python. That is acceptable at one user's scale
  and would not be at a million; the port is where that gets fixed.
- Storing whole documents costs space, and a revision rewrites the whole record
  rather than the changed field. Deliberate: a version that is a diff cannot be
  read without replaying every version before it.
- `Entity.model_dump_json` is now part of the storage contract. A field renamed
  in the model is a migration, and this repository has no migration tooling yet.
  The first schema change to a stored attributes model must add it.
