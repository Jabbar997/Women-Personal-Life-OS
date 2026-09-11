"""ADV-09 to 14 and 25 to 28 — consent, verdicts, retries and undo."""

from datetime import datetime, timedelta

import pytest

from scenario_helpers import emit
from wplos.core.identifiers import ActionId, AttemptId, AuthorizationId, UserId
from wplos.core.identifiers import IdempotencyKeyLike as Key
from wplos.core.money import Money
from wplos.core.roles import AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.events.bus import InMemoryEventBus
from wplos.events.payloads import (
    OperatorActionPayload,
    OperatorActionResultPayload,
    OperatorOutcomeUnknownPayload,
    OperatorPartialOutcomePayload,
)
from wplos.events.types import EventType
from wplos.policy.decisions import PolicyOutcome, ReasonCode
from wplos.policy.execution import (
    AuthorizationMethod,
    ExecutionAuthorization,
    ExecutionPolicy,
    ProposedAction,
)
from wplos.policy.execution_state import (
    ExecutionAttempt,
    ExecutionState,
    ExecutionStep,
    may_transition,
)
from wplos.policy.guardian import (
    GuardianAssessment,
    GuardianCheck,
    GuardianFinding,
    GuardianVerdict,
)
from wplos.policy.guardian_authority import GuardianAuthority
from wplos.policy.permissions import ActionDomain, PermissionLevel, ReversibilityClass
from wplos.shared.errors import InvariantViolation

PILATES = ActionId("act_pilates")


def _pilates(
    owner: UserId,
    now: datetime,
    *,
    price: Money | None = None,
    starts_at: str = "2026-03-03T19:00:00Z",
    merchant: str = "branch-a",
    quantity: int = 1,
    target: str | None = None,
    location: str = "riyadh-nakheel",
    offer_expires_at: datetime | None = None,
) -> ProposedAction:
    return ProposedAction(
        action_id=PILATES,
        owner_id=owner,
        proposed_by=AgentName.OPERATOR,
        proposed_at=now,
        domain=ActionDomain.PURCHASE,
        permission_level=PermissionLevel.A3,
        summary="Book a Pilates class",
        reversibility=ReversibilityClass.COMPENSATABLE,
        target_entity_id=target,  # type: ignore[arg-type]
        offer_expires_at=offer_expires_at,
        material_terms={
            "price": (price or Money.of(10000, "SAR")).as_terms(),
            "starts_at": starts_at,
            "merchant": merchant,
            "quantity": quantity,
            "location": location,
        },
    )


def _authority() -> GuardianAuthority:
    return GuardianAuthority()


def _consent(
    action: ProposedAction, now: datetime, *, expires_in: timedelta = timedelta(minutes=15)
) -> ExecutionAuthorization:
    return ExecutionAuthorization.for_action(
        action,
        authorization_id=AuthorizationId("aut_pilates"),
        granted_at=now,
        method=AuthorizationMethod.EXPLICIT_CONFIRMATION,
        expires_at=now + expires_in,
        audit_ref="audit_pilates",
    )


# --- ADV-12 — which terms are material ------------------------------------


@pytest.mark.parametrize(
    ("label", "changes"),
    [
        ("date", {"starts_at": "2026-03-04T19:00:00Z"}),
        ("time", {"starts_at": "2026-03-03T20:00:00Z"}),
        ("price", {"price": Money.of(18000, "SAR")}),
        ("merchant", {"merchant": "branch-b"}),
        ("quantity", {"quantity": 2}),
        ("location", {"location": "riyadh-olaya"}),
    ],
)
def test_changing_any_material_term_invalidates_consent(
    owner: UserId, now: datetime, label: str, changes: dict[str, object]
) -> None:
    authority = _authority()
    policy = ExecutionPolicy(authority)
    agreed = _pilates(owner, now)
    consent = _consent(agreed, now)
    changed = _pilates(owner, now, **changes)  # type: ignore[arg-type]

    verdict = authority.allow(
        action_id=changed.action_id, fingerprint=changed.terms_fingerprint, at=now
    )
    decision = policy.authorize(changed, verdict, consent, now)

    assert decision.outcome is PolicyOutcome.DENY, label
    assert decision.has_reason(ReasonCode.MATERIAL_TERMS_CHANGED), label


