# ADR-008 — Guardian's verdict is a capability, not a data class

- **Status:** Accepted
- **Date:** 2026-09-11
- **Phase:** Adversarial validation (before Phase 04)

## Context

Guardian holds a veto, and the execution gate checks it before anything else.
ADR-006 bound an assessment to the action it assessed, which stopped a verdict
about one action being reused for another.

ADV-14 asked a blunter question: who made the verdict? `GuardianAssessment` was
an ordinary Pydantic model. Any code that could call the gate could also write
`GuardianAssessment(verdict=ALLOW)` and pass it in. The gate had no way to tell
that from a verdict Guardian actually reached. A `BLOCK` was bypassable by
constructing an `ALLOW` — which makes the veto decorative.

ADV-13 added a second problem: a verdict had no time and no lifecycle. An
`ALLOW` issued before new information arrived stayed valid afterwards.

## Decision

**Verdicts are issued through `GuardianAuthority`, and the gate believes nothing
else.**

1. `GuardianAuthority.assess(...)` mints an assessment with an unguessable id,
   records a digest of its contents, and tracks the latest assessment per
   action.
2. `is_authentic()` fails for anything this authority did not issue, and for an
   assessment edited after issue.
3. `is_superseded()` fails an older verdict once Guardian has reassessed the
   action — so a stale `ALLOW` cannot be replayed after the picture changes.
4. `is_stale_at()` fails a verdict older than the authority's window.
5. `ExecutionPolicy` holds an authority and applies all three checks before the
   verdict itself is read.
6. `GuardianAssessment.issued_by` is validated to be Guardian, and
   `GuardianAssessment.allow()` remains available but is documented as
   unverifiable — useful for tests of other things, useless at the gate.

## Alternatives considered

- **Leave it as a data class and rely on review.** Rejected. An authority
  boundary that depends on nobody writing the wrong constructor is not a
  boundary.
- **Sign assessments with HMAC and a secret.** Rejected for now: it adds key
  management and a secret to a repository that deliberately has none, and inside
  one process it protects against exactly the same set of callers as holding the
  object does. It becomes the right answer the moment Guardian is remote.
- **Have the gate call Guardian itself.** Tempting, and it removes the forgery
  question by removing the parameter. Rejected because it inverts the layering:
  the policy layer would depend on a mind, and Guardian's own reads would have
  to be projected from inside the gate. Routing is the Orchestrator's job.
- **A private sentinel object inside the assessment.** Rejected: it fights
  Pydantic, breaks serialization, and buys no more than the registry does.

## Consequences

**Positive**

- A forged or edited verdict is detected and denied with a named reason.
- A verdict now has a lifetime and can be retired, so Guardian reassessing an
  action actually stops the old answer being used.
- The capability is explicit and transferable: the Orchestrator holds it, and a
  mind that does not hold it cannot mint.

**Negative / trade-offs**

- **This is a process-level capability, not a cryptographic proof.** Anything
  holding a reference to the authority can mint a verdict the gate believes.
  Within one process this is the correct and enforceable boundary; it is not a
  defence against code running inside the same process that has the reference.
- The issuance registry grows with every assessment and has no eviction. In a
  long-running process it needs bounding. It is in-memory and per-process, which
  also means a restart invalidates outstanding verdicts — acceptable, and
  arguably desirable, for something that is supposed to be fresh.
- Every call site that built an assessment by hand had to change.

## When to revisit

When Guardian runs as its own service or process. At that point the registry
becomes a signature or a token issued across the boundary, `is_authentic`
becomes verification rather than lookup, and the residual risk above goes away.
