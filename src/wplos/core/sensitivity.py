from enum import StrEnum


class SensitivityLevel(StrEnum):
    """How much damage disclosure of a record would do.

    S0 non-sensitive, S1 personal, S2 sensitive, S3 highly sensitive.
    Cycle, pregnancy, health and payment data are S3 by default.
    """

    S0 = "S0"
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"

    @property
    def rank(self) -> int:
        return _RANKS[self]

    def dominates(self, other: "SensitivityLevel") -> bool:
        return self.rank >= other.rank

    @classmethod
    def highest(cls, levels: "tuple[SensitivityLevel, ...]") -> "SensitivityLevel":
        return max(levels, key=lambda level: level.rank, default=cls.S0)


_RANKS: dict[SensitivityLevel, int] = {
    SensitivityLevel.S0: 0,
    SensitivityLevel.S1: 1,
    SensitivityLevel.S2: 2,
    SensitivityLevel.S3: 3,
}
