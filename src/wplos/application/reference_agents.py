"""Deterministic reference minds.

These exist to prove the runtime coordinates six independent minds safely. They
are not the product: none of them reasons, and each does the least its contract
allows while still exercising the machinery. When real minds arrive they replace
these behind the same port, and every boundary test here still applies.
"""

from datetime import datetime, timedelta

from wplos.agents.contracts import (
    AgentContract,
    AgentDecision,
    AgentEvidence,
    AgentOutput,
    AgentRecommendation,
    DecisionState,
    EvidenceKind,
    PriorityClass,
)
from wplos.agents.registry import contract_for
from wplos.application.agent_port import AgentInvocation, AgentUnavailable
from wplos.core.confidence import Confidence
from wplos.core.identifiers import (
    ActionId,
    IdempotencyKeyLike,
    UserId,
    new_action_id,
    new_attempt_id,
)
from wplos.core.money import Money
from wplos.core.roles import AgentName
from wplos.personal_life_graph.attributes import (
    AvailabilityState,
    AvailabilityStateAttributes,
    CommitmentAttributes,
    GoalAttributes,
    RadarCategory,
    RadarItemAttributes,
    RequirementAttributes,
)
from wplos.personal_life_graph.context import ContextView
from wplos.personal_life_graph.entity import Entity
from wplos.personal_life_graph.entity_types import EntityType
from wplos.policy.execution import ProposedAction
from wplos.policy.execution_state import ExecutionAttempt, ExecutionState
from wplos.policy.guardian import (
    GuardianAssessment,
    GuardianCheck,
    GuardianFinding,
    GuardianVerdict,
)
from wplos.policy.guardian_authority import GuardianAuthority
from wplos.policy.permissions import ActionDomain, PermissionLevel, ReversibilityClass

DUE_SOON = timedelta(days=2)


def _evidence(entity: Entity) -> AgentEvidence:
    return AgentEvidence(
        kind=EvidenceKind.ENTITY,
        reference=entity.id,
        statement=entity.label,
        source=entity.source,
        confidence=entity.confidence,
    )


def _of_type(view: ContextView, entity_type: EntityType) -> tuple[Entity, ...]:
    return tuple(entity for entity in view.entities if entity.entity_type is entity_type)


class _Base:
    agent: AgentName

    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    @property
    def contract(self) -> AgentContract:
        return contract_for(self.agent)

    def _guard(self) -> None:
        if not self.available:
            raise AgentUnavailable(f"{self.agent} is not reachable")


class DeterministicNavigator(_Base):
    agent = AgentName.NAVIGATOR

    def run(self, invocation: AgentInvocation) -> AgentOutput:
        self._guard()
        goals = _of_type(invocation.view, EntityType.GOAL)
        decisions = tuple(
            AgentDecision(
                subject=goal.label,
                decision_state=DecisionState.SURFACE,
                priority=PriorityClass.P2,
                rationale="an open goal with time left on it",
                confidence=goal.confidence,
                evidence=(_evidence(goal),),
            )
            for goal in goals
            if goal.attributes_as(GoalAttributes).progress < 1.0
        )
        return AgentOutput(agent=self.agent, request_id=invocation.request_id, decisions=decisions)


class DeterministicRadar(_Base):
    agent = AgentName.RADAR

    def run(self, invocation: AgentInvocation) -> AgentOutput:
        self._guard()
        finds = _of_type(invocation.view, EntityType.RADAR_ITEM)
        recommendations = tuple(
            AgentRecommendation(
                title=find.attributes_as(RadarItemAttributes).headline,
                rationale="near her, and in something she has shown interest in",
                decision_state=DecisionState.RECOMMEND,
                priority=PriorityClass.P3,
                confidence=find.confidence,
                evidence=(_evidence(find),),
            )
            for find in finds
            if find.attributes_as(RadarItemAttributes).category is not RadarCategory.LOCAL_CHANGE
        )
        return AgentOutput(
            agent=self.agent, request_id=invocation.request_id, recommendations=recommendations
        )


class DeterministicLifeAdmin(_Base):
    agent = AgentName.LIFE_ADMIN

    def run(self, invocation: AgentInvocation) -> AgentOutput:
        self._guard()
        decisions: list[AgentDecision] = []
        for commitment in _of_type(invocation.view, EntityType.COMMITMENT):
            state = commitment.attributes_as(CommitmentAttributes).state
            if not state.is_open:
                continue
            due = commitment.markers.due_at
            urgent = due is not None and due - invocation.now <= DUE_SOON
            decisions.append(
                AgentDecision(
                    subject=commitment.label,
                    decision_state=DecisionState.SURFACE,
                    priority=PriorityClass.P1 if urgent else PriorityClass.P2,
                    rationale="an open loop she has not closed",
                    confidence=commitment.confidence,
                    evidence=(_evidence(commitment),),
                )
            )
        for event in _of_type(invocation.view, EntityType.CALENDAR_EVENT):
            decisions.append(
                AgentDecision(
                    subject=event.label,
                    decision_state=DecisionState.SURFACE,
                    priority=PriorityClass.P1,
                    rationale="already in her day",
                    confidence=event.confidence,
                    evidence=(_evidence(event),),
                )
            )
        return AgentOutput(
            agent=self.agent, request_id=invocation.request_id, decisions=tuple(decisions)
        )


