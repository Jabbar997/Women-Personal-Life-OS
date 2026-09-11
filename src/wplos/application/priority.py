from pydantic import BaseModel, ConfigDict, Field

from wplos.agents.contracts import PriorityClass
from wplos.application.candidates import CandidateKind, PlanCandidate
from wplos.policy.guardian import GuardianVerdict


class PriorityFactors(BaseModel):
    """The things that make something matter, scored between 0 and 1.

    Deterministic and replaceable on purpose: no model ranks a life here, and
    the weights are visible so a wrong answer can be argued with.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    urgency: float = Field(default=0.0, ge=0.0, le=1.0)
    importance: float = Field(default=0.0, ge=0.0, le=1.0)
    goal_alignment: float = Field(default=0.0, ge=0.0, le=1.0)
    risk: float = Field(default=0.0, ge=0.0, le=1.0)
    timing: float = Field(default=0.0, ge=0.0, le=1.0)
    feasibility: float = Field(default=1.0, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


WEIGHTS: dict[str, float] = {
    "urgency": 0.30,
    "importance": 0.25,
    "goal_alignment": 0.15,
    "timing": 0.10,
    "feasibility": 0.10,
    "confidence": 0.10,
}


class PriorityPolicy:
    """Turns a candidate into a priority class, and a score for ordering inside it."""

    name = "runtime.priority"

    def factors(self, candidate: PlanCandidate) -> PriorityFactors:
        return PriorityFactors(
            urgency=_URGENCY_BY_KIND[candidate.kind],
            importance=_IMPORTANCE_BY_CLASS[candidate.priority],
            goal_alignment=0.6 if candidate.kind is CandidateKind.FOCUS else 0.2,
            risk=1.0 if candidate.kind is CandidateKind.WARNING else 0.0,
            timing=0.5,
            feasibility=1.0 if candidate.feasible else 0.0,
            confidence=candidate.confidence.score,
        )

    def score(self, candidate: PlanCandidate) -> float:
        factors = self.factors(candidate)
        weighted = {
            "urgency": factors.urgency,
            "importance": factors.importance,
            "goal_alignment": factors.goal_alignment,
            "timing": factors.timing,
            "feasibility": factors.feasibility,
            "confidence": factors.confidence,
        }
        return sum(value * WEIGHTS[field] for field, value in weighted.items())

    def classify(
        self, candidate: PlanCandidate, guardian_verdict: GuardianVerdict | None = None
    ) -> PriorityClass:
        """Safety wins outright; an infeasible item cannot lead the answer."""
        if guardian_verdict is GuardianVerdict.BLOCK or candidate.kind is CandidateKind.WARNING:
            return PriorityClass.P0
        if not candidate.feasible:
            return max(candidate.priority, PriorityClass.P2, key=lambda item: item.rank)
        return candidate.priority

    def order(self, candidates: tuple[PlanCandidate, ...]) -> tuple[PlanCandidate, ...]:
        return tuple(
            sorted(candidates, key=lambda item: (item.priority.rank, -self.score(item), item.title))
        )


_URGENCY_BY_KIND: dict[CandidateKind, float] = {
    CandidateKind.WARNING: 1.0,
    CandidateKind.COMMITMENT: 0.8,
    CandidateKind.ACTION: 0.7,
    CandidateKind.PREPARATION: 0.5,
    CandidateKind.CARRY: 0.4,
    CandidateKind.FOCUS: 0.4,
    CandidateKind.OPPORTUNITY: 0.1,
}

_IMPORTANCE_BY_CLASS: dict[PriorityClass, float] = {
    PriorityClass.P0: 1.0,
    PriorityClass.P1: 0.75,
    PriorityClass.P2: 0.45,
    PriorityClass.P3: 0.15,
}

DEFAULT_PRIORITY_POLICY = PriorityPolicy()
