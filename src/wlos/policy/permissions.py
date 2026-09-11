from __future__ import annotations

from enum import IntEnum


class PermissionLevel(IntEnum):
    """How much authority an action needs. Ordered so comparisons are meaningful."""

    A0 = 0
    A1 = 1
    A2 = 2
    A3 = 3

    @property
    def description(self) -> str:
        return _DESCRIPTIONS[self]

    @property
    def is_external(self) -> bool:
        return self >= PermissionLevel.A2

    @property
    def requires_user_confirmation(self) -> bool:
        return self >= PermissionLevel.A2

    @property
    def requires_explicit_confirmation(self) -> bool:
        return self is PermissionLevel.A3

    @property
    def requires_audit(self) -> bool:
        return self is PermissionLevel.A3


_DESCRIPTIONS: dict[PermissionLevel, str] = {
    PermissionLevel.A0: "suggest only",
    PermissionLevel.A1: "internal automatic action",
    PermissionLevel.A2: "external action requiring confirmation",
    PermissionLevel.A3: "high-impact action requiring explicit confirmation and audit",
}
