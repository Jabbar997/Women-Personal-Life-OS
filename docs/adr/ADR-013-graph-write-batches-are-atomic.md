# ADR-013 — Everything one run asks for is applied as one unit, under one key

- **Status:** Accepted
- **Date:** 2026-09-13
- **Phase:** 05 — Persistent GraphWrite

## Context

A single run of the Orchestrator can produce several `GraphWriteIntent`s from
several minds: Life Admin opens a commitment, Readiness adds the task that
prepares for it. They came out of one reading of one situation.

Two questions had to be answered rather than left to whatever the code happened
to do.

**Are those writes one unit or several?** If they are several and the second
fails, the graph keeps the first: a commitment with no preparation task, which
is a state no mind decided on and nothing downstream can interpret. The event
stream then announces half a decision, and a consumer that acts on it acts on
something that was never true.

**What is a retry?** Mobile networks retry, and a woman on a train tapping twice
is not two commitments. The Integration Kernel already answers this for external
actions with a client request id, a fingerprint of the logical command and a
unique constraint. Graph writes needed the same answer, not a different one.

## Decision

**One run, one batch, one idempotency key, all or nothing.**

1. `GraphWriteService.apply` validates every write in the batch before any of
   them is persisted, and hands the whole batch to the store, which commits it
   in one transaction. A rejection anywhere leaves nothing behind: no entity
   version, no event, not even a run record.
2. Two writes to the same entity in one batch are **refused**. The second would
   have to be built on a revision the first has not produced yet, and inferring
   the intended order is guessing.
3. The graph mutation and the domain event announcing it are in the same
   transaction. There is no arrangement in which the graph moved and nothing
   said so.
4. Idempotency is `(owner_id, idempotency_key)`, a `PRIMARY KEY` in the
   database. The same key with the same fingerprint returns the first attempt's
   receipt marked `DUPLICATE`; the same key with a different fingerprint is
   `CONFLICT` and writes nothing.
5. **`request_id` is a second identity, unique in the same table.** One request
   id is one run. A second, different batch presented under a request id that
   already has one is `CONFLICT`; the same batch arriving under a new key is
   `DUPLICATE`. Without this, both batches committed their mutations while
   `graph_runs` kept only the first — a durable contradiction, with a run record
   describing work other than the work that happened. The run insert is now a
   plain insert, so a clash there is loud rather than silently ignored.
6. The fingerprint covers what makes the command the command it is: operation,
   owner, entity type, target, expected revision, closure, the closure time
   normalised to UTC, and the entity's content. It deliberately excludes the
   entity id a `CREATE` mints, record time (`created_at`/`updated_at`), the
   derived `revision`, and the capture bookkeeping on the source — all of which
   differ between two attempts at the same command. An idempotency key that
   changes on every retry protects nothing.
7. **`closed_at` is not attempt metadata.** It sets `temporal.valid_until`, so
   it decides what the graph says about last Tuesday. Closing at a different
   time is a different closure, and treating it as noise would let one retry
   silently rewrite history the first attempt had already written. It is
   normalised to UTC before hashing, so the same instant expressed in another
   zone is still the same closure.
8. **Both identities are resolved before anything is checked against graph
   state**, and neither is left to be discovered inside `commit`. A retry that
   reaches validation is validated against the state its own first attempt
   produced and then refused for it — "entity already exists", a stale
   revision, "already ARCHIVED" — which is success reported as failure. The
   resolver answers one of four things: nothing found, `DUPLICATE`, `CONFLICT`,
   or `RequestIdentityConflict`. Reading both names is a correctness path; the
   uniqueness constraints remain the protection, and two retries arriving
   together still both reach `commit`, where the database decides.
9. **If the two identities disagree, it fails closed.** A key naming one stored
   request while the run id names another cannot be resolved by picking one:
   either answer risks handing the caller a receipt for work it never asked for.
10. **A request id is checked against its owner before any receipt is
    returned.** The id is unique across the store rather than per owner, so
    guessing one must not become a way to read what somebody else's run did. An
    owner mismatch is answered exactly as a fingerprint mismatch is, and says no
    more than that. The fingerprint already includes the owner, so today the two
    guards agree; the check stands on its own so that it keeps holding if the
    fingerprint's contents ever change.
11. **A retry can lose the race after its look-up.** It finds nothing, the winner
    commits, and validation then fails against the state the winner left. Before
    returning that failure the service resolves the request again, by both
    names, and returns the answer it has meanwhile been given. The re-read is
    deliberately narrow: it can only ever produce a receipt the database
    actually holds, so a genuinely stale write under its own names still raises.
12. A stale revision is otherwise not one of these outcomes. It is an invariant
    of the graph, and it raises `ConcurrentModification` — the same exception the
    in-memory graph has raised since Phase 01. Every write against an existing
    record names the version it saw, `CLOSE` included: a close prepared against
    a revision someone has since moved past is refused, not applied to whatever
    is current.

## Alternatives considered

- **Independent writes with partial success.** Rejected. It makes the caller
  responsible for reconciling a half-applied decision, and there is no caller in
  this architecture whose job that is. Revisit only when a run legitimately
  produces writes with no relationship to each other — and then say so in the
  request rather than inferring it.
- **Raising on a reused idempotency key**, as the Integration Kernel does.
  Rejected here. The kernel's caller is a worker driving one external action;
  this service's caller may be applying a batch on behalf of a device that lost
  its response, and a conflict is an answer it can act on rather than a failure
  it can only log. Both boundaries use the same fingerprint mechanism, which is
  the part that matters.
- **Letting the caller order two writes to one entity.** Rejected for now. It
  needs the batch to carry an explicit dependency between writes, and nothing
  yet produces one.
- **Applying writes even when the run was blocked.** Rejected. If Guardian could
  not be reached, the run failed closed, and persisting what the other minds
  asked for anyway would make failing closed cosmetic.

## Consequences

**Positive**

- The graph only ever holds states a whole decision produced.
- A retry is cheap and safe: it returns the original receipt, with the same
  entity ids and the same event ids.
- A reused key carrying different work is caught rather than silently answered
  with someone else's result.

**Negative / trade-offs**

- Making `request_id` unique means a caller that reuses one for genuinely
  separate work gets a conflict rather than two runs. That is the intent, but it
  does put the burden of minting a fresh request id on the caller.
- A large batch is all-or-nothing, so one bad write costs the good ones. That is
  the point, but it means a caller assembling unrelated writes into one batch
  gets worse behaviour than it should. The fix is smaller batches, not partial
  application.
- Refusing two writes to one entity in a batch will eventually be limiting. When
  it is, the answer is an explicit ordered dependency, not silent sequencing.
- The fingerprint's exclusions are a judgement. If a caller genuinely means two
  different commands and they differ only in an excluded field, the second is
  answered with the first's receipt. Every excluded field is listed in
  `ResolvedGraphWrite.logical_terms` with the reason it is excluded, so the
  judgement is reviewable rather than buried.
