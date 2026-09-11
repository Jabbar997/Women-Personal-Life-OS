# Orchestrator Runtime

The machinery that lets six minds work together safely. It is not a seventh
mind: it routes, coordinates, enforces, composes and records, and it holds no
opinion about careers, cycles, deals, health, family or goals.

## Pipeline

```
RuntimeRequest
  ↓ intake            idempotency check, delay noted
  ↓ routing           declarative rules pick the minds and the purpose
  ↓ planning          a dependency DAG, cycle-rejected
  ↓ context           contract + purpose → scope → projection, per mind
  ↓ agent execution   each mind runs, its output checked against its contract
  ↓ guardian          verdicts on everything this run proposed
  ↓ conflict          arbitration between rivals, deadlocks reported
  ↓ priority          deterministic classification and ordering
  ↓ composition       dedupe, suppress, budget, group
  ↓ authorization     A0 suggest, A1 run, A2/A3 ask
  ↓ emission          domain events, separate from the trace
RuntimeResult
```

## Layer

`src/wplos/application/` is the application layer. The domain
(`core`, `policy`, `personal_life_graph`, `events`, `agents`, `orchestration`)
knows nothing about it, and the import direction is enforced by
`tests/test_architecture_boundaries.py`:

```
shared → core → policy → personal_life_graph → events → agents → orchestration → application
```

Three models stay distinct and only the first exists today: the **domain model**,
the **API contract**, and the **mobile view model**. `ComposedActionPlan` is an
application model, not a screen — it has no copy, no layout and no ordering that
assumes a surface.

## Statelessness

`OrchestratorRuntime` keeps nothing between runs. A request plus the current
graph produces a result, which is what allows the same request to be served by
any instance. The only memory is the `RuntimeLedger`, an injected port, and it
exists so a retried submission resolves to the run that already happened rather
than to a second one.

## Input

`RuntimeRequest` covers user text, a mobile action, a capture result, a domain
event, a scheduled trigger and a system re-evaluation. It carries
`occurred_at` and `received_at` separately: an intent formed offline two hours
ago is not an instruction to act as though it were formed now, and
`arrived_late` says so.

`ClientContext` holds the device, session and client request id. That is
transport. Nothing in the Personal Life Graph is keyed by a device, and a test
asserts it.

## Output

`RuntimeResult` is structured. Its `status` covers the business outcomes without
raising:

| Status | Meaning |
| --- | --- |
| `COMPLETED` | a plan was produced |
| `NO_ACTION` | nothing useful to say, and nothing invented to fill the gap |
| `NEEDS_AUTHORIZATION` | something waits on her answer |
| `PARTIAL` | a mind was lost, the rest still produced a plan |
| `BLOCKED` | fail-closed; nothing executable survived |
| `FAILED` | the run itself could not complete |

## Events versus trace

A domain event records that something happened to her life. The runtime trace
records how the machine reached an answer. Conflating them would fill her
history with function calls.

Emitted as domain events: `ORCHESTRATION_STARTED`, `ORCHESTRATION_COMPLETED`,
`ORCHESTRATION_FAILED`, `ACTION_PLAN_CREATED`, `AUTHORIZATION_REQUESTED`, and
the Operator lifecycle when something actually runs.

Kept in the trace only: routed agents, matched rules, execution order and waves,
per-mind scopes, policy decisions, conflicts, suppressions. `AGENT_EXECUTION_*`
deliberately never became a domain event.

The trace carries shape and counts, never values. A test dumps it and asserts
that entity labels do not appear in it.

## What the Orchestrator may not do

- It does not write to the Personal Life Graph. A test runs a full plan and
  asserts every entity revision is unchanged. Mutations arrive as
  `GraphWriteIntent` on a mind's output, checked against that mind's contract,
  and applying them is an explicit application service — not something the
  Orchestrator does on its own initiative.
- It does not mint Guardian verdicts, soften them, or proceed without one.
- It does not decide anything about a life. Every judgement in a result traces
  to a mind that was allowed to make it.
