# Adversarial Validation V3

Thirty adversarial scenarios plus the mobile stale-action case, run against the
foundation before any runtime is built on it. Executable as
`tests/test_adversarial_*.py`, `tests/test_foundation_gaps.py` and
`tests/test_mobile_readiness.py`.

This pass was not about the happy path. It was about what happens when reality
is messy: late data, contradictory statements, two devices, a clock change, a
withdrawn source, a timeout, and a screen left open for two hours.

## Verdict

**PASS — 58/60.** Five critical gaps were found and closed; none remain.

| # | Scenario | Score |
| --- | --- | --- |
| ADV-01 | Contradictory user statements | 2 |
| ADV-02 | Explicit statement vs behavioural inference | 2 |
| ADV-03 | Out-of-order events | 2 |
| ADV-04 | Duplicate events | 2 |
| ADV-05 | Concurrent updates from two devices | 2 |
| ADV-06 | Timezone boundary | 2 |
| ADV-07 | DST boundary | 2 |
| ADV-08 | Stale connector data | 2 |
| ADV-09 | Correction after execution | 2 |
| ADV-10 | Authorization expiry | 2 |
| ADV-11 | Authorization revocation | 2 |
| ADV-12 | Material terms mutation | 2 |
| ADV-13 | Guardian verdict staleness | 2 |
| ADV-14 | Guardian cannot be spoofed | 2 |
| ADV-15 | Agent privilege escalation | 2 |
| ADV-16 | Context exfiltration | 2 |
| ADV-17 | Relationship privacy | **1** |
| ADV-18 | Withdrawn source | 2 |
| ADV-19 | Source correction cascade | 2 |
| ADV-20 | Conflicting sources | 2 |
| ADV-21 | Low-confidence inference | 2 |
| ADV-22 | Sensitive inference | 2 |
| ADV-23 | Event causation chain | 2 |
| ADV-24 | Causation cycle attack | 2 |
| ADV-25 | Operator retry | 2 |
| ADV-26 | Partial failure | 2 |
| ADV-27 | Undo | 2 |
| ADV-28 | Non-reversible action | 2 |
| ADV-29 | Recommendation flood | **1** |
| ADV-30 | "Forget this" | 2 |

ADV-31 (stale mobile action) is scored separately under mobile readiness: it
passes.

## Critical gaps found and closed

### C-03 — A Guardian verdict could be made by anyone

*ADV-14.* `GuardianAssessment` was an ordinary model. Any caller could
construct `GuardianAssessment(verdict=ALLOW)` and hand it to the execution gate,
which believed it. A `BLOCK` was therefore bypassable by anyone who could call
the gate. **Fixed:** `GuardianAuthority` mints verdicts and is the only thing
that can produce one the gate verifies. Editing a verdict after issue also fails
verification. See ADR-008.

### C-04 — An old `ALLOW` outlived the risk it cleared

*ADV-13.* Nothing tied a verdict to when it was made or retired it when Guardian
reassessed. An `ALLOW` issued before new information arrived stayed usable.
**Fixed:** verdicts carry `assessed_at` and the terms they assessed; the
authority retires a verdict once a newer one exists for the same action, and the
gate refuses a stale one.

### C-05 — Two devices resolved by whichever wrote last

*ADV-05.* `revise_entity` accepted any write. A device marking an open loop
completed and another marking it cancelled resolved silently in favour of the
later packet — a silent destructive overwrite. **Fixed:** records carry a
`revision`; a write built on a stale read is refused with
`ConcurrentModification`, and the conflict policy now reports a deadlock instead
of keeping both claims as though they never disagreed.

### C-06 — A calendar event had no zone

*ADV-06, ADV-07.* Events stored only a UTC instant. A 09:00 appointment in
Riyadh rendered as 09:00 wherever the user happened to be, and a local time in a
DST gap or fold had no defined meaning — an incorrect temporal reading that
reminders and departure times are computed from. **Fixed:** `ZonedInstant`
carries the instant and its IANA zone, refuses naive input, and refuses to guess
at a DST edge unless the caller states a policy. `CalendarEventAttributes` is
anchored to its own zone.

### C-07 — Causation could be corrupted

*ADV-24.* An event could name a cause that had never been published, and walking
a cycle looped forever. **Fixed:** an event cannot be its own cause, the bus
refuses a cause it has not seen (causation points backwards, so a cycle cannot
be built), and the chain walk reports a cycle rather than hanging.

## Known foundation gaps, now closed

| Gap | Resolution |
| --- | --- |
| **G-A** Radar monetary value | `Money` — integer minor units and a currency, never a float, never a number inside a headline. Used by Radar, purchases, subscriptions, requirements and Operator material terms. |
| **G-B** Monetary carry requirement | `REQUIREMENT` entity with `RequirementKind`, distinguishing carrying cash on the day from paying ahead, an entry fee and a purchase. "Bring SAR 40" is an amount, not a task whose title contains a number. |
| **G-C** Required item availability | `RequirementStatus` with `blocks_readiness`, plus `REQUIREMENT_CREATED` and `REQUIREMENT_STATUS_CHANGED` carrying the previous status and the cause. A broken dependency is an event with a reason, not something to re-derive. |

## Important non-critical gaps found and closed

