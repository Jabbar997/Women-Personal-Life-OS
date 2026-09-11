# ADR-001 — Backend and core stack

- **Status:** Accepted
- **Date:** 2026-09-11
- **Phase:** 01 — Domain Foundation

## Context

The foundation layer needs a single backend language for the domain core. The
criteria set for this decision were: strong type safety, clear domain modelling,
JSON and schema interoperability, easy testing, suitability for a later API,
suitability for AI orchestration, suitability for an event-driven architecture,
and easy integration with a Flutter or other mobile client later.

The default proposal was Python 3.13 with FastAPI and Pydantic v2, but it was to
be justified rather than assumed, with TypeScript (Node.js + Zod) as the
realistic alternative.

## Decision

**Python 3.13 with Pydantic v2 for the domain core. FastAPI is the intended HTTP
layer for a later phase and is not a dependency today.**

One backend language. No second runtime in this phase.

## Alternatives considered

### Node.js + TypeScript + Zod

Genuinely competitive. Structural typing is excellent, Zod gives runtime
validation with inferred static types, JSON is native, and a single language
could later cover both API and tooling.

Rejected for this core because:

- Discriminated unions of domain records are ergonomic in Zod but the *runtime*
  object model is plain data. Pydantic gives typed records with behaviour
  (`revised()`, `expired()`, `invalidated()`) and validation on the same class,
  which suits a domain built around record invariants.
- The AI orchestration ecosystem this system will eventually sit beside is
  Python-first, and the gateway integration is the one place where library
  gravity matters.
- Rules that must never be delegated to a model — cycle arithmetic, date
  handling, scheduling conflicts — are a better fit for Python's datetime and
  numeric ecosystem than for JavaScript's.

### Python + FastAPI installed now

Rejected for this phase only. Phase 01 exposes no HTTP surface, so adding
FastAPI would be an unused dependency contradicting "no dependencies without
need". The domain is written to be transport-agnostic, so adding FastAPI later
is additive: the API layer will import domain models, not the other way round.

### Go, Rust, Kotlin

Rejected. Strong typing and performance, but heavier domain modelling for a
schema-dense, evolving life model, and weaker fit with the eventual AI gateway
work.

## Consequences

**Positive**

- One language, one runtime, one test story.
- Pydantic v2 gives validation, JSON schema and serialization from the same
  models, which the Personal Life Graph and the event envelope both rely on.
- `mypy --strict` with `disallow_any_explicit` makes "no `dict[str, Any]`"
  enforceable rather than aspirational.

**Negative / trade-offs**

- Python's typing is gradual; strictness is a discipline the configuration must
  keep enforcing, not a language guarantee.
- Sharing types with a Flutter client means generating schemas from Pydantic
  rather than sharing source. Acceptable: the wire contract will be JSON Schema.
- A future high-throughput component may want a different runtime. That would be
  a separate service and a separate ADR, not a second language inside this core.

## Constraints this decision carries

- Runtime dependencies are `pydantic` and nothing else, enforced by a test.
- No provider SDK may be imported anywhere in `src/wplos`, enforced by a test.
- Python 3.13 minimum.
