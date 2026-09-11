# Integration Kernel / Walking Skeleton v1

Status: implementation candidate pending repository CI and blocking reviewer acceptance.

## Scope

This phase proves the minimum durable integration path before any real connector, API,
or Flutter client is added:

```text
Command
  -> database transaction
     -> action mutation
     -> transactional outbox event
  -> worker
  -> consumer
  -> projection
  -> action status
```

It deliberately does not implement a full compensation framework, DLQ operations UI,
reconciliation scheduler, push transport, or external provider SDK.

## Invariants

1. A side-effect action and its first outbox event commit atomically.
2. Client idempotency is database-enforced with a unique constraint. It is not a
   read-then-write convention.
3. Delivery is at-least-once. Consumer effects are deduplicated durably by
   `(consumer_name, event_id)`.
4. Events are ordered per aggregate, never globally. A version gap is parked instead
   of being applied out of order.
5. Authorization is checked using server time at the moment of execution.
6. Guardian is re-evaluated at execution. A stale mobile screen has no authority.
7. Material-term drift moves the action to `REAUTHORIZATION_REQUIRED`; it never silently
   executes under old consent.
8. `UNKNOWN` means the external world may already have changed. It is never treated as
   a normal failure and is queryable for operations.
9. A provider without idempotency or reliable lookup is never automatically retried
   after an ambiguous timeout.
10. Projection staleness is derived from active actions affecting the projection. The
    server never promises an `expected_projection_version`.
11. A projection records `last_applied_event_id`. The client follows `action_id` until
    a terminal state, including failure.
12. Every event contract has a schema version. Consumers tolerate unknown fields and
    accept current and N-1 versions during migration.
13. Event payloads are sufficient for the consumer but avoid personal narrative or raw
    sensitive content. The skeleton carries ids, status and projection identity only.

## ActionSpec

Every side-effect action declares executable policy, not prose-only documentation:

- execution mode
- offline policy
- permission level
- idempotency requirement
- ordering policy
- reversibility
- post-commit failure policy
- emitted events
- affected projections
- reauthorization TTL and expiry behavior

External authorized actions are server-only. Async side effects must declare
idempotency.

## Event / consumer registry

`EventSpec` declares the consumers for an event. A consumer-free event must carry an
explicit `no_consumers_by_design` reason inside the spec; there is no external bypass
allowlist.

`ConsumerRegistry.validate()` compares declared consumers to actual runtime
registrations. This validation belongs in CI as well as runtime construction.

Consumer handlers are pure mappers that return a `ConsumerEffect`. The durable store
applies that effect and the dedupe marker in one database transaction.

## UNKNOWN and reconciliation

A provider timeout after request transmission produces `UNKNOWN`, not `FAILED`.

Reconciliation rules:

```text
UNKNOWN
  -> provider lookup supported
       -> lookup first
       -> confirmed success/failure settles the action
       -> confirmed not-found + provider idempotency may return to PENDING
  -> provider lookup unsupported
       -> provider idempotency supported: PENDING may be retried with same reference
       -> neither available: NEEDS_ATTENTION
```

There is intentionally no reconciliation scheduler in v1. `UNKNOWN` and
`NEEDS_ATTENTION` are queryable so ambiguous operations cannot disappear silently.

## Reauthorization

`REAUTHORIZATION_REQUIRED` has a server-owned TTL. Expiry behavior is declared by the
`ActionSpec` (`CANCEL` or `NEEDS_ATTENTION`). The device clock is never consulted.

## Per-aggregate ordering

Consumers track the last applied aggregate version. If version 9 appears while version
8 is missing, version 9 becomes `PARKED_FOR_GAP`. Once the gap closes, the parked event
can proceed. If the configured gap timeout elapses, it becomes operationally visible as
`NEEDS_ATTENTION` at the outbox level.

## Projection contract

A projection stores:

```text
projection_id
last_applied_event_id
updated_at
```

Its `is_stale` state is computed from non-terminal actions that declare they affect that
projection. No future projection revision is promised when an action is accepted.

## Exit tests

The skeleton is not accepted because files exist. It must survive these behaviors:

1. Worker stops after the action/outbox transaction commits; the event survives.
2. The same event is redelivered; one logical consumer effect occurs.
3. Provider request times out; action becomes `UNKNOWN`.
4. Provider has no idempotency and no lookup; automatic retry is forbidden and the
   action becomes `NEEDS_ATTENTION`.
5. Material terms change while pending; external execution does not occur and fresh
   authorization is required.
6. Guardian changes to `BLOCK` before execution; external execution does not occur.
7. Projection stale state follows active actions and clears on terminal failure without
   waiting for a promised version.
8. An event gains an unknown compatible field; the existing consumer still works.
9. Two concurrent commands use the same client request id; the database uniqueness
   constraint creates one logical action and one initial outbox event.

Additional tests cover gap recovery, server-clock reauthorization expiry and registry
registration drift.
