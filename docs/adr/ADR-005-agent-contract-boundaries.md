# ADR-005 — Agent contracts before agent implementations

- **Status:** Accepted
- **Date:** 2026-09-11
- **Phase:** 01 — Domain Foundation

## Context

Six minds will eventually be backed by a language model through an AI gateway.
The risk is that authority boundaries — who may read what, who may decide what,
who may execute — end up implied by prompts and scattered checks, where they
cannot be tested and quietly drift.

## Decision

**Define every mind as an explicit, validated `AgentContract` and build no agent
implementation in this phase.**

1. A contract declares mission, reads, writes, memory reads, decision authority,
   maximum permission level, sensitivity ceiling, events consumed and produced,
   required policies, forbidden actions and veto.
2. Boundaries are validated by the model, not by convention:
   - only Guardian may hold a veto;
   - only the Operator may hold `ACT` or an executable permission level.
3. `reads` is executable: `contract.context_scope(purpose)` produces the
   `ContextScope` that `project_context` enforces. A mind cannot read outside its
   contract because it never gets the data.
4. Outputs are structured — `AgentDecision`, `AgentRecommendation`,
   `AgentEvidence`, `AgentOutput` — never a string. An `ACT` recommendation
   without a `ProposedAction` is rejected.
5. The Orchestrator is a coordinator with a separate contract type, no business
   domain, and no power to override Guardian. `ROUTING_TABLE` fixes ordering, and
   a test asserts Guardian precedes the Operator in every executing route.
6. Conflict resolution is an ordered list of replaceable rules keyed on a claim's
   nature, not a hard-coded chain of mind names.

## Alternatives considered

- **Implement the minds now with a provider behind them.** Rejected. It would
  couple the domain to a provider before the boundaries are settled, and this
  phase explicitly forbids it.
- **Contracts as documentation only.** Rejected. A boundary that is not
  executable is a boundary that erodes.
- **A single `Agent` base class with permissions as method overrides.** Rejected.
  Authority would live in code paths rather than in data that can be inspected,
  diffed and tested.
- **A fixed precedence chain for conflicts.** Rejected as too rigid; the
  precedence in the architecture is stated as a usual case, not a law.

## Consequences

**Positive**

- Authority is inspectable data. `AGENT_CONTRACTS` is the whole truth about who
  may do what.
- An implementation added later cannot exceed its contract without failing a
  test.
- Guardian's veto and the Operator's authorization gate are enforced in the
  policy layer, below any mind.

**Negative / trade-offs**

- Contracts written before implementations will need revision once the minds are
  real. Revising a contract is a visible, reviewable change — which is the point.
- Some contract fields (`events_consumed`, `events_produced`) are currently
  declarations with no runtime enforcement. Enforcing them is a candidate for the
  phase that implements the minds.
