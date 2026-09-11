# Agent Contracts

Implementation: `src/wlos/agents/`, registry in
`src/wlos/orchestration/registry.py`.

This phase defines contracts and structured output types. No mind runs an LLM,
and none is autonomous.

## 1. Shared abstractions

`AgentContext` (policy-filtered view of the graph), `AgentRequest`,
`AgentDecision`, `AgentRecommendation`, `AgentEvidence`, `AgentConfidence`,
`AgentOutput`.

A mind never answers with a bare string. Output is structured, carries evidence,
and states its own confidence.

## 2. Canonical decision states

```
IGNORE  ·  SURFACE  ·  RECOMMEND  ·  ACT
```

Only the Operator holds `ACT`.

## 3. Priority classes

```
P0  safety / critical
P1  must handle
P2  should handle
P3  optional
```

## 4. Contract shape

Each contract declares: `mind`, `mission`, `reads`, `writes`,
`decision_authority`, `max_permission_level`, `forbidden_actions`,
`events_consumed`, `events_produced`, `required_policies`.

`assert_within_contract()` enforces it: a mind that decides beyond its authority,
requests a permission level above its ceiling, or emits an event it does not own
raises `ContractViolationError`.

## 5. Navigator

Mission: determine what matters and where the user is going.

Reads goals, priorities, commitments, tasks, calendar, energy, behavioural
history, career, education, family, radar. Writes priorities and goals.

Outputs: priority, next milestone, focus recommendation, deprioritization, goal
risk, progress assessment.

Must not: execute external actions, override Guardian, invent commitments.

## 6. Radar

Mission: detect relevant external opportunities and changes.

Reads places, interests, hobbies, goals, calendar availability, family, career,
past radar behaviour. Writes radar.

Classifications: `FYI`, `SAVE`, `RECOMMEND`, `ACT_NOW`. A candidate carries its
origin, source and relevance, and a `verified` flag.

Must not: execute, treat advertising copy as fact, override a calendar
commitment, override Guardian.

## 7. Life Admin

Mission: own the user's open loops — commitments, deadlines, tasks, returns,
refunds, renewals, appointments, bills, subscriptions, waiting-for items,
follow-ups, documents, preparation items.

Open loop states:

```
CAPTURED · CLARIFIED · SCHEDULED · WAITING · BLOCKED · DUE · COMPLETED · CANCELLED
```

Transitions are constrained by `ALLOWED_TRANSITIONS`; terminal states are final.

Must not: turn every piece of information into a task, execute external actions
directly.

## 8. Guardian

Mission: protect the user and constrain system behaviour. Veto authority.

Vocabulary, and nothing else:

```
ALLOW · CAUTION · BLOCK · ESCALATE
```

Checks: safety, privacy, health boundaries, financial risk, fraud, sensitive data
sharing, high-impact execution, schedule conflicts. Guardian is rule-based by
design — safety is not delegated to a model. The verdict is the most severe
concern raised.

## 9. Readiness

Mission: make the user ready for what comes next.

Reads upcoming events, available time, body context, cycle context, wardrobe,
beauty inventory, carry items, location and travel context, historical prep
duration.

Outputs: `wear`, `get_ready`, `carry`, `prepare`, `leave_at`, `avoid`, `tonight`,
`tomorrow`. `ReadinessPlan.quick()` produces Quick Ready Mode from the same
sections.

## 10. Operator

Mission: turn authorized intent into real-world action.

Permission levels:

```
A0  suggest only
A1  internal automatic action
A2  external action requiring confirmation
A3  high-impact action requiring explicit confirmation and audit
```

Hard rule: the Operator must not execute an A2/A3 action without a valid
authorization, and must not execute anything Guardian blocked. Every attempt
emits `OPERATOR_ACTION_PROPOSED`, then either `OPERATOR_ACTION_REJECTED` or the
authorized/started/succeeded chain — so refusals are as auditable as executions.

## 11. Orchestrator

Coordinates: intent classification, context retrieval, agent selection, ordering,
conflict handling, Guardian enforcement, priority aggregation, action
composition, authorization routing, event emission. Owns no business domain.

## 12. Conflict resolution

Default rank: Guardian → Navigator → Life Admin → Readiness → Radar → Operator.

The rank is a fallback, not a rigid chain. `ConflictResolutionPolicy` evaluates
ordered rules first — a Guardian `BLOCK` wins, a binding commitment beats a
discretionary opportunity, a P0 safety claim wins — and the rank breaks
remaining ties. Both the rules and the rank are configurable.

A claim that loses a conflict is demoted to at most `SURFACE`: it may still be
shown, it may never act.
