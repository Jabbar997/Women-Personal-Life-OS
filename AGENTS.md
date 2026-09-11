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

**Phase 01 — Domain Foundation.** The repository holds the domain core only.

Already built:

- Personal Life Graph: entities, relationships, memory, provenance, confidence,
  sensitivity, temporal semantics, context projection.
- Event model: envelope, catalog, typed payloads, in-memory bus.
- Agent contracts for the six minds plus the Orchestrator contract.
- Policy primitives: permission levels, Guardian verdicts, sensitivity policy,
  execution authorization.

Deliberately **not** built yet, and not to be added without a new ADR:

- Any UI (Flutter, React, landing page, chat surface, Today view).
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
   destructive external actions always require authorization.
7. **Known is not Shown.** Knowing something does not license showing it, or
   handing it to a mind that does not need it.
8. **No UI in this phase.**

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
- Small, cohesive modules. Explicit domain names over clever ones.
- Docstrings only where they add something the signature does not. Never write a
  comment that restates the line below it.
- Do not add a dependency without an ADR. Runtime dependencies are pydantic and
  nothing else.
- Imports point one way only:
  `shared -> core -> policy -> personal_life_graph -> events -> agents -> orchestration`.
  A test enforces this.

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

## 10. Source-of-truth documents

| Topic | Document |
| --- | --- |
| Architecture | `docs/architecture/master-architecture-v3.md` |
| Personal Life Graph | `docs/domain/personal-life-graph.md` |
| Events | `docs/domain/event-model.md` |
| Agent contracts | `docs/domain/agent-contracts.md` |
| Policy | `docs/domain/policy-model.md` |
| Decisions | `docs/adr/` |

## 11. Next phase, when it is authorized

The domain is shaped to serve a mobile app, a REST or GraphQL API, background
jobs, an AI gateway, connectors, calendar integrations, Radar sources and
Operator actions. None of them are built yet. Adding one is a new phase with its
own ADR, not an incidental commit.
