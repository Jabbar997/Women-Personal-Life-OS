# AGENTS.md

The brief for any coding agent or contributor working in this repository. Read
this before writing code. Where this file and a code comment disagree, this file
wins; where this file and an ADR disagree, the ADR wins and this file is stale.

---

## 1. What this product is

**Women Personal Life OS** — a Personal Life OS for women.

It is **not** a period tracker, a beauty app, a planner, a deals app, a generic
AI chatbot, or a super-app assembled from unrelated features.

From the outside it is **one assistant**. Inside, six specialised minds do the
work and an orchestrator routes between them. The user never chooses a mind and
never sees the routing.

## 2. Current phase

**Phase 05 — Persistent GraphWrite.** The domain core, the decision runtime,
the Integration Kernel, and now a durable Personal Life Graph: a sanctioned
`GraphWriteIntent` becomes a typed mutation and its domain event, committed
together, and still there after a restart. Six deterministic reference minds
prove the machinery; no model is connected to anything. Two validation passes
have run against the foundation: a ten-scenario life simulation
(`docs/validation/foundation-validation-01.md`) and thirty adversarial scenarios
plus mobile readiness (`docs/validation/adversarial-validation-v3.md`). Seven
critical gaps were found across the two and all are closed.

**The product is a native-feeling iOS and Android application**, with Flutter
the likely client. No client code exists and none belongs here: the domain runs
server-side and is the authority. See ADR-009.

Already built:

- Personal Life Graph: entities, relationships, memory, provenance, confidence,
  sensitivity, temporal semantics, context projection.
- Event model: envelope, catalog, typed payloads, in-memory bus.
- Agent contracts for the six minds plus the Orchestrator contract.
- Policy primitives: permission levels, Guardian verdicts, sensitivity policy,
  execution authorization bound to material terms.
- The agent authority matrix and the handoff map, both derived from the
  contracts and checked by tests.
- `Money`, event `REQUIREMENT`s, `ZonedInstant`, record revisions, field-level
  sensitivity, the execution state machine, source authority, device
  capabilities and the notification decision/delivery split.
- The runtime: `RuntimeRequest`/`RuntimeResult`, declarative routing, a
  dependency DAG with cycle rejection, purpose-bound context, the agent port,
  contract enforcement, conflict and priority resolution, the Action Composer
  with a budget and typed suppression, authorization routing and a runtime
  trace.
- The Integration Kernel: a transactional outbox, DB-enforced idempotency,
  per-aggregate ordering, consumer offsets, projection staleness and an atomic
  processing claim, on stdlib `sqlite3`.
- Durable graph writes: `ResolvedGraphWrite`, the `GraphWriteService`, an
  append-only SQLite entity store that reconstructs canonical `Entity` models,
  graph mutation events in the same transaction, batch atomicity and
  request-level idempotency. See `docs/runtime/graph-write.md`.

Deliberately **not** built yet, and not to be added without a new ADR:

- Any UI or client (Flutter, React, landing page, chat surface, Today view).
- Any LLM provider behind the agent port. The reference minds are deterministic
  and are not the product.
- An HTTP API. The runtime is tested by calling it.
- Real connectors, bookings, payments or messaging. The Operator executes
  in-memory only, to prove the flow.
- An offline sync engine, a push provider, deep-link routing, or precomputed
  Today projections. The architecture must *permit* them; it must not assume
  them, and it must not assume a device is reachable at the moment of an action.
- A resolver that turns a phrase into a typed entity. `GraphWriteResolver` is a
  port; nothing in `src/` implements it, and Universal Capture is a later phase.
- Projections over the graph outbox. Events are durable and observable; nothing
  subscribes yet.
- Durable relationships or memory records. Only entities are persisted.
- Schema migrations. `Entity.model_dump_json` is part of the storage contract
  now, and the first change to a stored attributes model needs a migration path.
- Any LLM provider integration, DeepSeek included.
- Authentication, payments, a marketplace, an autonomous agent loop.
- A vector database, a graph database, Kafka, Redis, microservices.
- An HTTP API.

## 3. Architectural principles (non-negotiable)

1. **One assistant, six minds.** The Orchestrator decides who runs and in what
   order. Never expose a mind picker.
2. **The Personal Life Graph is the system of record.** No mind keeps a private
   memory store.
3. **Event-driven core.** Every significant change must be expressible as a
   domain event.
4. **AI is not the authority.**
   `AI proposes -> Rules constrain -> Policies authorize -> Operator executes.`
   A model never owns cycle calculations, deadlines, time arithmetic,
   permissions, payment decisions, safety blocks, inventory truth, calendar
   conflicts, or external execution authorization.
