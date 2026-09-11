from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from wplos.core.identifiers import ActionId, AuthorizationId, UserId
from wplos.core.roles import AgentName
from wplos.core.temporal import ensure_utc
from wplos.policy.decisions import (
    PolicyDecision,
    PolicyOutcome,
    PolicyReason,
    ReasonCode,
    reason,
)
from wplos.policy.guardian import GuardianAssessment, GuardianVerdict
from wplos.policy.permissions import ActionDomain, PermissionLevel, minimum_permission_for
from wplos.shared.errors import AuthorizationRequired
from wplos.shared.json import JsonValue

POLICY_NAME = "execution.authorization"


class AuthorizationMethod(StrEnum):
    EXPLICIT_CONFIRMATION = "EXPLICIT_CONFIRMATION"
    STANDING_RULE = "STANDING_RULE"
    INTERNAL_POLICY = "INTERNAL_POLICY"


class ProposedAction(BaseModel):
    """An intent to change the world, before anyone has agreed to it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: ActionId
    owner_id: UserId
    proposed_by: AgentName
    proposed_at: datetime
    domain: ActionDomain
    permission_level: PermissionLevel
    summary: str
    reversible: bool
    parameters: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("proposed_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @model_validator(mode="after")
    def _permission_matches_domain(self) -> Self:
        """A0 is a suggestion and always allowed; executing in a domain is not.

        The floor governs what authority execution demands, so proposing a
        payment is fine while running one at A1 is not.
        """
        if not self.permission_level.is_executable:
            return self
        floor = minimum_permission_for(self.domain)
        if self.permission_level.rank < floor.rank:
            raise ValueError(
                f"executing a {self.domain} action requires at least {floor}, "
                f"got {self.permission_level}"
            )
        return self


class ExecutionAuthorization(BaseModel):
    """Proof that the user agreed to this specific action."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    authorization_id: AuthorizationId
    action_id: ActionId
    granted_by: UserId
    granted_at: datetime
    granted_level: PermissionLevel
    method: AuthorizationMethod
    expires_at: datetime | None = None
    audit_ref: str | None = None

    @field_validator("granted_at", "expires_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)

    def is_expired_at(self, at: datetime) -> bool:
        return self.expires_at is not None and ensure_utc(at) >= self.expires_at


class ExecutionPolicy:
    """The single gate between intent and the real world.

    Guardian's veto is checked before anything else, so no permission level and
    no authorization can buy past a BLOCK.
    """

    name = POLICY_NAME

    def authorize(
        self,
        action: ProposedAction,
        guardian: GuardianAssessment,
        authorization: ExecutionAuthorization | None,
        at: datetime,
    ) -> PolicyDecision:
        veto = self._check_guardian(guardian)
        if veto is not None:
            return veto

        level = action.permission_level
        if not level.is_executable:
            return PolicyDecision.deny(
                POLICY_NAME,
                reason(
                    ReasonCode.SUGGESTION_ONLY, f"{level} actions are proposals, never executed"
                ),
            )

        if not level.requires_authorization:
            return PolicyDecision.permit(POLICY_NAME, *self._internal_reasons(guardian))

        return self._check_authorization(action, authorization, at, guardian)

    def _check_guardian(self, guardian: GuardianAssessment) -> PolicyDecision | None:
        if guardian.verdict is GuardianVerdict.BLOCK:
            return PolicyDecision.deny(
                POLICY_NAME,
                reason(ReasonCode.GUARDIAN_BLOCKED, "Guardian vetoed this action"),
            )
        if guardian.verdict is GuardianVerdict.ESCALATE:
            return PolicyDecision.escalate(
                POLICY_NAME,
                reason(ReasonCode.GUARDIAN_ESCALATED, "Guardian escalated this action"),
            )
        return None

    def _internal_reasons(self, guardian: GuardianAssessment) -> tuple[PolicyReason, ...]:
        if guardian.verdict is GuardianVerdict.CAUTION:
            return (
                reason(ReasonCode.GUARDIAN_CAUTION, "permitted with Guardian caution recorded"),
            )
        return (reason(ReasonCode.ALLOWED, "internal action within A1 authority"),)

    def _check_authorization(
        self,
        action: ProposedAction,
        authorization: ExecutionAuthorization | None,
        at: datetime,
        guardian: GuardianAssessment,
    ) -> PolicyDecision:
        level = action.permission_level
        if authorization is None:
            return PolicyDecision.require_confirmation(
                POLICY_NAME,
                reason(
                    ReasonCode.AUTHORIZATION_MISSING,
                    f"{level} action requires user authorization before execution",
                ),
            )
        if authorization.action_id != action.action_id:
            return PolicyDecision.deny(
                POLICY_NAME,
                reason(
                    ReasonCode.AUTHORIZATION_MISMATCH,
                    "authorization was granted for a different action",
                ),
            )
        if authorization.granted_by != action.owner_id:
            return PolicyDecision.deny(
                POLICY_NAME,
                reason(
                    ReasonCode.AUTHORIZATION_MISMATCH, "authorization was granted by another user"
                ),
            )
        if authorization.is_expired_at(at):
            return PolicyDecision.require_confirmation(
                POLICY_NAME,
                reason(ReasonCode.AUTHORIZATION_EXPIRED, "authorization has expired"),
            )
        if authorization.granted_level.rank < level.rank:
            return PolicyDecision.deny(
                POLICY_NAME,
                reason(
                    ReasonCode.AUTHORIZATION_INSUFFICIENT,
                    f"authorization covers {authorization.granted_level}, action needs {level}",
                ),
            )
        if (
            level.requires_explicit_confirmation
            and authorization.method is not AuthorizationMethod.EXPLICIT_CONFIRMATION
        ):
            return PolicyDecision.require_confirmation(
                POLICY_NAME,
                reason(
                    ReasonCode.AUTHORIZATION_INSUFFICIENT,
                    f"{level} requires explicit confirmation, not {authorization.method}",
                ),
            )
        if level.requires_audit_trail and authorization.audit_ref is None:
            return PolicyDecision.deny(
                POLICY_NAME,
                reason(ReasonCode.AUDIT_TRAIL_MISSING, f"{level} requires an audit reference"),
            )
        if guardian.verdict is GuardianVerdict.CAUTION:
            return PolicyDecision.permit(
                POLICY_NAME,
                reason(ReasonCode.GUARDIAN_CAUTION, "authorized with Guardian caution recorded"),
            )
        return PolicyDecision.permit(
            POLICY_NAME, reason(ReasonCode.ALLOWED, "authorized by the user")
        )


DEFAULT_EXECUTION_POLICY = ExecutionPolicy()


def require_execution_authorization(
    action: ProposedAction,
    guardian: GuardianAssessment,
    authorization: ExecutionAuthorization | None,
    at: datetime,
    policy: ExecutionPolicy = DEFAULT_EXECUTION_POLICY,
) -> PolicyDecision:
    """Gate used by the Operator. Raises unless the decision is PERMIT."""
    decision = policy.authorize(action, guardian, authorization, at)
    if decision.outcome is not PolicyOutcome.PERMIT:
        codes = ", ".join(item.code for item in decision.reasons)
        raise AuthorizationRequired(
            f"{action.action_id} not authorized ({decision.outcome}): {codes}"
        )
    return decision
