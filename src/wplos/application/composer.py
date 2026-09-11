from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from wplos.agents.contracts import AgentEvidence, DecisionState, PriorityClass
from wplos.application.candidates import CandidateKind, PlanCandidate
from wplos.application.priority import DEFAULT_PRIORITY_POLICY, PriorityPolicy
from wplos.core.identifiers import ActionId, EntityId
from wplos.core.roles import AgentName
from wplos.orchestration.conflict import (
    DEFAULT_CONFLICT_POLICY,
    Claim,
    ClaimNature,
    ConflictResolutionPolicy,
)
from wplos.policy.execution import ProposedAction
from wplos.policy.guardian import GuardianAssessment, GuardianVerdict
from wplos.policy.permissions import PermissionLevel


class SuppressionReason(StrEnum):
    """Why something the system knew did not reach her.

    Every drop is typed so a plan that feels wrong can be explained rather than
    guessed at.
    """

    LOW_RELEVANCE = "LOW_RELEVANCE"
    DUPLICATE = "DUPLICATE"
    LOW_PRIORITY = "LOW_PRIORITY"
    CONFLICT = "CONFLICT"
    GUARDIAN_BLOCK = "GUARDIAN_BLOCK"
    NOT_ACTIONABLE = "NOT_ACTIONABLE"
    STALE = "STALE"
    OVER_CAPACITY = "OVER_CAPACITY"
    UNRESOLVED_CONTENTION = "UNRESOLVED_CONTENTION"


class SuppressedItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    origin_agent: AgentName
    reason: SuppressionReason
    detail: str | None = None


class PlanItem(BaseModel):
    """One line of the answer, structured. The composer writes no prose."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str
    kind: CandidateKind
    title: str
    rationale: str
    priority: PriorityClass
    origin_agent: AgentName
    entity_ids: tuple[EntityId, ...] = Field(default_factory=tuple)
    evidence: tuple[AgentEvidence, ...] = Field(default_factory=tuple)
    action_id: ActionId | None = None


class AuthorizationRequest(BaseModel):
    """What has to be put to her before anything happens."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: ProposedAction
    guardian_verdict: GuardianVerdict
    reason: str

    @property
    def permission_level(self) -> PermissionLevel:
        return self.action.permission_level

    @property
    def is_high_impact(self) -> bool:
        return self.action.permission_level.requires_explicit_confirmation


class HighImpactAuthorizationRequest(AuthorizationRequest):
    """A3: the terms have to be shown, and the answer recorded for audit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    guardian_findings: tuple[str, ...] = Field(default_factory=tuple)
    audit_required: bool = True


class CompositionBudget(BaseModel):
    """A day has a shape. Twenty-two items is not a plan, it is a list.

    Safety is never budgeted; everything else is.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    p1: int = 3
    p2: int = 3
    p3: int = 1
    max_opportunities: int = 2
    max_total: int = 12

    def allowance(self, priority: PriorityClass) -> int | None:
        return {
            PriorityClass.P0: None,
            PriorityClass.P1: self.p1,
            PriorityClass.P2: self.p2,
            PriorityClass.P3: self.p3,
        }[priority]


DEFAULT_BUDGET = CompositionBudget()


