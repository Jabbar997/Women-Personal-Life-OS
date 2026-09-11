"""Mobile-first constraints, and ADV-31.

The client is a phone that is often offline, often stale, and never the
authority. Nothing here builds a client; it checks the foundation does not
prevent one.
"""

import ast
from datetime import datetime, timedelta
from pathlib import Path

from wplos.agents.radar import RADAR_CONTRACT
from wplos.agents.readiness import READINESS_CONTRACT
from wplos.agents.registry import AGENT_CONTRACTS
from wplos.core.capabilities import CapabilitySet, CapabilityState, DeviceCapability
from wplos.core.client import ClientEventId, ClientRef, DeviceId, EventOrigin
from wplos.core.identifiers import (
    ActionId,
    AuthorizationId,
    EventId,
    NotificationId,
    UserId,
)
from wplos.core.money import Money
from wplos.core.roles import AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.events.payloads import CaptureKind, CapturePayload, MediaRef
from wplos.personal_life_graph.attributes import LocationPrecision, PlaceAttributes
from wplos.personal_life_graph.entity_types import EntityType
from wplos.policy.decisions import PolicyOutcome, ReasonCode
from wplos.policy.execution import (
    AuthorizationMethod,
    ExecutionAuthorization,
    ExecutionPolicy,
    ProposedAction,
)
from wplos.policy.guardian import GuardianCheck, GuardianFinding, GuardianVerdict
from wplos.policy.guardian_authority import GuardianAuthority
from wplos.policy.notification import (
    DEFAULT_NOTIFICATION_POLICY,
    DeliveryAttempt,
    DeliveryState,
    NotificationCandidate,
    NotificationUrgency,
)
from wplos.policy.permissions import ActionDomain, PermissionLevel, ReversibilityClass

SRC = Path(__file__).resolve().parents[1] / "src" / "wplos"

MOBILE_FRAMEWORKS = frozenset(
    {"flutter", "kivy", "toga", "beeware", "requests", "httpx", "aiohttp", "starlette", "uvicorn"}
)


# --- the domain knows nothing about a client ------------------------------


