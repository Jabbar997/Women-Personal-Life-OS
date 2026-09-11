from datetime import datetime

from wplos.agents.contracts import AgentOutput, Intent
from wplos.agents.registry import contract_for
from wplos.application.agent_port import (
    ActionExecutor,
    AgentInvocation,
    AgentRuntime,
    AgentUnavailable,
)
from wplos.application.candidates import PlanCandidate, candidates_from
from wplos.application.composer import (
    DEFAULT_COMPOSER,
    ActionComposer,
    AuthorizationRequest,
    HighImpactAuthorizationRequest,
)
from wplos.application.enforcement import enforce_output
from wplos.application.failure import (
    DEFAULT_FAILURE_POLICY,
    AgentFailure,
    FailurePolicy,
)
from wplos.application.idempotency import RuntimeLedger
from wplos.application.planning import DEFAULT_PLANNER, ExecutionPlan, Planner
from wplos.application.purpose_scopes import scope_for
from wplos.application.request import RuntimeRequest
from wplos.application.result import RuntimeResult, RuntimeStatus, RuntimeWarning
from wplos.application.routing import DEFAULT_ROUTER, Router, RoutingDecision
from wplos.application.trace import (
    PolicyTrace,
    RuntimePhase,
    RuntimeTrace,
    ScopeTrace,
    TraceStep,
)
from wplos.core.identifiers import ActionId
from wplos.core.provenance import SourceRef, SourceType
from wplos.core.purpose import Purpose
from wplos.core.roles import ActorRole, AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.events.envelope import Actor, DomainEvent, Subject
from wplos.events.payloads import (
    ActionPlanPayload,
    AuthorizationRequestedPayload,
    OperatorActionResultPayload,
    OrchestrationOutcomePayload,
    OrchestrationPayload,
)
from wplos.events.types import EventType
from wplos.personal_life_graph.context import ContextView, project_context
from wplos.personal_life_graph.graph import PersonalLifeGraph
from wplos.policy.decisions import PolicyOutcome, ReasonCode
from wplos.policy.execution import DEFAULT_EXECUTION_POLICY, ExecutionPolicy, ProposedAction
from wplos.policy.execution_state import ExecutionState
from wplos.policy.guardian import GuardianAssessment, GuardianVerdict


