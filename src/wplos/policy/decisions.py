from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PolicyOutcome(StrEnum):
    PERMIT = "PERMIT"
    DENY = "DENY"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"
    ESCALATE = "ESCALATE"


class ReasonCode(StrEnum):
    """Every policy answer names a machine-readable reason.

    Permissions must never be scattered ``if`` statements whose justification
    lives only in a commit message.
    """

    ALLOWED = "ALLOWED"
    GUARDIAN_BLOCKED = "GUARDIAN_BLOCKED"
    GUARDIAN_ESCALATED = "GUARDIAN_ESCALATED"
    GUARDIAN_CAUTION = "GUARDIAN_CAUTION"
    SUGGESTION_ONLY = "SUGGESTION_ONLY"
    AUTHORIZATION_MISSING = "AUTHORIZATION_MISSING"
    AUTHORIZATION_EXPIRED = "AUTHORIZATION_EXPIRED"
    AUTHORIZATION_MISMATCH = "AUTHORIZATION_MISMATCH"
    AUTHORIZATION_INSUFFICIENT = "AUTHORIZATION_INSUFFICIENT"
    MATERIAL_TERMS_CHANGED = "MATERIAL_TERMS_CHANGED"
    GUARDIAN_ASSESSMENT_MISSING = "GUARDIAN_ASSESSMENT_MISSING"
    AUDIT_TRAIL_MISSING = "AUDIT_TRAIL_MISSING"
    CONSUMER_CEILING_EXCEEDED = "CONSUMER_CEILING_EXCEEDED"
    NEED_TO_KNOW_NOT_ESTABLISHED = "NEED_TO_KNOW_NOT_ESTABLISHED"
    SHARED_CONTEXT_DISCLOSURE = "SHARED_CONTEXT_DISCLOSURE"
    NOT_USER_INITIATED = "NOT_USER_INITIATED"


class PolicyReason(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: ReasonCode
    message: str


class PolicyDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy: str
    outcome: PolicyOutcome
    reasons: tuple[PolicyReason, ...] = Field(default_factory=tuple)

    @classmethod
    def permit(cls, policy: str, *reasons: PolicyReason) -> "PolicyDecision":
        return cls(policy=policy, outcome=PolicyOutcome.PERMIT, reasons=reasons)

    @classmethod
    def deny(cls, policy: str, *reasons: PolicyReason) -> "PolicyDecision":
        return cls(policy=policy, outcome=PolicyOutcome.DENY, reasons=reasons)

    @classmethod
    def require_confirmation(cls, policy: str, *reasons: PolicyReason) -> "PolicyDecision":
        return cls(policy=policy, outcome=PolicyOutcome.REQUIRE_CONFIRMATION, reasons=reasons)

    @classmethod
    def escalate(cls, policy: str, *reasons: PolicyReason) -> "PolicyDecision":
        return cls(policy=policy, outcome=PolicyOutcome.ESCALATE, reasons=reasons)

    @property
    def is_permitted(self) -> bool:
        return self.outcome is PolicyOutcome.PERMIT

    def has_reason(self, code: ReasonCode) -> bool:
        return any(reason.code is code for reason in self.reasons)


def reason(code: ReasonCode, message: str) -> PolicyReason:
    return PolicyReason(code=code, message=message)
