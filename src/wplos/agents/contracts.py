from datetime import datetime
from enum import StrEnum
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from wplos.core.confidence import Confidence
from wplos.core.identifiers import CorrelationId, RequestId, UserId
from wplos.core.provenance import SourceRef
from wplos.core.roles import AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.events.envelope import DomainEvent
from wplos.events.types import EventType
from wplos.personal_life_graph.context import ContextScope, ContextView
from wplos.personal_life_graph.entity_types import EntityType
from wplos.personal_life_graph.memory import MemoryType
from wplos.policy.execution import ProposedAction
from wplos.policy.guardian import GuardianAssessment
from wplos.policy.permissions import PermissionLevel

type AgentConfidence = Confidence


class DecisionState(StrEnum):
    """The canonical four. Every mind answers in these terms, not in prose."""

    IGNORE = "IGNORE"
    SURFACE = "SURFACE"
    RECOMMEND = "RECOMMEND"
    ACT = "ACT"

    @property
    def rank(self) -> int:
        return _DECISION_RANKS[self]


_DECISION_RANKS: dict[DecisionState, int] = {
    DecisionState.IGNORE: 0,
    DecisionState.SURFACE: 1,
    DecisionState.RECOMMEND: 2,
    DecisionState.ACT: 3,
}


class PriorityClass(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"

    @property
    def rank(self) -> int:
        """Lower is more urgent, so P0 ranks 0."""
        return _PRIORITY_RANKS[self]

    def outranks(self, other: "PriorityClass") -> bool:
        return self.rank < other.rank


_PRIORITY_RANKS: dict[PriorityClass, int] = {
    PriorityClass.P0: 0,
    PriorityClass.P1: 1,
    PriorityClass.P2: 2,
    PriorityClass.P3: 3,
}


class Intent(StrEnum):
    """What the user turn is for. The Orchestrator classifies; minds do not."""

    CAPTURE = "CAPTURE"
    PLAN_DAY = "PLAN_DAY"
    DIRECTION_CHECK = "DIRECTION_CHECK"
    GET_READY = "GET_READY"
    OPEN_LOOPS = "OPEN_LOOPS"
    DISCOVER = "DISCOVER"
    EXECUTE = "EXECUTE"
    REFLECT = "REFLECT"
    UNKNOWN = "UNKNOWN"


class EvidenceKind(StrEnum):
    ENTITY = "ENTITY"
    RELATIONSHIP = "RELATIONSHIP"
    MEMORY = "MEMORY"
    EVENT = "EVENT"
    EXTERNAL_SIGNAL = "EXTERNAL_SIGNAL"


class AgentEvidence(BaseModel):
    """Why a mind believes what it says. No evidence, no recommendation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: EvidenceKind
    reference: str
    statement: str
    source: SourceRef
    confidence: Confidence


class AgentDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: str
    decision_state: DecisionState
    priority: PriorityClass
    rationale: str
    confidence: Confidence
    evidence: tuple[AgentEvidence, ...] = Field(default_factory=tuple)


class AgentRecommendation(BaseModel):
    """A structured proposal. Minds never return a bare string."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    rationale: str
    decision_state: DecisionState
    priority: PriorityClass
    confidence: Confidence
    evidence: tuple[AgentEvidence, ...] = Field(default_factory=tuple)
    proposed_action: ProposedAction | None = None

    @model_validator(mode="after")
    def _act_needs_an_action(self) -> Self:
        if self.decision_state is DecisionState.ACT and self.proposed_action is None:
            raise ValueError("an ACT recommendation must carry a ProposedAction")
        return self


class AgentContext(BaseModel):
    """Everything a mind may read for this turn, already filtered."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    owner_id: UserId
    now: datetime
    view: ContextView


class AgentRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: RequestId
    correlation_id: CorrelationId
    intent: Intent
    context: AgentContext
    instruction: str | None = None


class AgentOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: AgentName
    request_id: RequestId
    decisions: tuple[AgentDecision, ...] = Field(default_factory=tuple)
    recommendations: tuple[AgentRecommendation, ...] = Field(default_factory=tuple)
    events: tuple[DomainEvent, ...] = Field(default_factory=tuple)
    guardian_assessment: GuardianAssessment | None = None

    @property
    def highest_priority(self) -> PriorityClass | None:
        priorities = [decision.priority for decision in self.decisions]
        priorities += [item.priority for item in self.recommendations]
        return min(priorities, key=lambda value: value.rank, default=None)


class AgentContract(BaseModel):
    """The explicit boundary of one mind.

    Reads are enforced by projecting a :class:`ContextScope` from this contract,
    so "allowed reads" is a runtime constraint rather than a paragraph of prose.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: AgentName
    mission: str
    reads: frozenset[EntityType]
    writes: frozenset[EntityType]
    reads_memory: frozenset[MemoryType]
    decision_authority: frozenset[DecisionState]
    max_permission_level: PermissionLevel
    max_sensitivity: SensitivityLevel
    events_consumed: frozenset[EventType]
    events_produced: frozenset[EventType]
    required_policies: tuple[str, ...]
    forbidden: tuple[str, ...]
    holds_veto: bool = False

    @model_validator(mode="after")
    def _authority_is_bounded(self) -> Self:
        if self.holds_veto and self.agent is not AgentName.GUARDIAN:
            raise ValueError("only Guardian holds veto authority")
        if self.max_permission_level.is_executable and self.agent is not AgentName.OPERATOR:
            raise ValueError(f"{self.agent} must not hold an executable permission level")
        if DecisionState.ACT in self.decision_authority and self.agent is not AgentName.OPERATOR:
            raise ValueError(f"{self.agent} must not hold ACT authority")
        return self

    def context_scope(self, purpose: str) -> ContextScope:
        return ContextScope(
            consumer=self.agent,
            purpose=purpose,
            required_entity_types=self.reads,
            required_memory_types=self.reads_memory,
            max_sensitivity=self.max_sensitivity,
        )

    def may_decide(self, state: DecisionState) -> bool:
        return state in self.decision_authority

    def may_write(self, entity_type: EntityType) -> bool:
        return entity_type in self.writes


class Agent(Protocol):
    """Phase 01 defines the shape only. No mind is implemented with an LLM yet."""

    @property
    def contract(self) -> AgentContract: ...

    def handle(self, request: AgentRequest) -> AgentOutput: ...