class OrchestratorRuntime:
    """The machinery that lets six minds produce one safe answer.

    It routes, coordinates, enforces, composes and records. It holds no opinion
    about careers, cycles, deals or families, and it keeps no state between
    runs: a request plus the current graph produces a result, which is what
    lets the same run happen on any server.
    """

    def __init__(
        self,
        *,
        agents: dict[AgentName, AgentRuntime],
        router: Router = DEFAULT_ROUTER,
        planner: Planner = DEFAULT_PLANNER,
        composer: ActionComposer = DEFAULT_COMPOSER,
        execution_policy: ExecutionPolicy = DEFAULT_EXECUTION_POLICY,
        failure_policy: FailurePolicy = DEFAULT_FAILURE_POLICY,
        executor: ActionExecutor | None = None,
    ) -> None:
        self.agents = agents
        self.executor = executor
        self.router = router
        self.planner = planner
        self.composer = composer
        self.execution_policy = execution_policy
        self.failure_policy = failure_policy

    def run(
        self,
        request: RuntimeRequest,
        *,
        graph: PersonalLifeGraph,
        intent: Intent = Intent.UNKNOWN,
        now: datetime | None = None,
        ledger: RuntimeLedger | None = None,
    ) -> RuntimeResult:
        replay = self._replay(request, ledger)
        if replay is not None:
            return replay

        at = now or request.received_at
        steps: list[TraceStep] = [TraceStep(phase=RuntimePhase.INTAKE)]

        routing = self.router.route(request, intent)
        steps.append(TraceStep(phase=RuntimePhase.ROUTING, detail=",".join(routing.matched_rules)))
        if routing.is_empty:
            return self._finish(request, self._no_action(request, routing, steps), ledger)

        plan = self.planner.plan(routing.agents, routing.purpose)
        steps.append(TraceStep(phase=RuntimePhase.PLANNING))

        outputs, failures, scopes = self._execute(request, plan, graph, intent, at, steps)
        result = self._settle(request, routing, plan, outputs, failures, scopes, steps, at)
        return self._finish(request, result, ledger)

    # --- phases -------------------------------------------------------------

    def _replay(
        self, request: RuntimeRequest, ledger: RuntimeLedger | None
    ) -> RuntimeResult | None:
        """A retried submission is the same run, not another one."""
        key = request.client_request_id
        if ledger is None or key is None:
            return None
        return ledger.lookup(key)

    def _finish(
        self, request: RuntimeRequest, result: RuntimeResult, ledger: RuntimeLedger | None
    ) -> RuntimeResult:
        key = request.client_request_id
        if ledger is not None and key is not None:
            ledger.remember(key, result)
        return result

    def _execute(
        self,
        request: RuntimeRequest,
        plan: ExecutionPlan,
        graph: PersonalLifeGraph,
        intent: Intent,
        at: datetime,
        steps: list[TraceStep],
    ) -> tuple[dict[AgentName, AgentOutput], list[AgentFailure], list[ScopeTrace]]:
        outputs: dict[AgentName, AgentOutput] = {}
        failures: list[AgentFailure] = []
        scopes: list[ScopeTrace] = []

        for wave in plan.waves():
            for agent in wave:
                node = plan.node_for(agent)
                runtime = self.agents.get(agent)
                if runtime is None:
                    failures.append(
                        self.failure_policy.record(agent, node.criticality, "no runtime registered")
                    )
                    continue
                view = self._context_for(agent, node.purpose, graph, request, at)
                proposals = _proposals_so_far(outputs)
                scopes.append(_scope_trace(agent, node.purpose, view))
                steps.append(TraceStep(phase=RuntimePhase.CONTEXT, agent=agent))
                try:
                    output = enforce_output(
                        contract_for(agent),
                        runtime.run(
                            AgentInvocation(
                                request_id=request.request_id,
                                correlation_id=request.correlation_id,
                                purpose=node.purpose,
                                intent=intent,
                                view=view,
                                now=at,
                                proposals=proposals,
                            )
                        ),
                    )
                except AgentUnavailable as unavailable:
                    failures.append(
                        self.failure_policy.record(agent, node.criticality, str(unavailable))
                    )
                    continue
                outputs[agent] = output
                steps.append(TraceStep(phase=RuntimePhase.AGENT_EXECUTION, agent=agent))
        return outputs, failures, scopes

    def _context_for(
        self,
        agent: AgentName,
        purpose: Purpose,
        graph: PersonalLifeGraph,
        request: RuntimeRequest,
        at: datetime,
    ) -> ContextView:
        """A mind never sees the graph, only what its contract and job allow."""
        return project_context(
            graph, owner_id=request.user_id, scope=scope_for(agent, purpose), at=at
        )

    def _settle(
        self,
        request: RuntimeRequest,
        routing: RoutingDecision,
        plan: ExecutionPlan,
        outputs: dict[AgentName, AgentOutput],
        failures: list[AgentFailure],
        scopes: list[ScopeTrace],
        steps: list[TraceStep],
        at: datetime,
    ) -> RuntimeResult:
        guardian_failed = any(failure.blocks_action for failure in failures)
        assessments = _assessments(outputs)
        steps.append(TraceStep(phase=RuntimePhase.GUARDIAN_ENFORCEMENT))

        candidates: list[PlanCandidate] = []
        for output in outputs.values():
            candidates.extend(candidates_from(output))

        blocked, authorizations, policy_traces, executions = self._authorize(
            tuple(candidates), assessments, guardian_failed, at
        )
        steps.append(TraceStep(phase=RuntimePhase.AUTHORIZATION))

        composed = self.composer.compose(
            tuple(candidates),
            blocked_actions=blocked,
            assessments=assessments,
            authorization_requests=authorizations,
        )
        steps.append(TraceStep(phase=RuntimePhase.COMPOSITION))

        events = self._emit(request, routing, composed, authorizations, at) + executions
        steps.append(TraceStep(phase=RuntimePhase.EMISSION))

        trace = RuntimeTrace(
            routed_agents=routing.agents,
            matched_rules=routing.matched_rules,
            execution_order=plan.execution_order(),
            waves=plan.waves(),
            scopes=tuple(scopes),
            policy_decisions=tuple(policy_traces),
            conflicts=tuple(
                item.detail or item.candidate_id
                for item in composed.suppressed
                if item.reason.value in {"CONFLICT", "UNRESOLVED_CONTENTION"}
            ),
            suppressions=tuple(
                f"{item.candidate_id}:{item.reason}" for item in composed.suppressed
            ),
            steps=tuple(steps),
            candidates_considered=len(candidates),
            items_composed=len(composed.items),
        )

        return RuntimeResult(
            request_id=request.request_id,
            correlation_id=request.correlation_id,
            status=_status(composed, authorizations, failures, guardian_failed),
            plan=composed,
            emitted_events=events,
            failures=tuple(failures),
            warnings=_warnings(failures, guardian_failed),
            trace=trace,
        )

    def _authorize(
        self,
        candidates: tuple[PlanCandidate, ...],
        assessments: tuple[GuardianAssessment, ...],
        guardian_failed: bool,
        at: datetime,
    ) -> tuple[
        frozenset[ActionId],
        tuple[AuthorizationRequest, ...],
        list[PolicyTrace],
        tuple[DomainEvent, ...],
    ]:
        """Every proposed action goes past Guardian and the execution policy.

        With Guardian unavailable nothing executable survives: the mind that
        would have said no could not be asked.
        """
        by_action = {
            assessment.subject_action_id: assessment
            for assessment in assessments
            if assessment.subject_action_id is not None
        }
        blocked: set[ActionId] = set()
        requests: list[AuthorizationRequest] = []
        traces: list[PolicyTrace] = []
        executions: list[DomainEvent] = []

        for candidate in candidates:
            action = candidate.proposed_action
            if action is None:
                continue
            if guardian_failed:
                blocked.add(action.action_id)
                traces.append(PolicyTrace(policy="runtime.failure", outcome=PolicyOutcome.DENY))
                continue
            assessment = by_action.get(action.action_id)
            if assessment is None:
                blocked.add(action.action_id)
                traces.append(PolicyTrace(policy="runtime.guardian", outcome=PolicyOutcome.DENY))
                continue
            decision = self.execution_policy.authorize(action, assessment, None, at)
            traces.append(
                PolicyTrace(
                    policy=self.execution_policy.name,
                    outcome=decision.outcome,
                    reason_codes=tuple(item.code for item in decision.reasons),
                )
            )
            if decision.outcome is PolicyOutcome.DENY:
                if not decision.has_reason(ReasonCode.SUGGESTION_ONLY):
                    blocked.add(action.action_id)
                # An A0 proposal is a suggestion that was never meant to run.
                # It stays in the plan; it simply never becomes executable.
            elif decision.outcome is PolicyOutcome.REQUIRE_CONFIRMATION:
                requests.append(_authorization_request(action, assessment))
            elif decision.outcome is PolicyOutcome.ESCALATE:
                blocked.add(action.action_id)
            else:
                executions.extend(self._execute_action(action, at))
        return frozenset(blocked), tuple(requests), traces, tuple(executions)

    def _execute_action(self, action: ProposedAction, at: datetime) -> tuple[DomainEvent, ...]:
        """Run what the policy permitted, and say so in events.

        Only A1 reaches here: everything else stopped at an authorization
        request or a denial.
        """
        if self.executor is None:
            return ()
        attempt = self.executor.execute(action, at)
        started = DomainEvent.emit(
            event_type=EventType.OPERATOR_ACTION_STARTED,
            payload=OperatorActionResultPayload(
                action_id=action.action_id, attempt_id=attempt.attempt_id
            ),
            actor=Actor.agent_actor(AgentName.OPERATOR, action.owner_id),
            subject=Subject(owner_id=action.owner_id),
            source=SourceRef(source_type=SourceType.OPERATOR_RESULT, captured_at=at),
            sensitivity=SensitivityLevel.S2,
            occurred_at=at,
        )
        settled = started.caused(
            event_type=_OUTCOME_EVENTS[attempt.state],
            payload=OperatorActionResultPayload(
                action_id=action.action_id, attempt_id=attempt.attempt_id
            ),
            actor=started.actor,
            source=started.source,
            sensitivity=SensitivityLevel.S2,
            occurred_at=at,
        )
        return (started, settled)

    def _emit(
        self,
        request: RuntimeRequest,
        routing: RoutingDecision,
        composed: object,
        authorizations: tuple[AuthorizationRequest, ...],
        at: datetime,
    ) -> tuple[DomainEvent, ...]:
        started = DomainEvent.emit(
            event_type=EventType.ORCHESTRATION_STARTED,
            payload=OrchestrationPayload(
                runtime_request_id=request.request_id,
                trigger=str(request.trigger),
                agents=routing.agents,
            ),
            actor=Actor(role=ActorRole.ORCHESTRATOR, user_id=request.user_id),
            subject=Subject(owner_id=request.user_id),
            source=SourceRef(source_type=SourceType.SYSTEM_DERIVED, captured_at=at),
            sensitivity=SensitivityLevel.S1,
            occurred_at=at,
            correlation_id=request.correlation_id,
        )
        events: list[DomainEvent] = [started]
        plan_items = getattr(composed, "items", ())
        suppressed = getattr(composed, "suppressed", ())

        events.append(
            started.caused(
                event_type=EventType.ACTION_PLAN_CREATED,
                payload=ActionPlanPayload(
                    runtime_request_id=request.request_id,
                    item_count=len(plan_items),
                    authorization_count=len(authorizations),
                ),
                actor=started.actor,
                source=started.source,
                sensitivity=SensitivityLevel.S1,
                occurred_at=at,
            )
        )
        for authorization in authorizations:
            events.append(
                started.caused(
                    event_type=EventType.AUTHORIZATION_REQUESTED,
                    payload=AuthorizationRequestedPayload(
                        action_id=authorization.action.action_id,
                        permission_level=authorization.permission_level,
                        domain=authorization.action.domain,
                        high_impact=authorization.is_high_impact,
                    ),
                    actor=started.actor,
                    source=started.source,
                    sensitivity=SensitivityLevel.S2,
                    occurred_at=at,
                )
            )
        events.append(
            started.caused(
                event_type=EventType.ORCHESTRATION_COMPLETED,
                payload=OrchestrationOutcomePayload(
                    runtime_request_id=request.request_id,
                    trigger=str(request.trigger),
                    agents=routing.agents,
                    status=str(RuntimeStatus.COMPLETED),
                    item_count=len(plan_items),
                    suppressed_count=len(suppressed),
                ),
                actor=started.actor,
                source=started.source,
                sensitivity=SensitivityLevel.S1,
                occurred_at=at,
            )
        )
        return tuple(events)

    def _no_action(
        self,
        request: RuntimeRequest,
        routing: RoutingDecision,
        steps: list[TraceStep],
    ) -> RuntimeResult:
        return RuntimeResult(
            request_id=request.request_id,
            correlation_id=request.correlation_id,
            status=RuntimeStatus.NO_ACTION,
            trace=RuntimeTrace(
                routed_agents=routing.agents,
                matched_rules=routing.matched_rules,
                steps=tuple(steps),
            ),
        )


