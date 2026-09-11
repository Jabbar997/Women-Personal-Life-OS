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
2. Client idempotency is database-enforced by `UNIQUE(user_id, client_request_id)`,
   named explicitly as the conflict target. It is not a read-then-write convention, and
   no other integrity error is read as "I have seen this request". A reused action id, a
   reused event id or a duplicate aggregate version is a bug and surfaces as one.
3. Delivery is at-least-once. Consumer effects are deduplicated durably by
   `(consumer_name, event_id)`.
4. Events are ordered per aggregate, never globally. A version *ahead* of what a
   consumer expects is a gap and parks. A version *behind* is a redelivery and goes to
   the durable dedupe, because parking a duplicate holds the stream on a hole that does
   not exist.
5. Authorization is checked using server time at the moment of execution.
6. Guardian is re-evaluated at execution. A stale mobile screen has no authority.
7. Material-term drift moves the action to `REAUTHORIZATION_REQUIRED`; it never silently
   executes under old consent.
8. `UNKNOWN` means the external world may already have changed. It is never treated as
   a normal failure and is queryable for operations.
9. A provider without idempotency or reliable lookup is never automatically retried
   after an ambiguous timeout.
10. Projection staleness is derived from two things: a non-terminal action affecting
    the projection, or a result event affecting it that is still unapplied. The server
    never promises an `expected_projection_version`. An action reaching `SUCCEEDED`
    does not make the view current while its event is still in the outbox.
11. A projection records `last_applied_event_id`. The client follows `action_id` until
    a terminal state, including failure.
12. Every event contract has a schema version. Consumers tolerate unknown fields and
    accept current and N-1 versions during migration.
13. Event payloads are sufficient for the consumer but avoid personal narrative or raw
    sensitive content. The skeleton carries ids, status and projection identity only.
14. Exactly one worker executes an action. Ownership is taken by a conditional UPDATE
    inside a transaction, never by a process lock, and the status machine is enforced in
    the same statement rather than checked beforehand.

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

Consumers track the last applied aggregate version independently. For each consumer,
the version it expects next is its offset plus one, and there are three cases:

```text
version >  expected   a gap; something earlier has not arrived, so park
version == expected   deliver
version <  expected   a redelivery; skip it, the dedupe key already has it
```

If version 9 appears while version 8 is missing, version 9 becomes `PARKED_FOR_GAP`.
Once the gap closes the parked event proceeds. If the configured gap timeout elapses it
becomes operationally visible as `NEEDS_ATTENTION` at the outbox level.

Because consumers advance separately, one that failed after another succeeded catches up
on the retry: the consumer that already applied the event skips it, the one that is
behind receives it, and the event is not parked for a gap that never existed.

## Execution ownership

`execute` claims the action before it decides anything:

```text
claim (conditional UPDATE)  →  re-read  →  Guardian  →  policy  →  provider
```

The claim comes first for two reasons. It is what makes exactly one worker proceed when
several are running, and it means Guardian is consulted once by the winner. Two workers
each asking Guardian would produce two assessments of the same action, and the second
retires the first — so the loser's verdict would arrive stale through no fault of its
own. Re-reading after the claim also picks up terms that moved between the first look
and the claim.

`ALLOWED_FROM` is the state machine. Every terminal status is absent from its value
sets, so `SUCCEEDED → PENDING`, `FAILED → PROCESSING` and `CANCELLED → PENDING` cannot be
expressed. The guard travels in the UPDATE's `WHERE` clause, because a check that runs
before the write is a check two workers can both pass.

## Projection contract

A projection stores:

```text
projection_id
last_applied_event_id
updated_at
```

Its `is_stale` state is true when either a non-terminal action affects the projection or
an unapplied outbox event does. No future projection revision is promised when an action
is accepted.

The second half matters: an action can reach `SUCCEEDED` while its result event is still
queued. Reporting fresh at that moment would tell a reader the view is current while it
still shows the state from before the action ran.

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
7. Projection stale state follows active actions and unapplied result events, and
   clears once the result event lands — including on terminal failure — without waiting
   for a promised version.
8. An event gains an unknown compatible field; the existing consumer still works.
9. Two concurrent commands use the same client request id and *different* action ids;
   `UNIQUE(user_id, client_request_id)` alone decides the winner, creating one logical
   action and one initial outbox event, and both callers are given the same action.

Additional tests cover gap recovery, a consumer catching up after a partial failure,
concurrent execution calling the provider exactly once, rejected terminal transitions,
integrity errors that must not be mistaken for duplicate requests, server-clock
reauthorization expiry and registry registration drift.

Lifecycle event names are an `IntegrationEventType` enum, deliberately outside the
Personal Life Graph event catalog: they record what the delivery machinery did, not what
happened in her life.