5. **Guardian has veto authority.** Its only outputs are `ALLOW`, `CAUTION`,
   `BLOCK`, `ESCALATE`. Nothing overrides a `BLOCK`.
6. **The Operator never executes high-impact actions silently.** Payment,
   purchase, legal, medical, sensitive communication, sensitive data sharing and
   destructive external actions always require authorization, and that
   authorization binds to the action's material terms. Consent to one price and
   time is not consent to another.
7. **Known is not Shown.** Knowing something does not license showing it, or
   handing it to a mind that does not need it. Sensitivity is classified per
   field as well as per record, so a mind gets the city without the street.
8. **The server is the authority.** A client's copy of an offer is an input.
   Terms, consent, the Guardian verdict and availability are revalidated
   server-side before anything happens, however recently the screen was drawn.
9. **No UI or client in this phase.**

## 4. Authority boundaries

| Mind | May decide | Max permission | Sensitivity ceiling | Writes |
| --- | --- | --- | --- | --- |
| Navigator | IGNORE, SURFACE, RECOMMEND | A0 | S2 | PRIORITY, MILESTONE |
| Radar | IGNORE, SURFACE, RECOMMEND | A0 | S2 | RADAR_ITEM |
| Life Admin | IGNORE, SURFACE, RECOMMEND | A0 | S3 | COMMITMENT, TASK, DEADLINE, DOCUMENT |
| Guardian | IGNORE, SURFACE (+ veto) | A0 | S3 | nothing |
| Readiness | IGNORE, SURFACE, RECOMMEND | A0 | S3 | TASK, ROUTINE |
| Operator | IGNORE, SURFACE, RECOMMEND, ACT | A3 | S3 | TASK, COMMITMENT, CALENDAR_EVENT |

These are enforced by validators on `AgentContract`, not by convention. Only the
Operator may hold `ACT` or an executable permission level; only Guardian may
hold a veto. The Orchestrator owns no business domain and cannot override
Guardian.

The full object-level matrix is generated from these contracts into
`docs/domain/agent-authority-matrix.md` — never edit it by hand, run
`scripts/generate_authority_matrix.py`. Permitted passes of work between minds
are in `docs/domain/agent-handoffs.md` and in `AGENT_HANDOFFS`; a handoff must
actually connect, meaning the source produces the events and the target consumes
them.

## 5. Coding conventions

- Python 3.13. Typed code, `mypy --strict` with `disallow_any_explicit`.
- Pydantic v2 models for every domain record. `extra="forbid"` everywhere;
  `frozen=True` for value objects and events.
- No magic strings for anything in the domain vocabulary: entity types, event
  types, verdicts, states and reasons are `StrEnum`s.
- `dict[str, Any]` is banned. Incidental values go in a record's
  `metadata: dict[str, JsonValue]`; anything meaningful gets a schema.
- Every `EntityType` must register an attributes model, and every `EventType`
  must register a payload model. Tests enforce both.
- Attributes that can hold something sharper than their type's default raise the
  record's floor through `minimum_sensitivity()`, rather than relying on the
  caller to classify correctly.
- Small, cohesive modules. Explicit domain names over clever ones.
- Docstrings only where they add something the signature does not. Never write a
  comment that restates the line below it.
- Do not add a dependency without an ADR. Runtime dependencies are pydantic and
  nothing else.
- Imports point one way only:
  `shared -> core -> policy -> personal_life_graph -> events -> agents -> orchestration -> application -> integration`.
  A test enforces this. `application/` is the runtime and the domain never
  imports it; `integration/` is the outermost layer, holds every adapter, and
  nothing below it may reach into sqlite, an outbox or a worker.
- Domain model, API contract and mobile view model stay three separate things.
  `ComposedActionPlan` is an application model, not a screen.

## 6. Time, provenance, confidence, sensitivity

- Naive datetimes are rejected at the boundary. Everything is UTC-aware.
- Keep the clocks apart: `created_at`/`updated_at` are record time,
  `valid_from`/`valid_until` are when a fact is true of the world, and
  `occurred_at`/`scheduled_for`/`due_at`/`completed_at` are domain time.
- Every stored fact carries an `Attribution`: source, confidence, sensitivity.
- A declaration is `CERTAIN` and carries no probability. Only inferential
  sources (`AI_INFERRED`, `BEHAVIORAL_INFERENCE`, `RADAR`) carry a probability,
  and the model refuses an inferential source that claims certainty.
- Sensitivity defaults: cycle, pregnancy, health, body signals, purchases and
  money context are `S3`; calendar, people and places are `S2`.
- Closing a record is three different acts. `superseded()` means it stopped
  being true and history keeps it; `invalidated()` means it was never true and
  it is never read back as history; `suppressed()` means do not mention it,
  while it stays true and audited. Only `INVALIDATED` is retroactive. Choosing
  the wrong one corrupts every as-of query.
