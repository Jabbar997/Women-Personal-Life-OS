from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from wplos.application.planning import AgentCriticality
from wplos.core.roles import AgentName


class FailureDisposition(StrEnum):
    """What a failed mind means for the rest of the run."""

    CONTINUE = "CONTINUE"
    CONTINUE_DEGRADED = "CONTINUE_DEGRADED"
    FAIL_CLOSED = "FAIL_CLOSED"


class AgentFailure(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: AgentName
    criticality: AgentCriticality
    reason: str
    disposition: FailureDisposition

    @property
    def blocks_action(self) -> bool:
        return self.disposition is FailureDisposition.FAIL_CLOSED


class FailurePolicy:
    """Losing Radar costs a suggestion. Losing Guardian costs the right to act.

    When the mind that would have said no cannot be reached, the answer is no.
    """

    name = "runtime.failure"

    def disposition(self, criticality: AgentCriticality) -> FailureDisposition:
        if criticality is AgentCriticality.SAFETY_CRITICAL:
            return FailureDisposition.FAIL_CLOSED
        if criticality is AgentCriticality.REQUIRED:
            return FailureDisposition.CONTINUE_DEGRADED
        return FailureDisposition.CONTINUE

    def record(self, agent: AgentName, criticality: AgentCriticality, reason: str) -> AgentFailure:
        return AgentFailure(
            agent=agent,
            criticality=criticality,
            reason=reason,
            disposition=self.disposition(criticality),
        )


DEFAULT_FAILURE_POLICY = FailurePolicy()
