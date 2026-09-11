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
    price_minor: int = 10000,
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
        material_terms={"price_minor": price_minor, "starts_at": "2026-03-03T19:00:00Z"},
    )


def _authorization(
    action: ProposedAction,
    now: datetime,
    level: PermissionLevel,
    method: AuthorizationMethod = AuthorizationMethod.EXPLICIT_CONFIRMATION,
    audit_ref: str | None = "audit_1",
) -> ExecutionAuthorization:
    return ExecutionAuthorization.for_action(
        action,
        authorization_id=AuthorizationId("aut_1"),
        granted_at=now,
        granted_level=level,
        method=method,
        expires_at=now + timedelta(minutes=10),
        audit_ref=audit_ref,
    )


def _allow() -> GuardianAssessment:
    return GuardianAssessment.allow(ACTION_ID)


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
    authorization = _authorization(action, now, PermissionLevel.A3)

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
        action, guardian, _authorization(action, now, PermissionLevel.A3), now
    )

    assert decision.outcome is PolicyOutcome.ESCALATE


def test_a2_without_authorization_is_not_executable(owner: UserId, now: datetime) -> None:
    action = _action(owner, now, ActionDomain.COMMUNICATION, PermissionLevel.A2)

    decision = DEFAULT_EXECUTION_POLICY.authorize(action, _allow(), None, now)

    assert decision.outcome is PolicyOutcome.REQUIRE_CONFIRMATION
    assert decision.has_reason(ReasonCode.AUTHORIZATION_MISSING)
    with pytest.raises(AuthorizationRequired, match="AUTHORIZATION_MISSING"):
        require_execution_authorization(action, _allow(), None, now)


def test_a1_internal_action_runs_without_a_confirmation(owner: UserId, now: datetime) -> None:
    action = _action(owner, now, ActionDomain.INTERNAL, PermissionLevel.A1)

    decision = require_execution_authorization(action, _allow(), None, now)

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

    decision = DEFAULT_EXECUTION_POLICY.authorize(action, _allow(), None, now)

    assert decision.outcome is PolicyOutcome.DENY
    assert decision.has_reason(ReasonCode.SUGGESTION_ONLY)


def test_a3_needs_explicit_confirmation_not_a_standing_rule(owner: UserId, now: datetime) -> None:
    action = _action(owner, now, ActionDomain.PURCHASE, PermissionLevel.A3)
    standing = _authorization(
        action, now, PermissionLevel.A3, method=AuthorizationMethod.STANDING_RULE
    )

    decision = DEFAULT_EXECUTION_POLICY.authorize(action, _allow(), standing, now)

    assert decision.outcome is PolicyOutcome.REQUIRE_CONFIRMATION
    assert decision.has_reason(ReasonCode.AUTHORIZATION_INSUFFICIENT)


def test_a3_without_an_audit_reference_is_denied(owner: UserId, now: datetime) -> None:
    action = _action(owner, now, ActionDomain.PAYMENT, PermissionLevel.A3)
    unaudited = _authorization(action, now, PermissionLevel.A3, audit_ref=None)

    decision = DEFAULT_EXECUTION_POLICY.authorize(action, _allow(), unaudited, now)

    assert decision.outcome is PolicyOutcome.DENY
    assert decision.has_reason(ReasonCode.AUDIT_TRAIL_MISSING)


def test_an_authorization_for_another_action_is_rejected(owner: UserId, now: datetime) -> None:
    action = _action(owner, now, ActionDomain.COMMUNICATION, PermissionLevel.A2)
    other = _authorization(action, now, PermissionLevel.A2).model_copy(
        update={"action_id": ActionId("act_other")}
    )

    decision = DEFAULT_EXECUTION_POLICY.authorize(action, _allow(), other, now)

    assert decision.outcome is PolicyOutcome.DENY
    assert decision.has_reason(ReasonCode.AUTHORIZATION_MISMATCH)


def test_an_expired_authorization_asks_again(owner: UserId, now: datetime) -> None:
    action = _action(owner, now, ActionDomain.COMMUNICATION, PermissionLevel.A2)
    authorization = _authorization(action, now, PermissionLevel.A2)

    decision = DEFAULT_EXECUTION_POLICY.authorize(
        action, _allow(), authorization, now + timedelta(hours=1)
    )

    assert decision.outcome is PolicyOutcome.REQUIRE_CONFIRMATION
    assert decision.has_reason(ReasonCode.AUTHORIZATION_EXPIRED)


