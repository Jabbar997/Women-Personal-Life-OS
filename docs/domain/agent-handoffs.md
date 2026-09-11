# Agent Handoffs

The permitted passes of work between minds. The source of truth is
`AGENT_HANDOFFS` in `src/wplos/orchestration/handoffs.py`; this document
describes it. `tests/test_agent_authority.py` fails if the two disagree, and if
any handoff claims to carry an event its endpoints cannot actually exchange.

A handoff is not a suggestion between minds. The Orchestrator performs it: a
mind never calls another mind, and never chooses who runs next.

## Canonical handoffs

| From | To | Purpose | Carries |
| --- | --- | --- | --- |
| Radar | Navigator | Opportunity evaluation against the user's direction. | `RADAR_ITEM_DISCOVERED` |
| Navigator | Life Admin | An accepted milestone becomes a commitment candidate. | `GOAL_UPDATED`, `GOAL_PROGRESS_UPDATED` |
| Life Admin | Readiness | An upcoming commitment requires preparation. | `COMMITMENT_CAPTURED`, `DEADLINE_APPROACHING` |
| Readiness | Guardian | A safety-sensitive preparation step needs a verdict. | `READINESS_PLAN_CREATED` |
| Radar | Guardian | A discovered item is checked before it is ever recommended. | `RADAR_ITEM_DISCOVERED` |
| Life Admin | Guardian | A scheduling clash is checked for real-world consequence. | `CALENDAR_CONFLICT_DETECTED` |
| Operator | Guardian | Every proposed action is assessed before authorization is sought. | `OPERATOR_ACTION_PROPOSED` |
| Guardian | Operator | A verdict reaches the only mind that can execute. | `GUARDIAN_BLOCKED_ACTION`, `GUARDIAN_CAUTION_RAISED` |
| *(Orchestrator)* | Operator | An authorized decision is routed to execution. | `OPERATOR_ACTION_AUTHORIZED` |

A handoff with no source agent is issued by the Orchestrator itself, not passed
between minds.

## Rules

1. **Every proposing mind hands off to Guardian before anything executes.**
   Guardian is not one stop among several; it is the gate.
2. **Only the Orchestrator hands work to the Operator with authority.** A mind
   cannot authorize another mind's action, and the Operator accepts execution
   only against an `ExecutionAuthorization` bound to the action's material
   terms.
3. **A handoff carries events, not instructions.** The target reads its own
   projected context; it never inherits the source's view, so a handoff cannot
   be used to smuggle data past the sensitivity policy.
4. **Handoffs do not create authority.** Receiving a handoff never widens what
   the target may read, write, decide or execute.
5. **A declared handoff must connect.** The source has to produce the events and
   the target has to consume them; an unconnected flow is a contract bug, not a
   documentation detail.

## Flow of a turn that ends in an action

```
capture ─▶ Life Admin ─▶ Navigator ─▶ Readiness
                  │           │            │
                  └───────────┴────────────┴──▶ Guardian
                                                   │
                                     ALLOW/CAUTION │ BLOCK/ESCALATE ──▶ stop
                                                   ▼
                                            Orchestrator
                                     (authorization routing)
                                                   │
                                                   ▼
                                              Operator
```

## What is deliberately absent

- **Mind-to-mind calls.** There is no path by which Radar invokes Navigator.
- **A handoff that skips Guardian on the way to execution.** Every route
  containing the Operator places Guardian before it, and a test asserts it.
- **A handoff from Guardian that widens anything.** Guardian can stop work and
  raise caution; it cannot grant authority, and it writes nothing to the graph.
