from pydantic import BaseModel, ConfigDict

from wplos.core.purpose import Purpose
from wplos.core.roles import AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.policy.decisions import PolicyDecision, ReasonCode, reason

POLICY_NAME = "sensitivity.need_to_know"
NEED_TO_KNOW_FROM = SensitivityLevel.S2


class ExposureRequest(BaseModel):
    """One agent asking to read one record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    consumer: AgentName
    consumer_ceiling: SensitivityLevel
    record_sensitivity: SensitivityLevel
    explicitly_required: bool
    purpose: Purpose


class SurfaceRequest(BaseModel):
    """A request to show something to the user. Known is not Shown."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_sensitivity: SensitivityLevel
    user_initiated: bool
    shared_context: bool


class SensitivityPolicy:
    """Decides who may *read* a record and whether it may be *surfaced*.

    Two separate questions: an agent holding cycle data in working context is
    not the same as the assistant mentioning it out loud.
    """

    name = POLICY_NAME

    def evaluate_exposure(self, request: ExposureRequest) -> PolicyDecision:
        if not request.consumer_ceiling.dominates(request.record_sensitivity):
            return PolicyDecision.deny(
                POLICY_NAME,
                reason(
                    ReasonCode.CONSUMER_CEILING_EXCEEDED,
                    f"{request.consumer} is cleared to {request.consumer_ceiling}, "
                    f"record is {request.record_sensitivity}",
                ),
            )
        if (
            request.record_sensitivity.dominates(NEED_TO_KNOW_FROM)
            and not request.explicitly_required
        ):
            return PolicyDecision.deny(
                POLICY_NAME,
                reason(
                    ReasonCode.NEED_TO_KNOW_NOT_ESTABLISHED,
                    f"{request.record_sensitivity} data is not required for: {request.purpose}",
                ),
            )
        return PolicyDecision.permit(
            POLICY_NAME, reason(ReasonCode.ALLOWED, f"within {request.consumer_ceiling} clearance")
        )

    def evaluate_surfacing(self, request: SurfaceRequest) -> PolicyDecision:
        if request.shared_context and request.record_sensitivity.dominates(SensitivityLevel.S2):
            return PolicyDecision.deny(
                POLICY_NAME,
                reason(
                    ReasonCode.SHARED_CONTEXT_DISCLOSURE,
                    "sensitive data is never surfaced into a shared context",
                ),
            )
        if request.record_sensitivity is SensitivityLevel.S3 and not request.user_initiated:
            return PolicyDecision.require_confirmation(
                POLICY_NAME,
                reason(
                    ReasonCode.NOT_USER_INITIATED,
                    "S3 data is surfaced only in a turn the user opened",
                ),
            )
        return PolicyDecision.permit(POLICY_NAME, reason(ReasonCode.ALLOWED, "surfacing permitted"))


DEFAULT_SENSITIVITY_POLICY = SensitivityPolicy()
