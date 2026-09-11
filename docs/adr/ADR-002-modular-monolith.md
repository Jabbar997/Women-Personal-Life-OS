# ADR-002 — Modular monolith over microservices

- Status: accepted
- Date: 2026-09-11
- Phase: 01 — Foundation Layer

## Context

The system has six minds, an orchestrator, a shared graph and an event core.
"Six minds" invites a service per mind. At this phase there is one user-facing
product, no traffic, no team boundaries to mirror, and the domain boundaries are
still being discovered.

## Decision

Build a **modular monolith**: one deployable, split into modules by domain
boundary, with dependencies pointing inwards:

```
shared → core → personal_life_graph / events / policy → agents → orchestration
```

No microservices, no service mesh, no inter-service transport in this phase.

## Alternatives considered

**A service per mind.** Matches the mental model, and is how the architecture may
eventually deploy. Rejected now: it would fix boundaries before they are
understood, force network calls and partial failure into every interaction
between minds, and fragment the Personal Life Graph — the one thing the
architecture insists must stay unified.

**A single flat package.** Simpler still, but it would let Guardian logic leak
into Radar and policy checks scatter into feature code, which is exactly what the
authority model forbids.

## Consequences

Positive:

- Refactoring across boundaries is cheap while the model is still moving.
- The Personal Life Graph stays a single system of record.
- Tests run in-process with no infrastructure.
- Extraction stays available: each module already has an explicit contract, and
  `GraphRepository` and `EventBus` are protocols, so a module can move behind a
  network boundary without rewriting its callers.

Negative / accepted trade-offs:

- Module boundaries are conventions the compiler does not enforce; import
  direction must be reviewed rather than assumed. `AGENTS.md` states the rule and
  the layering is part of code review.
- Scaling is per-deployable rather than per-mind. Irrelevant at personal scale.
