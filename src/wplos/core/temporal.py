from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


class AmbiguousTimePolicy(StrEnum):
    """What to do with a local time that happens twice when clocks go back."""

    REJECT = "REJECT"
    EARLIER = "EARLIER"
    LATER = "LATER"


class NonexistentTimePolicy(StrEnum):
    """What to do with a local time that never happens when clocks go forward."""

    REJECT = "REJECT"
    SHIFT_FORWARD = "SHIFT_FORWARD"


class ZonedInstant(BaseModel):
    """An instant, plus the zone the event is anchored to.

    A wedding at 20:00 in Riyadh stays at 20:00 in Riyadh when the user flies to
    London. Storing only a UTC instant loses the local intent; storing only a
    local wall time loses the instant. Both are kept.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    instant: datetime
    time_zone: str

    @field_validator("instant")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("time_zone")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown IANA time zone: {value}") from error
        return value

    @classmethod
    def from_local(
        cls,
        local: datetime,
        time_zone: str,
        *,
        on_ambiguous: AmbiguousTimePolicy = AmbiguousTimePolicy.REJECT,
        on_nonexistent: NonexistentTimePolicy = NonexistentTimePolicy.REJECT,
    ) -> "ZonedInstant":
        """Anchor a wall-clock time to a zone, refusing to guess at a DST edge."""
        if local.tzinfo is not None:
            raise InvariantViolation("from_local takes a wall-clock time without a zone")
        zone = ZoneInfo(time_zone)

        if _is_nonexistent(local, zone):
            if on_nonexistent is NonexistentTimePolicy.REJECT:
                raise InvariantViolation(
                    f"{local.isoformat()} does not exist in {time_zone}; "
                    "the clocks move forward over it"
                )
            # The pre-transition reading names a real instant; it simply renders
            # on the far side of the gap.
            shifted = local.replace(tzinfo=zone, fold=0)
            return cls(instant=shifted.astimezone(UTC), time_zone=time_zone)

        if _is_ambiguous(local, zone):
            if on_ambiguous is AmbiguousTimePolicy.REJECT:
                raise InvariantViolation(
                    f"{local.isoformat()} happens twice in {time_zone}; "
                    "say which occurrence is meant"
                )
            fold = 0 if on_ambiguous is AmbiguousTimePolicy.EARLIER else 1
            resolved = local.replace(tzinfo=zone, fold=fold)
            return cls(instant=resolved.astimezone(UTC), time_zone=time_zone)

        return cls(instant=local.replace(tzinfo=zone).astimezone(UTC), time_zone=time_zone)

    @property
    def local(self) -> datetime:
        """The wall-clock time in the event's own zone."""
        return self.instant.astimezone(ZoneInfo(self.time_zone))

    def local_in(self, time_zone: str) -> datetime:
        """The same instant as read from somewhere else, for display only."""
        return self.instant.astimezone(ZoneInfo(time_zone))

    def utc_offset_minutes(self) -> int:
        offset = self.local.utcoffset()
        return 0 if offset is None else int(offset.total_seconds() // 60)


def _is_nonexistent(local: datetime, zone: ZoneInfo) -> bool:
    attached = local.replace(tzinfo=zone)
    return attached.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != local


def _is_ambiguous(local: datetime, zone: ZoneInfo) -> bool:
    earlier = local.replace(tzinfo=zone, fold=0)
    later = local.replace(tzinfo=zone, fold=1)
    return earlier.utcoffset() != later.utcoffset()
