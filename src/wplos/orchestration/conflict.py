from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from wplos.agents.contracts import DecisionState, PriorityClass
from wplos.core.confidence import Confidence
from wplos.core.roles import AgentName
from wplos.policy.guardian import GuardianVerdict


class ClaimNature(StrEnum):
    """What kind of pull a claim exerts.

    Resolution keys off nature rather than off which mind spoke, so precedence
    can evolve without rewriting every rule.
    """

    CONSTRAINT = "CONSTRAINT"
    PRIORITY = "PRIORITY"
    COMMITMENT = "COMMITMENT"
    PREPARATION = "PREPARATION"
    OPPORTUNITY = "OPPORTUNITY"
    EXECUTION = "EXECUTION"


class Claim(BaseModel):
    """One mind's bid on one contested subject."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: str
    agent: AgentName
    subject: str
    nature: ClaimNature
    decision_state: DecisionState
    priority: PriorityClass
    statement: str
    confidence: Confidence
    guardian_verdict: GuardianVerdict | None = None


class ConflictRule(Protocol):
    """A single, replaceable arbitration step."""

    @property
    def name(self) -> str: ...

    def arbitrate(self, left: Claim, right: Claim) -> Claim | None: ...


class GuardianVetoRule:
    name = "guardian_veto"

    def arbitrate(self, left: Claim, right: Claim) -> Claim | None:
        for candidate, other in ((left, right), (right, left)):
            if candidate.agent is AgentName.GUARDIAN and candidate.guardian_verdict is not None:
                if not candidate.guardian_verdict.permits_execution:
                    return candidate
                if other.nature is ClaimNature.EXECUTION:
                    return None
        return None


class SafetyPriorityRule:
    name = "safety_priority"

    def arbitrate(self, left: Claim, right: Claim) -> Claim | None:
        if left.priority is PriorityClass.P0 and right.priority is not PriorityClass.P0:
            return left
        if right.priority is PriorityClass.P0 and left.priority is not PriorityClass.P0:
            return right
        return None


class CommitmentOverOpportunityRule:
    """An existing commitment is not displaced by something newly discovered."""

    name = "commitment_over_opportunity"

    def arbitrate(self, left: Claim, right: Claim) -> Claim | None:
        if left.nature is ClaimNature.COMMITMENT and right.nature is ClaimNature.OPPORTUNITY:
            return left
        if right.nature is ClaimNature.COMMITMENT and left.nature is ClaimNature.OPPORTUNITY:
            return right
        return None


NATURE_PRECEDENCE: dict[ClaimNature, int] = {
    ClaimNature.CONSTRAINT: 0,
    ClaimNature.PRIORITY: 1,
    ClaimNature.COMMITMENT: 2,
    ClaimNature.PREPARATION: 3,
    ClaimNature.EXECUTION: 4,
    ClaimNature.OPPORTUNITY: 5,
}


class NaturePrecedenceRule:
    name = "nature_precedence"

    def __init__(self, precedence: dict[ClaimNature, int] | None = None) -> None:
        self._precedence = precedence or NATURE_PRECEDENCE

    def arbitrate(self, left: Claim, right: Claim) -> Claim | None:
        left_rank = self._precedence[left.nature]
        right_rank = self._precedence[right.nature]
        if left_rank == right_rank:
            return None
        return left if left_rank < right_rank else right


class PriorityClassRule:
    name = "priority_class"

    def arbitrate(self, left: Claim, right: Claim) -> Claim | None:
        if left.priority is right.priority:
            return None
        return left if left.priority.outranks(right.priority) else right


class ConfidenceRule:
    name = "confidence"

    def arbitrate(self, left: Claim, right: Claim) -> Claim | None:
        if left.confidence.score == right.confidence.score:
            return None
        return left if left.confidence.score > right.confidence.score else right


class SuppressedClaim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: Claim
    lost_to: str
    rule: str


class ConflictResolution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    surviving: tuple[Claim, ...] = Field(default_factory=tuple)
    suppressed: tuple[SuppressedClaim, ...] = Field(default_factory=tuple)

    def winner_for(self, subject: str) -> Claim | None:
        return next((claim for claim in self.surviving if claim.subject == subject), None)

    def was_suppressed(self, claim_id: str) -> bool:
        return any(item.claim.claim_id == claim_id for item in self.suppressed)


class ConflictResolutionPolicy:
    """An ordered, replaceable list of rules rather than one hard-coded chain."""

    name = "orchestration.conflict"

    def __init__(self, rules: tuple[ConflictRule, ...] | None = None) -> None:
        self.rules: tuple[ConflictRule, ...] = rules or (
            GuardianVetoRule(),
            SafetyPriorityRule(),
            CommitmentOverOpportunityRule(),
            NaturePrecedenceRule(),
            PriorityClassRule(),
            ConfidenceRule(),
        )

    def arbitrate(self, left: Claim, right: Claim) -> tuple[Claim, Claim, str] | None:
        """Return (winner, loser, rule) or None when both may stand."""
        for rule in self.rules:
            winner = rule.arbitrate(left, right)
            if winner is not None:
                loser = right if winner is left else left
                return winner, loser, rule.name
        return None

    def resolve(self, claims: tuple[Claim, ...]) -> ConflictResolution:
        surviving: list[Claim] = []
        suppressed: list[SuppressedClaim] = []
        by_subject: dict[str, list[Claim]] = {}
        for claim in claims:
            by_subject.setdefault(claim.subject, []).append(claim)

        for subject_claims in by_subject.values():
            leader = subject_claims[0]
            for challenger in subject_claims[1:]:
                outcome = self.arbitrate(leader, challenger)
                if outcome is None:
                    surviving.append(challenger)
                    continue
                winner, loser, rule = outcome
                suppressed.append(SuppressedClaim(claim=loser, lost_to=winner.claim_id, rule=rule))
                leader = winner
            surviving.append(leader)

        return ConflictResolution(surviving=tuple(surviving), suppressed=tuple(suppressed))


DEFAULT_CONFLICT_POLICY = ConflictResolutionPolicy()
