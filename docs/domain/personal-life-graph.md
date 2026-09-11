# Personal Life Graph

The system of record. One graph for the whole system; no mind keeps its own
store.

A life is modelled as **entities + relationships + state + temporal context +
provenance**. The model is independent of any storage engine: it can be
persisted to PostgreSQL or to a graph database later without rewriting domain
logic. `GraphStore` is the port; `PersonalLifeGraph` is the in-memory
implementation used in this phase.

## 1. Records

Everything stored shares `ProvenancedRecord`:

| Field | Meaning |
| --- | --- |
| `attribution` | source, confidence and sensitivity, bound together |
| `temporal` | `valid_from` / `valid_until` — when the fact is true of the world |
| `status` | `ACTIVE`, `SUPERSEDED`, `INVALIDATED`, `EXPIRED`, `ARCHIVED` |
| `created_at`, `updated_at` | record time |
| `metadata` | incidental `JsonValue` data, never meaningful domain state |

`source`, `confidence` and `sensitivity` are exposed as properties, so a record
reads the way the architecture describes it while the three stay inseparable.

## 2. Entity

```
id · entity_type · owner_id · label · attributes · markers
+ everything from ProvenancedRecord
```

`attributes` is a typed model chosen by `entity_type`. Every `EntityType`
registers one in `ATTRIBUTES_BY_TYPE`, and a validator refuses a mismatch, in
both directions, on construction and on deserialization. Reading them back is
explicit: `entity.attributes_as(GoalAttributes)`.

Adding a life domain therefore means adding a schema, deliberately — not
widening an untyped bag.

## 3. Domain coverage

Primitives, not one table per topic:

| Required domain | Primitive |
| --- | --- |
| Identity | `PERSON` with `is_self`, plus `PREFERENCE` memory |
| Goals, Priorities | `GOAL`, `PRIORITY`, `MILESTONE` |
| People, Family, Relationships | `PERSON` + `RELATED_TO` with `Kinship` |
| Career | `CAREER_ROLE`, `WORKS_AS` |
| Education | `EDUCATION_PROGRAM`, `COURSE`, `SKILL`, `ENROLLED_IN` |
| Calendar, Events | `CALENDAR_EVENT` |
| Commitments | `COMMITMENT` with `CommitmentKind` and `OpenLoopState` |
| Tasks | `TASK` with `OpenLoopState` |
| Health Context | `HEALTH_CONDITION` |
| Cycle Context | `CYCLE_STATE` with `CyclePhase` |
| Pregnancy Context | `PREGNANCY_STATE` with `PregnancyStage` |
| Mood, Energy, Sleep, Skin, Hair | `BODY_SIGNAL` with `BodySignalKind` |
| Wardrobe | `WARDROBE_ITEM` with `WardrobeCategory` |
| Beauty Inventory, Essentials | `PRODUCT` with `ProductCategory` |
| Purchases | `PURCHASE` |
| Subscriptions | `SUBSCRIPTION` |
| Places | `PLACE` |
| Interests, Hobbies | `INTEREST` with `EngagementLevel` |
| Money Context | `MONEY_CONTEXT` |
| Routines, Habits | `ROUTINE`, `HABIT` |
| Preferences | `MemoryType.PREFERENCE` |
| Behavioral History | `BEHAVIOR_PATTERN` + `MemoryType.BEHAVIOR` + the event log |
| Events (system) | domain events, see `event-model.md` |
| Event requirements | `REQUIREMENT` with `RequirementKind` and `RequirementStatus` |
| Money | `Money`, integer minor units plus a currency |

`INGREDIENT`, `AVAILABILITY_STATE`, `DOCUMENT` and `RADAR_ITEM` round out the
required relationship shapes.

### Requirements and money

A `REQUIREMENT` is one thing an event needs: an item, an outfit, a document or
money. `RequirementKind` separates carrying cash on the day from paying ahead,
an entry fee and a purchase, because those are different obligations with
different deadlines. Money is a `Money` value — integer minor units and a
currency, never a float and never a number inside a headline — and the same
primitive carries a Radar price, a purchase, a subscription and an Operator
material term.

`RequirementStatus` closes the loop when a dependency breaks: the gown going to
the laundry moves the requirement to `AT_RISK`, which `blocks_readiness`, and
emits `REQUIREMENT_STATUS_CHANGED` carrying the previous status and the cause.

## 4. Relationships

```
id · owner_id · from_entity_id · relationship_type · to_entity_id · attributes
+ everything from ProvenancedRecord
```

The canonical shapes are constrained by `RELATIONSHIP_SPECS`:

```
USER   HAS_GOAL       GOAL
USER   LIKES          INTEREST
USER   USES           PRODUCT
PRODUCT CONTAINS      INGREDIENT
EVENT  REQUIRES       ITEM
GOAL   SUPPORTED_BY   COURSE
PERSON RELATED_TO     PERSON      (symmetric)
ITEM   HAS_STATUS     AVAILABILITY_STATE
EVENT  CONFLICTS_WITH EVENT       (symmetric)
EVENT  REQUIRES       REQUIREMENT
```

`CONFLICTS_WITH` makes a clash between two commitments durable state rather than
a transient observation: the graph can be asked what collides on Thursday, not
just replayed until a conflict event reappears.

An edge whose meaning does not depend on its endpoints (`OWNS`, `LOCATED_AT`,
`PREPARES_FOR`, `BLOCKS`, `DERIVED_FROM`, `ATTENDS`, `ASSIGNED_TO`) is left
deliberately open. The graph refuses an edge its spec forbids.

## 5. Time

Three clocks, never collapsed into one:

