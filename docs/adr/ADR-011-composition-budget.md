# ADR-011 — A composed plan is bounded, and every omission has a reason

- **Status:** Accepted
- **Date:** 2026-09-11
- **Phase:** 04 — Orchestrator Runtime

## Context

Six minds looking at one day produce more than one day can hold. In the flood
test, 300 Radar finds, 14 open loops, 8 requirements and 4 goals reach the
composer. Showing all of them is not an answer; it is the raw material of an
answer handed over unprocessed.

The obvious failure mode is worse than the obvious problem. A system that
silently truncates produces a plan that is quietly wrong: something important
missing, no way to tell whether it was considered, and no way to debug a
complaint that "it didn't mention the thing that mattered".

## Decision

**Output is budgeted, and every suppression is typed.**

1. Default budget: P0 unlimited, P1 up to 3, P2 up to 3, P3 up to 1, at most 2
   opportunities, at most 12 items in total excluding P0.
2. **P0 is exempt, always.** A budget that can drop a safety warning will
   eventually drop one.
3. Every item removed at any stage produces a `SuppressedItem` with a typed
   reason: `LOW_RELEVANCE`, `DUPLICATE`, `LOW_PRIORITY`, `CONFLICT`,
   `GUARDIAN_BLOCK`, `NOT_ACTIONABLE`, `STALE`, `OVER_CAPACITY`,
   `UNRESOLVED_CONTENTION`.
4. The order is fixed: drop blocked, merge duplicates, arbitrate rivals, apply
   the budget, group into disjoint sections. Budgeting last means what survives
   is what mattered most, not what arrived first.
5. The budget is a constructor argument, so a caller can widen or tighten it.

## Alternatives considered

- **No budget; let the client decide what to show.** Rejected. The suppression
  reasoning would then live in a Flutter view, which is exactly where safety and
  coordination logic must not accumulate — and each future client would
  reimplement it differently.
- **A relevance score with a cutoff instead of per-class allowances.** Rejected
  for now: a single threshold across classes makes a P1 commitment compete
  directly with a P3 find, and tuning one number to keep that from happening
  reinvents the classes badly.
- **Silent truncation.** Rejected outright. It is the specific failure this ADR
  exists to prevent.
- **Making the numbers a finding rather than a default.** Rejected as premature.
  They are stated in `docs/runtime/action-composer.md` as a starting position to
  be revisited once a real person reads a real plan.

## Consequences

**Positive**

- A plan reads as a day: a few things that matter, one or two worth
  considering, the rest held back.
- A complaint is answerable. "Why wasn't X there" has a recorded answer.
- Volume is bounded without anything being lost from the record — suppressed
  items are returned with the result, not discarded.

**Negative / trade-offs**

- The numbers are a guess made without a user. They will be wrong in some
  direction and the ADR should be revisited with evidence rather than defended.
- Carrying every suppressed item makes a result from a flood large. That is the
  cost of explainability; if it becomes a problem the fix is summarising the
  suppression list, not dropping it.
- Per-class allowances mean a day with four genuine P1 commitments shows three
  and suppresses one with `OVER_CAPACITY`. That is intended — but it means the
  budget must be tuned against real days, not invented ones.
