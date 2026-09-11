# Failure Policy

Losing Radar costs a suggestion. Losing Guardian costs the right to act.

## Criticality

| Mind | Criticality | Losing it means |
| --- | --- | --- |
| Guardian | `SAFETY_CRITICAL` | fail closed |
| Operator | `REQUIRED` | degraded; nothing executes |
| Life Admin | `REQUIRED` | degraded |
| Readiness | `REQUIRED` | degraded |
| Navigator | `OPTIONAL` | continue |
| Radar | `OPTIONAL` | continue |

## Dispositions

- **`CONTINUE`** — the run proceeds and the result carries a warning.
- **`CONTINUE_DEGRADED`** — the run proceeds, the status becomes `PARTIAL`, and
  the plan is formed from the minds that answered.
- **`FAIL_CLOSED`** — no candidate action survives. The status is `BLOCKED`,
  every proposed action is suppressed with `GUARDIAN_BLOCK`, and the result
  carries a `FAIL_CLOSED` warning.

## Fail closed

When the mind that would have said no cannot be reached, the answer is no.

This is not a degraded mode that still executes carefully. With Guardian
unavailable, `_authorize` blocks every action before the execution policy is
consulted at all, no authorization request is raised, and the Operator is never
called. `E2E-10` asserts exactly this: the runtime returns `BLOCKED`, the
executor's record of what it ran stays empty, and the user is told why.

The same holds for an action Guardian simply did not assess. Silence is not
consent: an action with no verdict is blocked as surely as one with a `BLOCK`.

## Business outcomes are not exceptions

`RuntimeStatus` represents `NO_ACTION`, `NEEDS_AUTHORIZATION`, `PARTIAL`,
`BLOCKED` and `FAILED` as values. Nothing in normal operation is communicated by
raising. Exceptions are reserved for programming errors and contract violations
— a mind returning something its contract forbids raises `ContractViolation`,
because that is a bug, not an outcome.

## What is not covered yet

Retry of a failed mind, circuit breaking, timeouts and partial-wave recovery are
not implemented. The plan records the failure and the disposition; deciding to
try again is work for the phase that puts real implementations behind the port.
