# Agent Contracts

Six minds, one orchestrator. In this phase the contracts exist and the
implementations do not: no mind is backed by a language model yet.

## 1. Shared shape

| Concept | Purpose |
| --- | --- |
| `AgentContext` | the `ContextView` a mind may read for this turn |
| `AgentRequest` | request id, correlation id, `Intent`, context, instruction |
| `AgentEvidence` | why the mind believes what it says, with source and confidence |
| `AgentDecision` | a judgement on a subject |
| `AgentRecommendation` | a structured proposal, optionally with a `ProposedAction` |
| `AgentOutput` | decisions, recommendations, events and a Guardian assessment |
| `AgentConfidence` | the same `Confidence` the graph uses |

No mind returns a bare string. An `ACT` recommendation without a
`ProposedAction` is rejected by the model.

## 2. Canonical decision states

```
IGNORE  ·  SURFACE  ·  RECOMMEND  ·  ACT
```

## 3. Priority classes

```
P0 = Safety / Critical   P1 = Must Handle   P2 = Should Handle   P3 = Optional
```

## 4. Contract fields

`AgentContract` declares `mission`, `reads`, `writes`, `reads_memory`,
`decision_authority`, `max_permission_level`, `max_sensitivity`,
`events_consumed`, `events_produced`, `required_policies`, `forbidden` and
`holds_veto`.

`reads` is not documentation: `contract.context_scope(purpose)` turns it into the
`ContextScope` that `project_context` enforces.

Validators enforce the boundaries: only Guardian may hold a veto, only the
Operator may hold `ACT` or an executable permission level.

## 5. Navigator

**Mission:** determine what matters and where the user is going.

Reads goals, priorities, milestones, commitments, tasks, deadlines, calendar,
career, education, people, behaviour patterns and relevant Radar items.
Writes priorities and milestones. Ceiling `S2`.

Outputs: priority, next milestone, focus recommendation, deprioritization, goal
risk, progress assessment.

**Must not:** execute external actions; override Guardian; invent a commitment
the user never made.

## 6. Radar

**Mission:** detect relevant external opportunities and changes.

Reads city and area, interests, goals, calendar availability, family context,
career, past Radar behaviour. Writes radar items. Ceiling `S2`.

Classifications: `FYI`, `SAVE`, `RECOMMEND`, `ACT_NOW`. `ACT_NOW` is still a
proposal, never an act.

**Must not:** execute; treat an advertisement as an established fact; override a
calendar commitment; override Guardian.

## 7. Life Admin

**Mission:** own the user's open loops.

Reads and writes commitments, deadlines, tasks, returns, refunds, renewals,
appointments, bills, subscriptions, waiting-for items, follow-ups, documents and
preparation items. Ceiling `S3`.

Open loop states:

```
CAPTURED · CLARIFIED · SCHEDULED · WAITING · BLOCKED · DUE · COMPLETED · CANCELLED
```

**Must not:** turn every piece of information into a task; execute external
actions directly; compute a deadline with a model instead of date arithmetic.

## 8. Guardian

**Mission:** protect the user and constrain system behaviour.

Outputs only `ALLOW`, `CAUTION`, `BLOCK`, `ESCALATE`. Guardian holds a veto:
nothing overrides a `BLOCK`, and no permission level or authorization buys past
it.

Checks at minimum: safety, privacy, health boundaries, financial risk, fraud,
sensitive data sharing, high-impact execution, schedule conflicts.

When several findings disagree, the strictest decides. Guardian averages
nothing. Guardian writes nothing to the graph.

## 9. Readiness

**Mission:** make the user ready for what comes next.

Reads upcoming events, available time, weather, body context, cycle context,
wardrobe, beauty inventory, carry items, location and travel context, and
historical preparation durations. Ceiling `S3`, and cycle context reaches it
only because its contract declares the need.

Output kinds: `WEAR`, `GET_READY`, `CARRY`, `PREPARE`, `LEAVE_AT`, `AVOID`,
`TONIGHT`, `TOMORROW`. `ReadinessMode` carries `FULL` and `QUICK`, so Quick
Ready Mode is supported later without a redesign.

**Must not:** execute; compute departure time with a model instead of travel
arithmetic; surface body or cycle context outside the reason it was read for.

## 10. Operator

**Mission:** turn authorized intent into real-world action.

Permission levels:

```
A0 = suggest only
A1 = internal automatic action
A2 = external action requiring confirmation
A3 = high-impact action requiring explicit confirmation + audit
```

**Hard rule:** the Operator must not execute an A2 or A3 action without valid
authorization. Payment, purchase, legal, medical, sensitive communication,
sensitive data sharing and destructive external actions are never silent.

## 11. Orchestrator

Responsible for intent classification, context retrieval, agent selection,
ordering, conflict handling, Guardian enforcement, priority aggregation, action
composition, authorization routing and event emission.

It owns no business domain, cannot override Guardian, cannot execute, and never
exposes a mind picker. `ROUTING_TABLE` maps each `Intent` to an ordered route,
and a test asserts Guardian precedes the Operator in every route that can
execute.

## 12. Conflict resolution

The usual precedence is Guardian constraint > Navigator priority > Life Admin
commitment > Radar opportunity — as a default, not a fixed chain.

Arbitration is an ordered list of replaceable rules keyed on a claim's *nature*
(`CONSTRAINT`, `PRIORITY`, `COMMITMENT`, `PREPARATION`, `EXECUTION`,
`OPPORTUNITY`) rather than on which mind spoke:

```
GuardianVetoRule · SafetyPriorityRule · CommitmentOverOpportunityRule ·
NaturePrecedenceRule · PriorityClassRule · ConfidenceRule
```

Claims on different subjects coexist. A suppressed claim records what it lost to
and which rule decided.
