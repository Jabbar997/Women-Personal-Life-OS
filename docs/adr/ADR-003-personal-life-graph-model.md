# ADR-003 — Personal Life Graph as a storage-independent domain model

- Status: accepted
- Date: 2026-09-11
- Phase: 01 — Foundation Layer

## Context

The Personal Life Graph is the system of record for every mind. It must represent
entities, relationships, state, temporal context and provenance across some
thirty life domains, and it must survive a change of storage engine without a
domain rewrite.

## Decision

Model the graph as **typed domain objects behind a `GraphRepository` protocol**,
with an in-memory reference implementation. Specifically:

- `Entity`, `Relationship` and `MemoryRecord` are frozen Pydantic models.
- Every one of them carries `SourceRef` provenance and a confidence value that
  `resolve_confidence` keeps consistent with that provenance.
- Entities carry a `Sensitivity` that may be raised above the type's floor but
  never lowered.
- Validity is bitemporal: `valid_from` / `valid_until` for the world, plus
  `created_at` / `updated_at` for the record.
- Writes append revisions; invalidation closes a window. Nothing is deleted.
- Entity types with a known shape validate against a typed attribute schema;
  the rest use a typed (not `Any`) attribute bag.
- Reads by a consumer go through `project_context`, never through the repository
  directly.

## Alternatives considered

**Adopt a graph database now (Neo4j, Memgraph).** Rejected: the name is not a
requirement. Traversals in this phase are shallow, the data is personal-scale,
and adding a database would add operational weight before a single query pattern
is known.

**Model directly as relational tables.** Rejected: it would push storage concerns
(join tables, nullable columns, migration shape) into the domain before the
domain has settled.

**One table/model per life domain.** Rejected: thirty-plus near-identical models
with no shared invariants, and every cross-domain rule written thirty times.

**Mutable entities with in-place updates.** Rejected: it makes "never delete
history" a convention rather than a property, and makes event sourcing awkward.

## Consequences

Positive:

- Provenance, confidence, sensitivity and validity are enforced at construction,
  so a mind cannot record a fact without saying where it came from.
- History is queryable as of any past moment, so an expired relationship stays
  auditable instead of vanishing.
- PostgreSQL or a graph database can be introduced later as an adapter.
- Sensitivity in the model from day one is what makes `Known ≠ shown` enforceable
  rather than aspirational.

Negative / accepted trade-offs:

- The in-memory implementation is O(n) for queries and single-process. Acceptable
  for a foundation phase; the protocol is the contract, not the performance.
- Frozen models mean updates allocate new objects and callers must reassign.
- A typed attribute bag is less rigid than a full schema per entity type; schemas
  cover the types where the shape is known and can expand over time.