def test_changing_the_target_invalidates_consent(owner: UserId, now: datetime) -> None:
    authority = _authority()
    policy = ExecutionPolicy(authority)
    agreed = _pilates(owner, now, target="ent_slot_a")
    consent = _consent(agreed, now)
    elsewhere = _pilates(owner, now, target="ent_slot_b")

    decision = policy.authorize(
        elsewhere,
        authority.allow(
            action_id=elsewhere.action_id, fingerprint=elsewhere.terms_fingerprint, at=now
        ),
        consent,
        now,
    )

    assert decision.outcome is PolicyOutcome.DENY
    assert decision.has_reason(ReasonCode.MATERIAL_TERMS_CHANGED)


def test_the_unchanged_action_still_goes_through(owner: UserId, now: datetime) -> None:
    authority = _authority()
    policy = ExecutionPolicy(authority)
    agreed = _pilates(owner, now)
    consent = _consent(agreed, now)

    decision = policy.authorize(
        agreed,
        authority.allow(action_id=PILATES, fingerprint=agreed.terms_fingerprint, at=now),
        consent,
        now,
    )

    assert decision.is_permitted


# --- ADV-10 / ADV-11 — expiry and revocation ------------------------------


def test_consent_does_not_last_forever(owner: UserId, now: datetime) -> None:
    authority = _authority()
    policy = ExecutionPolicy(authority)
    action = _pilates(owner, now)
    consent = _consent(action, now, expires_in=timedelta(minutes=15))
    much_later = now + timedelta(days=3)

    decision = policy.authorize(
        action,
        authority.allow(action_id=PILATES, fingerprint=action.terms_fingerprint, at=much_later),
        consent,
        much_later,
    )

    assert decision.outcome is PolicyOutcome.REQUIRE_CONFIRMATION
    assert decision.has_reason(ReasonCode.AUTHORIZATION_EXPIRED)
    assert consent.is_expired_at(much_later)


def test_withdrawn_consent_stops_execution_even_a_moment_before_it(
    owner: UserId, now: datetime
) -> None:
    authority = _authority()
    policy = ExecutionPolicy(authority)
    action = _pilates(owner, now)
    consent = _consent(action, now)
    a_moment_later = now + timedelta(seconds=1)

    revoked = consent.revoked(at=a_moment_later, reason="she said to leave it")
    decision = policy.authorize(
        action,
        authority.allow(action_id=PILATES, fingerprint=action.terms_fingerprint, at=a_moment_later),
        revoked,
        a_moment_later,
    )

    assert decision.outcome is PolicyOutcome.DENY
    assert decision.has_reason(ReasonCode.AUTHORIZATION_REVOKED)
    assert revoked.is_revoked
    assert revoked.revocation_reason == "she said to leave it"
    # The original consent is not rewritten; the revocation is a new fact.
    assert not consent.is_revoked


# --- ADV-13 / ADV-14 — the verdict itself ---------------------------------


def test_a_newer_verdict_retires_the_one_that_came_before_it(owner: UserId, now: datetime) -> None:
    authority = _authority()
    policy = ExecutionPolicy(authority)
    action = _pilates(owner, now)
    consent = _consent(action, now)

    old_allow = authority.allow(action_id=PILATES, fingerprint=action.terms_fingerprint, at=now)
    authority.assess(
        action_id=PILATES,
        fingerprint=action.terms_fingerprint,
        at=now + timedelta(minutes=1),
        findings=(
            GuardianFinding(
                check=GuardianCheck.FRAUD,
                verdict=GuardianVerdict.BLOCK,
                explanation="the merchant was flagged since",
            ),
        ),
    )

    decision = policy.authorize(action, old_allow, consent, now + timedelta(minutes=2))

    assert decision.outcome is PolicyOutcome.DENY
    assert decision.has_reason(ReasonCode.GUARDIAN_ASSESSMENT_SUPERSEDED)
    assert authority.is_superseded(old_allow)


def test_a_verdict_goes_stale_on_its_own(owner: UserId, now: datetime) -> None:
    authority = GuardianAuthority(max_age=timedelta(minutes=5))
    policy = ExecutionPolicy(authority)
    action = _pilates(owner, now)
    consent = _consent(action, now, expires_in=timedelta(days=1))
    verdict = authority.allow(action_id=PILATES, fingerprint=action.terms_fingerprint, at=now)

    decision = policy.authorize(action, verdict, consent, now + timedelta(hours=2))

    assert decision.outcome is PolicyOutcome.REQUIRE_CONFIRMATION
    assert decision.has_reason(ReasonCode.GUARDIAN_ASSESSMENT_STALE)


