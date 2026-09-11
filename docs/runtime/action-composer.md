# Action Composer

Many internal outputs, one coordinated plan. If Navigator produces 2 items,
Radar 5, Life Admin 7, Readiness 6 and Guardian 2, the answer is not twenty-two
items — twenty-two items is not a plan, it is a list.

The composer writes no prose. It produces `ComposedActionPlan`, an application
model with no copy, no layout and no assumption about a screen.

## Order of operations

The order is the design. Each step depends on the last having already happened.

1. **Drop what cannot happen.** Guardian-blocked actions leave first, so nothing
   downstream can count them, rank them or budget around them. `IGNORE`
   decisions leave here too.
2. **Merge what is the same.** Two minds naming the same thing in the same way
   are saying one thing; the surviving item cites both.
   Deduplication keys on the title *and the nature of the claim*: a commitment
   and an opportunity that happen to share a title are not duplicates, they are
   rivals, and merging them would let a find quietly absorb a commitment.
3. **Arbitrate what competes.** The conflict policy from the domain decides.
   When two exclusive claims cannot be separated, the deadlock is reported as
   `UNRESOLVED_CONTENTION` rather than resolved by arrival order.
4. **Apply the budget.** Last, so what survives is what mattered most rather
   than what arrived first.
5. **Group into sections.** Disjoint by construction: an item appears once. A
   plan listing the same thing under "now" and again under "must handle" reads
   as two obligations.

## Sections

```
primary_focus   one thing, from Navigator
now             the single most pressing item
must_handle     the rest of P0/P1
next_up         P2
prepare         Readiness preparation
carry           things to take
opportunities   Radar finds
warnings        Guardian concerns
optional        P3
authorization_requests
suppressed
```

## Budget

| Class | Allowance |
| --- | --- |
| P0 | unlimited — safety is never budgeted away |
| P1 | 3 |
| P2 | 3 |
| P3 | 1 |
| opportunities | 2 |
| total (excluding P0) | 12 |

These numbers are a starting position, not a finding. They were chosen so that a
day reads as a day: a few things that matter, one or two worth considering, and
everything else held back with a reason. They are configurable per run and will
want revisiting once real plans are read by a real person. What is *not*
negotiable is that P0 is exempt: a budget that can drop a safety warning is a
budget that will eventually drop one.

## Suppression

Nothing is dropped silently. Every suppressed item carries a typed reason:

```
LOW_RELEVANCE · DUPLICATE · LOW_PRIORITY · CONFLICT · GUARDIAN_BLOCK
NOT_ACTIONABLE · STALE · OVER_CAPACITY · UNRESOLVED_CONTENTION
```

This is what makes a plan that feels wrong explainable rather than guessable,
and it is the mechanism behind Known ≠ Shown at runtime: the system knowing
something and the system saying it are separate, and the gap between them is
recorded.

## Priority

Deterministic and replaceable. Factors — urgency, importance, goal alignment,
risk, timing, feasibility, confidence — are weighted into a score used for
ordering *within* a class; the class itself comes from explicit rules:

- a Guardian block or a safety warning is P0;
- an infeasible item is demoted no further up than P2, because Guardian allowing
  something does not make it possible;
- otherwise the mind's own priority stands.

No model ranks a life here. The weights are visible so a wrong answer can be
argued with.

## Authorization

| Level | What the composer does |
| --- | --- |
| A0 | stays in the plan as a suggestion; never becomes executable |
| A1 | runs, through the executor port, and emits Operator events |
| A2 | becomes an `AuthorizationRequest`; nothing runs |
| A3 | becomes a `HighImpactAuthorizationRequest` carrying the material terms and Guardian's findings; nothing runs |

An action with no Guardian verdict does not execute, and neither does one where
Guardian could not be reached.
