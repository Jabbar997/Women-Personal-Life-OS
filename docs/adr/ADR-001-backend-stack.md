# ADR-001 — Backend and domain core stack

- Status: accepted
- Date: 2026-09-11
- Phase: 01 — Foundation Layer

## Context

The foundation layer must express a rich domain model (Personal Life Graph,
domain events, agent contracts, policy primitives) with strong typing, clean
JSON interoperability, easy testing, and a path to an API, background jobs, an AI
gateway, connectors and a mobile client. Only one backend language may be used in
this phase.

## Decision

**Python 3.13 + Pydantic v2 for the domain core, with FastAPI reserved for the
API layer when that phase begins.**

The domain core's only runtime dependency is Pydantic. FastAPI is a documented
direction, not an installed dependency, because this phase builds no API.

## Alternatives considered

**Node.js + TypeScript + Zod.** Strong structural typing, excellent JSON
ergonomics, and one language across a future web client. Rejected for this phase:
TypeScript's types are erased at runtime, so domain invariants (provenance versus
confidence, sensitivity floors, temporal ordering) need a parallel validation
layer, and the planned AI/ML and data work around cycle and behavioural modelling
is better served by Python. No web frontend exists to unify with.

**Go.** Excellent for services and concurrency, weaker for expressive domain
modelling with optional fields, unions and validation; more ceremony per model.

**Kotlin / JVM.** Strong modelling and mature ecosystem, but a heavier toolchain
than this phase justifies and a smaller overlap with the intended AI work.

**Python with dataclasses instead of Pydantic.** Fewer dependencies, but
validation, JSON round-tripping and schema export would all be hand-written —
exactly the invariants this phase exists to encode.

## Consequences

Positive:

- Runtime-enforced domain invariants: a naive datetime, a certain AI inference,
  or a downgraded sensitivity floor fails at construction, not in review.
- `mypy --strict` runs clean over the whole package, tests included.
- JSON serialization is native, so the event envelope and payload registry
  round-trip without bespoke codecs.
- A straight path to FastAPI (Pydantic models become request/response schemas)
  and to schema export for a future mobile client.

Negative / accepted trade-offs:

- Python's static typing is weaker than TypeScript's or Kotlin's; strict mypy is
  mandatory, not optional, and is enforced in `scripts/check.sh`.
- Pydantic validation costs runtime cycles. Acceptable: these are personal-scale
  models, and the correctness guarantees are the point.
- If a web frontend later dominates the work, the stack will need a boundary
  (OpenAPI/JSON schema) rather than shared types. That boundary is planned anyway
  for the mobile client.
