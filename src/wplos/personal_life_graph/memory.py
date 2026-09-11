from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator

from wplos.core.attribution import Attribution
from wplos.core.identifiers import EntityId, MemoryId, UserId, new_memory_id
from wplos.core.records import ProvenancedRecord, RecordStatus
from wplos.core.temporal import TemporalValidity, ensure_utc
from wplos.shared.json import JsonValue


class MemoryType(StrEnum):
    FACT = "FACT"
    PREFERENCE = "PREFERENCE"
    BEHAVIOR = "BEHAVIOR"
    DECISION = "DECISION"
    RELATIONSHIP = "RELATIONSHIP"
    TEMPORAL = "TEMPORAL"


class MemoryRecord(ProvenancedRecord):
    """What the system remembers about the user, as a first-class record.

    Memory is part of the one Personal Life Graph. No mind keeps a private
    store, and nothing here presumes a vector index.
    """

    id: MemoryId
    owner_id: UserId
    memory_type: MemoryType
    statement: str
    subject_entity_id: EntityId | None = None
    structured: dict[str, JsonValue] = Field(default_factory=dict)
    last_confirmed_at: datetime | None = None
    review_after: datetime | None = None
    expires_at: datetime | None = None

    @field_validator("last_confirmed_at", "review_after", "expires_at")
    @classmethod
    def _optional_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)

    @classmethod
    def create(
        cls,
        *,
        owner_id: UserId,
        memory_type: MemoryType,
        statement: str,
        attribution: Attribution,
        at: datetime,
        subject_entity_id: EntityId | None = None,
        structured: dict[str, JsonValue] | None = None,
        review_after: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> "MemoryRecord":
        return cls(
            id=new_memory_id(),
            owner_id=owner_id,
            memory_type=memory_type,
            statement=statement,
            subject_entity_id=subject_entity_id,
            structured=structured or {},
            attribution=attribution,
            temporal=TemporalValidity.open_from(at),
            created_at=at,
            updated_at=at,
            last_confirmed_at=at if not attribution.is_inferred else None,
            review_after=review_after,
            expires_at=expires_at,
        )

    def confirmed(self, *, at: datetime, attribution: Attribution | None = None) -> "MemoryRecord":
        return self.model_copy(
            update={
                "last_confirmed_at": at,
                "updated_at": at,
                "attribution": attribution or self.attribution,
            }
        )

    def superseded(self, *, at: datetime, reason: str) -> "MemoryRecord":
        """The memory was true and has stopped being true.

        History keeps it: an as-of query before ``at`` still sees it.
        """
        return self._closed(at=at, reason=reason, status=RecordStatus.SUPERSEDED)

    def invalidated(self, *, at: datetime, reason: str) -> "MemoryRecord":
        """The memory was wrong. It is retained for audit but never read back
        as something that was once true."""
        return self._closed(at=at, reason=reason, status=RecordStatus.INVALIDATED)

    def _closed(self, *, at: datetime, reason: str, status: RecordStatus) -> "MemoryRecord":
        return self.model_copy(
            update={
                "temporal": self.temporal.closed_at(at),
                "status": status,
                "updated_at": at,
                "metadata": {**self.metadata, "closure_reason": reason},
            }
        )

    def needs_review_at(self, at: datetime) -> bool:
        if self.review_after is None:
            return False
        return ensure_utc(at) >= self.review_after

    def is_expired_at(self, at: datetime) -> bool:
        if self.expires_at is None:
            return False
        return ensure_utc(at) >= self.expires_at

    def is_usable_at(self, at: datetime) -> bool:
        return self.is_active_at(at) and not self.is_expired_at(at)
