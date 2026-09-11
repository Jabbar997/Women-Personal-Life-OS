# ADR-005 — Agent contract boundaries and where authority lives

- Status: accepted
- Date: 2026-09-11
- Phase: 01 — Foundation Layer

## Context

Six minds share one graph and one user. Without explicit boundaries, Radar starts
booking things, Life Admin starts deciding what matters, and Guardian becomes
advisory. The architecture requires that AI proposes while rules constrain,
policies authorize and only the Operator executes.

## Decision

- Every mind declares a machine-readable `AgentContract`: reads, writes, decision
  authority, permission ceiling, forbidden actions, events consumed and produced,
  required policies.
- `assert_within_contract()` enforces the contract on output rather than trusting
  the implementation.
- Decision states are exactly `IGNORE`, `SURFACE`, `RECOMMEND`, `ACT`, and only
  the Operator may hold `ACT`.
- Guardian's verdict types live in the **policy** layer, not inside the Guardian
  mind, and `ExecutionPolicy` consumes them.
- The Operator executes only through `ExecutionPolicy`, which refuses A2/A3
  actions without a valid authorization and refuses anything Guardian blocked.
- Conflicts between minds resolve through a `ConflictResolutionPolicy` of ordered
  rules with a configurable mind ranking as a fallback, not a hard-coded chain.
- Minds receive a policy-filtered `ContextView`, never the raw repository.

## Alternatives considered

**Contracts as documentation only.** Rejected: an unenforced boundary is a
comment. Making the contract data means a violation is a test failure.

**Guardian as a mind the orchestrator may consult.** Rejected: a veto that a
caller can forget to ask for is not a veto. Putting the verdict in the policy
gate makes the gate authoritative.

**A fixed precedence chain (Guardian > Navigator > Life Admin > Radar).**
Rejected as the whole mechanism: it is the right default, but real situations
(a P0 safety claim from any mind, a binding commitment versus an opportunity)
need rules. The chain survives as the fallback ranking.

**Letting each mind emit free-text output for the assistant to compose.**
Rejected: unstructured output cannot be checked against a contract, aggregated by
priority, or audited.

## Consequences

Positive:

- A mind cannot silently exceed its authority; the violation raises
  `ContractViolationError`.
- The "no silent execution" rule is enforced in one place and tested directly.
- New minds, or new conflict situations, are added as contracts and rules rather
  than by editing a chain of conditionals.
- Contracts document the system precisely enough that implementations can be
  written later without renegotiating boundaries.

Negative / accepted trade-offs:

- Extra ceremony: adding an event to a mind means updating its contract. That is
  the intended friction.
- Contract enforcement is at the output boundary, so a mind could still read more
  than it needs in its own process; the context projection, not the contract, is
  what constrains reads.
- Structured output is more work than free text and will need a composition layer
  before anything user-facing ships.
