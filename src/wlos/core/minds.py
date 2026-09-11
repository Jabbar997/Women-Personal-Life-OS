from __future__ import annotations

from enum import StrEnum


class Mind(StrEnum):
    """The six specialised minds behind the single assistant.

    The orchestrator coordinates them; it is not a seventh mind and holds no
    business domain of its own.
    """

    NAVIGATOR = "NAVIGATOR"
    RADAR = "RADAR"
    LIFE_ADMIN = "LIFE_ADMIN"
    GUARDIAN = "GUARDIAN"
    READINESS = "READINESS"
    OPERATOR = "OPERATOR"


SIX_MINDS: tuple[Mind, ...] = (
    Mind.NAVIGATOR,
    Mind.RADAR,
    Mind.LIFE_ADMIN,
    Mind.GUARDIAN,
    Mind.READINESS,
    Mind.OPERATOR,
)
