# Foundation Validation 01 — Life Simulation

Ten real-life scenarios run against the Phase 01 foundation, to break it before
anything is built on top. Executable as `tests/test_scenarios_life.py`.

## Verdict

**PASS — 196/200.** Two critical gaps were found and closed; none remain.

| # | Scenario | Score |
| --- | --- | --- |
| 01 | Event preparation — wedding, dress at the laundry | 19 |
| 02 | School message capture | 19 |
| 03 | Purchase and return window | 20 |
| 04 | Career goal meets a Radar find | 19 |
| 05 | Conflicting commitments | 20 |
| 06 | Health and product safety | 20 |
| 07 | Behavioural learning | 20 |
| 08 | Operator authority | 20 |
| 09 | Privacy and context minimization | 20 |
| 10 | One input, several minds | 19 |

## Critical gaps found

### C-01 — Authorization was not bound to what was agreed

*Scenario 08-D.* An authorization bound only `action_id`. Consent to *Pilates
19:00 for SAR 100* was spent on *20:00 for SAR 180*.
**Type:** authority / policy. **Impact:** the Operator could execute terms the
user never saw. **Fixed:** see ADR-006.

### C-02 — A Guardian verdict was not bound to the action it assessed

*Scenario 08-C.* `subject_action_id` was never compared to the action, so an
`ALLOW` for an unrelated action satisfied the gate and a `BLOCK` could be routed
around. **Type:** authority. **Impact:** Guardian veto bypass. **Fixed:** the
gate now requires an assessment of this action.

## Other gaps found

| # | Scenario | Type | Finding | Resolution |
| --- | --- | --- | --- | --- |
| G-03 | 07 | Temporal | `is_active_at` mixed current status with past validity, so closing a record hid it from as-of queries and from `graph.entities(at=…)`. | `INVALIDATED` alone is retroactive; `superseded()` added for "no longer true". |
| G-04 | 10 | Policy | Arbitration treated every claim on a subject as exclusive, so Readiness preparation was deleted by the commitment it served. | `ClaimNature.is_exclusive`; non-contending claims coexist. |
| G-05 | 04 | Schema | `SUPPORTED_BY` could not connect a `GOAL` to a `RADAR_ITEM` — the goal-fit link the Radar→Navigator handoff depends on. | `RADAR_ITEM` added to the spec. |
| G-06 | — | Contract | Four of nine canonical handoffs were disconnected: the target did not consume what the source produced. | Contracts reconnected; a test now fails on any disconnected handoff. |
| G-07 | 05 | Schema | A clash between two commitments had no durable representation, only a transient event. | `CONFLICTS_WITH`, symmetric. |
| G-08 | 07 | Event | No event recorded that a recommendation was offered, ignored, accepted or dismissed, so a derived preference had no evidence. | Recommendation lifecycle events added. |
| G-09 | 03 | Event | A purchase arriving, and its return window closing, produced no event. | `PURCHASE_RECORDED`, `RETURN_WINDOW_CLOSING`. |
| G-10 | 09 | Privacy | Sensitivity is per record, so an exact address either over-classified the whole place or was dropped. | `minimum_sensitivity()` raises a record's floor; an address forces `S3`. |
| G-11 | 09 | Privacy | Relationships were admitted to a context with need-to-know hard-coded true. | Need-to-know now derives from both endpoint types. |
| G-12 | 03 | Schema | `PurchaseAttributes.amount_minor` was required, forcing a fabricated `0` for a purchase captured in chat. | Optional; `None` means unknown. |
| G-13 | 02 | Schema | No wardrobe category for sportswear. | `ACTIVEWEAR`. |

## Known gaps not patched

- **Composition has no domain type.** Scenario 10 assembles one answer from
  surviving claims, but there is no `ComposedResponse`. This is Orchestrator
  runtime work and belongs to Phase 02, not to a validation pass.
- **Money as a requirement.** "Bring SAR 40" is modelled as a `TASK`. It works
  and stays an open loop, but a required amount is not a first-class carry item.
- **Radar price.** A find's price lives in its headline text, not a typed field.
  Fine while Radar cannot act on price; revisit when it can.
- **Redaction under-reporting.** Types outside a scope are never retrieved, so
  they produce no redaction record. This is correct minimization — the withheld
  set is not itself leaked — but it means the redaction list is not a complete
  audit of everything withheld.

## What held up without changes

- Provenance and confidence: a declaration stays certain, an inference stays
  probabilistic, and an inferential source cannot claim certainty.
- Entity history: revisions keep every previous version with `created_at`
  intact.
- Three clocks: record time, validity and domain time never collapsed.
- Radar's context minimization: cycle, pregnancy and health never entered its
  candidate set, and the `S3` home address was refused by its ceiling.
- Guardian severity: the strictest finding decides, with no averaging.
- Causation: every scenario's events reconstruct back to the sentence that
  started them, under one correlation id.
