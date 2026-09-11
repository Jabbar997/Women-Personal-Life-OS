# Master Architecture V3 — Six-Mind Architecture

Status: authoritative architectural reference for Women Personal Life OS.
Phase: 01 — Foundation Layer.

## 1. Shape of the system

```
                        ┌──────────────────────────────┐
   user  ───────────▶   │        One Assistant         │
                        └──────────────┬───────────────┘
                                       │
                              ┌────────▼────────┐
                              │  Orchestrator   │  intent, context, selection,
                              │ (not a mind)    │  ordering, conflicts, authorization
                              └───┬───┬───┬─────┘
             ┌────────────┬───────┘   │   └───────┬────────────┐
        ┌────▼────┐  ┌────▼────┐ ┌────▼────┐ ┌────▼─────┐ ┌────▼─────┐ ┌──────────┐
        │Navigator│  │  Radar  │ │Life Admin│ │ Readiness│ │ Operator │ │ Guardian │
        └────┬────┘  └────┬────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘
             └────────────┴───────────┴────────────┴────────────┘            │ veto
                                       │                                     │
                        ┌──────────────▼─────────────────────────────────────▼──┐
                        │            Personal Life Graph (system of record)      │
                        └──────────────┬─────────────────────────────────────────┘
                                       │
                        ┌──────────────▼──────────────┐
                        │        Domain Events        │  append-only
                        └─────────────────────────────┘
```

The user sees one assistant. The six minds and the orchestrator are internal.

## 2. The six minds

| Mind | Mission | Core output |
| --- | --- | --- |
| Navigator | Determine what matters and where the user is going | priority, next milestone, focus, deprioritization, goal risk, progress |
| Radar | Detect relevant external opportunities and changes | opportunity, change, event, deal, candidate (FYI / SAVE / RECOMMEND / ACT_NOW) |
| Life Admin | Own the user's open loops | commitments, deadlines, tasks, returns, renewals, follow-ups |
| Guardian | Protect the user and constrain system behaviour | ALLOW / CAUTION / BLOCK / ESCALATE |
| Readiness | Make the user ready for what comes next | wear, get ready, carry, prepare, leave at, avoid, tonight, tomorrow |
| Operator | Turn authorized intent into real-world action | executed action plus its audit trail |

## 3. The orchestrator

Responsibilities: intent classification, context retrieval, agent selection,
ordering, conflict handling, Guardian enforcement, priority aggregation, action
composition, authorization routing, event emission.

It is explicitly **not** a seventh mind and owns no business domain. Encoded as
`ORCHESTRATOR_CONTRACT` in `src/wlos/orchestration/contract.py`.

## 4. Authority chain

```
AI proposes  →  Rules constrain  →  Policies authorize  →  Operator executes
```

An LLM is never the sole authority for cycle calculations, deadlines, time
arithmetic, permissions, payment decisions, safety blocks, inventory truth,
calendar conflicts, or external execution authorization. Those are deterministic
rules in the domain, testable without a model.

Guardian sits across the whole chain with veto authority. A `BLOCK` ends the
matter; `ESCALATE` hands the decision to the user.

## 5. Personal Life Graph

One graph per user: `Entities + Relationships + State + Temporal Context +
Provenance`. Modelled independently of storage so PostgreSQL or a graph database
can back it later without rewriting domain logic.

Every node and edge carries `SourceRef`, `Confidence`, validity window, and (for
nodes) `Sensitivity`. Details: [`../domain/personal-life-graph.md`](../domain/personal-life-graph.md).

## 6. Event-driven core

Every meaningful change is a `DomainEvent` with a uniform envelope:
identity, type, `schema_version`, `occurred_at` / `recorded_at`, actor, subject,
`correlation_id`, `causation_id`, source, sensitivity, typed payload, metadata.

Events are immutable and append-only; corrections are new events. The transport
in this phase is an in-process bus. Details:
[`../domain/event-model.md`](../domain/event-model.md).

## 7. Policy layer

Permission levels `A0`–`A3`, Guardian verdicts, sensitivity tiers `S0`–`S3`, and
the execution authorization gate live in `src/wlos/policy/`. Authority is data,
not scattered conditionals. Details:
[`../domain/policy-model.md`](../domain/policy-model.md).

## 8. Conflict resolution

Default precedence:

```
Guardian constraint  >  Navigator priority  >  Life Admin commitment  >  Radar opportunity
```

This is a starting rank, not a fixed chain. `ConflictResolutionPolicy` evaluates
ordered rules first (Guardian block wins, a binding commitment beats a
discretionary opportunity, P0 safety wins) and falls back to a configurable mind
ranking. A claim that loses may still be surfaced; it may never act.

## 9. Intended AI boundary

The planned model is DeepSeek V4.1 behind an AI Gateway. **No provider is wired
in, and the domain core must never depend on one.** When the gateway arrives it
sits outside the domain: it proposes structured candidates, the domain validates
them, policies authorize them, and the Operator executes.

## 10. Deployment shape

A modular monolith, split by domain boundary rather than by service. Each module
is separable later because dependencies point inwards (`shared` → `core` →
`personal_life_graph` / `events` / `policy` → `agents` → `orchestration`), never
outwards. No microservices in this phase.

## 11. What this phase deliberately omits

UI, HTTP API, authentication, payments, marketplace, autonomous agent loops,
vector database, graph database, external broker, connectors, and any
provider-specific AI integration.
