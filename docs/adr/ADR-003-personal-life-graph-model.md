# ADR-003 — Personal Life Graph model

- **Status:** Accepted
- **Date:** 2026-09-11
- **Phase:** 01 — Domain Foundation

## Context

The Personal Life Graph is the system of record for every mind. It has to
represent identity, goals, people, career, education, calendar, commitments,
tasks, health, cycle, pregnancy, mood, energy, sleep, skin, hair, wardrobe,
beauty inventory, essentials, purchases, subscriptions, places, interests, money,
routines, preferences, habits and behavioural history — without becoming thirty
unrelated tables, and without binding the domain to a storage engine.

## Decision

**A storage-agnostic domain graph of typed entities and typed relationships,
with provenance, confidence, sensitivity and bitemporal semantics on every
record. No graph database.**

Key choices:

1. **Primitives, not one type per topic.** Mood, energy, sleep, skin and hair are
   one `BODY_SIGNAL` with a `BodySignalKind`. Beauty stock and household
   essentials are one `PRODUCT` with a `ProductCategory`.
2. **A registry of typed attribute models.** Every `EntityType` maps to exactly
   one attributes model, validated in both directions and enforced by a test.
   `dict[str, Any]` is rejected; incidental values go in `metadata`.
3. **Attribution as one object.** Source, confidence and sensitivity travel
   together, so a record cannot know where a fact came from but not how far it
   may travel.
4. **Three clocks.** Record time, validity, and domain time are separate fields.
5. **Append-only.** Revise, close or expire; never delete.
6. **Constrained edges.** `RELATIONSHIP_SPECS` fixes the endpoints of the
   relationships whose meaning depends on them, and leaves the rest open.
7. **Projection, not querying.** A mind receives a `ContextView` built under its
   contract's scope; it never queries the graph.

## Alternatives considered

- **Neo4j or another graph database now.** Rejected. The name says "graph"; that
  is not an argument for an engine. Traversals in this phase are shallow and the
  domain model is still moving. A graph database can be adopted later behind
  `GraphStore` if traversal depth ever justifies it.
- **One generic entity table with a JSON blob.** Rejected. It would make every
  mind a parser and every bug a runtime surprise.
- **A separate model per life domain.** Rejected. Thirty near-identical records
  with thirty copies of provenance and sensitivity handling.
- **Event sourcing as the only store.** Rejected as the primary model for this
  phase: the event log exists and is authoritative for change, but reconstructing
  current state from events on every read is complexity the domain does not need
  yet. The graph is kept append-only so the two stay reconcilable.

## Consequences

**Positive**

- The same model serves PostgreSQL, a document store or a graph database.
- Sensitivity and provenance cannot be forgotten; they are structural.
- History survives every update, which the domain tests assert.

**Negative / trade-offs**

- Adding an entity type costs a schema. That is the point, but it is friction.
- The in-memory implementation is not a database: no indexes, no concurrency, no
  durability. It is the reference implementation of the port, not the product.
- Bitemporal reasoning is harder to think about than a single timestamp. The
  alternative is silent correctness bugs in a system whose core promise is
  getting time right.
