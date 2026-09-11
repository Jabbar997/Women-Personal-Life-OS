# Routing

Routing decides which minds wake and for what purpose. It uses no model, and it
is a table rather than a chain of conditionals so it can be read, tested and
extended without editing a function body.

## Rules

`RoutingRule` matches on trigger type, event type and intent, and names an
ordered set of agents plus a `Purpose`. A request may match several rules; the
agents are unioned in declaration order and the first matched rule supplies the
purpose.

| Rule | Fires on | Wakes |
| --- | --- | --- |
| `deadline_pressure` | `DEADLINE_APPROACHING`, `DEADLINE_MISSED`, `RETURN_WINDOW_CLOSING` | Life Admin, Readiness |
| `radar_discovery` | `RADAR_ITEM_DISCOVERED` | Radar, Life Admin, Navigator, Guardian |
| `action_proposed` | `OPERATOR_ACTION_PROPOSED`, `OPERATOR_ACTION_AUTHORIZED` | Guardian, Operator |
| `capture_triage` | `CAPTURE_PARSED`, `CAPTURE_ROUTED` | Life Admin, Guardian |
| `calendar_change` | event created/updated, conflict, requirement change | Life Admin, Readiness, Guardian |
| `plan_the_day` | `PLAN_DAY` intent | Navigator, Life Admin, Readiness, Guardian |
| `open_loops` | `OPEN_LOOPS` intent | Life Admin, Navigator, Guardian |
| `get_ready` | `GET_READY` intent | Readiness, Guardian |
| `direction_check` | `DIRECTION_CHECK`, `REFLECT` | Navigator, Guardian |
| `discover` | `DISCOVER` intent | Radar, Life Admin, Navigator, Guardian |
| `execute` | `EXECUTE` intent | Life Admin, Guardian, Operator |
| `capture` | `CAPTURE` intent | Life Admin, Guardian |
| `safety_fallback` | unknown intent | Guardian |

Life Admin rides along with Radar on purpose. An opportunity cannot be judged
without knowing what is already committed, and the architecture's own rule —
that Radar must not override a calendar commitment — is unenforceable if the run
never looks at the commitments.

A request matching nothing routes to no agents, and the runtime returns
`NO_ACTION` rather than inventing a reason to wake somebody.

## Purpose-bound context

A contract says the widest a mind may ever read. A purpose says what this
particular job needs. `PurposeScope` narrows a contract and can never widen it —
a validator refuses an entity type outside the contract's `reads` or a ceiling
above the contract's.

Radar looking for something local receives place, interest, calendar and radar
items at `S2`. The same Radar looking for a wellness opportunity receives less,
at `S1`. Neither ever receives cycle, pregnancy, health or body context.

A job with no declared scope falls back to the full contract scope, which is a
deliberate default: no scope means no narrowing, not no limit.

## Execution plan

Dependencies come from the declared handoffs rather than being invented by the
planner, so the plan cannot disagree with the map of how work may pass between
minds. The plan is a DAG and a cycle is rejected outright.

One subtlety is worth stating, because getting it backwards is easy. The handoff
map is cyclic on purpose: the Operator proposes, Guardian assesses, the verdict
returns to the Operator. Inside a single run that deadlocks, so the loop is cut
at the verdict, not at the proposal. Proposing and acting are different acts — a
mind has to say what it would do before Guardian can judge it. So the Operator
speaks first and Guardian runs last, and execution is not an agent step at all:
it happens in the authorization phase, after Guardian has answered and the
execution policy has permitted it.

"Guardian before the Operator" is a rule about acting, not about speaking.
