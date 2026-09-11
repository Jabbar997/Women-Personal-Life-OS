# Policy Model

Permissions are a model, not a scattering of `if` statements. Every answer is a
`PolicyDecision` carrying an outcome and machine-readable reasons.

## 1. Primitives

| Primitive | Purpose |
| --- | --- |
| `PolicyOutcome` | `PERMIT`, `DENY`, `REQUIRE_CONFIRMATION`, `ESCALATE` |
| `PolicyReason` | a `ReasonCode` and a human-readable message |
| `PolicyDecision` | policy name, outcome, reasons |
| `PermissionLevel` | `A0`, `A1`, `A2`, `A3` |
| `GuardianVerdict` | `ALLOW`, `CAUTION`, `BLOCK`, `ESCALATE` |
| `SensitivityPolicy` | who may read a record, and whether it may be surfaced |
| `ExecutionPolicy` | the single gate between intent and the real world |

A decision never returns a bare boolean, because "no" without a reason cannot be
explained to the user or audited later.

## 2. Permission levels

| Level | Meaning | Needs authorization | Needs explicit confirmation | Needs audit |
| --- | --- | --- | --- | --- |
| `A0` | suggest only | — | — | — |
| `A1` | internal automatic | no | no | no |
| `A2` | external, confirmed | yes | no | no |
| `A3` | high impact | yes | yes | yes |

`A0` is always available in any domain: proposing a payment is fine, running one
at `A1` is not. `MINIMUM_PERMISSION` sets the floor an action domain demands
*to execute*:

```
INTERNAL A1 · SCHEDULING A2 · COMMUNICATION A2 ·
SENSITIVE_COMMUNICATION A3 · PURCHASE A3 · PAYMENT A3 · LEGAL A3 ·
MEDICAL A3 · DATA_SHARING A3 · DESTRUCTIVE_EXTERNAL A3
```

`NEVER_SILENT` names the domains that can never execute without the user
knowing.

## 3. Guardian

`GuardianAssessment` carries a verdict and its findings. Built from findings, the
strictest wins:

```
ALLOW < CAUTION < ESCALATE < BLOCK
```

`BLOCK` is a veto. `ESCALATE` stops execution and asks for a human.

## 4. Execution authorization

`ExecutionPolicy.authorize(action, guardian, authorization, at)` evaluates in
this order:

1. Guardian `BLOCK` → `DENY`. Checked first, so no level and no authorization
   can buy past it.
2. Guardian `ESCALATE` → `ESCALATE`.
3. `A0` → `DENY` with `SUGGESTION_ONLY`.
4. `A1` → `PERMIT`, recording a Guardian caution if one was raised.
5. `A2` / `A3` → the authorization is checked: present, for this action, granted
   by this owner, unexpired, of a sufficient level; `A3` additionally requires an
   explicit confirmation rather than a standing rule, and an audit reference.

`require_execution_authorization(...)` is the gate the Operator calls: it raises
`AuthorizationRequired` unless the outcome is `PERMIT`.

Missing or expired authorization yields `REQUIRE_CONFIRMATION` — ask the user.
A mismatched, insufficient or unaudited authorization yields `DENY` — something
is wrong, do not ask, refuse.

## 5. Sensitivity

`evaluate_exposure` answers whether a mind may read a record:

- above the mind's ceiling → `DENY` (`CONSUMER_CEILING_EXCEEDED`)
- `S2` or above without an established need → `DENY`
  (`NEED_TO_KNOW_NOT_ESTABLISHED`)
- otherwise `PERMIT`

`evaluate_surfacing` answers the separate question of showing something to the
user:

- `S2` or above in a shared context → `DENY` (`SHARED_CONTEXT_DISCLOSURE`)
- `S3` outside a user-initiated turn → `REQUIRE_CONFIRMATION`
  (`NOT_USER_INITIATED`)

Holding cycle data in a mind's working context and saying it out loud are not the
same act, and the model keeps them apart.

## 6. Where policies are used

| Policy | Used by |
| --- | --- |
| `sensitivity.need_to_know` | `project_context`, every agent contract |
| `execution.authorization` | the Operator, the Orchestrator's authorization routing |
| `orchestration.conflict` | the Orchestrator's conflict handling |

Each agent contract names the policies it requires in `required_policies`.
