# Policy Model

Implementation: `src/wlos/policy/`.

Authority is data and explicit evaluation, never conditionals scattered through
feature code.

## 1. Primitives

| Primitive | Purpose |
| --- | --- |
| `PermissionLevel` | how much authority an action needs (`A0`–`A3`) |
| `PolicyDecision` | outcome plus reasons, returned by every evaluation |
| `PolicyReason` / `ReasonCode` | why a decision came out the way it did |
| `GuardianVerdict` / `GuardianDecision` | Guardian's veto vocabulary and its concerns |
| `SensitivityPolicy` | who may see what (`Known ≠ shown`) |
| `ExecutionPolicy` | the single gate in front of every real-world action |

## 2. Policy outcomes

```
PERMIT · DENY · REQUIRE_CONFIRMATION · ESCALATE
```

Nothing returns a bare boolean: a refusal always carries its reason codes, which
is what makes the behaviour auditable and testable.

## 3. Permission levels

| Level | Meaning | Confirmation | Audit |
| --- | --- | --- | --- |
| `A0` | suggest only | — | — |
| `A1` | internal automatic action | — | — |
| `A2` | external action | user confirmation | — |
| `A3` | high-impact action | explicit user confirmation | required |

Each `ActionKind` has a floor (`MINIMUM_PERMISSION`) that cannot be lowered:
payment, purchase, legal, medical, sensitive communication, data sharing and
destructive external actions are always `A3`. Requesting `A1` for a payment
still yields `A3`.

## 4. Execution authorization

`ExecutionPolicy.evaluate(request, guardian, authorization, at)` decides in this
order:

1. Guardian `BLOCK` → `DENY` (`GUARDIAN_BLOCK`). Nothing overrides it.
2. Guardian `ESCALATE` → `ESCALATE` to the user.
3. Effective level `A0` → `DENY`; suggest-only never executes.
4. Level `A1` → `PERMIT`; internal actions need no confirmation.
5. Level `A2`/`A3` → the authorization must exist and must match the action, the
   kind, the owner, the level, and the validity window. `A3` additionally
   requires explicit confirmation — a standing rule is not enough.

A missing authorization returns `REQUIRE_CONFIRMATION` (ask the user); an invalid
one returns `DENY` (something is wrong, do not re-ask blindly).

## 5. Sensitivity policy

A `ContextConsumer` declares `required_domains` and a `clearance`. Exposure
requires both:

- clearance ≥ the item's sensitivity, otherwise `SENSITIVITY_ABOVE_CLEARANCE`;
- the domain is in `required_domains`, otherwise `NOT_NEED_TO_KNOW`.

Clearance alone is never sufficient. An `S3` cycle record is withheld from a
styling consumer that never declared a need for cycle data, even if that consumer
is cleared for `S3`.

## 6. Guardian's place in the chain

Guardian produces a `GuardianDecision`; `ExecutionPolicy` consumes it. Keeping
the verdict types in the policy layer, rather than inside the Guardian mind,
means a blocked action is refused by policy even if a caller forgets to ask
Guardian directly — the gate, not the caller, is authoritative.

## 7. Testing the policy layer

Covered by `tests/test_policy_execution.py` and `tests/test_context_privacy.py`:
Guardian block prevents authorization, A2 without authorization fails, A1
executes, A3 rejects standing rules, expired and mismatched authorizations are
refused, payments cannot be reclassified below A3, and S3 data is not exposed to
a consumer that does not require it.
