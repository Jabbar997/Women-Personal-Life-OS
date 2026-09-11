from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator

from wlos.core.base import DomainModel
from wlos.shared.clock import ensure_utc, utc_now


class PolicyOutcome(StrEnum):
    PERMIT = "PERMIT"
    DENY = "DENY"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"
    ESCALATE = "ESCALATE"


class ReasonCode(StrEnum):
    PERMITTED = "PERMITTED"
    GUARDIAN_BLOCK = "GUARDIAN_BLOCK"
    GUARDIAN_CAUTION = "GUARDIAN_CAUTION"
    GUARDIAN_ESCALATE = "GUARDIAN_ESCALATE"
    AUTHORIZATION_MISSING = "AUTHORIZATION_MISSING"
    AUTHORIZATION_EXPIRED = "AUTHORIZATION_EXPIRED"
    AUTHORIZATION_SCOPE_MISMATCH = "AUTHORIZATION_SCOPE_MISMATCH"
    AUTHORIZATION_LEVEL_INSUFFICIENT = "AUTHORIZATION_LEVEL_INSUFFICIENT"
    EXPLICIT_CONFIRMATION_REQUIRED = "EXPLICIT_CONFIRMATION_REQUIRED"
    PERMISSION_LEVEL_TOO_LOW = "PERMISSION_LEVEL_TOO_LOW"
    SENSITIVITY_ABOVE_CLEARANCE = "SENSITIVITY_ABOVE_CLEARANCE"
    NOT_NEED_TO_KNOW = "NOT_NEED_TO_KNOW"
    CONTRACT_FORBIDS_ACTION = "CONTRACT_FORBIDS_ACTION"


class PolicyReason(DomainModel):
    code: ReasonCode
    message: str
    subject: str | None = None


class PolicyDecision(DomainModel):
    """The output of every policy evaluation: an outcome plus why."""

    policy_id: str
    outcome: PolicyOutcome
    reasons: tuple[PolicyReason, ...] = ()
    evaluated_at: datetime = Field(default_factory=utc_now)

    @field_validator("evaluated_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @property
    def is_permitted(self) -> bool:
        return self.outcome is PolicyOutcome.PERMIT

    @property
    def reason_codes(self) -> tuple[ReasonCode, ...]:
        return tuple(reason.code for reason in self.reasons)

    @classmethod
    def permit(cls, policy_id: str, *, at: datetime | None = None) -> PolicyDecision:
        return cls(
            policy_id=policy_id,
            outcome=PolicyOutcome.PERMIT,
            reasons=(PolicyReason(code=ReasonCode.PERMITTED, message="policy conditions met"),),
            evaluated_at=at or utc_now(),
        )

    @classmethod
    def refuse(
        cls,
        policy_id: str,
        outcome: PolicyOutcome,
        reasons: tuple[PolicyReason, ...],
        *,
        at: datetime | None = None,
    ) -> PolicyDecision:
        if outcome is PolicyOutcome.PERMIT:
            raise ValueError("use PolicyDecision.permit for permitted outcomes")
        return cls(
            policy_id=policy_id, outcome=outcome, reasons=reasons, evaluated_at=at or utc_now()
        )
