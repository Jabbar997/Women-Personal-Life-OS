# Women Personal Life OS

A Personal Life OS for women. One assistant on the outside; six specialised
minds and an orchestrator on the inside.

It is not a period tracker, a beauty app, a planner, a deals app, a generic AI
chatbot, or a super-app stitched together from separate features.

> **Current phase: Phase 01 — Domain Foundation.**
> This repository contains the domain core only: the Personal Life Graph, the
> event model, the agent contracts and the policy primitives. There is no UI, no
> API, no LLM integration and no database yet, by design.

## The six minds

| Mind | Mission |
| --- | --- |
| **Navigator** | Determine what matters and where the user is going. |
| **Radar** | Detect relevant external opportunities and changes. |
| **Life Admin** | Own the user's open loops. |
| **Guardian** | Protect the user and constrain system behaviour. Holds a veto. |
| **Readiness** | Make the user ready for what comes next. |
| **Operator** | Turn authorized intent into real-world action. |

The **Orchestrator** routes between them. It is a coordinator, not a seventh
mind, and owns no business domain of its own. The user never picks a mind.

## The rule that governs everything

```
AI proposes  ->  Rules constrain  ->  Policies authorize  ->  Operator executes
```

A language model never owns cycle calculations, deadlines, time arithmetic,
permissions, payment decisions, safety blocks, inventory truth, calendar
conflicts, or external execution authorization.

## Layout

```
src/wplos/
  shared/               errors and JSON primitives
  core/                 ids, time, sensitivity, provenance, confidence, records
  policy/               policy decisions, permission levels, Guardian verdicts,
                        sensitivity and execution authorization
  personal_life_graph/  entities, relationships, memory, the graph, context projection
  events/               event catalog, typed payloads, envelope, in-memory bus
  agents/               the six contracts and the shared agent abstractions
  orchestration/        orchestrator contract and conflict resolution
tests/                  domain tests, including the architecture boundary suite
docs/                   architecture, domain and decision records
```

Imports only ever point one way, and a test enforces it:

```
shared -> core -> policy -> personal_life_graph -> events -> agents -> orchestration
```

## Getting started

Requires Python 3.13.

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
./scripts/check.sh
```

`scripts/check.sh` runs the formatter check, the linter, `mypy --strict` and the
test suite. All four must pass before anything is pushed.

## Documentation

| Document | What it is |
| --- | --- |
| [`AGENTS.md`](AGENTS.md) | The brief for any agent or contributor working here. Read first. |
| [`docs/architecture/master-architecture-v3.md`](docs/architecture/master-architecture-v3.md) | Master Architecture V3 — Six-Mind Architecture. |
| [`docs/domain/personal-life-graph.md`](docs/domain/personal-life-graph.md) | Entities, relationships, memory, time, provenance, sensitivity. |
| [`docs/domain/event-model.md`](docs/domain/event-model.md) | Envelope, catalog, bus, event rules. |
| [`docs/domain/agent-contracts.md`](docs/domain/agent-contracts.md) | What each mind may read, write, decide and never do. |
| [`docs/domain/policy-model.md`](docs/domain/policy-model.md) | Permission levels, Guardian verdicts, sensitivity and execution policy. |
| [`docs/domain/agent-authority-matrix.md`](docs/domain/agent-authority-matrix.md) | Who may read, write, propose, veto and execute. Generated from the contracts. |
| [`docs/domain/agent-handoffs.md`](docs/domain/agent-handoffs.md) | The permitted passes of work between minds. |
| [`docs/validation/foundation-validation-01.md`](docs/validation/foundation-validation-01.md) | The ten-scenario life simulation and what it broke. |
| [`docs/adr/`](docs/adr/) | Architecture decision records. |

## Licence

Proprietary and confidential. See [`LICENSE`](LICENSE). This is not open source.