def test_a_payment_cannot_be_proposed_below_its_permission_floor(
    owner: UserId, now: datetime
) -> None:
    with pytest.raises(ValueError, match="requires at least A3"):
        _action(owner, now, ActionDomain.PAYMENT, PermissionLevel.A1)


def test_changed_material_terms_invalidate_the_authorization(owner: UserId, now: datetime) -> None:
    """Consent to Pilates at 19:00 for SAR 100 is not consent to 20:00 for SAR 180."""
    agreed = _action(owner, now, ActionDomain.PURCHASE, PermissionLevel.A3, price_minor=10000)
    authorization = _authorization(agreed, now, PermissionLevel.A3)
    repriced = agreed.with_terms(price_minor=18000, starts_at="2026-03-03T20:00:00Z")

    assert DEFAULT_EXECUTION_POLICY.authorize(agreed, _allow(), authorization, now).is_permitted

    decision = DEFAULT_EXECUTION_POLICY.authorize(repriced, _allow(), authorization, now)

    assert decision.outcome is PolicyOutcome.DENY
    assert decision.has_reason(ReasonCode.MATERIAL_TERMS_CHANGED)
    assert not authorization.covers(repriced)
    with pytest.raises(AuthorizationRequired, match="MATERIAL_TERMS_CHANGED"):
        require_execution_authorization(repriced, _allow(), authorization, now)


def test_incidental_parameters_do_not_revoke_consent(owner: UserId, now: datetime) -> None:
    action = _action(owner, now, ActionDomain.PURCHASE, PermissionLevel.A3)
    authorization = _authorization(action, now, PermissionLevel.A3)
    retried = action.model_copy(update={"parameters": {"attempt": 2}})

    assert DEFAULT_EXECUTION_POLICY.authorize(retried, _allow(), authorization, now).is_permitted


def test_a_guardian_verdict_about_another_action_is_not_an_assessment(
    owner: UserId, now: datetime
) -> None:
    """Otherwise a BLOCK is bypassed by handing the gate an unrelated ALLOW."""
    action = _action(owner, now, ActionDomain.PURCHASE, PermissionLevel.A3)
    authorization = _authorization(action, now, PermissionLevel.A3)
    elsewhere = GuardianAssessment.allow(ActionId("act_unrelated"))

    decision = DEFAULT_EXECUTION_POLICY.authorize(action, elsewhere, authorization, now)

    assert decision.outcome is PolicyOutcome.DENY
    assert decision.has_reason(ReasonCode.GUARDIAN_ASSESSMENT_MISSING)


def test_consent_captured_under_a_block_never_becomes_valid(owner: UserId, now: datetime) -> None:
    action = _action(owner, now, ActionDomain.PURCHASE, PermissionLevel.A3)
    tainted = ExecutionAuthorization.for_action(
        action,
        authorization_id=AuthorizationId("aut_tainted"),
        granted_at=now,
        method=AuthorizationMethod.EXPLICIT_CONFIRMATION,
        guardian_verdict=GuardianVerdict.BLOCK,
        audit_ref="audit_x",
    )

    decision = DEFAULT_EXECUTION_POLICY.authorize(action, _allow(), tainted, now)

    assert decision.outcome is PolicyOutcome.DENY
    assert decision.has_reason(ReasonCode.GUARDIAN_BLOCKED)


def test_an_authorization_records_what_was_authorized(owner: UserId, now: datetime) -> None:
    action = _action(owner, now, ActionDomain.PURCHASE, PermissionLevel.A3)
    authorization = _authorization(action, now, PermissionLevel.A3)

    assert authorization.granted_by == action.owner_id
    assert authorization.action_id == action.action_id
    assert authorization.authorized_fingerprint == action.terms_fingerprint
    assert authorization.granted_level is PermissionLevel.A3
    assert authorization.method is AuthorizationMethod.EXPLICIT_CONFIRMATION
    assert authorization.guardian_verdict is GuardianVerdict.ALLOW
    assert authorization.granted_at == now
    assert authorization.expires_at is not None
    assert authorization.audit_ref is not None
