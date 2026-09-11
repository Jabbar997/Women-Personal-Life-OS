"""Test 9: a discovered opportunity does not displace an existing commitment."""

from wplos.agents.contracts import DecisionState, PriorityClass
from wplos.core.confidence import Confidence
from wplos.core.roles import AgentName
from wplos.orchestration.conflict import (
    DEFAULT_CONFLICT_POLICY,
    Claim,
    ClaimNature,
    ConflictResolutionPolicy,
    NaturePrecedenceRule,
)
from wplos.policy.guardian import GuardianVerdict

SUBJECT = "thursday-19:00"


def _commitment() -> Claim:
    return Claim(
        claim_id="claim_commitment",
        agent=AgentName.LIFE_ADMIN,
        subject=SUBJECT,
        nature=ClaimNature.COMMITMENT,
        decision_state=DecisionState.SURFACE,
        priority=PriorityClass.P2,
        statement="Dinner with her sister, promised last week",
        confidence=Confidence.certain(),
    )


def _opportunity(priority: PriorityClass = PriorityClass.P1) -> Claim:
    return Claim(
        claim_id="claim_opportunity",
        agent=AgentName.RADAR,
        subject=SUBJECT,
        nature=ClaimNature.OPPORTUNITY,
        decision_state=DecisionState.RECOMMEND,
        priority=priority,
        statement="A one-night pottery workshop nearby",
        confidence=Confidence.probabilistic(0.9),
    )


def test_radar_opportunity_cannot_override_a_commitment() -> None:
    resolution = DEFAULT_CONFLICT_POLICY.resolve((_commitment(), _opportunity()))

    winner = resolution.winner_for(SUBJECT)
    assert winner is not None
    assert winner.agent is AgentName.LIFE_ADMIN
    assert resolution.was_suppressed("claim_opportunity")
    assert resolution.suppressed[0].rule == "commitment_over_opportunity"


def test_the_commitment_wins_regardless_of_claim_order() -> None:
    resolution = DEFAULT_CONFLICT_POLICY.resolve((_opportunity(), _commitment()))

    winner = resolution.winner_for(SUBJECT)
    assert winner is not None
    assert winner.claim_id == "claim_commitment"


def test_a_safety_claim_outranks_a_commitment() -> None:
    safety = Claim(
        claim_id="claim_safety",
        agent=AgentName.GUARDIAN,
        subject=SUBJECT,
        nature=ClaimNature.CONSTRAINT,
        decision_state=DecisionState.SURFACE,
        priority=PriorityClass.P0,
        statement="Travel advisory for the venue's area",
        confidence=Confidence.certain(),
        guardian_verdict=GuardianVerdict.BLOCK,
    )

    resolution = DEFAULT_CONFLICT_POLICY.resolve((_commitment(), safety))

    winner = resolution.winner_for(SUBJECT)
    assert winner is not None
    assert winner.agent is AgentName.GUARDIAN
    assert resolution.suppressed[0].rule == "guardian_veto"


def test_claims_on_different_subjects_both_stand() -> None:
    other = _opportunity().model_copy(update={"subject": "saturday-11:00"})

    resolution = DEFAULT_CONFLICT_POLICY.resolve((_commitment(), other))

    assert len(resolution.surviving) == 2
    assert resolution.suppressed == ()


def test_the_precedence_chain_is_replaceable_not_hard_coded() -> None:
    opportunity_first = ConflictResolutionPolicy(
        rules=(
            NaturePrecedenceRule(
                {
                    ClaimNature.OPPORTUNITY: 0,
                    ClaimNature.CONSTRAINT: 1,
                    ClaimNature.PRIORITY: 2,
                    ClaimNature.COMMITMENT: 3,
                    ClaimNature.PREPARATION: 4,
                    ClaimNature.EXECUTION: 5,
                }
            ),
        )
    )

    resolution = opportunity_first.resolve((_commitment(), _opportunity()))

    winner = resolution.winner_for(SUBJECT)
    assert winner is not None
    assert winner.agent is AgentName.RADAR
