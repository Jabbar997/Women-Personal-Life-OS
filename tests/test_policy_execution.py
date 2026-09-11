from __future__ import annotations

from datetime import timedelta

import pytest

from wlos.agents.guardian import Guardian, GuardianReview
from wlos.agents.operator import ExecutionOutcome, ExecutionResult, Operator
from wlos.core.errors import AuthorizationRequiredError, GuardianVetoError
from wlos.events.catalog import EventType
from wlos.policy.decisions import PolicyOutcome, ReasonCode
from wlos.policy.execution import (
    ActionKind,
    AuthorizationMethod,
    ExecutionPolicy,
    ExecutionRequest,
    UserAuthorization,
)
from wlos.policy.guardian_verdict import GuardianDecision, GuardianVerdict
from wlos.policy.permissions import PermissionLevel
from wlos.policy.sensitivity_policy import ConsumerKind
from wlos.shared.identifiers import ActionId
from wlos.shared.sensitivity import Sensitivity


def _request(owner_id, kind: ActionKind, **overrides) -> ExecutionRequest:
    defaults = {
        "action_id": ActionId("act_test_1"),
        "owner_id": owner_id,
        "kind": kind,
        "description": "test action",
    }
    return ExecutionRequest(**{**defaults, **overrides})


def _executed(request: ExecutionRequest) -> ExecutionResult:
    return ExecutionResult(action_id=str(request.action_id), outcome=ExecutionOutcome.SUCCEEDED)


class RecordingExecutor:
    """Proves the side effect never happens when policy refuses the action."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, request: ExecutionRequest) -> ExecutionResult:
        self.calls.append(str(request.action_id))
        return _executed(request)


def test_guardian_block_prevents_operator_authorization(owner_id, now, bus):
    """Test 6: Guardian has veto authority; nothing downstream can overrule it."""
    request = _request(owner_id, ActionKind.PURCHASE, sensitivity=Sensitivity.S3)
    review = GuardianReview(action=request, amount=120.0, source_verified=False)
    guardian_decision = Guardian().review(review, at=now)

    assert guardian_decision.verdict is GuardianVerdict.BLOCK

    authorization = UserAuthorization(
        action_id=request.action_id,
        granted_by=owner_id,
        scope=ActionKind.PURCHASE,
        level=PermissionLevel.A3,
        method=AuthorizationMethod.USER_EXPLICIT_CONFIRMATION,
        granted_at=now,
    )
    decision = ExecutionPolicy.evaluate(
        request, guardian=guardian_decision, authorization=authorization, at=now
    )

    assert decision.outcome is PolicyOutcome.DENY
    assert ReasonCode.GUARDIAN_BLOCK in decision.reason_codes

    executor = RecordingExecutor()
    with pytest.raises(GuardianVetoError):
        Operator(bus).execute(
            request,
            guardian=guardian_decision,
            authorization=authorization,
            executor=executor,
            at=now,
        )

    assert executor.calls == []
    emitted = [event.event_type for event in bus.published()]
    assert EventType.OPERATOR_ACTION_REJECTED in emitted
    assert EventType.OPERATOR_ACTION_AUTHORIZED not in emitted
    assert EventType.OPERATOR_ACTION_STARTED not in emitted


def test_a2_action_without_authorization_fails(owner_id, now, bus):
    """Test 7: external actions never execute silently."""
    request = _request(owner_id, ActionKind.EXTERNAL_BOOKING, sensitivity=Sensitivity.S2)
    guardian_decision = GuardianDecision.allow(at=now)

    decision = ExecutionPolicy.evaluate(request, guardian=guardian_decision, at=now)
    assert request.effective_level is PermissionLevel.A2
    assert decision.outcome is PolicyOutcome.REQUIRE_CONFIRMATION
    assert ReasonCode.AUTHORIZATION_MISSING in decision.reason_codes

    executor = RecordingExecutor()
    with pytest.raises(AuthorizationRequiredError):
        Operator(bus).execute(request, guardian=guardian_decision, executor=executor, at=now)
    assert executor.calls == []


def test_a1_internal_action_executes(owner_id, now, bus):
    """Test 8: an internal action inside the operator's permission level runs."""
    request = _request(owner_id, ActionKind.INTERNAL_REMINDER)
    guardian_decision = GuardianDecision.allow(at=now)

    assert request.effective_level is PermissionLevel.A1

    result = Operator(bus).execute(request, guardian=guardian_decision, executor=_executed, at=now)

    assert result.outcome is ExecutionOutcome.SUCCEEDED
    emitted = [event.event_type for event in bus.published()]
    assert emitted == [
        EventType.OPERATOR_ACTION_PROPOSED,
        EventType.OPERATOR_ACTION_AUTHORIZED,
        EventType.OPERATOR_ACTION_STARTED,
        EventType.OPERATOR_ACTION_SUCCEEDED,
    ]
    assert all(
        event.correlation_id == bus.published()[0].correlation_id for event in bus.published()
    )


def test_a3_requires_explicit_confirmation_not_a_standing_rule(owner_id, now):
    request = _request(owner_id, ActionKind.PAYMENT, sensitivity=Sensitivity.S3)
    standing = UserAuthorization(
        action_id=request.action_id,
        granted_by=owner_id,
        scope=ActionKind.PAYMENT,
        level=PermissionLevel.A3,
        method=AuthorizationMethod.STANDING_RULE,
        granted_at=now,
    )

    decision = ExecutionPolicy.evaluate(
        request, guardian=GuardianDecision.allow(at=now), authorization=standing, at=now
    )

    assert decision.outcome is PolicyOutcome.DENY
    assert ReasonCode.EXPLICIT_CONFIRMATION_REQUIRED in decision.reason_codes


def test_expired_or_mismatched_authorization_is_refused(owner_id, now):
    request = _request(owner_id, ActionKind.EXTERNAL_MESSAGE)
    expired = UserAuthorization(
        action_id=request.action_id,
        granted_by=owner_id,
        scope=ActionKind.EXTERNAL_MESSAGE,
        level=PermissionLevel.A2,
        method=AuthorizationMethod.USER_CONFIRMATION,
        granted_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
    )
    decision = ExecutionPolicy.evaluate(
        request, guardian=GuardianDecision.allow(at=now), authorization=expired, at=now
    )
    assert ReasonCode.AUTHORIZATION_EXPIRED in decision.reason_codes

    wrong_scope = expired.model_copy(
        update={"scope": ActionKind.INTERNAL_UPDATE, "expires_at": None}
    )
    decision = ExecutionPolicy.evaluate(
        request, guardian=GuardianDecision.allow(at=now), authorization=wrong_scope, at=now
    )
    assert ReasonCode.AUTHORIZATION_SCOPE_MISMATCH in decision.reason_codes


def test_payment_cannot_be_reclassified_below_a3(owner_id):
    request = _request(owner_id, ActionKind.PAYMENT, requested_level=PermissionLevel.A1)
    assert request.effective_level is PermissionLevel.A3


def test_guardian_escalates_sensitive_sharing_and_medical_actions(owner_id, now):
    guardian = Guardian()

    sharing = guardian.review(
        GuardianReview(
            action=_request(owner_id, ActionKind.DATA_SHARING, sensitivity=Sensitivity.S3),
            recipient=ConsumerKind.EXTERNAL_RECIPIENT,
            shares_sensitivity=Sensitivity.S3,
        ),
        at=now,
    )
    assert sharing.verdict is GuardianVerdict.BLOCK

    medical = guardian.review(GuardianReview(action=_request(owner_id, ActionKind.MEDICAL)), at=now)
    assert medical.verdict is GuardianVerdict.ESCALATE
