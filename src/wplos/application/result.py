from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from wplos.application.composer import (
    AuthorizationRequest,
    ComposedActionPlan,
    SuppressedItem,
)
from wplos.application.failure import AgentFailure
from wplos.application.trace import RuntimeTrace
from wplos.core.identifiers import CorrelationId, RequestId
from wplos.events.envelope import DomainEvent


class RuntimeStatus(StrEnum):
    """What the run amounted to. A business outcome is not an exception."""

    COMPLETED = "COMPLETED"
    NO_ACTION = "NO_ACTION"
    NEEDS_AUTHORIZATION = "NEEDS_AUTHORIZATION"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"

    @property
    def produced_a_plan(self) -> bool:
        return self in {
            RuntimeStatus.COMPLETED,
            RuntimeStatus.NEEDS_AUTHORIZATION,
            RuntimeStatus.PARTIAL,
        }


class RuntimeWarning(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str


class RuntimeResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: RequestId
    correlation_id: CorrelationId
    status: RuntimeStatus
    plan: ComposedActionPlan = Field(default_factory=ComposedActionPlan)
    emitted_events: tuple[DomainEvent, ...] = Field(default_factory=tuple)
    failures: tuple[AgentFailure, ...] = Field(default_factory=tuple)
    warnings: tuple[RuntimeWarning, ...] = Field(default_factory=tuple)
    trace: RuntimeTrace = Field(default_factory=RuntimeTrace)

    @property
    def required_authorizations(self) -> tuple[AuthorizationRequest, ...]:
        return self.plan.authorization_requests

    @property
    def suppressed_items(self) -> tuple[SuppressedItem, ...]:
        return self.plan.suppressed

    @property
    def decisions(self) -> tuple[str, ...]:
        return tuple(item.item_id for item in self.plan.items)
