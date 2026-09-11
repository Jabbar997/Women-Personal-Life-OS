from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from wplos.core.identifiers import ActionId, AssessmentId, new_assessment_id
from wplos.core.roles import AgentName
from wplos.core.temporal import ensure_utc, utc_now


class GuardianVerdict(StrEnum):
    """The only four things Guardian may say. Guardian holds a veto."""

    ALLOW = "ALLOW"
    CAUTION = "CAUTION"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"

    @property
    def is_veto(self) -> bool:
        return self is GuardianVerdict.BLOCK

    @property
    def permits_execution(self) -> bool:
        return self in {GuardianVerdict.ALLOW, GuardianVerdict.CAUTION}


class GuardianCheck(StrEnum):
    SAFETY = "SAFETY"
    PRIVACY = "PRIVACY"
    HEALTH_BOUNDARY = "HEALTH_BOUNDARY"
    FINANCIAL_RISK = "FINANCIAL_RISK"
    FRAUD = "FRAUD"
    SENSITIVE_DATA_SHARING = "SENSITIVE_DATA_SHARING"
    HIGH_IMPACT_EXECUTION = "HIGH_IMPACT_EXECUTION"
    SCHEDULE_CONFLICT = "SCHEDULE_CONFLICT"


class GuardianFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    check: GuardianCheck
    verdict: GuardianVerdict
    explanation: str


class GuardianAssessment(BaseModel):
    """Guardian's answer about one subject, usually a proposed action.

    It names what it assessed, the exact terms it assessed, and when. A verdict
    floating free of its subject is how a BLOCK gets bypassed; a verdict with no
    timestamp is how a stale ALLOW outlives the risk it cleared.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    assessment_id: AssessmentId = Field(default_factory=new_assessment_id)
    subject_action_id: ActionId | None = None
    subject_fingerprint: str | None = None
    verdict: GuardianVerdict
    findings: tuple[GuardianFinding, ...] = Field(default_factory=tuple)
    issued_by: AgentName = AgentName.GUARDIAN
    assessed_at: datetime = Field(default_factory=utc_now)

    @field_validator("assessed_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("issued_by")
    @classmethod
    def _only_guardian(cls, value: AgentName) -> AgentName:
        if value is not AgentName.GUARDIAN:
            raise ValueError("only Guardian issues a Guardian assessment")
        return value

    @classmethod
    def allow(cls, subject_action_id: ActionId) -> "GuardianAssessment":
        """Unverifiable by design: use ``GuardianAuthority.allow`` for anything
        the execution gate will see."""
        return cls(subject_action_id=subject_action_id, verdict=GuardianVerdict.ALLOW)

    @classmethod
    def from_findings(
        cls,
        findings: tuple[GuardianFinding, ...],
        subject_action_id: ActionId | None = None,
        subject_fingerprint: str | None = None,
    ) -> "GuardianAssessment":
        """The strictest finding decides; Guardian never averages its own warnings."""
        verdict = max(
            (finding.verdict for finding in findings),
            key=lambda value: _SEVERITY[value],
            default=GuardianVerdict.ALLOW,
        )
        return cls(
            subject_action_id=subject_action_id,
            subject_fingerprint=subject_fingerprint,
            verdict=verdict,
            findings=findings,
        )

    @property
    def is_veto(self) -> bool:
        return self.verdict.is_veto

    def findings_for(self, check: GuardianCheck) -> tuple[GuardianFinding, ...]:
        return tuple(finding for finding in self.findings if finding.check is check)


_SEVERITY: dict[GuardianVerdict, int] = {
    GuardianVerdict.ALLOW: 0,
    GuardianVerdict.CAUTION: 1,
    GuardianVerdict.ESCALATE: 2,
    GuardianVerdict.BLOCK: 3,
}
