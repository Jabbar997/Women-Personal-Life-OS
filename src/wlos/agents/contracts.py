from __future__ import annotations

from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Protocol

from pydantic import Field, field_validator

from wlos.core.base import DomainModel
from wlos.core.errors import ContractViolationError
from wlos.core.minds import Mind
from wlos.events.catalog import EventType
from wlos.personal_life_graph.context import ContextView
from wlos.personal_life_graph.domains import LifeDomain
from wlos.policy.permissions import PermissionLevel
from wlos.shared.attributes import Attributes
from wlos.shared.clock import ensure_utc
from wlos.shared.confidence import Confidence
from wlos.shared.identifiers import (
    ActionId,
    CorrelationId,
    EntityId,
    EventId,
    MemoryId,
    OwnerId,
    RecommendationId,
    RequestId,
    new_recommendation_id,
    new_request_id,
)
from wlos.shared.provenance import SourceRef
from wlos.shared.sensitivity import Sensitivity


class DecisionState(StrEnum):
    """What a mind concluded should happen with what it found."""

    IGNORE = "IGNORE"
    SURFACE = "SURFACE"
    RECOMMEND = "RECOMMEND"
    ACT = "ACT"


class PriorityClass(IntEnum):
    """Ordered so aggregation across minds is comparable. P0 is most urgent."""

    P0 = 0
    P1 = 1
    P2 = 2
    P3 = 3

    @property
    def description(self) -> str:
        return _PRIORITY_DESCRIPTIONS[self]


_PRIORITY_DESCRIPTIONS: dict[PriorityClass, str] = {
    PriorityClass.P0: "safety / critical",
    PriorityClass.P1: "must handle",
    PriorityClass.P2: "should handle",
    PriorityClass.P3: "optional",
}


class AgentConfidence(DomainModel):
    value: Confidence
    rationale: str | None = None


class AgentEvidence(DomainModel):
    """What the conclusion rests on. No evidence, no recommendation."""

    entity_ids: tuple[EntityId, ...] = ()
    memory_ids: tuple[MemoryId, ...] = ()
    event_ids: tuple[EventId, ...] = ()
    source: SourceRef
    note: str | None = None


class AgentRecommendation(DomainModel):
    id: RecommendationId = Field(default_factory=new_recommendation_id)
    title: str
    detail: str | None = None
    decision_state: DecisionState
    priority: PriorityClass
    evidence: tuple[AgentEvidence, ...] = ()
    confidence: AgentConfidence
    sensitivity: Sensitivity = Sensitivity.S1
    requires_permission: PermissionLevel = PermissionLevel.A0
    proposed_action_id: ActionId | None = None
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)


class AgentDecision(DomainModel):
    """A mind's overall stance for one request."""

    decision_state: DecisionState
    priority: PriorityClass
    rationale: str
    confidence: AgentConfidence


class AgentContext(DomainModel):
    """Everything a mind is allowed to see, already filtered by policy."""

    owner_id: OwnerId
    now: datetime
    view: ContextView
    correlation_id: CorrelationId

    @field_validator("now")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class AgentRequest(DomainModel):
    request_id: RequestId = Field(default_factory=new_request_id)
    mind: Mind
    intent: str
    context: AgentContext
    parameters: Attributes = Field(default_factory=dict)


class AgentOutput(DomainModel):
    """Structured output. A mind never answers with a bare string."""

    mind: Mind
    request_id: RequestId
    decision: AgentDecision
    recommendations: tuple[AgentRecommendation, ...] = ()
    emitted_event_types: tuple[EventType, ...] = ()
    notes: tuple[str, ...] = ()


class AgentContract(DomainModel):
    """An explicit, machine-checkable statement of what a mind may do."""

    mind: Mind
    mission: str
    reads: frozenset[LifeDomain]
    writes: frozenset[LifeDomain] = frozenset()
    decision_authority: frozenset[DecisionState]
    max_permission_level: PermissionLevel = PermissionLevel.A0
    forbidden_actions: tuple[str, ...] = ()
    events_consumed: frozenset[EventType] = frozenset()
    events_produced: frozenset[EventType] = frozenset()
    required_policies: tuple[str, ...] = ()

    def may_read(self, domain: LifeDomain) -> bool:
        return domain in self.reads

    def may_write(self, domain: LifeDomain) -> bool:
        return domain in self.writes

    def may_decide(self, state: DecisionState) -> bool:
        return state in self.decision_authority


class Agent(Protocol):
    """A mind. Implementations arrive in a later phase; the contract does not change."""

    contract: AgentContract

    def handle(self, request: AgentRequest) -> AgentOutput: ...


def assert_within_contract(contract: AgentContract, output: AgentOutput) -> None:
    """Reject any output a mind is not authorised to produce."""
    if output.mind is not contract.mind:
        raise ContractViolationError(
            f"{output.mind} produced output under {contract.mind}'s contract"
        )
    if not contract.may_decide(output.decision.decision_state):
        raise ContractViolationError(
            f"{contract.mind} may not decide {output.decision.decision_state}"
        )
    for recommendation in output.recommendations:
        if not contract.may_decide(recommendation.decision_state):
            raise ContractViolationError(
                f"{contract.mind} may not recommend with state {recommendation.decision_state}"
            )
        if recommendation.requires_permission > contract.max_permission_level:
            raise ContractViolationError(
                f"{contract.mind} may not request {recommendation.requires_permission.name}; "
                f"its ceiling is {contract.max_permission_level.name}"
            )
    for event_type in output.emitted_event_types:
        if event_type not in contract.events_produced:
            raise ContractViolationError(f"{contract.mind} may not emit {event_type}")
