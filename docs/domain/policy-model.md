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

## 4. What an authorization is bound to

An authorization answers *what exactly was authorized*, not merely *that
something was*. It carries:

| Binding | Field |
| --- | --- |
| actor | `granted_by` |
| action | `action_id` |
| target and material parameters | `authorized_fingerprint` |
| permission level | `granted_level` |
| issued at | `granted_at` |
| validity | `expires_at` |
| Guardian decision at the time of consent | `guardian_verdict` |
| withdrawal | `revoked_at`, `revocation_reason` |
| user confirmation when required | `method`, `audit_ref` |

`ProposedAction.material_terms` holds the facts consent was given for — a price,
a time, a recipient — and `terms_fingerprint` is their stable digest, taken
together with the action, owner, domain, permission level and target. Incidental
`parameters` such as a retry counter are excluded, so a retry does not revoke
consent while a repricing does.

Consent to *Pilates Tuesday 19:00 for SAR 100* therefore cannot be spent on
*Tuesday 20:00 for SAR 180*: the fingerprint differs and the gate answers
`DENY / MATERIAL_TERMS_CHANGED`. Build one with
`ExecutionAuthorization.for_action(...)`, which captures the fingerprint from
the action exactly as it was presented to the user.

## 5. Execution authorization

`ExecutionPolicy.authorize(action, guardian, authorization, at)` evaluates in
this order:

1. The Guardian assessment must be *about this action*
   (`subject_action_id == action_id`), about the same terms, issued by the
   Guardian authority, not superseded by a newer verdict, and not stale.
   Otherwise `DENY` with `GUARDIAN_ASSESSMENT_MISSING`,
   `GUARDIAN_ASSESSMENT_FORGED` or `GUARDIAN_ASSESSMENT_SUPERSEDED`. Without
   these checks a `BLOCK` is bypassed by handing the gate an unrelated or
   home-made `ALLOW`. See ADR-008.
2. Guardian `BLOCK` → `DENY`. No level and no authorization buys past it.
3. Guardian `ESCALATE` → `ESCALATE`.
4. `A0` → `DENY` with `SUGGESTION_ONLY`.
5. `A1` → `PERMIT`, recording a Guardian caution if one was raised.
6. The offer must not have lapsed (`offer_expires_at`), otherwise
   `REQUIRE_CONFIRMATION` with `OFFER_EXPIRED`. A screen rendered two hours ago
   does not carry a live offer.
7. `A2` / `A3` → the authorization is checked: present, not revoked, for this
   action, for the same material terms, granted by this owner, captured under a
   Guardian verdict that permitted execution, unexpired, and of a sufficient
   level. `A3` additionally requires an explicit confirmation rather than a
   standing rule, and an audit reference.

The `action` handed to the gate must be the server's freshly derived proposal.
A client's copy of it is an input, never a source of truth.

## 6. Execution states

`ExecutionState` covers what actually happens to an action:

```
PROPOSED -> AUTHORIZED | REJECTED | REVOKED | EXPIRED
AUTHORIZED -> STARTED
STARTED -> SUCCEEDED | PARTIALLY_SUCCEEDED | FAILED | UNKNOWN
UNKNOWN -> SUCCEEDED | PARTIALLY_SUCCEEDED | FAILED
SUCCEEDED -> REVERSED | COMPENSATED
```

`UNKNOWN` exists because a timeout is not a failure: `touched_the_world` is true
for it, so a retry is not automatically safe and `ExecutionAttempt` carries the
action's idempotency key rather than the attempt's.
`PARTIALLY_SUCCEEDED` exists because a booking that succeeded while its calendar
write failed is neither success nor failure, and the steps say which was which.

`ReversibilityClass` separates `REVERSIBLE`, `COMPENSATABLE` and `IRREVERSIBLE`,
so an interface cannot offer to undo a sent message.

## 7. Source authority

`SourceAuthorityPolicy` decides who wins when two sources disagree:
`USER_EXPLICIT > USER_ACTION > CONNECTOR > DERIVED > INFERRED`, with recency
breaking ties within a level. A lower authority never overwrites a higher one —
a calendar feed replaying last week's time cannot erase the time the user
confirmed — and a refusal is a conflict to surface, not an error to swallow.

## 8. Notifications

A notification is a decision to tell her, kept separate from the domain event
that prompted it, from the attempt to deliver it, and from her opening it.
`NotificationPolicy` sends an `S2`-or-above alert with its content withheld,
because a lock screen is a shared context; the deep link survives so opening it
still lands in the right place.

`require_execution_authorization(...)` is the gate the Operator calls: it raises
`AuthorizationRequired` unless the outcome is `PERMIT`.

Missing or expired authorization yields `REQUIRE_CONFIRMATION` — ask the user.
A mismatched, insufficient or unaudited authorization yields `DENY` — something
is wrong, do not ask, refuse.

## 9. Sensitivity

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

## 10. Where policies are used

| Policy | Used by |
| --- | --- |
| `sensitivity.need_to_know` | `project_context`, every agent contract |
| `execution.authorization` | the Operator, the Orchestrator's authorization routing |
| `orchestration.conflict` | the Orchestrator's conflict handling |
| `source.authority` | reconciling connectors, inferences and what she said |
| `notification.disclosure` | what a push notification may say |

Each agent contract names the policies it requires in `required_policies`.
