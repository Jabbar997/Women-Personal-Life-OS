# Personal Life Graph

The system of record. One graph per user, holding
`Entities + Relationships + State + Temporal Context + Provenance`.

Implementation: `src/wlos/personal_life_graph/`.

## 1. Storage independence

The domain model has no storage engine. `GraphRepository` is a protocol;
`InMemoryPersonalLifeGraph` is the reference implementation used by the domain
and the tests. A PostgreSQL adapter (relational tables for entities, edges and
memories) or a graph database can implement the same protocol later without any
change to domain logic. No graph database is being introduced now simply because
the model is called a graph.

## 2. Entity

| Field | Meaning |
| --- | --- |
| `id` | stable identifier |
| `entity_type` | node kind (`EntityType`) |
| `owner_id` | the user this belongs to |
| `attributes` | typed where the shape is known, open bag otherwise |
| `status` | `ACTIVE` / `INACTIVE` / `ARCHIVED` / `SUPERSEDED` |
| `created_at`, `updated_at` | record lifecycle |
| `valid_from`, `valid_until` | when the statement holds in the real world |
| `source` | `SourceRef` — where it came from |
| `confidence` | `0.0 … 1.0` |
| `sensitivity` | `S0 … S3` |
| `metadata` | non-domain annotations |

Entities are frozen. `with_attributes`, `with_status` and `invalidated_at` return
new revisions; the repository keeps every revision.

## 3. Life domains and entity types

`LifeDomain` covers the required areas: identity, goals, priorities, people,
family, relationships, career, education, calendar, commitments, tasks, health,
cycle, pregnancy, mood, energy, sleep, skin, hair, wardrobe, beauty inventory,
essentials, purchases, subscriptions, places, interests, hobbies, money,
routines, preferences, habits, life events, behavioural history, radar,
documents.

`EntityType` maps onto those domains (`ENTITY_DOMAIN`) and each domain has a
default sensitivity (`DOMAIN_SENSITIVITY`). These are extensible primitives, not
a table per life area.

## 4. Typed attributes

Entity types with a known shape are validated against a schema at construction:
goals, commitments, tasks, calendar events, cycle state, wardrobe items, beauty
products, radar items (`schemas.py`). Everything else uses the open attribute
bag, which is still typed (`ScalarValue`), never `Any`.

## 5. Relationship

`id`, `from_entity_id`, `relationship_type`, `to_entity_id`, `attributes`,
`confidence`, `source`, `valid_from`, `valid_until`, `created_at`.

Supported shapes include:

```
USER      HAS_GOAL      GOAL
USER      LIKES         INTEREST
USER      USES          BEAUTY_PRODUCT
PRODUCT   CONTAINS      INGREDIENT
EVENT     REQUIRES      ITEM
GOAL      SUPPORTED_BY  COURSE
PERSON    RELATED_TO    PERSON
ITEM      HAS_STATUS    AVAILABILITY_STATE
```

Expiry closes the validity window (`expired_at`); the edge and its history remain
queryable as of any past moment.

## 6. Temporal model

Distinct timestamps, never one field for everything:

| Timestamp | Question it answers |
| --- | --- |
| `created_at` | when the record was written |
| `updated_at` | when the record last changed |
| `occurred_at` | when the thing happened in the world |
| `recorded_at` | when the system learned of it |
| `valid_from` / `valid_until` | the window in which the statement holds |
| `due_at` | when something is owed |
| `scheduled_for` | when it is planned |
| `completed_at` | when it was finished |

All timestamps are timezone-aware UTC; `ensure_utc` rejects naive values, because
time arithmetic is rules work rather than something a model gets to guess at.

## 7. Provenance

Every fact, relationship and memory carries a `SourceRef` with one of:

```
USER_DECLARED · USER_ACTION · SYSTEM_DERIVED · AI_INFERRED
CALENDAR · EXTERNAL_CONNECTOR · RADAR · OPERATOR_RESULT
```

`AI_INFERRED` and `RADAR` are *inferential*; the rest are deterministic.

## 8. Confidence

Range `0.0 … 1.0`, paired with provenance by `resolve_confidence`:

- `USER_DECLARED`, `USER_ACTION`, `OPERATOR_RESULT` are declarations and must be
  `1.0`. "My favourite activity is Pilates" is a fact, not a 0.7 guess.
- `AI_INFERRED` and `RADAR` must stay below `1.0` (ceiling `0.99`, default `0.6`).
- Other sources default to `1.0` and may be lowered deliberately.

## 9. Sensitivity

```
S0  public-like / non-sensitive
S1  personal
S2  sensitive
S3  highly sensitive
```

Defaults: interests `S1`, wardrobe `S1`, calendar `S2`, family `S2`, purchases
`S2`, cycle `S3`, health `S3`, pregnancy `S3`, mood `S3`, money `S3`. An entity
may be classified higher than its type's floor, never lower.

## 10. Memory

`MemoryType` is `FACT`, `PREFERENCE`, `BEHAVIOR`, `DECISION`, `RELATIONSHIP`, or
`TEMPORAL`. Each record carries `domain`, `source`, `confidence`, `sensitivity`,
`last_confirmed_at`, `review_after`, `expires_at` and a status.

Memory lives in the graph. There is no per-mind memory silo, and no vector
database in this phase.

## 11. Context views — known ≠ shown

Minds never read the repository directly. `project_context` builds a
`ContextView` for one `ContextConsumer`, which declares `required_domains` and a
`clearance`. An item is included only if the consumer needs that domain **and**
is cleared for its sensitivity. Relationships appear only when both endpoints are
visible.

The refusal trail (`ContextProjection.audit`) stays with the orchestrator; the
consumer receives only the view and a count of what was withheld.
