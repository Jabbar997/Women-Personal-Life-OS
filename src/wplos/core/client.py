from datetime import datetime
from enum import StrEnum
from typing import NewType

from pydantic import BaseModel, ConfigDict, field_validator

from wplos.core.temporal import ensure_utc

DeviceId = NewType("DeviceId", str)
ClientSessionId = NewType("ClientSessionId", str)
ClientEventId = NewType("ClientEventId", str)
IdempotencyKey = NewType("IdempotencyKey", str)


class EventOrigin(StrEnum):
    """Which part of the system produced an event.

    Distinct from provenance, which answers where a *fact* came from. A phone
    can report a fact the user declared; the two axes must not be collapsed.
    """

    SERVER = "SERVER"
    MOBILE_DEVICE = "MOBILE_DEVICE"
    CONNECTOR = "CONNECTOR"
    SYSTEM = "SYSTEM"
    AI = "AI"

    @property
    def is_remote_client(self) -> bool:
        return self is EventOrigin.MOBILE_DEVICE


class ClientRef(BaseModel):
    """Transport identity for an event submitted by a client.

    Kept out of the business domain: nothing in the Personal Life Graph is keyed
    by device. This exists for idempotency, deduplication, sync and debugging,
    and for nothing else.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_event_id: ClientEventId
    device_id: DeviceId | None = None
    session_id: ClientSessionId | None = None
    submitted_at: datetime | None = None
    client_clock_skew_seconds: int | None = None

    @field_validator("submitted_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)