def _assessments(outputs: dict[AgentName, AgentOutput]) -> tuple[GuardianAssessment, ...]:
    guardian = outputs.get(AgentName.GUARDIAN)
    return () if guardian is None else guardian.assessments


def _proposals_so_far(outputs: dict[AgentName, AgentOutput]) -> tuple[ProposedAction, ...]:
    """Everything proposed by the minds that have already run this wave order."""
    return tuple(
        recommendation.proposed_action
        for output in outputs.values()
        for recommendation in output.recommendations
        if recommendation.proposed_action is not None
    )


def _authorization_request(
    action: ProposedAction, assessment: GuardianAssessment
) -> AuthorizationRequest:
    if action.permission_level.requires_explicit_confirmation:
        return HighImpactAuthorizationRequest(
            action=action,
            guardian_verdict=assessment.verdict,
            reason="a high-impact action needs her explicit confirmation",
            guardian_findings=tuple(finding.explanation for finding in assessment.findings),
        )
    return AuthorizationRequest(
        action=action,
        guardian_verdict=assessment.verdict,
        reason="an external action needs her confirmation",
    )


def _status(
    composed: object,
    authorizations: tuple[AuthorizationRequest, ...],
    failures: list[AgentFailure],
    guardian_failed: bool,
) -> RuntimeStatus:
    if guardian_failed:
        return RuntimeStatus.BLOCKED
    if authorizations:
        return RuntimeStatus.NEEDS_AUTHORIZATION
    if getattr(composed, "is_empty", False):
        return RuntimeStatus.NO_ACTION
    if failures:
        return RuntimeStatus.PARTIAL
    return RuntimeStatus.COMPLETED


