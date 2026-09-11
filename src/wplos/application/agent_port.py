from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from wplos.agents.contracts import AgentContext, AgentContract, AgentOutput, AgentRequest, Intent
from wplos.core.identifiers import CorrelationId, RequestId
from wplos.core.purpose import Purpose
from wplos.personal_life_graph.context import ContextView
from wplos.policy.execution import ProposedAction
from wplos.policy.execution_state import ExecutionAttempt
from wplos.shared.errors import DomainError


class AgentInvocation(BaseModel):
    """Everything a mind is given for one turn, and nothing else.

    It receives a projected view, not the graph, and a purpose, not a free hand.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: RequestId
    correlation_id: CorrelationId
    purpose: Purpose
    intent: Intent
    view: ContextView
    now: datetime
    proposals: tuple[ProposedAction, ...] = ()
    """What earlier minds in this run proposed.

    Guardian cannot assess what it has not been shown, and a verdict that has to
    be wired in by hand is a verdict nobody reached.
    """

    def as_agent_request(self) -> AgentRequest:
        return AgentRequest(
            request_id=self.request_id,
            correlation_id=self.correlation_id,
            intent=self.intent,
            context=AgentContext(owner_id=self.view.owner_id, now=self.now, view=self.view),
        )


class AgentUnavailable(DomainError):
    """A mind could not be run at all. Whether that is fatal depends on policy."""


class ActionExecutor(Protocol):
    """Whatever actually performs an authorized action.

    In this phase the only implementation is in-memory: proving the flow does
    not require a booking system, and building one before the flow is proven
    would put a real purchase behind an unproven gate.
    """

    def execute(self, action: ProposedAction, at: datetime) -> ExecutionAttempt: ...


class AgentRuntime(Protocol):
    """The port the Orchestrator calls.

    It says nothing about what is behind it: a rules engine today, a model
    behind a gateway later, a remote service after that. Swapping the
    implementation must never change who is allowed to decide what.
    """

    @property
    def contract(self) -> AgentContract: ...

    def run(self, invocation: AgentInvocation) -> AgentOutput: ...