def test_the_domain_imports_no_client_or_transport_framework() -> None:
    offenders: list[str] = []
    for module in sorted(SRC.rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                roots.add(node.module.split(".")[0])
        hit = roots & MOBILE_FRAMEWORKS
        if hit:
            offenders.append(f"{module.relative_to(SRC)}: {sorted(hit)}")
    assert not offenders, offenders


def test_the_minds_are_declared_without_any_assumption_of_a_device() -> None:
    """Agents run server-side; a phone cannot be relied on to run them."""
    for contract in AGENT_CONTRACTS.values():
        assert contract.reads
        assert contract.required_policies


# --- event origin, idempotency, out-of-order sync -------------------------


def test_an_event_records_which_part_of_the_system_produced_it() -> None:
    assert {origin.value for origin in EventOrigin} == {
        "SERVER",
        "MOBILE_DEVICE",
        "CONNECTOR",
        "SYSTEM",
        "AI",
    }
    assert EventOrigin.MOBILE_DEVICE.is_remote_client
    assert not EventOrigin.SERVER.is_remote_client


def test_a_client_reference_carries_what_sync_needs_and_nothing_more(
    now: datetime,
) -> None:
    ref = ClientRef(
        client_event_id=ClientEventId("cev_1"),
        device_id=DeviceId("dev_1"),
        submitted_at=now,
        client_clock_skew_seconds=-4,
    )

    assert ref.client_event_id == ClientEventId("cev_1")
    assert ref.submitted_at == now
    # Device identity is transport, not domain: nothing in the graph is keyed by it.
    assert "device_id" not in PlaceAttributes.model_fields


def test_nothing_in_the_graph_is_keyed_by_a_device() -> None:
    from wplos.personal_life_graph.attributes import ATTRIBUTES_BY_TYPE

    for model in ATTRIBUTES_BY_TYPE.values():
        assert not any("device" in field or "session" in field for field in model.model_fields), (
            model
        )


# --- capture is not a text box -------------------------------------------


def test_capture_represents_voice_photos_screenshots_and_files() -> None:
    assert {kind.value for kind in CaptureKind} >= {
        "TEXT",
        "VOICE",
        "PHOTO",
        "SCREENSHOT",
        "DOCUMENT_FILE",
        "SHARE_SHEET",
    }


def test_media_is_referenced_never_carried(now: datetime) -> None:
    payload = CapturePayload(
        capture_id="cap_voice",
        kind=CaptureKind.VOICE,
        media=(
            MediaRef(
                media_id="med_1",
                media_type="audio/m4a",
                byte_size=184320,
                checksum="sha256:abc",
                storage_ref="blob://recordings/med_1",
                duration_seconds=12.5,
            ),
        ),
    )

    assert payload.media[0].storage_ref == "blob://recordings/med_1"
    # No field anywhere holds bytes.
    assert not any(field_info.annotation is bytes for field_info in MediaRef.model_fields.values())
    assert "bytes" not in payload.model_dump_json()


# --- notifications are a decision, not the truth --------------------------


def _candidate(
    owner: UserId, now: datetime, sensitivity: SensitivityLevel
) -> NotificationCandidate:
    return NotificationCandidate(
        notification_id=NotificationId("ntf_1"),
        owner_id=owner,
        triggered_by_event_id=EventId("evt_1"),
        title="Your cycle entered a new phase",
        body="Day 22, luteal",
        urgency=NotificationUrgency.NORMAL,
        sensitivity=sensitivity,
        created_at=now,
    )


def test_a_sensitive_notification_is_sent_without_its_content(owner: UserId, now: datetime) -> None:
    candidate = _candidate(owner, now, SensitivityLevel.S3)

    decision = DEFAULT_NOTIFICATION_POLICY.evaluate(candidate)
    prepared = DEFAULT_NOTIFICATION_POLICY.prepare(candidate)

    assert decision.outcome is PolicyOutcome.REQUIRE_CONFIRMATION
    assert decision.has_reason(ReasonCode.SHARED_CONTEXT_DISCLOSURE)
    assert "luteal" not in prepared.body
    assert "cycle" not in prepared.title.lower()
    assert prepared.notification_id == candidate.notification_id


def test_an_ordinary_notification_keeps_its_words(owner: UserId, now: datetime) -> None:
    candidate = _candidate(owner, now, SensitivityLevel.S1).model_copy(
        update={"title": "Return window closing", "body": "Four days left to return the bag."}
    )

    assert DEFAULT_NOTIFICATION_POLICY.evaluate(candidate).is_permitted
    assert DEFAULT_NOTIFICATION_POLICY.prepare(candidate).body.startswith("Four days")


def test_deciding_to_notify_is_separate_from_managing_to_deliver(
    owner: UserId, now: datetime
) -> None:
    candidate = _candidate(owner, now, SensitivityLevel.S1)
    dispatched = DeliveryAttempt(
        notification_id=candidate.notification_id, state=DeliveryState.DISPATCHED, at=now
    )
    failed = DeliveryAttempt(
        notification_id=candidate.notification_id,
        state=DeliveryState.FAILED,
        at=now + timedelta(seconds=2),
        detail="the push service rejected the token",
    )
    opened = DeliveryAttempt(
        notification_id=candidate.notification_id,
        state=DeliveryState.OPENED,
        at=now + timedelta(hours=5),
    )

    # Four distinct facts, none standing in for the others.
    assert candidate.triggered_by_event_id == EventId("evt_1")
    assert dispatched.state is DeliveryState.DISPATCHED
    assert failed.state is DeliveryState.FAILED
    assert opened.at > dispatched.at


def test_a_notification_points_at_something_stable_to_open(owner: UserId, now: datetime) -> None:
    candidate = _candidate(owner, now, SensitivityLevel.S1).model_copy(
        update={"deep_link_entity_id": "ent_stable"}
    )

    assert candidate.deep_link_entity_id == "ent_stable"
    assert DEFAULT_NOTIFICATION_POLICY.prepare(candidate).deep_link_entity_id == "ent_stable"


# --- permissions are capabilities, and absence is the default -------------


def test_no_permission_is_assumed_until_it_is_granted() -> None:
    fresh = CapabilitySet.none_granted()

    for capability in DeviceCapability:
        assert fresh.state_of(capability) is CapabilityState.NOT_REQUESTED
        assert not fresh.allows(capability)


def test_a_revoked_permission_reads_as_unusable_not_as_an_error() -> None:
    granted = CapabilitySet.none_granted().with_state(
        DeviceCapability.CALENDAR, CapabilityState.GRANTED
    )
    revoked = granted.with_state(DeviceCapability.CALENDAR, CapabilityState.REVOKED)

    assert granted.allows(DeviceCapability.CALENDAR)
    assert not revoked.allows(DeviceCapability.CALENDAR)
    assert revoked.state_of(DeviceCapability.CALENDAR) is CapabilityState.REVOKED
    assert revoked.granted() == frozenset()


def test_radar_and_readiness_work_without_precise_location() -> None:
    area_only = PlaceAttributes(city="Riyadh", area="Al Nakheel")

    assert area_only.precision is LocationPrecision.AREA
    assert area_only.sensitivity_floor() is None
    assert EntityType.PLACE in RADAR_CONTRACT.reads
    assert EntityType.PLACE in READINESS_CONTRACT.reads
    # Radar is not cleared for the precise fields at all.
    assert not RADAR_CONTRACT.max_sensitivity.dominates(SensitivityLevel.S3)


# --- ADV-31 — the stale screen -------------------------------------------


def _offer(
    owner: UserId, at: datetime, price: Money, starts_at: str, expires_at: datetime | None = None
) -> ProposedAction:
    return ProposedAction(
        action_id=ActionId("act_pilates"),
        owner_id=owner,
        proposed_by=AgentName.OPERATOR,
        proposed_at=at,
        domain=ActionDomain.PURCHASE,
        permission_level=PermissionLevel.A3,
        summary="Book a Pilates class",
        reversibility=ReversibilityClass.COMPENSATABLE,
        offer_expires_at=expires_at,
        material_terms={"price": price.as_terms(), "starts_at": starts_at},
    )


def test_a_stale_confirm_button_cannot_push_an_old_offer_through(
    owner: UserId, now: datetime
) -> None:
    """She opens the screen at 08:00, taps Confirm at 10:00, and by then the
    price, the time and the risk have all changed."""
    authority = GuardianAuthority(max_age=timedelta(hours=4))
    policy = ExecutionPolicy(authority)
    two_hours_later = now + timedelta(hours=2)

    shown_at_breakfast = _offer(owner, now, Money.of(10000, "SAR"), "2026-03-03T19:00:00Z")
    consent = ExecutionAuthorization.for_action(
        shown_at_breakfast,
        authorization_id=AuthorizationId("aut_1"),
        granted_at=now,
        method=AuthorizationMethod.EXPLICIT_CONFIRMATION,
        expires_at=now + timedelta(hours=6),
        audit_ref="audit_1",
    )

    # What the server derives now bears no resemblance to what the phone shows.
    current = _offer(owner, two_hours_later, Money.of(18000, "SAR"), "2026-03-03T20:00:00Z")
    fresh_verdict = authority.assess(
        action_id=current.action_id,
        fingerprint=current.terms_fingerprint,
        at=two_hours_later,
        findings=(
            GuardianFinding(
                check=GuardianCheck.FINANCIAL_RISK,
                verdict=GuardianVerdict.BLOCK,
                explanation="the price moved past her stated caution threshold",
            ),
        ),
    )

    decision = policy.authorize(current, fresh_verdict, consent, two_hours_later)

    assert decision.outcome is PolicyOutcome.DENY
    assert decision.has_reason(ReasonCode.GUARDIAN_BLOCKED)


def test_even_without_a_block_the_stale_terms_are_refused(owner: UserId, now: datetime) -> None:
    authority = GuardianAuthority(max_age=timedelta(hours=4))
    policy = ExecutionPolicy(authority)
    two_hours_later = now + timedelta(hours=2)

    shown = _offer(owner, now, Money.of(10000, "SAR"), "2026-03-03T19:00:00Z")
    consent = ExecutionAuthorization.for_action(
        shown,
        authorization_id=AuthorizationId("aut_1"),
        granted_at=now,
        method=AuthorizationMethod.EXPLICIT_CONFIRMATION,
        expires_at=now + timedelta(hours=6),
        audit_ref="audit_1",
    )
    current = _offer(owner, two_hours_later, Money.of(18000, "SAR"), "2026-03-03T20:00:00Z")

    decision = policy.authorize(
        current,
        authority.allow(
            action_id=current.action_id,
            fingerprint=current.terms_fingerprint,
            at=two_hours_later,
        ),
        consent,
        two_hours_later,
    )

    assert decision.outcome is PolicyOutcome.DENY
    assert decision.has_reason(ReasonCode.MATERIAL_TERMS_CHANGED)


def test_an_offer_that_has_lapsed_is_not_executed_even_unchanged(
    owner: UserId, now: datetime
) -> None:
    authority = GuardianAuthority(max_age=timedelta(hours=4))
    policy = ExecutionPolicy(authority)
    two_hours_later = now + timedelta(hours=2)

    offer = _offer(
        owner,
        now,
        Money.of(10000, "SAR"),
        "2026-03-03T19:00:00Z",
        expires_at=now + timedelta(minutes=30),
    )
    consent = ExecutionAuthorization.for_action(
        offer,
        authorization_id=AuthorizationId("aut_1"),
        granted_at=now,
        method=AuthorizationMethod.EXPLICIT_CONFIRMATION,
        expires_at=now + timedelta(hours=6),
        audit_ref="audit_1",
    )

    decision = policy.authorize(
        offer,
        authority.allow(
            action_id=offer.action_id, fingerprint=offer.terms_fingerprint, at=two_hours_later
        ),
        consent,
        two_hours_later,
    )

    assert decision.outcome is PolicyOutcome.REQUIRE_CONFIRMATION
    assert decision.has_reason(ReasonCode.OFFER_EXPIRED)
    assert offer.offer_expired_at(two_hours_later)


def test_availability_is_the_servers_question_and_consent_alone_answers_nothing(
    owner: UserId, now: datetime
) -> None:
    """When the slot is gone the server derives no offer, and consent on its own
    is not an instruction: the gate is only ever given a live action."""
    shown_on_the_phone = _offer(owner, now, Money.of(10000, "SAR"), "2026-03-03T19:00:00Z")
    consent = ExecutionAuthorization.for_action(
        shown_on_the_phone,
        authorization_id=AuthorizationId("aut_1"),
        granted_at=now,
        method=AuthorizationMethod.EXPLICIT_CONFIRMATION,
        audit_ref="audit_1",
    )
    live_offers: dict[ActionId, ProposedAction] = {}

    current = live_offers.get(shown_on_the_phone.action_id)

    assert current is None, "the slot is no longer offered"
    # Consent names an action; with no live action there is nothing to authorize,
    # and the stale copy the phone holds is not a substitute for one.
    assert consent.action_id == shown_on_the_phone.action_id
    assert consent.covers(shown_on_the_phone)
    replacement = _offer(owner, now, Money.of(10000, "SAR"), "2026-03-05T19:00:00Z")
    assert not consent.covers(replacement)