- A time is an instant plus the zone it is anchored to. Never render an event in
  the user's current zone, and never resolve a DST gap or fold by guessing —
  `ZonedInstant.from_local` refuses unless the caller states a policy.
- Money is `Money`: integer minor units and a currency. Never a float, never a
  number inside a string.

## 7. Testing rules

- Test the domain, not the syntax. A test that only proves a field exists is not
  worth writing.
- Every architectural rule in this file that can be checked should be checked by
  a test. `tests/test_architecture_boundaries.py` is the pattern.
- Nothing is deleted in this system, so tests must assert that history survives
  an expiry or a revision.
- Run `./scripts/check.sh` before every push: format, lint, types, tests.

## 8. Security and privacy rules

- Never commit a secret, a token, a key or real user data. There is no `.env` in
  this repository and none should appear.
- Sensitivity is part of the model, not a later feature. A mind reads a record
  only through `project_context`, under its contract's scope.
- `S2` and above require an established need to know; a mind that does not
  declare the type in its contract does not receive it.
- `S3` is never surfaced into a shared context and only in a turn the user
  opened.
- Redactions record a count and a reason, never the withheld content.

## 9. Forbidden shortcuts

- Letting a model compute a date, a cycle phase, a permission or a conflict.
- Giving a mind a private store instead of using the graph.
- Hard-deleting a record instead of closing it in time.
- Mutating a recorded event. Corrections are new events.
- Scattering permission checks as `if` statements instead of a policy.
- Adding Kafka, Redis or a graph database because the architecture uses the
  words "event-driven" and "graph".
- Returning a bare string from a mind. Outputs are structured.
- Widening a contract to make a test pass.
- Putting a price, a time or a recipient in `parameters` instead of
  `material_terms`. Anything outside `material_terms` is not covered by consent.
- Handing the execution gate a Guardian assessment of a different action, or one
  the Guardian authority did not issue.
- Passing the gate an action a client sent back instead of one the server just
  derived.
- Writing a record over another without checking its `revision`.
- Persisting a simplified copy of an entity beside the canonical one. Storage
  may serialize a record; it may not define a second, weaker shape of it.
- Committing a graph mutation without the event announcing it, in the same
  transaction.
- Writing against a stored record without naming the revision it was built on.
  Closing is a write like any other.
- Moving a record between owners, or reopening a closed one, by handing the
  application a fully constructed `Entity` that went around the domain helper.
- Copying free-text provenance (`SourceRef.detail`) into anything durable that
  leaves the record. Events name where a fact came from, not what she said.
- Letting a resolver decide who authorized a write. It resolves data; the
  `SanctionedWrite` decides the mind, the operation and the target.
- Giving a mind a handle to a mutable graph. Minds propose writes; the
  application layer decides whether the graph accepts them.
- Putting business reasoning in the Orchestrator. It routes, coordinates,
  enforces, composes and records; it holds no opinion about a life.
- Letting the Orchestrator write to the graph, or a mind write outside its
  contract's `writes`.
- Executing an action Guardian did not assess. Silence is not consent.
- Dropping an item from a plan without a typed suppression reason.
- Putting bytes in a domain model, or a device id in the graph.
- Editing `docs/domain/agent-authority-matrix.md` by hand.

## 10. Source-of-truth documents

| Topic | Document |
| --- | --- |
| Architecture | `docs/architecture/master-architecture-v3.md` |
| Personal Life Graph | `docs/domain/personal-life-graph.md` |
| Events | `docs/domain/event-model.md` |
| Agent contracts | `docs/domain/agent-contracts.md` |
| Policy | `docs/domain/policy-model.md` |
| Agent authority | `docs/domain/agent-authority-matrix.md` (generated) |
| Agent handoffs | `docs/domain/agent-handoffs.md` |
| Runtime | `docs/runtime/orchestrator-runtime.md`, `routing.md`, `action-composer.md`, `failure-policy.md` |
| Integration kernel | `docs/runtime/integration-kernel.md` |
| Durable graph writes | `docs/runtime/graph-write.md` |
| Validation | `docs/validation/foundation-validation-01.md`, `docs/validation/adversarial-validation-v3.md` |
| Decisions | `docs/adr/` |

## 11. Next phase, when it is authorized

The domain is shaped to serve a mobile app, a REST or GraphQL API, background
jobs, an AI gateway, connectors, calendar integrations, Radar sources and
Operator actions. None of them are built yet. Adding one is a new phase with its
own ADR, not an incidental commit. Universal Capture — the first thing that will
need a real `GraphWriteResolver` — waits until Phase 05 is accepted and merged.