def _warnings(failures: list[AgentFailure], guardian_failed: bool) -> tuple[RuntimeWarning, ...]:
    warnings = tuple(
        RuntimeWarning(
            code=f"AGENT_{failure.disposition}", message=f"{failure.agent}: {failure.reason}"
        )
        for failure in failures
    )
    if guardian_failed:
        warnings += (
            RuntimeWarning(
                code="FAIL_CLOSED",
                message="Guardian could not be reached, so nothing executable was offered",
            ),
        )
    return warnings


def _scope_trace(agent: AgentName, purpose: Purpose, view: ContextView) -> ScopeTrace:
    return ScopeTrace(
        agent=agent,
        purpose=purpose,
        entity_types=tuple(sorted(view.scope.required_entity_types, key=lambda item: item.value)),
        max_sensitivity=view.scope.max_sensitivity,
        entities_delivered=len(view.entities),
        memories_delivered=len(view.memories),
        redactions=len(view.redactions),
    )


def _guardian_blocks(assessment: GuardianAssessment) -> bool:
    return assessment.verdict is GuardianVerdict.BLOCK


_OUTCOME_EVENTS: dict[ExecutionState, EventType] = {
    ExecutionState.SUCCEEDED: EventType.OPERATOR_ACTION_SUCCEEDED,
    ExecutionState.PARTIALLY_SUCCEEDED: EventType.OPERATOR_ACTION_PARTIALLY_SUCCEEDED,
    ExecutionState.FAILED: EventType.OPERATOR_ACTION_FAILED,
    ExecutionState.UNKNOWN: EventType.OPERATOR_ACTION_OUTCOME_UNKNOWN,
}
