# AGENTS.md — working agreement for this repository

Read this before writing any code here. It is the contract every coding agent and
engineer works under. Where this file and a prompt disagree, raise the conflict
rather than silently resolving it.

## 1. Product definition

**Women Personal Life OS** is a Personal Life OS for women.

It is **one assistant**. Internally it runs six specialised minds, coordinated by
an orchestrator, over a single Personal Life Graph.

It is **not**: a period tracker, a beauty app, a planner, a generic AI chatbot, a
deals app, or a super-app assembled from unrelated features. If a change makes
the product read like one of those, it is the wrong change.

## 2. Non-negotiable architectural principles

1. **One assistant — six minds.** The user never selects a mind. The orchestrator
   decides who runs and in what order.
2. **The Personal Life Graph is the system of record.** No per-mind memory silo.
   Every mind reads and writes the same graph through policy-filtered views.
3. **Event-driven core.** Every meaningful change is representable as a domain
   event.
4. **AI is not the authority.** `AI proposes → Rules constrain → Policies authorize
   → Operator executes`. An LLM must never be solely responsible for cycle
   calculations, deadlines, time arithmetic, permissions, payment decisions,
   safety blocks, inventory truth, calendar conflicts, or external execution
   authorization.
5. **Guardian has veto authority.** Its vocabulary is exactly `ALLOW`, `CAUTION`,
   `BLOCK`, `ESCALATE`. No mind overrides it.
6. **No silent high-impact execution.** Payment, purchase, legal, medical,
   sensitive communication, sensitive data sharing and destructive external
   actions always require authorization.
7. **Known ≠ shown.** The system knowing something is not permission to surface
   it. Exposure requires both clearance and a declared need for the domain.
8. **No UI in this phase.** No Flutter screens, no React frontend, no landing
   page, no chat interface, no Today UI.

## 3. The six minds and their authority

| Mind | Mission | May decide | Permission ceiling |
| --- | --- | --- | --- |
| Navigator | Determine what matters and where the user is going | IGNORE, SURFACE, RECOMMEND | A0 |
| Radar | Detect relevant external opportunities and changes | IGNORE, SURFACE, RECOMMEND | A0 |
| Life Admin | Own the user's open loops | IGNORE, SURFACE, RECOMMEND | A1 |
| Guardian | Protect the user and constrain system behaviour | IGNORE, SURFACE | A0 |
| Readiness | Make the user ready for what comes next | IGNORE, SURFACE, RECOMMEND | A1 |
| Operator | Turn authorized intent into real-world action | IGNORE, SURFACE, ACT | A3 |

Only the Operator may reach `ACT`, and only through `ExecutionPolicy`.

The **Orchestrator** owns: intent classification, context retrieval, agent
selection, ordering, conflict handling, Guardian enforcement, priority
aggregation, action composition, authorization routing, event emission. It owns
no business domain.

## 4. Boundaries you must not cross

- Domain code never imports an LLM SDK, an HTTP client, or a database driver.
  `src/wlos/` depends on Pydantic and the standard library. Nothing else.
- No mind writes outside the domains its contract declares.
- No `ACT` decision without `ExecutionPolicy.evaluate` returning `PERMIT`.
- No provenance-free facts. Every entity, relationship and memory carries a
  `SourceRef`.
- Never lower an entity type's sensitivity floor.
- Never delete history. Invalidate by closing a validity window; supersede by
  appending a revision.
- Never mutate a recorded event. Corrections are new events.

## 5. Coding conventions

- Python 3.13, Pydantic v2, strict typing. `mypy` runs in strict mode and must
  stay clean.
- Domain values are frozen Pydantic models (`DomainModel`). Changes return new
  values.
- Enums or typed literals for every closed vocabulary. Event names and decision
  states are never bare strings.
- Timestamps are timezone-aware UTC. `ensure_utc` rejects naive datetimes.
  Distinguish `created_at`, `occurred_at`, `recorded_at`, `valid_from`,
  `valid_until`, `due_at`, `scheduled_for`, `completed_at`.
- Small, cohesive modules with explicit domain names. No `dict[str, Any]` as a
  substitute for modelling.
- Docstrings only where they add something the code cannot say. No comments that
  restate the line below them.
- No new dependency without an ADR.

## 6. Testing rules

- Test domain behaviour, not syntax. A test that only checks a field exists is
  not worth writing.
- Every architectural rule in section 2 has at least one test that fails if the
  rule is broken.
- Tests pin time through the fixed `now` fixture, never wall-clock time.
- `./scripts/check.sh` (format, lint, mypy, pytest) must pass before any commit.

## 7. Security and privacy rules

- Sensitivity tiers: `S0` public-like, `S1` personal, `S2` sensitive, `S3` highly
  sensitive. Cycle, pregnancy, health, mood and money default to `S3`.
- Consumers of context declare `required_domains` and a `clearance`. Both must be
  satisfied; clearance alone is not enough.
- External recipients start at the lowest clearance and are widened deliberately,
  never by default.
- No secrets, tokens, keys or personal data in the repository, in tests, or in
  fixtures.
- Audit trails (why something was withheld) stay with the orchestrator and are
  never handed to the consumer that was refused.

## 8. Forbidden shortcuts

- Adding a UI, an LLM provider binding, full authentication, payments, a
  marketplace, an autonomous agent loop, or a vector database in this phase.
- Adding Kafka or Redis because the architecture is event-driven.
- Adding a graph database because the model is called a graph.
- Splitting the system into microservices.
- Replacing a domain rule with a prompt.
- Widening `Any` to make a type error disappear.

## 9. Current project phase

**Phase 01 — Foundation Layer (domain core).** Complete: Personal Life Graph,
event model, agent contracts, policy primitives, tests, docs, ADRs.

Not started, in rough order: persistence adapter, capture pipeline, orchestrator
runtime, AI gateway boundary, connectors, API layer, mobile client.

## 10. Source-of-truth documents

| Question | Document |
| --- | --- |
| What is the architecture? | `docs/architecture/master-architecture-v3.md` |
| How is the graph modelled? | `docs/domain/personal-life-graph.md` |
| How are events shaped? | `docs/domain/event-model.md` |
| What may each mind do? | `docs/domain/agent-contracts.md` |
| Who authorizes what? | `docs/domain/policy-model.md` |
| Why was this decided? | `docs/adr/` |

Code is the source of truth for behaviour; these documents are the source of
truth for intent. When they diverge, fix both in the same change.
