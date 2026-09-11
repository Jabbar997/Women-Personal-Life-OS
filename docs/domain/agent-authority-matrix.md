# Agent Authority Matrix

Generated from `AGENT_CONTRACTS` by `scripts/generate_authority_matrix.py`.
Do not edit by hand: `tests/test_agent_authority.py` regenerates this file and
fails if it disagrees with the contracts in code.

## Legend

```
R = Read          W = Write         P = Propose (RECOMMEND authority)
V = Veto          X = Execute       - = No access
```

Write implies read. `V` marks the mind that can stop an action outright.
`X` marks the only mind that may act on the world.

## Objects

| Domain | Object | Navigator | Radar | Life_Admin | Guardian | Readiness | Operator |
| --- | --- | --- | --- | --- | --- | --- | --- |
| APPEARANCE | `INGREDIENT` | - | - | - | RV | - | - |
| APPEARANCE | `WARDROBE_ITEM` | - | - | - | - | RP | - |
| BODY | `BODY_SIGNAL` | - | - | - | RV | RP | - |
| BODY | `CYCLE_STATE` | - | - | - | RV | RP | - |
| BODY | `HEALTH_CONDITION` | - | - | - | RV | - | - |
| BODY | `PREGNANCY_STATE` | - | - | - | RV | RP | - |
| DIRECTION | `GOAL` | RP | RP | RP | - | - | - |
| DIRECTION | `MILESTONE` | WRP | - | - | - | - | - |
| DIRECTION | `PRIORITY` | WRP | - | - | - | - | - |
| HOME | `AVAILABILITY_STATE` | - | - | - | - | RP | - |
| HOME | `DOCUMENT` | - | - | WRP | RV | RP | RP |
| HOME | `PRODUCT` | - | - | RP | RV | RP | RP |
| IDENTITY | `BEHAVIOR_PATTERN` | RP | RP | - | - | - | - |
| IDENTITY | `INTEREST` | - | RP | - | - | - | - |
| LEARNING | `COURSE` | RP | - | - | - | - | - |
| LEARNING | `EDUCATION_PROGRAM` | RP | - | - | - | - | - |
| LEARNING | `SKILL` | RP | - | - | - | - | - |
| MONEY | `MONEY_CONTEXT` | - | - | - | RV | - | - |
| MONEY | `PURCHASE` | - | - | RP | RV | - | RP |
| MONEY | `SUBSCRIPTION` | - | - | RP | RV | - | RP |
| SOCIAL | `PERSON` | RP | RP | RP | RV | - | RP |
| TIME | `CALENDAR_EVENT` | RP | RP | RP | RV | RP | WRX |
| TIME | `COMMITMENT` | RP | - | WRP | RV | RP | WRX |
| TIME | `DEADLINE` | RP | - | WRP | - | - | - |
| TIME | `HABIT` | - | - | - | - | - | - |
| TIME | `REQUIREMENT` | - | - | - | - | - | - |
| TIME | `ROUTINE` | - | - | - | - | WRP | - |
| TIME | `TASK` | RP | - | WRP | - | WRP | WRX |
| WORK | `CAREER_ROLE` | RP | RP | - | - | - | - |
| WORLD | `PLACE` | - | RP | - | - | RP | - |
| WORLD | `RADAR_ITEM` | RP | WRP | - | - | - | - |

## Authority summary

| Capability | Navigator | Radar | Life_Admin | Guardian | Readiness | Operator |
| --- | --- | --- | --- | --- | --- | --- |
| Max decision state | RECOMMEND | RECOMMEND | RECOMMEND | SURFACE | RECOMMEND | ACT |
| Max permission level | A0 | A0 | A0 | A0 | A0 | A3 |
| Sensitivity ceiling | S2 | S2 | S3 | S3 | S3 | S3 |
| Holds veto | no | no | no | yes | no | no |
| May execute | no | no | no | no | no | yes |
| Writable objects | 2 | 1 | 4 | 0 | 2 | 3 |
| Readable objects | 14 | 8 | 10 | 13 | 12 | 8 |

## Invariants this matrix must always satisfy

- Exactly one `V` column: Guardian, and Guardian writes nothing.
- Exactly one `X` column: the Operator.
- No mind writes an object outside its contract's `writes`.
- The Orchestrator appears nowhere: it owns no object and no domain.
