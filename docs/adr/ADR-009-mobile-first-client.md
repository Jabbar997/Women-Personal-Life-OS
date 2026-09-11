# ADR-009 — Mobile-first, with the server as the authority

- **Status:** Accepted
- **Date:** 2026-09-11
- **Phase:** Adversarial validation (before Phase 04)

## Context

The product is a native-feeling iOS and Android application. Flutter is the
likely client. The web is not the primary surface.

That changes what the foundation has to tolerate. A phone is offline sometimes,
stale often, killed by the operating system without warning, and restricted in
what it may do in the background. It also holds a screen that may have been
rendered two hours ago and still shows a Confirm button.

The temptation in a mobile-first product is to move logic into the client
because it feels faster. Doing that with Guardian rules, authorization policy or
conflict resolution would put safety decisions on a device the user controls and
that cannot be trusted to be current.

## Decision

**The client is a presentation, interaction, cache and device-integration layer.
The server holds the domain, and remains the authority.**

```
Mobile App -> Application/API layer -> Orchestrator -> Personal Life Graph -> Six Minds
```

1. The domain depends on no client framework, no HTTP library and no mobile SDK.
   A test fails the build if one appears.
2. The execution gate is only ever given the server's freshly derived action. A
   client's copy of an offer is an input, never a source of truth. Stale terms,
   a lapsed offer and a newer Guardian verdict each stop execution
   independently.
3. Events carry an `EventOrigin` and, from a device, a `ClientRef` with a client
   event id — so a retry over a flaky network is recognised rather than becoming
   a second commitment. Deduplication never keys on message text.
4. `occurred_at` and `recorded_at` stay separate, so delayed and out-of-order
   sync is representable without the log lying about when things happened.
5. Records carry a `revision`, so a server revision and a local revision can be
   compared and a conflict detected rather than resolved by whoever wrote last.
6. Device permissions are capabilities that default to `NOT_REQUESTED`. A denial
   degrades a feature; it never breaks the core.
7. Location defaults to city and area. Precise fields are `S3` and are redacted
   for anything cleared below that, so Radar and Readiness work without GPS.
8. A notification is a decision to tell her, distinct from the domain event that
   prompted it, from the attempt to deliver it, and from her opening it. An
   `S2`-or-above alert is sent with no content, keeping its deep link.

Not built, deliberately: any client, an offline sync engine, a push provider,
deep-link routing, precomputed projections, and mobile security measures.

## Alternatives considered

- **A local-first architecture with the device as the system of record.**
  Rejected. Guardian's veto, payment safety and consent would then live on a
  device, and reconciling six minds' writes across devices is a much harder
  problem than the product needs. The Personal Life Graph stays canonical
  server-side; a device may hold a cache or projection.
- **Building the sync engine now.** Rejected. The requirement was that the
  architecture not *assume* immediate delivery. It does not. Building the engine
  before there is a client would be guessing at its shape.
- **Running agents on the device in the background.** Rejected. Both platforms
  restrict background execution, so a design that depends on it is a design that
  fails silently for most users. Agents and the Orchestrator run server-side;
  device background work is for the narrow tasks the operating system actually
  permits.
- **Letting Flutter consume domain models directly.** Rejected. Domain model,
  API contract and view model stay separate, so internal state is not exposed by
  default and the domain can change without breaking a shipped app.

## Consequences

**Positive**

- Safety logic cannot be shipped inside an app binary and then need extracting.
- A stale screen is harmless: the server revalidates consent, terms, verdict and
  availability before anything happens.
- Offline and duplicate sync are representable today without a sync engine.
- Minimal disclosure reaches the lock screen for free, because sensitivity is
  already in the model.

**Negative / trade-offs**

- Every meaningful action needs the server, so genuinely offline *execution* is
  not available. Capture and local reads can work offline; booking cannot. This
  is the right trade for actions with money and safety attached.
- Latency becomes a real design constraint: opening Today cannot wait on six
  agents, a model and ten connectors. The domain permits caching and
  precomputation; nothing implements them yet.
- Keeping domain, API contract and view model separate is more layers than a
  small app needs, and will feel like overhead until the second client exists.
