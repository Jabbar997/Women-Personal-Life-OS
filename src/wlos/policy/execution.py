from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator

from wlos.core.base import DomainModel
from wlos.policy.decisions import PolicyDecision, PolicyOutcome, PolicyReason, ReasonCode
from wlos.policy.guardian_verdict import GuardianDecision, GuardianVerdict
from wlos.policy.permissions import PermissionLevel
from wlos.shared.attributes import Attributes
from wlos.shared.clock import ensure_utc, utc_now
from wlos.shared.identifiers import ActionId, CorrelationId, OwnerId, new_action_id
from wlos.shared.sensitivity import Sensitivity

POLICY_ID = "execution.authorization.v1"


class ActionKind(StrEnum):
    INTERNAL_UPDATE = "INTERNAL_UPDATE"
    INTERNAL_REMINDER = "INTERNAL_REMINDER"
    DRAFT_PREPARATION = "DRAFT_PREPARATION"
    EXTERNAL_BOOKING = "EXTERNAL_BOOKING"
    EXTERNAL_MESSAGE = "EXTERNAL_MESSAGE"
    SENSITIVE_COMMUNICATION = "SENSITIVE_COMMUNICATION"
    DATA_SHARING = "DATA_SHARING"
    PURCHASE = "PURCHASE"
    PAYMENT = "PAYMENT"
    LEGAL = "LEGAL"
    MEDICAL = "MEDICAL"
    DESTRUCTIVE_EXTERNAL = "DESTRUCTIVE_EXTERNAL"


MINIMUM_PERMISSION: dict[ActionKind, PermissionLevel] = {
    ActionKind.INTERNAL_UPDATE: PermissionLevel.A1,
    ActionKind.INTERNAL_REMINDER: PermissionLevel.A1,
    ActionKind.DRAFT_PREPARATION: PermissionLevel.A1,
    ActionKind.EXTERNAL_BOOKING: PermissionLevel.A2,
    ActionKind.EXTERNAL_MESSAGE: PermissionLevel.A2,
    ActionKind.SENSITIVE_COMMUNICATION: PermissionLevel.A3,
    ActionKind.DATA_SHARING: PermissionLevel.A3,
    ActionKind.PURCHASE: PermissionLevel.A3,
    ActionKind.PAYMENT: PermissionLevel.A3,
    ActionKind.LEGAL: PermissionLevel.A3,
    ActionKind.MEDICAL: PermissionLevel.A3,
    ActionKind.DESTRUCTIVE_EXTERNAL: PermissionLevel.A3,
}
"""Floor per action kind. Payments, legal, medical and destructive actions can
never be reclassified downwards into silent execution."""


def required_permission(kind: ActionKind, requested: PermissionLevel) -> PermissionLevel:
    return max(MINIMUM_PERMISSION[kind], requested)


class AuthorizationMethod(StrEnum):
    USER_CONFIRMATION = "USER_CONFIRMATION"
    USER_EXPLICIT_CONFIRMATION = "USER_EXPLICIT_CONFIRMATION"
    STANDING_RULE = "STANDING_RULE"


