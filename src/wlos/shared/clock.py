from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(moment: datetime) -> datetime:
    """Reject naive datetimes; normalise aware ones to UTC.

    Temporal reasoning (deadlines, cycle phases, calendar conflicts) is rules
    work, not AI work, so the domain refuses ambiguous timestamps outright.
    """
    if moment.tzinfo is None:
        raise ValueError("naive datetime rejected: timestamps must be timezone-aware")
    return moment.astimezone(UTC)
