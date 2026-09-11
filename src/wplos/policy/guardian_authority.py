import hashlib
import json
from datetime import datetime, timedelta

from wplos.core.identifiers import ActionId, AssessmentId, new_assessment_id
from wplos.core.temporal import ensure_utc
from wplos.policy.guardian import GuardianAssessment, GuardianFinding, GuardianVerdict

DEFAULT_MAX_ASSESSMENT_AGE = timedelta(minutes=10)


def _digest(assessment: GuardianAssessment) -> str:
    canonical = json.dumps(
        {
            "assessment_id": str(assessment.assessment_id),
            "subject_action_id": assessment.subject_action_id,
            "subject_fingerprint": assessment.subject_fingerprint,
            "verdict": str(assessment.verdict),
            "assessed_at": assessment.assessed_at.isoformat(),
            "findings": [
                {
                    "check": str(finding.check),
                    "verdict": str(finding.verdict),
                    "explanation": finding.explanation,
                }
                for finding in assessment.findings
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class GuardianAuthority:
    """The capability to issue a Guardian verdict that the gate will believe.

    A verdict is only as good as the question of who issued it. Anyone can
    construct a ``GuardianAssessment`` object; only the holder of this authority
    can produce one that :meth:`verify` accepts, and the gate accepts nothing
    else. The authority also keeps the latest assessment per action, so a stale
    ALLOW cannot be replayed once the picture has changed.

    Within a single process this is a capability, not a cryptographic proof.
    Running Guardian as its own service would make it one; until then, holding
    the authority object is the boundary, and it belongs to the Orchestrator.
    """

    def __init__(self, max_age: timedelta = DEFAULT_MAX_ASSESSMENT_AGE) -> None:
        self._issued: dict[AssessmentId, str] = {}
        self._latest_for_action: dict[ActionId, AssessmentId] = {}
        self.max_age = max_age

    def assess(
        self,
        *,
        action_id: ActionId,
        fingerprint: str,
        at: datetime,
        findings: tuple[GuardianFinding, ...] = (),
        verdict: GuardianVerdict | None = None,
    ) -> GuardianAssessment:
        assessment = GuardianAssessment(
            assessment_id=new_assessment_id(),
            subject_action_id=action_id,
            subject_fingerprint=fingerprint,
            verdict=verdict if verdict is not None else _strictest(findings),
            findings=findings,
            assessed_at=ensure_utc(at),
        )
        self._issued[assessment.assessment_id] = _digest(assessment)
        self._latest_for_action[action_id] = assessment.assessment_id
        return assessment

    def allow(self, *, action_id: ActionId, fingerprint: str, at: datetime) -> GuardianAssessment:
        return self.assess(
            action_id=action_id, fingerprint=fingerprint, at=at, verdict=GuardianVerdict.ALLOW
        )

    def is_authentic(self, assessment: GuardianAssessment) -> bool:
        """False for anything this authority did not issue, or that was edited."""
        expected = self._issued.get(assessment.assessment_id)
        return expected is not None and expected == _digest(assessment)

    def is_superseded(self, assessment: GuardianAssessment) -> bool:
        """True once a newer verdict exists for the same action."""
        if assessment.subject_action_id is None:
            return False
        latest = self._latest_for_action.get(assessment.subject_action_id)
        return latest is not None and latest != assessment.assessment_id

    def is_stale_at(self, assessment: GuardianAssessment, at: datetime) -> bool:
        return ensure_utc(at) - assessment.assessed_at > self.max_age


def _strictest(findings: tuple[GuardianFinding, ...]) -> GuardianVerdict:
    return max(
        (finding.verdict for finding in findings),
        key=lambda value: _SEVERITY[value],
        default=GuardianVerdict.ALLOW,
    )


_SEVERITY: dict[GuardianVerdict, int] = {
    GuardianVerdict.ALLOW: 0,
    GuardianVerdict.CAUTION: 1,
    GuardianVerdict.ESCALATE: 2,
    GuardianVerdict.BLOCK: 3,
}
