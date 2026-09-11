from __future__ import annotations

from enum import IntEnum


class Sensitivity(IntEnum):
    """How exposed a piece of the Personal Life Graph may be.

    Ordered on purpose: a consumer's clearance is compared against the
    sensitivity of what it asks for. Known is not the same as shown.
    """

    S0 = 0
    S1 = 1
    S2 = 2
    S3 = 3

    @property
    def label(self) -> str:
        return _LABELS[self]

    def is_readable_at(self, clearance: Sensitivity) -> bool:
        return self <= clearance


_LABELS: dict[Sensitivity, str] = {
    Sensitivity.S0: "public-like",
    Sensitivity.S1: "personal",
    Sensitivity.S2: "sensitive",
    Sensitivity.S3: "highly-sensitive",
}
