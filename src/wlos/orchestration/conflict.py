from __future__ import annotations

from collections.abc import Callable, Sequence

from pydantic import Field

from wlos.agents.contracts import DecisionState, PriorityClass
from wlos.core.base import DomainModel
from wlos.core.minds import Mind
from wlos.policy.guardian_verdict import GuardianVerdict
from wlos.shared.temporal import TemporalWindow

DEFAULT_RANK: dict[Mind, int] = {
    Mind.GUARDIAN: 0,
    Mind.NAVIGATOR: 1,
    Mind.LIFE_ADMIN: 2,
    Mind.READINESS: 3,
    Mind.RADAR: 4,
    Mind.OPERATOR: 5,
}
"""Starting order, not a law: rules below can override it per situation."""

MAX_STATE_FOR_LOSER = DecisionState.SURFACE
"""A claim that loses a conflict may still be shown; it may never act."""


class Claim(DomainModel):
    """One mind's bid for the user's attention or time."""

    mind: Mind
    decision_state: DecisionState
    priority: PriorityClass
    subject: str
    detail: str = ""
    window: TemporalWindow | None = None
    binding: bool = False
    guardian_verdict: GuardianVerdict | None = None

    def conflicts_with(self, other: Claim) -> bool:
        if self is other:
            return False
        if self.subject == other.subject:
            return True
        if self.window is None or other.window is None:
            return False
        return self.window.overlaps(other.window)


class ClaimOutcome(DomainModel):
    claim: Claim
    accepted: bool
    final_state: DecisionState
    reason: str


class Resolution(DomainModel):
    outcomes: tuple[ClaimOutcome, ...] = ()

    @property
    def accepted(self) -> tuple[Claim, ...]:
        return tuple(outcome.claim for outcome in self.outcomes if outcome.accepted)

    def state_of(self, claim: Claim) -> DecisionState:
        for outcome in self.outcomes:
            if outcome.claim == claim:
                return outcome.final_state
        raise KeyError("claim was not part of this resolution")


ConflictRule = Callable[[Claim, Claim], int | None]
"""Return -1 if the first claim wins, 1 if the second does, None to abstain."""


def guardian_first(left: Claim, right: Claim) -> int | None:
    left_blocks = left.guardian_verdict is GuardianVerdict.BLOCK
    right_blocks = right.guardian_verdict is GuardianVerdict.BLOCK
    if left_blocks == right_blocks:
        return None
    return -1 if left_blocks else 1


def binding_commitment_wins(left: Claim, right: Claim) -> int | None:
    """A commitment the user actually made outranks an opportunity someone found."""
    if left.binding == right.binding:
        return None
    return -1 if left.binding else 1


def safety_priority_wins(left: Claim, right: Claim) -> int | None:
    if left.priority is right.priority:
        return None
    if PriorityClass.P0 in (left.priority, right.priority):
        return -1 if left.priority is PriorityClass.P0 else 1
    return None


DEFAULT_RULES: tuple[ConflictRule, ...] = (
    guardian_first,
    binding_commitment_wins,
    safety_priority_wins,
)


class ConflictResolutionPolicy(DomainModel):
    """Ordered rules first, mind ranking as the fallback.

    Keeping the rules as a list is the point: the ranking is a default, and new
    situations are added as rules rather than by rewriting a fixed chain.
    """

    rank: dict[Mind, int] = Field(default_factory=lambda: dict(DEFAULT_RANK))
    rules: tuple[ConflictRule, ...] = DEFAULT_RULES

    def compare(self, left: Claim, right: Claim) -> int:
        for rule in self.rules:
            verdict = rule(left, right)
            if verdict is not None:
                return verdict
        by_rank = self.rank[left.mind] - self.rank[right.mind]
        if by_rank != 0:
            return -1 if by_rank < 0 else 1
        return left.priority.value - right.priority.value

    def accepted_first(self, left: Claim, right: Claim) -> Claim:
        return left if self.compare(left, right) <= 0 else right

    def resolve(self, claims: Sequence[Claim]) -> Resolution:
        outcomes: list[ClaimOutcome] = []
        for claim in claims:
            winner = claim
            reason = "no competing claim"
            for other in claims:
                if not claim.conflicts_with(other):
                    continue
                if self.compare(claim, other) > 0:
                    winner = other
                    reason = f"{other.mind} outranks {claim.mind} for {other.subject}"
                    break
            if winner is claim:
                outcomes.append(
                    ClaimOutcome(
                        claim=claim,
                        accepted=True,
                        final_state=claim.decision_state,
                        reason=reason,
                    )
                )
            else:
                outcomes.append(
                    ClaimOutcome(
                        claim=claim,
                        accepted=False,
                        final_state=_demote(claim.decision_state),
                        reason=reason,
                    )
                )
        return Resolution(outcomes=tuple(outcomes))


def _demote(state: DecisionState) -> DecisionState:
    if state in (DecisionState.ACT, DecisionState.RECOMMEND):
        return MAX_STATE_FOR_LOSER
    return state
