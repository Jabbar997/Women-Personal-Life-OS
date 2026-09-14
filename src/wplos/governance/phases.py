"""Expiry counted in phases, because that is what this repository plans in.

A wall-clock date would turn the quality gate red on a Tuesday for a reason
nobody can act on that morning, and would tempt whoever is blocked into moving
the date rather than answering the question. A phase is the unit the brief
already uses, it is declared in one place, and a test reads that declaration
back out of ``AGENTS.md`` so the constant here cannot drift away from it.
"""

from enum import StrEnum


class Phase(StrEnum):
    """The ordered vocabulary an exemption expires against.

    Numbers past the current phase exist so an exemption can name a deadline
    that has not arrived yet. They are a scale, not a roadmap: nothing here
    says what any later phase will contain.
    """

    PHASE_01 = "PHASE_01"
    PHASE_02 = "PHASE_02"
    PHASE_03 = "PHASE_03"
    PHASE_04 = "PHASE_04"
    PHASE_05 = "PHASE_05"
    PHASE_06 = "PHASE_06"
    PHASE_07 = "PHASE_07"
    PHASE_08 = "PHASE_08"

    @property
    def ordinal(self) -> int:
        return _ORDER[self]

    def is_after(self, other: "Phase") -> bool:
        return self.ordinal > other.ordinal


_ORDER: dict[Phase, int] = {phase: index for index, phase in enumerate(Phase)}

CURRENT_PHASE = Phase.PHASE_05
"""The phase the repository is in. ``AGENTS.md`` is the source; a test compares."""
