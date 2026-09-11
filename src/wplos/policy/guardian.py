from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from wplos.core.identifiers import ActionId


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
    """Guardian's answer about one subject, usually a proposed action."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject_action_id: ActionId | None = None
    verdict: GuardianVerdict
    findings: tuple[GuardianFinding, ...] = Field(default_factory=tuple)

    @classmethod
    def allow(cls, subject_action_id: ActionId | None = None) -> "GuardianAssessment":
        return cls(subject_action_id=subject_action_id, verdict=GuardianVerdict.ALLOW)

    @classmethod
    def from_findings(
        cls,
        findings: tuple[GuardianFinding, ...],
        subject_action_id: ActionId | None = None,
    ) -> "GuardianAssessment":
        """The strictest finding decides; Guardian never averages its own warnings."""
        verdict = max(
            (finding.verdict for finding in findings),
            key=lambda value: _SEVERITY[value],
            default=GuardianVerdict.ALLOW,
        )
        return cls(subject_action_id=subject_action_id, verdict=verdict, findings=findings)

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
