from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from wplos.core.identifiers import ActionId, AttemptId, IdempotencyKeyLike
from wplos.core.temporal import ensure_utc
from wplos.shared.errors import InvariantViolation


class ExecutionState(StrEnum):
    """Where an action stands.

    ``UNKNOWN`` and ``PARTIALLY_SUCCEEDED`` exist because the world does not
    always answer. A timeout is not a failure, and a booking that succeeded
    while its calendar write did not is neither success nor failure.
    """

    PROPOSED = "PROPOSED"
    AUTHORIZED = "AUTHORIZED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    PARTIALLY_SUCCEEDED = "PARTIALLY_SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    REVERSED = "REVERSED"
    COMPENSATED = "COMPENSATED"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL

    @property
    def touched_the_world(self) -> bool:
        """Whether anything may already have happened outside the system.

        ``UNKNOWN`` counts: a retry that assumes nothing happened is how a
        double booking is made.
        """
        return self in {
            ExecutionState.SUCCEEDED,
            ExecutionState.PARTIALLY_SUCCEEDED,
            ExecutionState.UNKNOWN,
            ExecutionState.REVERSED,
            ExecutionState.COMPENSATED,
        }


_TERMINAL: frozenset[ExecutionState] = frozenset(
    {
        ExecutionState.REJECTED,
        ExecutionState.REVOKED,
        ExecutionState.EXPIRED,
        ExecutionState.SUCCEEDED,
        ExecutionState.FAILED,
        ExecutionState.REVERSED,
        ExecutionState.COMPENSATED,
    }
)

TRANSITIONS: dict[ExecutionState, frozenset[ExecutionState]] = {
    ExecutionState.PROPOSED: frozenset(
        {
            ExecutionState.AUTHORIZED,
            ExecutionState.REJECTED,
            ExecutionState.REVOKED,
            ExecutionState.EXPIRED,
        }
    ),
    ExecutionState.AUTHORIZED: frozenset(
        {ExecutionState.STARTED, ExecutionState.REVOKED, ExecutionState.EXPIRED}
    ),
    ExecutionState.STARTED: frozenset(
        {
            ExecutionState.SUCCEEDED,
            ExecutionState.PARTIALLY_SUCCEEDED,
            ExecutionState.FAILED,
            ExecutionState.UNKNOWN,
        }
    ),
    ExecutionState.UNKNOWN: frozenset(
        {
            ExecutionState.SUCCEEDED,
            ExecutionState.PARTIALLY_SUCCEEDED,
            ExecutionState.FAILED,
        }
    ),
    ExecutionState.PARTIALLY_SUCCEEDED: frozenset(
        {ExecutionState.SUCCEEDED, ExecutionState.COMPENSATED, ExecutionState.FAILED}
    ),
    ExecutionState.SUCCEEDED: frozenset({ExecutionState.REVERSED, ExecutionState.COMPENSATED}),
    ExecutionState.REJECTED: frozenset(),
    ExecutionState.REVOKED: frozenset(),
    ExecutionState.EXPIRED: frozenset(),
    ExecutionState.FAILED: frozenset(),
    ExecutionState.REVERSED: frozenset(),
    ExecutionState.COMPENSATED: frozenset(),
}


def may_transition(current: ExecutionState, following: ExecutionState) -> bool:
    return following in TRANSITIONS[current]


class ExecutionStep(BaseModel):
    """One named part of an action, so partial outcomes are representable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    state: ExecutionState
    detail: str | None = None


class ExecutionAttempt(BaseModel):
    """One try at one action.

    The idempotency key is the action's, not the attempt's: a retry after a
    timeout must be recognisable downstream as the same request.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    attempt_id: AttemptId
    action_id: ActionId
    idempotency_key: IdempotencyKeyLike
    attempt_number: int = Field(ge=1)
    state: ExecutionState
    started_at: datetime
    settled_at: datetime | None = None
    steps: tuple[ExecutionStep, ...] = Field(default_factory=tuple)

    @field_validator("started_at", "settled_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)

    def settled(
        self,
        *,
        state: ExecutionState,
        at: datetime,
        steps: tuple[ExecutionStep, ...] | None = None,
    ) -> "ExecutionAttempt":
        if not may_transition(self.state, state):
            raise InvariantViolation(f"{self.state} cannot become {state}")
        return self.model_copy(
            update={"state": state, "settled_at": at, "steps": steps or self.steps}
        )

    @property
    def may_retry_safely(self) -> bool:
        """A retry is only safe when nothing may already have happened."""
        return not self.state.touched_the_world and not self.state.is_terminal

    def failed_steps(self) -> tuple[ExecutionStep, ...]:
        return tuple(step for step in self.steps if step.state is ExecutionState.FAILED)

    def succeeded_steps(self) -> tuple[ExecutionStep, ...]:
        return tuple(step for step in self.steps if step.state is ExecutionState.SUCCEEDED)
