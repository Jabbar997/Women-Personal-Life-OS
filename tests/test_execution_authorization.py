"""Tests 6, 7 and 8: the Operator gate.

Guardian's veto outranks any authorization; A2/A3 need the user; A1 does not.
"""

from datetime import datetime, timedelta

import pytest

from wplos.core.identifiers import ActionId, AuthorizationId, UserId
from wplos.core.roles import AgentName
from wplos.policy.decisions import PolicyOutcome, ReasonCode
from wplos.policy.execution import (
    DEFAULT_EXECUTION_POLICY,
    AuthorizationMethod,
    ExecutionAuthorization,
    ProposedAction,
    require_execution_authorization,
)
from wplos.policy.guardian import (
    GuardianAssessment,
    GuardianCheck,
    GuardianFinding,
    GuardianVerdict,
)
from wplos.policy.permissions import ActionDomain, PermissionLevel
from wplos.shared.errors import AuthorizationRequired

ACTION_ID = ActionId("act_1")


def _action(
    owner: UserId,
    now: datetime,
    domain: ActionDomain,
    level: PermissionLevel,
) -> ProposedAction:
    return ProposedAction(
        action_id=ACTION_ID,
        owner_id=owner,
        proposed_by=AgentName.OPERATOR,
        proposed_at=now,
        domain=domain,
        permission_level=level,
        summary=f"{domain} action",
        reversible=False,
    )


def _authorization(
    owner: UserId,
    now: datetime,
    level: PermissionLevel,
    method: AuthorizationMethod = AuthorizationMethod.EXPLICIT_CONFIRMATION,
    audit_ref: str | None = "audit_1",
) -> ExecutionAuthorization:
    return ExecutionAuthorization(
        authorization_id=AuthorizationId("aut_1"),
        action_id=ACTION_ID,
        granted_by=owner,
        granted_at=now,
        granted_level=level,
        method=method,
        expires_at=now + timedelta(minutes=10),
        audit_ref=audit_ref,
    )


def _blocked() -> GuardianAssessment:
    return GuardianAssessment.from_findings(
        (
            GuardianFinding(
                check=GuardianCheck.FINANCIAL_RISK,
                verdict=GuardianVerdict.BLOCK,
                explanation="spend exceeds the user's stated caution threshold",
            ),
        ),
        subject_action_id=ACTION_ID,
    )


def test_guardian_block_defeats_a_valid_authorization(owner: UserId, now: datetime) -> None:
    action = _action(owner, now, ActionDomain.PAYMENT, PermissionLevel.A3)
    authorization = _authorization(owner, now, PermissionLevel.A3)

    decision = DEFAULT_EXECUTION_POLICY.authorize(action, _blocked(), authorization, now)

    assert decision.outcome is PolicyOutcome.DENY
    assert decision.has_reason(ReasonCode.GUARDIAN_BLOCKED)
    with pytest.raises(AuthorizationRequired):
        require_execution_authorization(action, _blocked(), authorization, now)


def test_guardian_escalate_stops_execution_and_asks_for_a_human(
    owner: UserId, now: datetime
) -> None:
    action = _action(owner, now, ActionDomain.MEDICAL, PermissionLevel.A3)
    guardian = GuardianAssessment(subject_action_id=ACTION_ID, verdict=GuardianVerdict.ESCALATE)

    decision = DEFAULT_EXECUTION_POLICY.authorize(
        action, guardian, _authorization(owner, now, PermissionLevel.A3), now
    )

    assert decision.outcome is PolicyOutcome.ESCALATE


def test_a2_without_authorization_is_not_executable(owner: UserId, now: datetime) -> None:
    action = _action(owner, now, ActionDomain.COMMUNICATION, PermissionLevel.A2)

    decision = DEFAULT_EXECUTION_POLICY.authorize(action, GuardianAssessment.allow(), None, now)

    assert decision.outcome is PolicyOutcome.REQUIRE_CONFIRMATION
    assert decision.has_reason(ReasonCode.AUTHORIZATION_MISSING)
    with pytest.raises(AuthorizationRequired, match="AUTHORIZATION_MISSING"):
        require_execution_authorization(action, GuardianAssessment.allow(), None, now)


