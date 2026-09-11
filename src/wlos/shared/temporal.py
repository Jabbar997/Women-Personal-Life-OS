from __future__ import annotations

from datetime import datetime

from pydantic import field_validator, model_validator

from wlos.core.base import DomainModel
from wlos.core.errors import TemporalError
from wlos.shared.clock import ensure_utc


class TemporalWindow(DomainModel):
    """A bitemporal validity window: when a statement holds in the real world.

    ``valid_until = None`` means "still true as far as the system knows".
    """

    valid_from: datetime
    valid_until: datetime | None = None

    @field_validator("valid_from", "valid_until")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)

    @model_validator(mode="after")
    def _ordered(self) -> TemporalWindow:
        if self.valid_until is not None and self.valid_until < self.valid_from:
            raise TemporalError("valid_until precedes valid_from")
        return self

    def covers(self, moment: datetime) -> bool:
        moment = ensure_utc(moment)
        if moment < self.valid_from:
            return False
        return self.valid_until is None or moment < self.valid_until

    @property
    def is_open(self) -> bool:
        return self.valid_until is None

    def closed_at(self, moment: datetime) -> TemporalWindow:
        return TemporalWindow(valid_from=self.valid_from, valid_until=ensure_utc(moment))

    def overlaps(self, other: TemporalWindow) -> bool:
        starts_before_other_ends = other.valid_until is None or self.valid_from < other.valid_until
        other_starts_before_self_ends = (
            self.valid_until is None or other.valid_from < self.valid_until
        )
        return starts_before_other_ends and other_starts_before_self_ends