def test_a_verdict_nobody_issued_is_not_a_verdict(owner: UserId, now: datetime) -> None:
    authority = _authority()
    policy = ExecutionPolicy(authority)
    action = _pilates(owner, now)
    consent = _consent(action, now)

    home_made = GuardianAssessment(
        subject_action_id=PILATES,
        subject_fingerprint=action.terms_fingerprint,
        verdict=GuardianVerdict.ALLOW,
        assessed_at=now,
    )
    decision = policy.authorize(action, home_made, consent, now)

    assert decision.outcome is PolicyOutcome.DENY
    assert decision.has_reason(ReasonCode.GUARDIAN_ASSESSMENT_FORGED)
    assert not authority.is_authentic(home_made)


def test_a_verdict_edited_after_issue_stops_verifying(owner: UserId, now: datetime) -> None:
    authority = _authority()
    action = _pilates(owner, now)
    blocked = authority.assess(
        action_id=PILATES,
        fingerprint=action.terms_fingerprint,
        at=now,
        findings=(
            GuardianFinding(
                check=GuardianCheck.FINANCIAL_RISK,
                verdict=GuardianVerdict.BLOCK,
                explanation="too much",
            ),
        ),
    )

    tampered = blocked.model_copy(update={"verdict": GuardianVerdict.ALLOW})

    assert authority.is_authentic(blocked)
    assert not authority.is_authentic(tampered)


def test_only_guardian_can_be_named_as_the_issuer() -> None:
    with pytest.raises(ValueError, match="only Guardian issues"):
        GuardianAssessment(verdict=GuardianVerdict.ALLOW, issued_by=AgentName.RADAR)


# --- ADV-09 — a correction after the thing already happened ---------------


def test_a_correction_after_execution_does_not_unmake_the_execution(
    owner: UserId, now: datetime
) -> None:
    bus = InMemoryEventBus()
    executed = bus.publish(
        emit(
            EventType.OPERATOR_ACTION_SUCCEEDED,
            OperatorActionResultPayload(action_id=PILATES, detail="booked Tuesday 19:00"),
            owner,
            now,
            agent=AgentName.OPERATOR,
            sensitivity=SensitivityLevel.S2,
        )
    )
    compensating = bus.publish(
        executed.caused(
            event_type=EventType.OPERATOR_ACTION_PROPOSED,
            payload=OperatorActionPayload(
                action_id=ActionId("act_rebook"),
                domain=ActionDomain.PURCHASE,
                permission_level=PermissionLevel.A3,
            ),
            actor=executed.actor,
            source=executed.source,
            sensitivity=SensitivityLevel.S2,
            occurred_at=now + timedelta(minutes=10),
        )
    )

    # Tuesday still happened; Wednesday is a new action that must be authorized.
    assert bus.events_of(EventType.OPERATOR_ACTION_SUCCEEDED) == (executed,)
    assert compensating.causation_id == executed.event_id
    payload = compensating.payload
    assert isinstance(payload, OperatorActionPayload)
    assert payload.action_id != PILATES
    assert payload.permission_level is PermissionLevel.A3


# --- ADV-25 / ADV-26 — the world does not answer --------------------------


def test_a_timeout_is_unknown_not_failed(owner: UserId, now: datetime) -> None:
    attempt = ExecutionAttempt(
        attempt_id=AttemptId("att_1"),
        action_id=PILATES,
        idempotency_key=Key("idem_pilates_1"),
        attempt_number=1,
        state=ExecutionState.STARTED,
        started_at=now,
    )

    timed_out = attempt.settled(state=ExecutionState.UNKNOWN, at=now + timedelta(seconds=30))

    assert timed_out.state is ExecutionState.UNKNOWN
    assert timed_out.state.touched_the_world
    assert not timed_out.may_retry_safely
    assert not timed_out.state.is_terminal


def test_a_retry_reuses_the_idempotency_key_of_the_action(owner: UserId, now: datetime) -> None:
    first = ExecutionAttempt(
        attempt_id=AttemptId("att_1"),
        action_id=PILATES,
        idempotency_key=Key("idem_pilates_1"),
        attempt_number=1,
        state=ExecutionState.STARTED,
        started_at=now,
    )
    retry = first.model_copy(
        update={
            "attempt_id": AttemptId("att_2"),
            "attempt_number": 2,
            "started_at": now + timedelta(minutes=1),
        }
    )

    assert retry.idempotency_key == first.idempotency_key
    assert retry.attempt_number == 2
    assert retry.action_id == first.action_id


def test_an_unknown_outcome_is_announced_with_its_key(owner: UserId, now: datetime) -> None:
    bus = InMemoryEventBus()
    event = bus.publish(
        emit(
            EventType.OPERATOR_ACTION_OUTCOME_UNKNOWN,
            OperatorOutcomeUnknownPayload(
                action_id=PILATES,
                attempt_id=AttemptId("att_1"),
                idempotency_key=Key("idem_pilates_1"),
                detail="the studio's system did not answer",
            ),
            owner,
            now,
            agent=AgentName.OPERATOR,
        )
    )

    payload = event.payload
    assert isinstance(payload, OperatorOutcomeUnknownPayload)
    assert payload.idempotency_key == Key("idem_pilates_1")