def test_a1_internal_action_runs_without_a_confirmation(owner: UserId, now: datetime) -> None:
    action = _action(owner, now, ActionDomain.INTERNAL, PermissionLevel.A1)

    decision = require_execution_authorization(action, GuardianAssessment.allow(), None, now)

    assert decision.outcome is PolicyOutcome.PERMIT
    assert decision.has_reason(ReasonCode.ALLOWED)


def test_a0_is_a_proposal_and_never_executes(owner: UserId, now: datetime) -> None:
    action = ProposedAction(
        action_id=ACTION_ID,
        owner_id=owner,
        proposed_by=AgentName.OPERATOR,
        proposed_at=now,
        domain=ActionDomain.INTERNAL,
        permission_level=PermissionLevel.A0,
        summary="suggest a reschedule",
        reversible=True,
    )

    decision = DEFAULT_EXECUTION_POLICY.authorize(action, GuardianAssessment.allow(), None, now)

    assert decision.outcome is PolicyOutcome.DENY
    assert decision.has_reason(ReasonCode.SUGGESTION_ONLY)


def test_a3_needs_explicit_confirmation_not_a_standing_rule(owner: UserId, now: datetime) -> None:
    action = _action(owner, now, ActionDomain.PURCHASE, PermissionLevel.A3)
    standing = _authorization(
        owner, now, PermissionLevel.A3, method=AuthorizationMethod.STANDING_RULE
    )

    decision = DEFAULT_EXECUTION_POLICY.authorize(action, GuardianAssessment.allow(), standing, now)

    assert decision.outcome is PolicyOutcome.REQUIRE_CONFIRMATION
    assert decision.has_reason(ReasonCode.AUTHORIZATION_INSUFFICIENT)


def test_a3_without_an_audit_reference_is_denied(owner: UserId, now: datetime) -> None:
    action = _action(owner, now, ActionDomain.PAYMENT, PermissionLevel.A3)
    unaudited = _authorization(owner, now, PermissionLevel.A3, audit_ref=None)

    decision = DEFAULT_EXECUTION_POLICY.authorize(
        action, GuardianAssessment.allow(), unaudited, now
    )

    assert decision.outcome is PolicyOutcome.DENY
    assert decision.has_reason(ReasonCode.AUDIT_TRAIL_MISSING)


def test_an_authorization_for_another_action_is_rejected(owner: UserId, now: datetime) -> None:
    action = _action(owner, now, ActionDomain.COMMUNICATION, PermissionLevel.A2)
    other = _authorization(owner, now, PermissionLevel.A2).model_copy(
        update={"action_id": ActionId("act_other")}
    )

    decision = DEFAULT_EXECUTION_POLICY.authorize(action, GuardianAssessment.allow(), other, now)

    assert decision.outcome is PolicyOutcome.DENY
    assert decision.has_reason(ReasonCode.AUTHORIZATION_MISMATCH)


def test_an_expired_authorization_asks_again(owner: UserId, now: datetime) -> None:
    action = _action(owner, now, ActionDomain.COMMUNICATION, PermissionLevel.A2)
    authorization = _authorization(owner, now, PermissionLevel.A2)

    decision = DEFAULT_EXECUTION_POLICY.authorize(
        action, GuardianAssessment.allow(), authorization, now + timedelta(hours=1)
    )

    assert decision.outcome is PolicyOutcome.REQUIRE_CONFIRMATION
    assert decision.has_reason(ReasonCode.AUTHORIZATION_EXPIRED)


def test_a_payment_cannot_be_proposed_below_its_permission_floor(
    owner: UserId, now: datetime
) -> None:
    with pytest.raises(ValueError, match="requires at least A3"):
        _action(owner, now, ActionDomain.PAYMENT, PermissionLevel.A1)
