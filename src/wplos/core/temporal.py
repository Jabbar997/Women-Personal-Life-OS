from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from wplos.shared.errors import InvariantViolation


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Reject naive datetimes; normalise everything else to UTC.

    Time arithmetic is a rules concern, never an LLM concern, so the domain
    refuses ambiguous input at the boundary instead of guessing a zone.
    """
    if value.tzinfo is None:
        raise InvariantViolation("naive datetime is not accepted by the domain core")
    return value.astimezone(UTC)


class TemporalValidity(BaseModel):
    """When a record is *true of the world*, independent of when it was recorded."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    valid_from: datetime
    valid_until: datetime | None = None

    @field_validator("valid_from", "valid_until")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.valid_until is not None and self.valid_until < self.valid_from:
            raise ValueError("valid_until must not precede valid_from")
        return self

    @classmethod
    def open_from(cls, valid_from: datetime) -> "TemporalValidity":
        return cls(valid_from=valid_from, valid_until=None)

    def is_valid_at(self, at: datetime) -> bool:
        moment = ensure_utc(at)
        if moment < self.valid_from:
            return False
        return self.valid_until is None or moment < self.valid_until

    def closed_at(self, at: datetime) -> "TemporalValidity":
        return TemporalValidity(valid_from=self.valid_from, valid_until=ensure_utc(at))

    @property
    def is_open(self) -> bool:
        return self.valid_until is None


class TemporalMarkers(BaseModel):
    """Domain time, kept distinct from record time and from validity.

    ``created_at``/``updated_at`` live on the record, ``valid_from``/``valid_until``
    live on :class:`TemporalValidity`, and everything below is what the world did.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    occurred_at: datetime | None = None
    scheduled_for: datetime | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None

    @field_validator("occurred_at", "scheduled_for", "due_at", "completed_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)

    @classmethod
    def none(cls) -> "TemporalMarkers":
        return cls()

    @property
    def is_completed(self) -> bool:
        return self.completed_at is not None

    def is_overdue_at(self, at: datetime) -> bool:
        if self.due_at is None or self.is_completed:
            return False
        return ensure_utc(at) > self.due_at