class ComposedActionPlan(BaseModel):
    """Many internal decisions, one coordinated answer.

    An application model, not a screen: no copy, no layout, no ordering that
    assumes a particular surface.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    primary_focus: PlanItem | None = None
    now: tuple[PlanItem, ...] = Field(default_factory=tuple)
    next_up: tuple[PlanItem, ...] = Field(default_factory=tuple)
    must_handle: tuple[PlanItem, ...] = Field(default_factory=tuple)
    prepare: tuple[PlanItem, ...] = Field(default_factory=tuple)
    carry: tuple[PlanItem, ...] = Field(default_factory=tuple)
    opportunities: tuple[PlanItem, ...] = Field(default_factory=tuple)
    warnings: tuple[PlanItem, ...] = Field(default_factory=tuple)
    optional: tuple[PlanItem, ...] = Field(default_factory=tuple)
    authorization_requests: tuple[AuthorizationRequest, ...] = Field(default_factory=tuple)
    suppressed: tuple[SuppressedItem, ...] = Field(default_factory=tuple)

    @property
    def items(self) -> tuple[PlanItem, ...]:
        """Every item once. The sections are disjoint by construction."""
        focus = () if self.primary_focus is None else (self.primary_focus,)
        return (
            focus
            + self.now
            + self.must_handle
            + self.next_up
            + self.prepare
            + self.carry
            + self.opportunities
            + self.warnings
            + self.optional
        )

    @property
    def is_empty(self) -> bool:
        return not self.items and not self.authorization_requests

    def suppressed_for(self, reason: SuppressionReason) -> tuple[SuppressedItem, ...]:
        return tuple(item for item in self.suppressed if item.reason is reason)


class ActionComposer:
    """Turns everything the minds produced into one bounded plan.

    Order matters: blocked items leave before anything is counted, duplicates
    merge before conflicts are judged, and the budget applies last so that what
    survives is what mattered most rather than what arrived first.
    """

    name = "runtime.composition"

    def __init__(
        self,
        budget: CompositionBudget = DEFAULT_BUDGET,
        conflict_policy: ConflictResolutionPolicy = DEFAULT_CONFLICT_POLICY,
        priority_policy: PriorityPolicy = DEFAULT_PRIORITY_POLICY,
    ) -> None:
        self.budget = budget
        self.conflicts = conflict_policy
        self.priorities = priority_policy

    def compose(
        self,
        candidates: tuple[PlanCandidate, ...],
        *,
        blocked_actions: frozenset[ActionId] = frozenset(),
        assessments: tuple[GuardianAssessment, ...] = (),
        authorization_requests: tuple[AuthorizationRequest, ...] = (),
    ) -> ComposedActionPlan:
        suppressed: list[SuppressedItem] = []

        surviving = self._drop_blocked(candidates, blocked_actions, assessments, suppressed)
        surviving = self._merge_duplicates(surviving, suppressed)
        surviving = self._resolve_conflicts(surviving, suppressed)
        surviving = self._apply_budget(surviving, suppressed)

        return self._assemble(surviving, authorization_requests, tuple(suppressed))

    def _drop_blocked(
        self,
        candidates: tuple[PlanCandidate, ...],
        blocked_actions: frozenset[ActionId],
        assessments: tuple[GuardianAssessment, ...],
        suppressed: list[SuppressedItem],
    ) -> tuple[PlanCandidate, ...]:
        blocked = set(blocked_actions) | {
            assessment.subject_action_id
            for assessment in assessments
            if assessment.verdict is GuardianVerdict.BLOCK
            and assessment.subject_action_id is not None
        }
        kept: list[PlanCandidate] = []
        for candidate in candidates:
            action = candidate.proposed_action
            if action is not None and action.action_id in blocked:
                suppressed.append(
                    SuppressedItem(
                        candidate_id=candidate.candidate_id,
                        origin_agent=candidate.origin_agent,
                        reason=SuppressionReason.GUARDIAN_BLOCK,
                        detail="Guardian vetoed this action",
                    )
                )
                continue
            if candidate.decision_state is DecisionState.IGNORE:
                suppressed.append(
                    SuppressedItem(
                        candidate_id=candidate.candidate_id,
                        origin_agent=candidate.origin_agent,
                        reason=SuppressionReason.NOT_ACTIONABLE,
                    )
                )
                continue
            kept.append(candidate)
        return tuple(kept)

    def _merge_duplicates(
        self, candidates: tuple[PlanCandidate, ...], suppressed: list[SuppressedItem]
    ) -> tuple[PlanCandidate, ...]:
        # Two minds naming the same thing in the same way are saying the same
        # thing. A commitment and an opportunity that happen to share a title
        # are not duplicates, they are rivals, and rivals go to arbitration.
        merged: dict[tuple[str, ClaimNature], PlanCandidate] = {}
        for candidate in candidates:
            key = (candidate.dedupe_key, candidate.kind.nature)
            existing = merged.get(key)
            if existing is None:
                merged[key] = candidate
                continue
            combined = existing.merged_with(candidate)
            merged[key] = combined
            loser = candidate if combined.candidate_id == existing.candidate_id else existing
            suppressed.append(
                SuppressedItem(
                    candidate_id=loser.candidate_id,
                    origin_agent=loser.origin_agent,
                    reason=SuppressionReason.DUPLICATE,
                    detail=f"merged into {combined.candidate_id}",
                )
            )
        return tuple(merged.values())

    def _resolve_conflicts(
        self, candidates: tuple[PlanCandidate, ...], suppressed: list[SuppressedItem]
    ) -> tuple[PlanCandidate, ...]:
        by_id = {candidate.candidate_id: candidate for candidate in candidates}
        claims = tuple(
            Claim(
                claim_id=candidate.candidate_id,
                agent=candidate.origin_agent,
                subject=candidate.subject,
                nature=candidate.kind.nature,
                decision_state=candidate.decision_state,
                priority=candidate.priority,
                statement=candidate.title,
                confidence=candidate.confidence,
            )
            for candidate in candidates
        )
        resolution = self.conflicts.resolve(claims)

        for lost in resolution.suppressed:
            suppressed.append(
                SuppressedItem(
                    candidate_id=lost.claim.claim_id,
                    origin_agent=lost.claim.agent,
                    reason=SuppressionReason.CONFLICT,
                    detail=f"lost to {lost.lost_to} by {lost.rule}",
                )
            )
        for contention in resolution.unresolved:
            for claim_id in contention.claim_ids:
                candidate = by_id.get(claim_id)
                if candidate is None:
                    continue
                suppressed.append(
                    SuppressedItem(
                        candidate_id=claim_id,
                        origin_agent=candidate.origin_agent,
                        reason=SuppressionReason.UNRESOLVED_CONTENTION,
                        detail=f"needs her decision about {contention.subject}",
                    )
                )

        surviving_ids = {claim.claim_id for claim in resolution.surviving}
        return tuple(
            candidate for candidate in candidates if candidate.candidate_id in surviving_ids
        )

    def _apply_budget(
        self, candidates: tuple[PlanCandidate, ...], suppressed: list[SuppressedItem]
    ) -> tuple[PlanCandidate, ...]:
        ordered = self.priorities.order(candidates)
        counts: dict[PriorityClass, int] = dict.fromkeys(PriorityClass, 0)
        opportunities = 0
        kept: list[PlanCandidate] = []

        for candidate in ordered:
            allowance = self.budget.allowance(candidate.priority)
            over_class = allowance is not None and counts[candidate.priority] >= allowance
            over_opportunities = (
                candidate.kind is CandidateKind.OPPORTUNITY
                and opportunities >= self.budget.max_opportunities
            )
            over_total = (
                candidate.priority is not PriorityClass.P0 and len(kept) >= self.budget.max_total
            )
            if over_class or over_opportunities or over_total:
                suppressed.append(
                    SuppressedItem(
                        candidate_id=candidate.candidate_id,
                        origin_agent=candidate.origin_agent,
                        reason=SuppressionReason.OVER_CAPACITY
                        if over_total or over_class
                        else SuppressionReason.LOW_RELEVANCE,
                        detail=f"{candidate.priority} allowance spent",
                    )
                )
                continue
            counts[candidate.priority] += 1
            if candidate.kind is CandidateKind.OPPORTUNITY:
                opportunities += 1
            kept.append(candidate)
        return tuple(kept)

    def _assemble(
        self,
        candidates: tuple[PlanCandidate, ...],
        authorization_requests: tuple[AuthorizationRequest, ...],
        suppressed: tuple[SuppressedItem, ...],
    ) -> ComposedActionPlan:
        """Sort what survived into sections that do not overlap.

        An item appears once. A plan that lists the same thing under "now" and
        again under "must handle" reads as two obligations.
        """
        warnings: list[PlanItem] = []
        opportunities: list[PlanItem] = []
        prepare: list[PlanItem] = []
        carry: list[PlanItem] = []
        pressing: list[PlanItem] = []
        next_up: list[PlanItem] = []
        optional: list[PlanItem] = []
        focus: PlanItem | None = None

        for candidate in self.priorities.order(candidates):
            item = _to_item(candidate)
            if candidate.kind is CandidateKind.WARNING:
                warnings.append(item)
            elif candidate.kind is CandidateKind.OPPORTUNITY:
                opportunities.append(item)
            elif candidate.kind is CandidateKind.PREPARATION:
                prepare.append(item)
            elif candidate.kind is CandidateKind.CARRY:
                carry.append(item)
            elif candidate.kind is CandidateKind.FOCUS and focus is None:
                focus = item
            elif candidate.priority is PriorityClass.P3:
                optional.append(item)
            elif candidate.priority.rank <= PriorityClass.P1.rank:
                pressing.append(item)
            else:
                next_up.append(item)

        now = tuple(pressing[:1])
        return ComposedActionPlan(
            primary_focus=focus,
            now=now,
            next_up=tuple(next_up),
            must_handle=tuple(pressing[1:]),
            prepare=tuple(prepare),
            carry=tuple(carry),
            opportunities=tuple(opportunities),
            warnings=tuple(warnings),
            optional=tuple(optional),
            authorization_requests=authorization_requests,
            suppressed=suppressed,
        )


def _to_item(candidate: PlanCandidate) -> PlanItem:
    return PlanItem(
        item_id=candidate.candidate_id,
        kind=candidate.kind,
        title=candidate.title,
        rationale=candidate.rationale,
        priority=candidate.priority,
        origin_agent=candidate.origin_agent,
        entity_ids=candidate.entity_ids,
        evidence=candidate.evidence,
        action_id=None
        if candidate.proposed_action is None
        else candidate.proposed_action.action_id,
    )


DEFAULT_COMPOSER = ActionComposer()
