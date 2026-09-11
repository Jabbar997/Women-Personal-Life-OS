from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator

from wlos.core.base import DomainModel
from wlos.shared.clock import ensure_utc, utc_now
from wlos.shared.sensitivity import Sensitivity


class GuardianVerdict(StrEnum):
    """Guardian's only vocabulary. It has veto authority over every other mind."""

    ALLOW = "ALLOW"
    CAUTION = "CAUTION"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"

    @property
    def permits_execution(self) -> bool:
        return self in (GuardianVerdict.ALLOW, GuardianVerdict.CAUTION)


class GuardianCheck(StrEnum):
    SAFETY = "SAFETY"
    PRIVACY = "PRIVACY"
    HEALTH_BOUNDARY = "HEALTH_BOUNDARY"
    FINANCIAL_RISK = "FINANCIAL_RISK"
    FRAUD = "FRAUD"
    SENSITIVE_DATA_SHARING = "SENSITIVE_DATA_SHARING"
    HIGH_IMPACT_EXECUTION = "HIGH_IMPACT_EXECUTION"
    SCHEDULE_CONFLICT = "SCHEDULE_CONFLICT"


class GuardianConcern(DomainModel):
    check: GuardianCheck
    verdict: GuardianVerdict
    message: str


class GuardianDecision(DomainModel):
    verdict: GuardianVerdict
    concerns: tuple[GuardianConcern, ...] = ()
    sensitivity: Sensitivity = Sensitivity.S1
    decided_at: datetime = Field(default_factory=utc_now)

    @field_validator("decided_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @property
    def blocks(self) -> bool:
        return self.verdict is GuardianVerdict.BLOCK

    @classmethod
    def allow(cls, *, at: datetime | None = None) -> GuardianDecision:
        return cls(verdict=GuardianVerdict.ALLOW, decided_at=at or utc_now())
