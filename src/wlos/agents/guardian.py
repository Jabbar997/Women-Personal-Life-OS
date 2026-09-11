from __future__ import annotations

from datetime import datetime

from wlos.agents.contracts import AgentContract, DecisionState
from wlos.core.base import DomainModel
from wlos.core.minds import Mind
from wlos.events.catalog import EventType
from wlos.personal_life_graph.domains import LifeDomain
from wlos.policy.execution import ActionKind, ExecutionRequest
from wlos.policy.guardian_verdict import (
    GuardianCheck,
    GuardianConcern,
    GuardianDecision,
    GuardianVerdict,
)
from wlos.policy.permissions import PermissionLevel
from wlos.policy.sensitivity_policy import ConsumerKind
from wlos.shared.clock import utc_now
from wlos.shared.sensitivity import Sensitivity

CONTRACT = AgentContract(
    mind=Mind.GUARDIAN,
    mission="Protect the user and constrain system behaviour.",
    reads=frozenset(LifeDomain),
    writes=frozenset(),
    decision_authority=frozenset({DecisionState.IGNORE, DecisionState.SURFACE}),
    max_permission_level=PermissionLevel.A0,
    forbidden_actions=(
        "execute any action",
        "produce output outside ALLOW / CAUTION / BLOCK / ESCALATE",
    ),
    events_consumed=frozenset({EventType.OPERATOR_ACTION_PROPOSED}),
    events_produced=frozenset(
        {EventType.GUARDIAN_CAUTION_RAISED, EventType.GUARDIAN_BLOCKED_ACTION}
    ),
    required_policies=("execution.authorization.v1", "sensitivity.need-to-know.v1"),
)

HIGH_VALUE_THRESHOLD = 500.0

_SEVERITY: dict[GuardianVerdict, int] = {
    GuardianVerdict.ALLOW: 0,
    GuardianVerdict.CAUTION: 1,
    GuardianVerdict.ESCALATE: 2,
    GuardianVerdict.BLOCK: 3,
}


class GuardianReview(DomainModel):
    """Everything Guardian needs to judge one proposed action.

    Deliberately explicit: safety is rules work, not something an LLM decides.
    """

    action: ExecutionRequest
    recipient: ConsumerKind | None = None
    shares_sensitivity: Sensitivity | None = None
    amount: float | None = None
    source_verified: bool = True
    known_safety_flag: str | None = None
    schedule_conflict: bool = False
    irreversible: bool = False


class Guardian:
    """Rule-based veto. Guardian never proposes; it only constrains."""

    contract = CONTRACT

    def review(self, review: GuardianReview, *, at: datetime | None = None) -> GuardianDecision:
        moment = at or utc_now()
        concerns = tuple(
            concern for rule in _RULES for concern in (rule(review),) if concern is not None
        )
        verdict = max(
            (concern.verdict for concern in concerns),
            key=lambda candidate: _SEVERITY[candidate],
            default=GuardianVerdict.ALLOW,
        )
        return GuardianDecision(
            verdict=verdict,
            concerns=concerns,
            sensitivity=review.shares_sensitivity or review.action.sensitivity,
            decided_at=moment,
        )


def _safety(review: GuardianReview) -> GuardianConcern | None:
    if review.known_safety_flag is None:
        return None
    return GuardianConcern(
        check=GuardianCheck.SAFETY,
        verdict=GuardianVerdict.BLOCK,
        message=f"safety flag: {review.known_safety_flag}",
    )


def _health_boundary(review: GuardianReview) -> GuardianConcern | None:
    if review.action.kind is not ActionKind.MEDICAL:
        return None
    return GuardianConcern(
        check=GuardianCheck.HEALTH_BOUNDARY,
        verdict=GuardianVerdict.ESCALATE,
        message="medical actions are never taken on the system's own judgement",
    )


def _sensitive_sharing(review: GuardianReview) -> GuardianConcern | None:
    if review.recipient is not ConsumerKind.EXTERNAL_RECIPIENT:
        return None
    level = review.shares_sensitivity or review.action.sensitivity
    if level >= Sensitivity.S3:
        return GuardianConcern(
            check=GuardianCheck.SENSITIVE_DATA_SHARING,
            verdict=GuardianVerdict.BLOCK,
            message=f"{level.name} data may not leave the system",
        )
    if level is Sensitivity.S2:
        return GuardianConcern(
            check=GuardianCheck.PRIVACY,
            verdict=GuardianVerdict.ESCALATE,
            message=f"{level.name} data requires the user's decision before sharing",
        )
    return None


def _financial_risk(review: GuardianReview) -> GuardianConcern | None:
    if review.action.kind not in (ActionKind.PAYMENT, ActionKind.PURCHASE):
        return None
    if review.amount is not None and review.amount >= HIGH_VALUE_THRESHOLD:
        return GuardianConcern(
            check=GuardianCheck.FINANCIAL_RISK,
            verdict=GuardianVerdict.ESCALATE,
            message=f"amount {review.amount} is above the high-value threshold",
        )
    return GuardianConcern(
        check=GuardianCheck.FINANCIAL_RISK,
        verdict=GuardianVerdict.CAUTION,
        message="money leaves the user's account; confirmation is mandatory",
    )


def _fraud(review: GuardianReview) -> GuardianConcern | None:
    if review.source_verified:
        return None
    if review.action.kind in (ActionKind.PAYMENT, ActionKind.PURCHASE, ActionKind.DATA_SHARING):
        return GuardianConcern(
            check=GuardianCheck.FRAUD,
            verdict=GuardianVerdict.BLOCK,
            message="unverified source for a money or data action",
        )
    return GuardianConcern(
        check=GuardianCheck.FRAUD,
        verdict=GuardianVerdict.CAUTION,
        message="source could not be verified",
    )


def _high_impact(review: GuardianReview) -> GuardianConcern | None:
    if review.action.kind is ActionKind.DESTRUCTIVE_EXTERNAL or review.irreversible:
        return GuardianConcern(
            check=GuardianCheck.HIGH_IMPACT_EXECUTION,
            verdict=GuardianVerdict.ESCALATE,
            message="irreversible external action requires the user",
        )
    return None


def _schedule_conflict(review: GuardianReview) -> GuardianConcern | None:
    if not review.schedule_conflict:
        return None
    return GuardianConcern(
        check=GuardianCheck.SCHEDULE_CONFLICT,
        verdict=GuardianVerdict.CAUTION,
        message="the action collides with an existing commitment",
    )


_RULES = (
    _safety,
    _health_boundary,
    _sensitive_sharing,
    _financial_risk,
    _fraud,
    _high_impact,
    _schedule_conflict,
)
