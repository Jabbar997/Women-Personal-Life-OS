# Event Model

Implementation: `src/wlos/events/`.

## 1. Envelope

Every change in the system is recorded as a `DomainEvent`:

| Field | Purpose |
| --- | --- |
| `event_id` | identity |
| `event_type` | member of `EventType`, never a bare string |
| `schema_version` | payload contract version (starts at 1) |
| `occurred_at` | when it happened |
| `recorded_at` | when the system recorded it (never earlier than `occurred_at`) |
| `actor` | who caused it: user, mind, orchestrator, system, connector |
| `subject` | what it is about: entity, relationship, memory, action, user, system |
| `correlation_id` | ties one user-visible flow together |
| `causation_id` | the event that directly caused this one |
| `source` | `SourceRef` provenance |
| `sensitivity` | `S0 … S3` |
| `payload` | typed per event type |
| `metadata` | non-domain annotations |

## 2. Rules

1. A recorded event is never modified. Models are frozen and the store rejects a
   second append of the same `event_id`.
2. New information produces new events. Corrections are events, not edits.
3. Every event carries `schema_version`.
4. Every event carries `correlation_id`.
5. `causation_id` records the direct cause; `caused_by()` builds the next link in
   a chain and carries the correlation forward.
6. Payloads are serializable: `to_dict()` / `from_dict()` round-trip, restoring
   the concrete payload class from the catalog registry.
7. Event definitions depend on no LLM provider.

## 3. Typed payloads

Important events have typed payloads (`payloads.py`), for example
`GOAL_CREATED` → `GoalCreatedPayload`, `OPERATOR_ACTION_REJECTED` →
`OperatorActionRejectedPayload`. The envelope validates that the payload matches
the event type. Events whose shape is not yet pinned down use `GenericPayload`,
which still carries typed scalar values rather than `Any`.

## 4. Catalog

```
USER_PROFILE_UPDATED

GOAL_CREATED · GOAL_UPDATED · GOAL_PROGRESS_UPDATED

COMMITMENT_CAPTURED · COMMITMENT_UPDATED · COMMITMENT_COMPLETED

TASK_CREATED · TASK_COMPLETED

DEADLINE_CREATED · DEADLINE_APPROACHING · DEADLINE_MISSED

EVENT_CREATED · EVENT_UPDATED · EVENT_CANCELLED

CALENDAR_CONFLICT_DETECTED

CAPTURE_RECEIVED · CAPTURE_PARSED · CAPTURE_ROUTED

MEMORY_CREATED · MEMORY_UPDATED · MEMORY_INVALIDATED

PREFERENCE_OBSERVED · BEHAVIOR_PATTERN_UPDATED

PRODUCT_ADDED · PRODUCT_LOW · PRODUCT_EXPIRED

WARDROBE_ITEM_ADDED · WARDROBE_ITEM_STATUS_CHANGED

CYCLE_STATE_CHANGED

MOOD_UPDATED · ENERGY_UPDATED · SLEEP_UPDATED

WEATHER_CONTEXT_CHANGED

RADAR_ITEM_DISCOVERED · RADAR_ITEM_SAVED · RADAR_ITEM_DISMISSED · RADAR_ITEM_ACTED_ON

GUARDIAN_CAUTION_RAISED · GUARDIAN_BLOCKED_ACTION

READINESS_PLAN_CREATED · READINESS_PLAN_UPDATED · READY_CHECK_COMPLETED

OPERATOR_ACTION_PROPOSED · OPERATOR_ACTION_AUTHORIZED · OPERATOR_ACTION_REJECTED
OPERATOR_ACTION_STARTED · OPERATOR_ACTION_SUCCEEDED · OPERATOR_ACTION_FAILED
OPERATOR_ACTION_REVERSED
```

## 5. Store and bus

`InMemoryEventStore` is an append-only log with no update or delete operation. It
can return events by type, by correlation, and can walk a causal chain back to
its root.

`EventBus` is a protocol; `InMemoryEventBus` dispatches synchronously to
type-specific and global subscribers and appends to the store. No external broker
is introduced in this phase — an event-driven core does not require Kafka or
Redis to be correct.

## 6. Worked example — a capture becoming a task

```
CAPTURE_RECEIVED          correlation=C  causation=–
  └─ COMMITMENT_CAPTURED  correlation=C  causation=CAPTURE_RECEIVED
       └─ TASK_CREATED    correlation=C  causation=COMMITMENT_CAPTURED
```

One flow, three events, one correlation, an explicit causal chain.
