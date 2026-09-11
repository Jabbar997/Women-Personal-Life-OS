# Master Architecture V3 — Six-Mind Architecture

The highest architectural reference for Women Personal Life OS. Everything else
in this repository is downstream of this document.

## 1. Product

A Personal Life OS for women: one assistant that understands a life as a whole
rather than a collection of trackers. Not a period tracker, a beauty app, a
planner, a deals app, a generic chatbot, or a super-app of separate features.

## 2. Shape of the system

```
                      ┌──────────────────────────────┐
   user turn  ───────▶│        Orchestrator          │
                      │  intent · context · routing  │
                      │  conflict · authorization    │
                      └───┬──────────────────────┬───┘
                          │                      │
        ┌─────────────────┼──────────────┬───────┴────────┬─────────────┐
        ▼                 ▼              ▼                ▼             ▼
   ┌─────────┐      ┌─────────┐    ┌───────────┐    ┌───────────┐  ┌──────────┐
   │Navigator│      │  Radar  │    │ Life Admin│    │ Readiness │  │ Operator │
   └────┬────┘      └────┬────┘    └─────┬─────┘    └─────┬─────┘  └────┬─────┘
        │                │               │                │             │
        └────────────────┴───────┬───────┴────────────────┘             │
                                 │                                      │
                          ┌──────▼───────┐                              │
                          │   Guardian   │◀─────── veto ────────────────┘
                          └──────┬───────┘
                                 │
                 ┌───────────────▼────────────────┐
                 │     Personal Life Graph        │
                 │  entities · relationships ·    │
                 │  memory · provenance · time    │
                 └───────────────┬────────────────┘
                                 │
                          ┌──────▼───────┐
                          │  Event Bus   │
                          └──────────────┘
```

The Orchestrator is a coordinator, not a seventh mind. It has no business domain
of its own.

## 3. The six minds

| Mind | Mission | Characteristic output |
| --- | --- | --- |
| Navigator | Determine what matters and where the user is going. | Priority, next milestone, focus, deprioritization, goal risk, progress |
| Radar | Detect relevant external opportunities and changes. | Opportunity, change, event, deal, recommendation candidate |
| Life Admin | Own the user's open loops. | Commitments, deadlines, tasks, follow-ups, waiting-for items |
| Guardian | Protect the user and constrain system behaviour. | `ALLOW` / `CAUTION` / `BLOCK` / `ESCALATE` |
| Readiness | Make the user ready for what comes next. | Wear, get ready, carry, prepare, leave at, avoid, tonight, tomorrow |
| Operator | Turn authorized intent into real-world action. | Executed action, or a refusal with a reason |

## 4. Non-negotiable principles

1. **One assistant, six minds.** Routing is internal and invisible.
2. **The Personal Life Graph is the system of record.** One graph, no per-mind
   memory silos.
3. **Event-driven core.** Every significant change is expressible as a domain
   event.
4. **AI is not the authority.**
   `AI proposes -> Rules constrain -> Policies authorize -> Operator executes.`
5. **Guardian has veto authority.**
6. **No silent high-impact execution.**
7. **Known is not Shown.**
8. **No UI in the foundation phase.**

## 5. What a language model may never own

Cycle calculations · deadlines · time arithmetic · permissions · payment
decisions · safety blocks · inventory truth · calendar conflicts · external
execution authorization.

These are rules and policies in code. A model may propose; it never decides.

## 6. Request flow

1. **Capture.** A turn or a connector signal arrives and becomes a
   `CAPTURE_RECEIVED` event.
2. **Intent classification.** The Orchestrator classifies the turn into an
   `Intent`.
3. **Context retrieval.** For each selected mind, the Orchestrator projects a
   `ContextView` from the graph under that mind's `ContextScope`. A mind never
   queries the graph directly.
4. **Agent execution.** The selected minds run in the order the routing table
   gives. Guardian always runs before the Operator.
5. **Conflict handling.** Competing claims on the same subject are arbitrated by
   the conflict policy.
6. **Guardian enforcement.** A `BLOCK` ends the matter; nothing downstream may
   soften it.
7. **Authorization routing.** An `ACT` recommendation becomes a `ProposedAction`
   and goes through the execution policy. A2 and A3 stop for the user.
8. **Execution and event emission.** The Operator executes what was authorized;
   every step emits events carrying `correlation_id` and `causation_id`.

## 7. Conflict precedence

The usual ordering is:

```
Guardian constraint  >  Navigator priority  >  Life Admin commitment  >  Radar opportunity
```

It is a default, not a fixed chain. Arbitration is a list of replaceable rules
(`GuardianVetoRule`, `SafetyPriorityRule`, `CommitmentOverOpportunityRule`,
`NaturePrecedenceRule`, `PriorityClassRule`, `ConfidenceRule`) keyed on the
*nature* of a claim rather than on which mind made it, so precedence can evolve
without rewriting arbitration.

## 8. Layering

```
shared -> core -> policy -> personal_life_graph -> events -> agents -> orchestration
```

Imports point one way only, and `tests/test_architecture_boundaries.py` fails the
build if that stops being true.

## 9. Technology position

Python 3.13 with Pydantic v2 for the domain core (see `ADR-001`), a modular
monolith rather than microservices (`ADR-002`), a storage-agnostic graph model
(`ADR-003`), an in-process event model with no broker (`ADR-004`), and contracts
before implementations (`ADR-005`).

The planned assistant model is DeepSeek V4.1 behind an AI gateway. The domain
core does not know that, and must never depend on any provider.

## 10. Future surfaces

The domain is shaped to serve a mobile app, a REST or GraphQL API, background
jobs, an AI gateway, connectors, calendar integrations, Radar sources and
Operator actions. None of these exist yet. Each is a separate phase.
