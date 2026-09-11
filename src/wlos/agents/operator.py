from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator

from wlos.agents.contracts import AgentContract, DecisionState
from wlos.core.base import DomainModel
from wlos.core.errors import AuthorizationRequiredError, GuardianVetoError
from wlos.core.minds import Mind
from wlos.events.bus import EventBus
from wlos.events.catalog import EventType
from wlos.events.envelope import Actor, DomainEvent, Subject, caused_by, make_event
from wlos.events.payloads import (
    EventPayload,
    OperatorActionAuthorizedPayload,
    OperatorActionProposedPayload,
    OperatorActionRejectedPayload,
)
from wlos.personal_life_graph.domains import LifeDomain
from wlos.policy.decisions import PolicyDecision, PolicyOutcome, ReasonCode
from wlos.policy.execution import ExecutionPolicy, ExecutionRequest, UserAuthorization
from wlos.policy.guardian_verdict import GuardianDecision
from wlos.policy.permissions import PermissionLevel
from wlos.shared.clock import ensure_utc, utc_now
from wlos.shared.identifiers import CorrelationId, new_correlation_id
from wlos.shared.provenance import SourceRef, SourceType

CONTRACT = AgentContract(
    mind=Mind.OPERATOR,
    mission="Turn authorized intent into real-world action.",
    reads=frozenset({LifeDomain.COMMITMENTS, LifeDomain.TASKS, LifeDomain.PURCHASES}),
    writes=frozenset({LifeDomain.TASKS, LifeDomain.PURCHASES, LifeDomain.COMMITMENTS}),
    decision_authority=frozenset({DecisionState.IGNORE, DecisionState.SURFACE, DecisionState.ACT}),
    max_permission_level=PermissionLevel.A3,
    forbidden_actions=(
        "execute an A2 or A3 action without a valid authorization",
        "execute anything Guardian blocked",
        "decide on its own what the user wants",
    ),
    events_consumed=frozenset({EventType.OPERATOR_ACTION_AUTHORIZED}),
    events_produced=frozenset(
        {
            EventType.OPERATOR_ACTION_PROPOSED,
            EventType.OPERATOR_ACTION_AUTHORIZED,
            EventType.OPERATOR_ACTION_REJECTED,
            EventType.OPERATOR_ACTION_STARTED,
            EventType.OPERATOR_ACTION_SUCCEEDED,
            EventType.OPERATOR_ACTION_FAILED,
            EventType.OPERATOR_ACTION_REVERSED,
        }
    ),
    required_policies=("execution.authorization.v1",),
)


class ExecutionOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"


class ExecutionResult(DomainModel):
    action_id: str
    outcome: ExecutionOutcome
    detail: str | None = None
    completed_at: datetime = Field(default_factory=utc_now)

    @field_validator("completed_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


Executor = Callable[[ExecutionRequest], ExecutionResult]
"""Adapter boundary. Real connectors arrive later; the gate in front stays the same."""


class Operator:
    """The only component that touches the outside world.

    Every action passes ``ExecutionPolicy`` first, so a Guardian block or a
    missing authorization stops execution before any side effect happens.
    """

    contract = CONTRACT

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    def propose(
        self, request: ExecutionRequest, *, correlation_id: CorrelationId | None = None
    ) -> DomainEvent:
        return self._bus.publish(
            make_event(
                event_type=EventType.OPERATOR_ACTION_PROPOSED,
                actor=Actor.of_mind(Mind.OPERATOR),
                subject=Subject.action(str(request.action_id)),
                source=SourceRef(source_type=SourceType.SYSTEM_DERIVED),
                correlation_id=correlation_id or request.correlation_id or new_correlation_id(),
                sensitivity=request.sensitivity,
                payload=OperatorActionProposedPayload(
                    action_id=request.action_id,
                    kind=request.kind,
                    permission_level=request.effective_level,
                    description=request.description,
                ),
            )
        )

    def execute(
        self,
        request: ExecutionRequest,
        *,
        guardian: GuardianDecision,
        executor: Executor,
        authorization: UserAuthorization | None = None,
        at: datetime | None = None,
    ) -> ExecutionResult:
        moment = ensure_utc(at) if at is not None else utc_now()
        proposed = self.propose(request)
        decision = ExecutionPolicy.evaluate(
            request, guardian=guardian, authorization=authorization, at=moment
        )

        if not decision.is_permitted:
            self._emit(proposed, EventType.OPERATOR_ACTION_REJECTED, request, decision)
            raise _refusal(decision)

        self._emit(proposed, EventType.OPERATOR_ACTION_AUTHORIZED, request, decision)
        self._emit(proposed, EventType.OPERATOR_ACTION_STARTED, request, decision)

        try:
            result = executor(request)
        except Exception as error:
            self._emit(proposed, EventType.OPERATOR_ACTION_FAILED, request, decision)
            raise error

        outcome_event = (
            EventType.OPERATOR_ACTION_SUCCEEDED
            if result.outcome is ExecutionOutcome.SUCCEEDED
            else EventType.OPERATOR_ACTION_FAILED
        )
        self._emit(proposed, outcome_event, request, decision)
        return result

    def _emit(
        self,
        parent: DomainEvent,
        event_type: EventType,
        request: ExecutionRequest,
        decision: PolicyDecision,
    ) -> DomainEvent:
        payload: EventPayload | None = None
        if event_type is EventType.OPERATOR_ACTION_AUTHORIZED:
            payload = OperatorActionAuthorizedPayload(
                action_id=request.action_id,
                kind=request.kind,
                permission_level=request.effective_level,
            )
        elif event_type is EventType.OPERATOR_ACTION_REJECTED:
            payload = OperatorActionRejectedPayload(
                action_id=request.action_id,
                kind=request.kind,
                reason_codes=decision.reason_codes,
            )
        return self._bus.publish(
            caused_by(
                parent,
                event_type=event_type,
                actor=Actor.of_mind(Mind.OPERATOR),
                subject=Subject.action(str(request.action_id)),
                source=SourceRef(source_type=SourceType.OPERATOR_RESULT),
                payload=payload,
                sensitivity=request.sensitivity,
            )
        )


def _refusal(decision: PolicyDecision) -> Exception:
    if ReasonCode.GUARDIAN_BLOCK in decision.reason_codes:
        return GuardianVetoError("Guardian blocked this action")
    if decision.outcome is PolicyOutcome.ESCALATE:
        return AuthorizationRequiredError("action escalated to the user")
    return AuthorizationRequiredError(
        "; ".join(reason.message for reason in decision.reasons) or "action not authorized"
    )
