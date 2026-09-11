# ADR-010 — The Orchestrator is stateless, and orchestration is separate from intelligence

- **Status:** Accepted
- **Date:** 2026-09-11
- **Phase:** 04 — Orchestrator Runtime

## Context

Phase 04 turns a domain architecture into an executable decision runtime. Two
questions had to be settled before writing it, because both are expensive to
change later.

The first is where the runtime keeps its state. An orchestrator that accumulates
state across runs is the natural thing to write and the hard thing to run: it
cannot be served by two instances, it cannot be restarted mid-conversation, and
its behaviour depends on what happened to reach it earlier.

The second is what the runtime is *for*. A coordinator that starts making
judgements — this opportunity is good, this deadline matters more — becomes a
seventh mind with no contract, no authority boundary and no veto over it. That
is precisely the shape the Six-Mind Architecture exists to avoid.

## Decision

**`OrchestratorRuntime` holds no state between runs, and contains no business
reasoning.**

1. A run is `request + current graph → result`. Everything the run needs is
   passed in: the graph, the agents, the policies, the clock. Nothing is read
   from a previous run except through the graph, which is the system of record.
2. Idempotency lives behind an injected `RuntimeLedger` port, not in the
   Orchestrator. A retried client request resolves to the run that already
   happened.
3. The Orchestrator routes, coordinates, enforces, composes and records. Every
   judgement in a result traces to a mind that was permitted to make it.
4. Minds sit behind `AgentRuntime`. The port says nothing about whether a rules
   engine, a model behind a gateway, or a remote service is behind it. Swapping
   the implementation cannot change who may decide what, because the contract
   check runs on the output either way.
5. Deterministic reference implementations exist to prove the machinery. They
   are marked as such and are not the product.

## Alternatives considered

- **A stateful session object.** Natural for a conversation, and it would make
  multi-turn context trivial. Rejected: conversation state belongs in the graph
  or in an explicit session store, not inside the component that enforces
  safety. A safety gate whose answer depends on its own accumulated memory is a
  gate that cannot be reasoned about.
- **Letting the Orchestrator rank and filter on its own judgement.** Tempting,
  because it already sees everything. Rejected: it would own a business domain
  without a contract. The composer does exist and does suppress — but under a
  declared budget and typed reasons, which is mechanism, not judgement.
- **Implementing minds directly, without a port.** Rejected. The port is the
  reason a model can be added later without touching a single authority rule.
- **Putting the reference agents in the test tree.** Considered seriously. They
  live in `application/reference_agents.py` instead so that the contract checks,
  the enforcement path and the port itself are exercised by the same code a real
  implementation will replace. The module docstring says plainly that they are
  not the product.

## Consequences

**Positive**

- The runtime can be served by any instance, restarted freely, and tested by
  calling a function.
- Two runs of the same request agree, which is asserted rather than assumed.
- Adding a model later is a change behind one port.
- No business logic can accumulate in the coordinator without someone noticing:
  it has no place to put it.

**Negative / trade-offs**

- Multi-turn context is not solved by this phase. A conversation that needs to
  remember the previous turn will need an explicit mechanism, and that is a
  design decision deferred rather than made.
- Every run re-projects context for every mind. Correct, and not free. The
  latency constraint is recorded; caching is not built.
- Passing the graph, agents, policies and clock into each run makes call sites
  wordier than a configured singleton would.