| Clock | Fields | Question it answers |
| --- | --- | --- |
| Record time | `created_at`, `updated_at` | when did we write this down? |
| Validity | `valid_from`, `valid_until` | when is this true of the world? |
| Domain time | `occurred_at`, `scheduled_for`, `due_at`, `completed_at` | when does the world do it? |

A calendar event's start is its `scheduled_for` marker; only the end of the
interval lives in attributes, along with the IANA `time_zone` the event is
anchored to. `ZonedInstant` keeps an instant and its zone together: an
appointment at 09:00 in Riyadh is still at 09:00 in Riyadh after she lands in
London, and a local time that falls in a DST gap or fold is refused unless the
caller states which reading was meant. Naive datetimes are rejected at the boundary:
ambiguous time is a correctness bug, and time arithmetic is a rules concern.

## 6. Closing a record: wrong versus no longer true

`RecordStatus` separates two things that are easy to conflate and dangerous to
mix:

| Status | Meaning | Readable as history? |
| --- | --- | --- |
| `ACTIVE` | in force now | yes |
| `SUPERSEDED` | was true, replaced | yes |
| `EXPIRED` | was true, its time ran out | yes |
| `ARCHIVED` | was true, moved out of the working set | yes |
| `SUPPRESSED` | true, audited, not to be mentioned | yes, but never surfaced |
| `INVALIDATED` | was never true; we were wrong | **no** |

Only `INVALIDATED` is retroactive (`RecordStatus.negates_history`). Everything
else stays visible to an as-of query, so closing a record today does not rewrite
what the graph says about last month. `is_active_at(at)` asks "was this in force
then", not "is this the current row".

For memories these are separate methods: `superseded()` when she changed,
`invalidated()` when the system was wrong, and `suppressed()` when she asked us
not to bring something up. "Don't mention this" is a display decision; it is
neither a claim that the thing is untrue nor a request to erase it. Using the
wrong one is a history-integrity bug, not a naming preference.

Records also carry a `revision`, incremented on every change. `revise_entity`
accepts an `expected_revision` and refuses a write built on a stale read, so two
devices editing one open loop produce a detected conflict instead of a silent
last-write-wins.

## 7. Nothing is deleted

- An entity is revised into a new version; `entity_versions()` returns the full
  history and `created_at` survives.
- An entity is closed with `valid_until` and a status, so it is still readable
  as of a past moment.
- A relationship is expired, not removed: it disappears from "now", stays
  visible "then", and is still retrievable by id.
- A memory is invalidated with a reason recorded in metadata.

## 8. Provenance

`SourceRef` answers where a fact came from:

```
USER_DECLARED · USER_ACTION · SYSTEM_DERIVED · AI_INFERRED ·
BEHAVIORAL_INFERENCE · CALENDAR · EXTERNAL_CONNECTOR · RADAR · OPERATOR_RESULT
```

`AI_INFERRED`, `BEHAVIORAL_INFERENCE` and `RADAR` are *inferential*. Radar is
inferential on purpose: an advertisement is a claim, not a fact.

## 9. Confidence

`Confidence` is either `CERTAIN` (no probability attached) or `PROBABILISTIC`
(a value in `0.0 → 1.0`). "My favourite activity is Pilates" is certain;
treating it as a probability would be noise dressed up as rigour. An inferential
source claiming certainty is rejected by `Attribution`.

`score` gives a comparable scalar (`1.0` for certain) without pretending
certainty is a probability.

## 10. Sensitivity

| Level | Meaning | Examples |
| --- | --- | --- |
| `S0` | non-sensitive | ingredients, availability states, radar items |
| `S1` | personal | interests, goals, tasks, wardrobe |
| `S2` | sensitive | calendar, people, family, places, career |
| `S3` | highly sensitive | cycle, pregnancy, health, body signals, payments, money |

Sensitivity is part of the model from the start, not a later feature.

Sensitivity is classified at two levels, because a record is not uniform. A
place holds a city, an area, a street address and coordinates; only the last two
locate a woman precisely.

`EntityAttributes.SENSITIVE_FIELDS` names the fields sharper than their type's
default. From it:

- `sensitivity_floor()` is the highest level among *populated* sensitive fields.
  A record declared below its floor cannot be constructed, so an address can
  never sit on an `S1` place.
- `redacted_to(ceiling)` drops the fields above a ceiling and reports which
  names were dropped, never their values.

Projection tries the whole record first and falls back to a redacted one, so a
mind cleared to `S2` receives the city and area of the same record with the
address and coordinates withheld, and `redacted_fields` tells it something was
held back. Losing the city along with the street would be breakage dressed as
minimization. See ADR-007.

## 11. Memory

`MemoryType` is `FACT`, `PREFERENCE`, `BEHAVIOR`, `DECISION`, `RELATIONSHIP`,
`TEMPORAL`. A record carries `source`, `confidence`, `last_confirmed_at`,
`review_after`, `expires_at` and `sensitivity`.

A declared memory is confirmed the moment it is stored; an inferred one is not
confirmed until something authoritative confirms it. No vector database is
involved and none is needed at this layer.

## 12. Known is not Shown

A mind never queries the graph. It receives a `ContextView` built by
`project_context` from its contract's `ContextScope`, which carries the entity
and memory types the mind declares and its sensitivity ceiling.

Two gates apply:

1. **Scope** — types the mind did not declare are not retrieved at all.
2. **Policy** — `SensitivityPolicy` denies anything above the mind's ceiling,
   and denies `S2`/`S3` where no need to know is established.

Withheld records become a `Redaction`: a scope, a level, a reason and a count.
Never the content.

Surfacing to the user is a separate question from exposure to a mind:
`evaluate_surfacing` refuses `S2`+ in a shared context and requires a
user-initiated turn for `S3`.
