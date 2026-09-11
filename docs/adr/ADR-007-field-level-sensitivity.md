# ADR-007 — Sensitivity is classified per field, not only per record

- **Status:** Accepted
- **Date:** 2026-09-11
- **Phase:** Adversarial validation (before Phase 04)

## Context

Sensitivity was a property of a whole record. A place looks like this:

```
Place { city: "Al Ahsa", area: "Al Hofuf", street_address: "...", coordinates: ... }
```

The city is the sort of thing a recommendation needs. The street address is the
sort of thing that locates a woman precisely. Under record-level classification
there were only two options, and both were wrong:

- Classify the record `S2` and the address leaks to every mind cleared to `S2`.
- Classify the record `S3` and Radar loses the city as well, so it cannot rank
  anything nearby.

ADR-003 had already added a floor (`minimum_sensitivity`) that forced the second
option, which was safe but lossy. ADV-16 asked whether a mind allowed to read
the city receives the street with it, and made the cost of over-redaction
concrete: minimization that deletes the useful part is not minimization, it is
breakage, and it pushes designers toward storing the address somewhere less
careful.

## Decision

**An attributes model declares which of its fields are sharper than its type's
default, and projection redacts fields rather than whole records.**

1. `EntityAttributes.SENSITIVE_FIELDS` maps a field name to its level.
2. `sensitivity_floor()` returns the highest level among *populated* sensitive
   fields. An entity whose declared sensitivity is below that floor cannot be
   constructed, so an address can never be stored on an `S1` place.
3. `redacted_to(ceiling)` returns the attributes with the fields above the
   ceiling dropped, and the names dropped — never their values.
4. `Entity.redacted_to(ceiling)` rebuilds the record at the sensitivity of what
   actually survives, and records `redacted_fields`.
5. `project_context` tries the whole record first and falls back to a redacted
   one. If nothing readable survives, the record is withheld entirely.

## Alternatives considered

- **Split every mixed record into two entities.** A public "area" place and a
  private "address" place. This works and needs no new machinery, which is why
  it was the previous answer. Rejected as the general rule: it doubles the
  entity count for every mixed-sensitivity type, splits one real-world thing
  across two ids, and relies on every author remembering to do it.
- **Field-level sensitivity everywhere, on every field.** Rejected as
  overengineering. Most fields sit at their type's default; only the exceptions
  need declaring, and declaring only exceptions keeps the list readable.
- **Redact at the API layer instead.** Rejected. The leak this prevents is
  between minds, which happens below any API, and a boundary enforced only at
  the edge is not enforced.
- **Encrypt sensitive fields at rest.** Orthogonal. Encryption protects the
  store; this protects the projection. A later phase may well do both.

## Consequences

**Positive**

- Radar gets the city and never the street, from one record.
- Over-classification stops being the price of safety, which removes the
  incentive to model around the rule.
- `redacted_fields` makes it visible to a mind that something was withheld,
  without revealing what.
- The floor invariant means under-classification is impossible by construction,
  not by review.

**Negative / trade-offs**

- A sensitive field must be optional so it can be dropped. That is a real
  constraint on schema design and is why `street_address` and the coordinates
  are nullable.
- A redacted record and a record that genuinely has no address are
  indistinguishable by shape alone; `redacted_fields` is what tells them apart,
  and consumers that ignore it will conflate them.
- Sensitivity is now declared in two places — the type default and the field
  map. The floor invariant keeps them consistent, but it is more to hold in
  mind than one number per record.
