from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from wplos.agents.contracts import (
    AgentEvidence,
    AgentOutput,
    AgentRecommendation,
    DecisionState,
    PriorityClass,
)
from wplos.core.confidence import Confidence
from wplos.core.identifiers import EntityId
from wplos.core.roles import AgentName
from wplos.orchestration.conflict import ClaimNature
from wplos.policy.execution import ProposedAction


class CandidateKind(StrEnum):
    """What a mind is offering, in terms the composer can group by."""

    FOCUS = "FOCUS"
    COMMITMENT = "COMMITMENT"
    PREPARATION = "PREPARATION"
    CARRY = "CARRY"
    OPPORTUNITY = "OPPORTUNITY"
    WARNING = "WARNING"
    ACTION = "ACTION"

    @property
    def nature(self) -> ClaimNature:
        return _NATURES[self]


_NATURES: dict[CandidateKind, ClaimNature] = {
    CandidateKind.FOCUS: ClaimNature.PRIORITY,
    CandidateKind.COMMITMENT: ClaimNature.COMMITMENT,
    CandidateKind.PREPARATION: ClaimNature.PREPARATION,
    CandidateKind.CARRY: ClaimNature.PREPARATION,
    CandidateKind.OPPORTUNITY: ClaimNature.OPPORTUNITY,
    CandidateKind.WARNING: ClaimNature.CONSTRAINT,
    CandidateKind.ACTION: ClaimNature.EXECUTION,
}


class PlanCandidate(BaseModel):
    """One thing a mind thinks belongs in the answer.

    Normalised so the composer can compare a Radar find with a Life Admin
    deadline without either mind knowing the other exists.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    origin_agent: AgentName
    kind: CandidateKind
    title: str
    rationale: str
    priority: PriorityClass
    confidence: Confidence
    decision_state: DecisionState
    subject: str
    dedupe_key: str
    entity_ids: tuple[EntityId, ...] = Field(default_factory=tuple)
    evidence: tuple[AgentEvidence, ...] = Field(default_factory=tuple)
    proposed_action: ProposedAction | None = None
    feasible: bool = True

    @property
    def is_actionable(self) -> bool:
        return self.proposed_action is not None

    def merged_with(self, other: "PlanCandidate") -> "PlanCandidate":
        """Two minds saying the same thing become one item that cites both."""
        keep = self if self.priority.rank <= other.priority.rank else other
        return keep.model_copy(
            update={
                "evidence": self.evidence + other.evidence,
                "entity_ids": tuple(dict.fromkeys(self.entity_ids + other.entity_ids)),
                "proposed_action": self.proposed_action or other.proposed_action,
            }
        )


def candidates_from(output: AgentOutput) -> tuple[PlanCandidate, ...]:
    """Normalise one mind's structured output into comparable candidates."""
    items: list[PlanCandidate] = []
    for index, recommendation in enumerate(output.recommendations):
        items.append(_from_recommendation(output.agent, recommendation, index))
    for index, decision in enumerate(output.decisions):
        if decision.decision_state is DecisionState.IGNORE:
            continue
        items.append(
            PlanCandidate(
                candidate_id=f"{output.agent.value.lower()}_d{index}",
                origin_agent=output.agent,
                kind=_DECISION_KIND_BY_AGENT[output.agent],
                title=decision.subject,
                rationale=decision.rationale,
                priority=decision.priority,
                confidence=decision.confidence,
                decision_state=decision.decision_state,
                subject=decision.subject,
                dedupe_key=decision.subject.strip().casefold(),
                evidence=decision.evidence,
            )
        )
    return tuple(items)


def _from_recommendation(
    agent: AgentName, recommendation: AgentRecommendation, index: int
) -> PlanCandidate:
    kind = _KIND_BY_AGENT.get(agent, CandidateKind.OPPORTUNITY)
    if recommendation.proposed_action is not None:
        kind = CandidateKind.ACTION
    return PlanCandidate(
        candidate_id=f"{agent.value.lower()}_r{index}",
        origin_agent=agent,
        kind=kind,
        title=recommendation.title,
        rationale=recommendation.rationale,
        priority=recommendation.priority,
        confidence=recommendation.confidence,
        decision_state=recommendation.decision_state,
        subject=recommendation.title,
        dedupe_key=recommendation.title.strip().casefold(),
        evidence=recommendation.evidence,
        proposed_action=recommendation.proposed_action,
    )


_DECISION_KIND_BY_AGENT: dict[AgentName, CandidateKind] = {
    AgentName.NAVIGATOR: CandidateKind.FOCUS,
    AgentName.LIFE_ADMIN: CandidateKind.COMMITMENT,
    AgentName.READINESS: CandidateKind.PREPARATION,
    AgentName.RADAR: CandidateKind.OPPORTUNITY,
    AgentName.GUARDIAN: CandidateKind.WARNING,
    AgentName.OPERATOR: CandidateKind.ACTION,
}

_KIND_BY_AGENT: dict[AgentName, CandidateKind] = {
    AgentName.NAVIGATOR: CandidateKind.FOCUS,
    AgentName.LIFE_ADMIN: CandidateKind.COMMITMENT,
    AgentName.READINESS: CandidateKind.PREPARATION,
    AgentName.RADAR: CandidateKind.OPPORTUNITY,
    AgentName.GUARDIAN: CandidateKind.WARNING,
    AgentName.OPERATOR: CandidateKind.ACTION,
}