| Finding | Scenario | Resolution |
| --- | --- | --- |
| Record-level sensitivity forced a choice between over-classifying a place and dropping its address. Radar lost the city along with the street. | ADV-16 | Field-level classification and field redaction. See ADR-007. |
| A replayed connector or client submission created a second commitment: deduplication keyed only on a server-minted event id. | ADV-04 | `ClientRef.client_event_id`, `bus.accept()`, and refusal of a replay. Never keyed on message text. |
| An unresolvable contention between two exclusive claims was kept silently, indistinguishable from complementary claims. | ADV-05 | `ConflictResolution.unresolved` and `needs_the_user`. |
| No representation of a timeout, a partial outcome, a revocation or a compensation. | ADV-25 to ADV-28 | `ExecutionState` with `UNKNOWN`, `PARTIALLY_SUCCEEDED`, `REVOKED`, `EXPIRED`, `COMPENSATED`, a transition table, and `ReversibilityClass`. |
| Consent had no shelf life independent of its expiry, so a two-hour-old screen still carried a live offer. | ADV-31 | `ProposedAction.offer_expires_at`. |
| "Stop mentioning this" was conflated with "this was never true". | ADV-30 | `RecordStatus.SUPPRESSED`, distinct from `INVALIDATED` and from any erasure request. |
| No primitive stopped a stale connector reading from overwriting what the user confirmed. | ADV-08, ADV-20 | `SourceAuthorityPolicy`: lower authority never overwrites higher, equal authority resolves by recency, and a refusal is a conflict to surface. |

## Unresolved risks

These are stated rather than hidden. None is a critical gap, and none blocks the
runtime phase.

- **Guardian's authority is a process capability, not a cryptographic proof.**
  Anything holding a reference to the authority object can mint a verdict the
  gate believes. Within one process that is the correct boundary and it is
  enforced and tested; a real guarantee needs Guardian as its own service. This
  is recorded in ADR-008 as the condition under which the decision should be
  revisited.
- **Semantic inference leakage is not structurally preventable** (ADV-17, scored
  1). The graph guarantees that no edge reaches a record the mind was not given,
  and that nothing above its ceiling arrives. It cannot know that an S1 interest
  may imply an S3 condition. Mitigating that is a Guardian policy question at
  runtime, not a schema one.
- **Relevance is not a first-class field** (ADV-29, scored 1). Claims carry
  priority, confidence and decision state, and deadlines carry urgency through
  temporal markers, which is enough for the Orchestrator to rank 300 finds
  without the domain discarding anything. A dedicated relevance score may be
  wanted once ranking is real; adding one now would be guessing at its shape.
- **Correction does not cascade automatically.** A corrected event keeps a
  stable id and full history, so dependents can be recomputed, and the causation
  chain says what came from what. Actually recomputing them is runtime work.
- **The in-memory graph is not a database.** No indexes, no durability, no
  cross-process concurrency. `revision` makes optimistic concurrency
  *representable*; enforcing it across processes is a storage concern.

## Mobile readiness

The product is a native-feeling iOS and Android application with Flutter as the
likely client. No client work was done here; this checks the foundation does not
prevent one.

| Requirement | Status |
| --- | --- |
| Domain is framework-independent | Yes. A test fails the build if any module imports a client, HTTP or mobile framework. |
| Server remains the authority | Yes. The gate is only ever given the server's freshly derived action; a client's copy is an input. |
| Stale mobile actions cannot bypass policy | Yes. ADV-31: changed terms, a lapsed offer and a new Guardian verdict each stop execution independently. |
| Events tolerate delayed and out-of-order sync | Yes. `occurred_at` and `recorded_at` are separate, `arrived_late` is explicit, and the log can be read in either order. |
| Duplicate sync is safe | Yes. `client_event_id` deduplication and `bus.accept()`. |
| Capture supports non-text sources | Yes. `CaptureKind` covers voice, photo, screenshot, files and the share sheet; `MediaRef` points at media the domain never holds. |
| Sensitive data can be projected minimally | Yes. Field-level redaction, and a notification policy that sends an S2+ alert with no content. |
| Stable resource ids for deep links | Yes. Every entity, event and notification has a stable id; a suppressed notification keeps its deep link. |
| No continuous connectivity assumed | Yes. Nothing in the domain requires a reachable server at the moment of an action. |
| Permissions treated as capabilities | Yes. `CapabilitySet` defaults every permission to `NOT_REQUESTED`; a denial degrades a feature and cannot raise. |
| Location works without precise GPS | Yes. City and area are the default; precise fields are S3 and are redacted for anything cleared below that. |
| Agents runnable server-side | Yes. No contract depends on a device being awake. |

**Recorded as a runtime constraint, not built:** opening Today must not require
six agents, a model and ten connectors before anything renders. The domain
permits precomputed projections, a cached Today state, incremental
recomputation and background server processing. None of these exist yet.

## What held up without changes

- Provenance and confidence: a declaration stays certain, an inference stays
  probabilistic, and an inferential source claiming certainty is still refused.
- Authority boundaries: Radar cannot write health data, authorize anything,
  execute anything, or read cycle history even when it asks for it directly.
- The material-terms binding from ADR-006 held against every single-field
  mutation tried: date, time, price, merchant, quantity, target and location.
- History: no revision, expiry, suppression or invalidation lost a prior version.
- Causation: every chain reconstructed to a single root under one correlation id.