class UserAuthorization(DomainModel):
    """Proof that the user authorized one specific action."""

    action_id: ActionId
    granted_by: OwnerId
    scope: ActionKind
    level: PermissionLevel
    method: AuthorizationMethod
    granted_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = None

    @field_validator("granted_at", "expires_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)

    def is_valid_at(self, moment: datetime) -> bool:
        return self.expires_at is None or ensure_utc(moment) < self.expires_at


class ExecutionRequest(DomainModel):
    """An action the operator has been asked to perform."""

    action_id: ActionId = Field(default_factory=new_action_id)
    owner_id: OwnerId
    kind: ActionKind
    description: str
    requested_level: PermissionLevel = PermissionLevel.A0
    sensitivity: Sensitivity = Sensitivity.S1
    payload: Attributes = Field(default_factory=dict)
    correlation_id: CorrelationId | None = None

    @property
    def effective_level(self) -> PermissionLevel:
        return required_permission(self.kind, self.requested_level)


class ExecutionPolicy:
    """The single gate every real-world action passes through."""

    @staticmethod
    def evaluate(
        request: ExecutionRequest,
        *,
        guardian: GuardianDecision,
        authorization: UserAuthorization | None = None,
        at: datetime | None = None,
    ) -> PolicyDecision:
        moment = ensure_utc(at) if at is not None else utc_now()
        level = request.effective_level

        if guardian.verdict is GuardianVerdict.BLOCK:
            return PolicyDecision.refuse(
                POLICY_ID,
                PolicyOutcome.DENY,
                (
                    PolicyReason(
                        code=ReasonCode.GUARDIAN_BLOCK,
                        message="Guardian blocked this action; no mind may override it",
                        subject=str(request.action_id),
                    ),
                ),
                at=moment,
            )

        if guardian.verdict is GuardianVerdict.ESCALATE:
            return PolicyDecision.refuse(
                POLICY_ID,
                PolicyOutcome.ESCALATE,
                (
                    PolicyReason(
                        code=ReasonCode.GUARDIAN_ESCALATE,
                        message="Guardian escalated this action to the user",
                        subject=str(request.action_id),
                    ),
                ),
                at=moment,
            )

        if level is PermissionLevel.A0:
            return PolicyDecision.refuse(
                POLICY_ID,
                PolicyOutcome.DENY,
                (
                    PolicyReason(
                        code=ReasonCode.PERMISSION_LEVEL_TOO_LOW,
                        message="A0 is suggest-only and never executes",
                        subject=str(request.action_id),
                    ),
                ),
                at=moment,
            )

        if not level.requires_user_confirmation:
            return PolicyDecision.permit(POLICY_ID, at=moment)

        reason = _authorization_defect(request, level, authorization, moment)
        if reason is not None:
            outcome = (
                PolicyOutcome.REQUIRE_CONFIRMATION
                if reason.code is ReasonCode.AUTHORIZATION_MISSING
                else PolicyOutcome.DENY
            )
            return PolicyDecision.refuse(POLICY_ID, outcome, (reason,), at=moment)

        return PolicyDecision.permit(POLICY_ID, at=moment)


def _authorization_defect(
    request: ExecutionRequest,
    level: PermissionLevel,
    authorization: UserAuthorization | None,
    moment: datetime,
) -> PolicyReason | None:
    subject = str(request.action_id)
    if authorization is None:
        return PolicyReason(
            code=ReasonCode.AUTHORIZATION_MISSING,
            message=f"{level.name} action requires user authorization",
            subject=subject,
        )
    if authorization.action_id != request.action_id:
        return PolicyReason(
            code=ReasonCode.AUTHORIZATION_SCOPE_MISMATCH,
            message="authorization was granted for a different action",
            subject=subject,
        )
    if authorization.scope is not request.kind:
        return PolicyReason(
            code=ReasonCode.AUTHORIZATION_SCOPE_MISMATCH,
            message=f"authorization covers {authorization.scope}, not {request.kind}",
            subject=subject,
        )
    if authorization.granted_by != request.owner_id:
        return PolicyReason(
            code=ReasonCode.AUTHORIZATION_SCOPE_MISMATCH,
            message="authorization was granted by another owner",
            subject=subject,
        )
    if not authorization.is_valid_at(moment):
        return PolicyReason(
            code=ReasonCode.AUTHORIZATION_EXPIRED,
            message="authorization has expired",
            subject=subject,
        )
    if authorization.level < level:
        return PolicyReason(
            code=ReasonCode.AUTHORIZATION_LEVEL_INSUFFICIENT,
            message=f"authorization is {authorization.level.name}, action needs {level.name}",
            subject=subject,
        )
    if (
        level.requires_explicit_confirmation
        and authorization.method is not AuthorizationMethod.USER_EXPLICIT_CONFIRMATION
    ):
        return PolicyReason(
            code=ReasonCode.EXPLICIT_CONFIRMATION_REQUIRED,
            message="A3 actions require explicit user confirmation, not a standing rule",
            subject=subject,
        )
    return None
