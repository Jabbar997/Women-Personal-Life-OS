# ADR-006 — Authorization binds to material terms

- **Status:** Accepted
- **Date:** 2026-09-11
- **Phase:** Foundation validation (between Phase 01 and Phase 02)

## Context

The ten-scenario life simulation attacked the Operator gate with the case the
architecture cares most about: the user approves *Pilates, Tuesday 19:00, SAR
100*, and by the time the Operator runs, the class is *Tuesday 20:00, SAR 180*.

The Phase 01 `ExecutionAuthorization` bound only `action_id`, `granted_by`,
`granted_level`, `method`, `expires_at` and `audit_ref`. A re-stated action
keeping the same id passed the gate with the old consent. A second probe found
that `GuardianAssessment.subject_action_id` was never compared with the action
being authorized, so an `ALLOW` issued for an unrelated action satisfied the
gate — a Guardian `BLOCK` could be bypassed by supplying a different
assessment.

Both are the failure the permission model exists to prevent: execution without
valid authority.

## Decision

**An authorization binds to what was actually agreed, and a Guardian verdict
counts only for the action it assessed.**

1. `ProposedAction` gains `target_entity_id` and `material_terms` — the facts
   consent is given for. Incidental `parameters` stay separate.
2. `ProposedAction.terms_fingerprint` is a SHA-256 digest of the action id,
   owner, domain, permission level, target and material terms, over canonical
   JSON.
3. `ExecutionAuthorization` gains `authorized_fingerprint` and
   `guardian_verdict`, and is built with `for_action(...)`, which captures the
   fingerprint from the action as presented.
4. `ExecutionPolicy` denies with `MATERIAL_TERMS_CHANGED` when the fingerprints
   differ, denies when consent was captured under a verdict that did not permit
   execution, and denies with `GUARDIAN_ASSESSMENT_MISSING` when the assessment
   is not about this action.

## Alternatives considered

- **Compare `parameters` field by field.** Rejected: every caller would have to
  agree on which fields are material, which is exactly the decision that must
  live in the model.
- **A new `action_id` per restatement.** Rejected on its own: correct practice,
  but it relies on every caller doing it. The gate must not depend on a
  convention the caller might skip. With fingerprinting, either mistake is
  caught.
- **Typed material terms per action domain.** Rejected for now. The *rule* is
  universal; the *fields* are domain-specific and still moving. A typed union
  can replace the mapping later without changing the gate.
- **Trusting the caller to pass the right Guardian assessment.** Rejected. That
  is the definition of an unenforced boundary.

## Consequences

**Positive**

- Consent is specific, auditable, and answers "what exactly was authorized".
- A repricing or a reschedule sends the turn back to the user instead of
  through.
- A Guardian `BLOCK` can no longer be routed around.
- A retry or a changed trace id does not revoke valid consent.

**Negative / trade-offs**

- Callers must put the terms that matter in `material_terms`; anything left in
  `parameters` is not protected. This is a real obligation and the reason the
  two are named differently.
- The fingerprint is opaque in logs. The action record carries the readable
  terms, so the audit trail is not lost.
- `GuardianAssessment.allow()` now requires the action id, which is a breaking
  change to every call site. Worth it: the old default was the bug.
