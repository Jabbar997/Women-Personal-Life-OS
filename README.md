# Women Personal Life OS

A Personal Life OS for women: one assistant on the outside, six specialised minds
on the inside, all reasoning over a single Personal Life Graph.

It is **not** a period tracker, a beauty app, a planner, a generic AI chatbot, a
deals app, or a super-app stitched together from separate features.

## Current phase

**Phase 01 — Foundation Layer.** This repository contains the domain core only:

- the Personal Life Graph model (entities, relationships, memory, provenance,
  confidence, sensitivity, temporal semantics),
- the domain event model (envelope, catalog, append-only store, in-memory bus),
- the six agent contracts plus the orchestrator contract,
- the policy primitives (permission levels, Guardian verdicts, execution
  authorization, need-to-know context projection).

There is deliberately **no** UI, no HTTP API, no LLM provider integration, no
database, no broker, and no autonomous agent loop yet. See
[`AGENTS.md`](AGENTS.md) for what is in and out of scope.

## The six minds

| Mind | Mission |
| --- | --- |
| Navigator | Determine what matters and where the user is going. |
| Radar | Detect relevant external opportunities and changes. |
| Life Admin | Own the user's open loops. |
| Guardian | Protect the user and constrain system behaviour. |
| Readiness | Make the user ready for what comes next. |
| Operator | Turn authorized intent into real-world action. |

An **Orchestrator** coordinates them. It is not a seventh mind: it holds no
business domain of its own. The user never picks a mind.

## Authority model

```
AI proposes  →  Rules constrain  →  Policies authorize  →  Operator executes
```

Guardian has veto authority (`ALLOW` / `CAUTION` / `BLOCK` / `ESCALATE`), and the
Operator can never execute an A2/A3 action without a valid user authorization.

## Layout

```
src/wlos/
├── core/                  base model config, domain errors, invariants, the Mind enum
├── shared/                ids, clock, temporal windows, provenance, confidence, sensitivity
├── personal_life_graph/   entities, relationships, memory, schemas, repository, context views
├── events/                envelope, catalog, typed payloads, append-only store, in-memory bus
├── agents/                the six contracts and their structured output types
├── orchestration/         orchestrator contract, mind registry, conflict resolution policy
└── policy/                permission levels, policy decisions, sensitivity and execution policy
docs/
├── architecture/          master-architecture-v3.md
├── domain/                personal-life-graph, event-model, agent-contracts, policy-model
└── adr/                   ADR-001 … ADR-005
tests/                     domain tests (not syntax tests)
scripts/                   bootstrap.sh, check.sh
```

## Getting started

```bash
./scripts/bootstrap.sh   # Python 3.13 venv + dev dependencies
./scripts/check.sh       # format, lint, strict type check, tests
```

Requires Python 3.13. The only runtime dependency is Pydantic v2.

## Documentation

- [`AGENTS.md`](AGENTS.md) — the working agreement for any agent or engineer on this repo
- [`docs/architecture/master-architecture-v3.md`](docs/architecture/master-architecture-v3.md)
- [`docs/domain/personal-life-graph.md`](docs/domain/personal-life-graph.md)
- [`docs/domain/event-model.md`](docs/domain/event-model.md)
- [`docs/domain/agent-contracts.md`](docs/domain/agent-contracts.md)
- [`docs/domain/policy-model.md`](docs/domain/policy-model.md)
- [`docs/adr/`](docs/adr/) — architecture decision records

## License

Proprietary and confidential. See [`LICENSE`](LICENSE).
