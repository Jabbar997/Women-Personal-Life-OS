from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from wplos.core.identifiers import EntityId, EventId, NotificationId, UserId
from wplos.core.sensitivity import SensitivityLevel
from wplos.core.temporal import ensure_utc
from wplos.policy.decisions import PolicyDecision, ReasonCode, reason

POLICY_NAME = "notification.disclosure"


class NotificationUrgency(StrEnum):
    SILENT = "SILENT"
    QUIET = "QUIET"
    NORMAL = "NORMAL"
    TIME_CRITICAL = "TIME_CRITICAL"


class NotificationCandidate(BaseModel):
    """A decision that the user should be told, which is not the same thing as
    a domain event.

    Something important happening, deciding to mention it, attempting delivery,
    and the user opening it are four separate facts. Collapsing them makes the
    notification the record, and then a failed push becomes a thing that never
    happened.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    notification_id: NotificationId
    owner_id: UserId
    triggered_by_event_id: EventId
    title: str
    body: str
    urgency: NotificationUrgency
    sensitivity: SensitivityLevel
    deep_link_entity_id: EntityId | None = None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    def without_content(self) -> "NotificationCandidate":
        """The same alert with nothing disclosed in it.

        A lock screen is a shared context. The deep link survives, so opening it
        still lands on the right thing once the device is unlocked.
        """
        return self.model_copy(
            update={"title": "A new update", "body": "Open the app to see this."}
        )


class NotificationPolicy:
    """Decides what a push may say, never whether the underlying fact is true."""

    name = POLICY_NAME
    DISCLOSURE_CEILING = SensitivityLevel.S1

    def evaluate(self, candidate: NotificationCandidate) -> PolicyDecision:
        if candidate.sensitivity.dominates(SensitivityLevel.S2):
            return PolicyDecision.require_confirmation(
                POLICY_NAME,
                reason(
                    ReasonCode.SHARED_CONTEXT_DISCLOSURE,
                    "a notification body is a shared context; send it without content",
                ),
            )
        return PolicyDecision.permit(
            POLICY_NAME, reason(ReasonCode.ALLOWED, "safe to disclose in a notification")
        )

    def prepare(self, candidate: NotificationCandidate) -> NotificationCandidate:
        """The candidate as it may actually be sent."""
        decision = self.evaluate(candidate)
        return candidate if decision.is_permitted else candidate.without_content()


DEFAULT_NOTIFICATION_POLICY = NotificationPolicy()


class DeliveryState(StrEnum):
    """What happened to the attempt to tell her. Separate from the decision."""

    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    SUPPRESSED = "SUPPRESSED"
    OPENED = "OPENED"


class DeliveryAttempt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    notification_id: NotificationId
    state: DeliveryState
    at: datetime
    detail: str | None = Field(default=None)

    @field_validator("at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)
