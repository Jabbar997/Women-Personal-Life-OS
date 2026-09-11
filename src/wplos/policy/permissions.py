from enum import StrEnum


class PermissionLevel(StrEnum):
    """How much authority an action needs before the Operator may run it.

    A0 suggest only, A1 internal automatic, A2 external with confirmation,
    A3 high-impact with explicit confirmation and an audit record.
    """

    A0 = "A0"
    A1 = "A1"
    A2 = "A2"
    A3 = "A3"

    @property
    def rank(self) -> int:
        return _RANKS[self]

    @property
    def is_executable(self) -> bool:
        return self is not PermissionLevel.A0

    @property
    def requires_authorization(self) -> bool:
        return self in {PermissionLevel.A2, PermissionLevel.A3}

    @property
    def requires_explicit_confirmation(self) -> bool:
        return self is PermissionLevel.A3

    @property
    def requires_audit_trail(self) -> bool:
        return self is PermissionLevel.A3


_RANKS: dict[PermissionLevel, int] = {
    PermissionLevel.A0: 0,
    PermissionLevel.A1: 1,
    PermissionLevel.A2: 2,
    PermissionLevel.A3: 3,
}


class ActionDomain(StrEnum):
    """Domains whose actions can never be executed silently."""

    INTERNAL = "INTERNAL"
    COMMUNICATION = "COMMUNICATION"
    SENSITIVE_COMMUNICATION = "SENSITIVE_COMMUNICATION"
    PURCHASE = "PURCHASE"
    PAYMENT = "PAYMENT"
    LEGAL = "LEGAL"
    MEDICAL = "MEDICAL"
    DATA_SHARING = "DATA_SHARING"
    DESTRUCTIVE_EXTERNAL = "DESTRUCTIVE_EXTERNAL"
    SCHEDULING = "SCHEDULING"


NEVER_SILENT: frozenset[ActionDomain] = frozenset(
    {
        ActionDomain.PAYMENT,
        ActionDomain.PURCHASE,
        ActionDomain.LEGAL,
        ActionDomain.MEDICAL,
        ActionDomain.SENSITIVE_COMMUNICATION,
        ActionDomain.DATA_SHARING,
        ActionDomain.DESTRUCTIVE_EXTERNAL,
    }
)

MINIMUM_PERMISSION: dict[ActionDomain, PermissionLevel] = {
    ActionDomain.INTERNAL: PermissionLevel.A1,
    ActionDomain.SCHEDULING: PermissionLevel.A2,
    ActionDomain.COMMUNICATION: PermissionLevel.A2,
    ActionDomain.SENSITIVE_COMMUNICATION: PermissionLevel.A3,
    ActionDomain.PURCHASE: PermissionLevel.A3,
    ActionDomain.PAYMENT: PermissionLevel.A3,
    ActionDomain.LEGAL: PermissionLevel.A3,
    ActionDomain.MEDICAL: PermissionLevel.A3,
    ActionDomain.DATA_SHARING: PermissionLevel.A3,
    ActionDomain.DESTRUCTIVE_EXTERNAL: PermissionLevel.A3,
}


def minimum_permission_for(domain: ActionDomain) -> PermissionLevel:
    return MINIMUM_PERMISSION[domain]