class DeterministicReadiness(_Base):
    agent = AgentName.READINESS

    def __init__(self, *, available: bool = True, propose_unsafe: bool = False) -> None:
        super().__init__(available=available)
        self.propose_unsafe = propose_unsafe
        # A stable id: the same suggestion across runs is the same action, which
        # is what lets a verdict about it mean anything.
        self.unsafe_action_id: ActionId = new_action_id()

    def run(self, invocation: AgentInvocation) -> AgentOutput:
        self._guard()
        recommendations: list[AgentRecommendation] = []

        for requirement in _of_type(invocation.view, EntityType.REQUIREMENT):
            attributes = requirement.attributes_as(RequirementAttributes)
            if not attributes.status.blocks_readiness:
                continue
            recommendations.append(
                AgentRecommendation(
                    title=requirement.label,
                    rationale="something the event needs is not ready",
                    decision_state=DecisionState.RECOMMEND,
                    priority=PriorityClass.P1,
                    confidence=requirement.confidence,
                    evidence=(_evidence(requirement),),
                )
            )
        for item in _of_type(invocation.view, EntityType.AVAILABILITY_STATE):
            if item.attributes_as(AvailabilityStateAttributes).state is AvailabilityState.AVAILABLE:
                continue
            recommendations.append(
                AgentRecommendation(
                    title=f"Sort out: {item.label}",
                    rationale="an item she will need is not available",
                    decision_state=DecisionState.RECOMMEND,
                    priority=PriorityClass.P2,
                    confidence=item.confidence,
                    evidence=(_evidence(item),),
                )
            )
        if self.propose_unsafe:
            recommendations.append(
                AgentRecommendation(
                    title="Use the exfoliating serum tonight",
                    rationale="it is in her routine",
                    decision_state=DecisionState.RECOMMEND,
                    priority=PriorityClass.P2,
                    confidence=Confidence.probabilistic(0.6),
                    proposed_action=ProposedAction(
                        action_id=self.unsafe_action_id,
                        owner_id=invocation.view.owner_id,
                        proposed_by=self.agent,
                        proposed_at=invocation.now,
                        domain=ActionDomain.INTERNAL,
                        permission_level=PermissionLevel.A0,
                        summary="add the serum to tonight's routine",
                        reversibility=ReversibilityClass.REVERSIBLE,
                    ),
                )
            )
        return AgentOutput(
            agent=self.agent,
            request_id=invocation.request_id,
            recommendations=tuple(recommendations),
        )


class DeterministicGuardian(_Base):
    agent = AgentName.GUARDIAN

    def __init__(
        self,
        authority: GuardianAuthority,
        *,
        available: bool = True,
        block: frozenset[ActionId] = frozenset(),
    ) -> None:
        super().__init__(available=available)
        self.authority = authority
        self.block = block

    def run(self, invocation: AgentInvocation) -> AgentOutput:
        self._guard()
        assessments: list[GuardianAssessment] = []
        decisions: list[AgentDecision] = []

        for action in invocation.proposals:
            findings: tuple[GuardianFinding, ...] = ()
            if action.action_id in self.block:
                findings = (
                    GuardianFinding(
                        check=GuardianCheck.HEALTH_BOUNDARY,
                        verdict=GuardianVerdict.BLOCK,
                        explanation="this conflicts with something she reported today",
                    ),
                )
            assessments.append(
                self.authority.assess(
                    action_id=action.action_id,
                    fingerprint=action.terms_fingerprint,
                    at=invocation.now,
                    findings=findings,
                    verdict=None if findings else GuardianVerdict.ALLOW,
                )
            )
            if findings:
                decisions.append(
                    AgentDecision(
                        subject=action.summary,
                        decision_state=DecisionState.SURFACE,
                        priority=PriorityClass.P0,
                        rationale=findings[0].explanation,
                        confidence=Confidence.certain(),
                    )
                )
        return AgentOutput(
            agent=self.agent,
            request_id=invocation.request_id,
            decisions=tuple(decisions),
            assessments=tuple(assessments),
        )


class DeterministicOperator(_Base):
    agent = AgentName.OPERATOR

    def __init__(self, *, available: bool = True) -> None:
        super().__init__(available=available)
        self.proposal: ProposedAction | None = None
        self.executed: list[ActionId] = []

    def run(self, invocation: AgentInvocation) -> AgentOutput:
        self._guard()
        if self.proposal is None:
            return AgentOutput(agent=self.agent, request_id=invocation.request_id)
        return AgentOutput(
            agent=self.agent,
            request_id=invocation.request_id,
            recommendations=(
                AgentRecommendation(
                    title=self.proposal.summary,
                    rationale="ready to run once it is authorized",
                    decision_state=DecisionState.ACT,
                    priority=PriorityClass.P2,
                    confidence=Confidence.certain(),
                    proposed_action=self.proposal,
                ),
            ),
        )

    def execute(self, action: ProposedAction, at: datetime) -> ExecutionAttempt:
        """In-memory only. No connector, no network, nothing outside this process."""
        self.executed.append(action.action_id)
        return ExecutionAttempt(
            attempt_id=new_attempt_id(),
            action_id=action.action_id,
            idempotency_key=IdempotencyKeyLike(f"idem_{action.action_id}"),
            attempt_number=1,
            state=ExecutionState.SUCCEEDED,
            started_at=at,
            settled_at=at,
        )


def reference_pilates(owner_id: UserId, at: datetime, price: Money) -> ProposedAction:
    """A booking proposal used by the runtime tests."""
    return ProposedAction(
        action_id=new_action_id(),
        owner_id=owner_id,
        proposed_by=AgentName.OPERATOR,
        proposed_at=at,
        domain=ActionDomain.PURCHASE,
        permission_level=PermissionLevel.A3,
        summary="Book a Pilates class",
        reversibility=ReversibilityClass.COMPENSATABLE,
        material_terms={"price": price.as_terms(), "starts_at": "2026-03-03T19:00:00Z"},
    )