def test_a_partial_outcome_is_neither_success_nor_failure(owner: UserId, now: datetime) -> None:
    attempt = ExecutionAttempt(
        attempt_id=AttemptId("att_1"),
        action_id=PILATES,
        idempotency_key=Key("idem_pilates_1"),
        attempt_number=1,
        state=ExecutionState.STARTED,
        started_at=now,
    )

    settled = attempt.settled(
        state=ExecutionState.PARTIALLY_SUCCEEDED,
        at=now + timedelta(seconds=5),
        steps=(
            ExecutionStep(name="book_class", state=ExecutionState.SUCCEEDED),
            ExecutionStep(
                name="write_calendar", state=ExecutionState.FAILED, detail="calendar refused"
            ),
        ),
    )

    assert settled.state is ExecutionState.PARTIALLY_SUCCEEDED
    assert [step.name for step in settled.succeeded_steps()] == ["book_class"]
    assert [step.name for step in settled.failed_steps()] == ["write_calendar"]
    assert settled.state.touched_the_world
    assert may_transition(settled.state, ExecutionState.COMPENSATED)


def test_a_partial_outcome_reports_both_halves(owner: UserId, now: datetime) -> None:
    bus = InMemoryEventBus()
    event = bus.publish(
        emit(
            EventType.OPERATOR_ACTION_PARTIALLY_SUCCEEDED,
            OperatorPartialOutcomePayload(
                action_id=PILATES,
                attempt_id=AttemptId("att_1"),
                succeeded_steps=("book_class",),
                failed_steps=("write_calendar",),
            ),
            owner,
            now,
            agent=AgentName.OPERATOR,
        )
    )

    payload = event.payload
    assert isinstance(payload, OperatorPartialOutcomePayload)
    assert payload.succeeded_steps == ("book_class",)
    assert payload.failed_steps == ("write_calendar",)


def test_an_illegal_transition_is_refused(owner: UserId, now: datetime) -> None:
    done = ExecutionAttempt(
        attempt_id=AttemptId("att_1"),
        action_id=PILATES,
        idempotency_key=Key("idem_1"),
        attempt_number=1,
        state=ExecutionState.SUCCEEDED,
        started_at=now,
    )

    with pytest.raises(InvariantViolation, match="cannot become"):
        done.settled(state=ExecutionState.STARTED, at=now)


# --- ADV-27 / ADV-28 — undo, and the lie of undo -------------------------


def test_undoing_a_booking_is_a_new_action_not_a_deletion(owner: UserId, now: datetime) -> None:
    bus = InMemoryEventBus()
    succeeded = bus.publish(
        emit(
            EventType.OPERATOR_ACTION_SUCCEEDED,
            OperatorActionResultPayload(action_id=PILATES, attempt_id=AttemptId("att_1")),
            owner,
            now,
            agent=AgentName.OPERATOR,
        )
    )
    reversed_event = bus.publish(
        succeeded.caused(
            event_type=EventType.OPERATOR_ACTION_REVERSED,
            payload=OperatorActionResultPayload(
                action_id=PILATES, detail="cancelled at her request"
            ),
            actor=succeeded.actor,
            source=succeeded.source,
            sensitivity=SensitivityLevel.S2,
            occurred_at=now + timedelta(hours=1),
        )
    )

    assert len(bus.log) == 2
    assert reversed_event.causation_id == succeeded.event_id
    assert bus.events_of(EventType.OPERATOR_ACTION_SUCCEEDED) == (succeeded,)
    assert may_transition(ExecutionState.SUCCEEDED, ExecutionState.REVERSED)


def test_a_sent_message_is_never_offered_as_undoable(owner: UserId, now: datetime) -> None:
    message = ProposedAction(
        action_id=ActionId("act_message"),
        owner_id=owner,
        proposed_by=AgentName.OPERATOR,
        proposed_at=now,
        domain=ActionDomain.SENSITIVE_COMMUNICATION,
        permission_level=PermissionLevel.A3,
        summary="Send a message",
        reversibility=ReversibilityClass.IRREVERSIBLE,
    )
    booking = _pilates(owner, now)

    assert not message.reversibility.offers_undo
    assert not message.reversibility.offers_compensation
    assert not booking.reversibility.offers_undo
    assert booking.reversibility.offers_compensation
