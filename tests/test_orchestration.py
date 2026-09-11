from __future__ import annotations

from datetime import timedelta

from wlos.agents.contracts import DecisionState, PriorityClass
from wlos.core.minds import Mind
from wlos.orchestration.conflict import Claim, ConflictResolutionPolicy
from wlos.orchestration.contract import ORCHESTRATOR_CONTRACT
from wlos.policy.guardian_verdict import GuardianVerdict
from wlos.shared.temporal import TemporalWindow


def _window(start, hours: float) -> TemporalWindow:
    return TemporalWindow(valid_from=start, valid_until=start + timedelta(hours=hours))


def test_radar_opportunity_cannot_override_a_commitment(now):
    """Test 9: an opportunity never displaces something the user committed to."""
    commitment = Claim(
        mind=Mind.LIFE_ADMIN,
        decision_state=DecisionState.RECOMMEND,
        priority=PriorityClass.P1,
        subject="clinic appointment",
        window=_window(now, 2),
        binding=True,
    )
    opportunity = Claim(
        mind=Mind.RADAR,
        decision_state=DecisionState.ACT,
        priority=PriorityClass.P2,
        subject="pop-up sample sale",
        window=_window(now + timedelta(minutes=30), 1),
    )

    resolution = ConflictResolutionPolicy().resolve([commitment, opportunity])

    assert resolution.accepted == (commitment,)
    assert resolution.state_of(commitment) is DecisionState.RECOMMEND
    assert resolution.state_of(opportunity) is DecisionState.SURFACE


def test_guardian_block_outranks_every_other_claim(now):
    blocked = Claim(
        mind=Mind.GUARDIAN,
        decision_state=DecisionState.SURFACE,
        priority=PriorityClass.P0,
        subject="unverified payment link",
        guardian_verdict=GuardianVerdict.BLOCK,
    )
    navigator = Claim(
        mind=Mind.NAVIGATOR,
        decision_state=DecisionState.RECOMMEND,
        priority=PriorityClass.P1,
        subject="unverified payment link",
    )

    resolution = ConflictResolutionPolicy().resolve([navigator, blocked])

    assert resolution.accepted == (blocked,)
    assert resolution.state_of(navigator) is DecisionState.SURFACE


def test_non_overlapping_claims_both_stand(now):
    morning = Claim(
        mind=Mind.LIFE_ADMIN,
        decision_state=DecisionState.RECOMMEND,
        priority=PriorityClass.P1,
        subject="renew the passport",
        window=_window(now, 1),
        binding=True,
    )
    evening = Claim(
        mind=Mind.RADAR,
        decision_state=DecisionState.RECOMMEND,
        priority=PriorityClass.P3,
        subject="ceramics workshop",
        window=_window(now + timedelta(hours=6), 2),
    )

    resolution = ConflictResolutionPolicy().resolve([morning, evening])

    assert set(resolution.accepted) == {morning, evening}


def test_ranking_is_configurable_rather_than_hard_coded(now):
    readiness = Claim(
        mind=Mind.READINESS,
        decision_state=DecisionState.RECOMMEND,
        priority=PriorityClass.P2,
        subject="leave by 18:10",
        window=_window(now, 1),
    )
    navigator = Claim(
        mind=Mind.NAVIGATOR,
        decision_state=DecisionState.RECOMMEND,
        priority=PriorityClass.P2,
        subject="leave by 18:10",
        window=_window(now, 1),
    )

    default_policy = ConflictResolutionPolicy()
    assert default_policy.accepted_first(navigator, readiness) is navigator

    readiness_first = ConflictResolutionPolicy(rank={**default_policy.rank, Mind.READINESS: 0})
    assert readiness_first.accepted_first(navigator, readiness) is readiness


def test_orchestrator_owns_coordination_only():
    assert "guardian enforcement" in ORCHESTRATOR_CONTRACT.responsibilities
    assert "owning a business domain of its own" in ORCHESTRATOR_CONTRACT.forbidden
