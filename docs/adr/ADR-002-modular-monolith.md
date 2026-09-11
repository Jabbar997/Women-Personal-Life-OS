# ADR-002 — Modular monolith, not microservices

- **Status:** Accepted
- **Date:** 2026-09-11
- **Phase:** 01 — Domain Foundation

## Context

The system has six minds, an orchestrator, an event-driven core and future
connectors. That shape invites a premature split into services, which would buy
deployment independence at the cost of a domain model that is still being
discovered.

## Decision

**A single modular monolith with enforced internal boundaries, structured so a
module can be extracted later without a rewrite.**

Modules and their one-way dependency order:

```
shared -> core -> policy -> personal_life_graph -> events -> agents -> orchestration
```

The direction is enforced by `tests/test_architecture_boundaries.py`, which
parses every module's imports and fails the build on a violation.

## Alternatives considered

- **Microservices per mind.** Rejected. Six network boundaries around a domain
  model that will change weekly, plus distributed tracing, retries and partial
  failure, for a system with no users yet.
- **A single flat package.** Rejected. Nothing would stop the Guardian from
  importing the Operator, or a mind from querying the graph directly, and the
  architecture's authority boundaries would degrade into convention.
- **Plugin architecture with runtime discovery.** Rejected as premature
  indirection.

## Consequences

**Positive**

- Refactoring across the domain stays cheap while the model is still moving.
- Authority boundaries are compile-time and test-time facts.
- Extraction later is mechanical: a module with one-way imports and a port
  interface can move behind a network boundary without touching its callers.

**Negative / trade-offs**

- Everything scales together. Acceptable at this stage.
- Discipline is needed to keep boundaries from eroding; the boundary test is the
  mechanism that supplies it.

## Extraction seams already in place

- `GraphStore` — the storage port, so persistence can move.
- `EventBus` — the transport port, so a broker can be introduced.
- `AgentContract` / `Agent` — so a mind can become a remote service.
