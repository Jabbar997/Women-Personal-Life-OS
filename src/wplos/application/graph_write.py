"""The typed vocabulary of a durable graph write.

A :class:`GraphWriteIntent` is a mind asking for a change; it deliberately does
not carry enough to build a canonical :class:`Entity`, and its ``summary`` is
prose, not data. :class:`ResolvedGraphWrite` is that intent after deterministic
resolution into an actual typed mutation: the concrete entity, the revision the
write was built on, and who asked for it.

The store port below is coarse on purpose. A graph mutation and the event that
announces it must land or fail together, and a transaction cannot be expressed
across a fine-grained port without letting the adapter's transaction leak into
the application. So the application hands the adapter a whole batch and the
adapter commits it once.
"""

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from wplos.agents.contracts import GraphWriteIntent, WriteOperation
from wplos.application.result import RuntimeStatus
from wplos.application.writes import SanctionedWrite
from wplos.core.identifiers import CorrelationId, EntityId, EventId, RequestId, UserId
from wplos.core.records import RecordStatus
from wplos.core.roles import AgentName
from wplos.core.temporal import ensure_utc
from wplos.events.envelope import DomainEvent
from wplos.events.types import EventType
from wplos.personal_life_graph.entity import Entity
from wplos.personal_life_graph.entity_types import EntityType


class GraphWriteOutcome(StrEnum):
    """What became of a submitted batch.

    These are answers about a command, not failures of the program. A stale
    revision is neither: it is an invariant the graph enforces, so it raises
    :class:`~wplos.shared.errors.ConcurrentModification` instead of appearing
    here.
    """

    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"
    REJECTED = "REJECTED"


class ResolvedGraphWrite(BaseModel):
    """One sanctioned request, resolved into the mutation it actually asks for.

    The authority half is not restated here, it is carried: ``sanctioned`` is
    the same value the runtime produced after ``enforce_output``, and the agent,
    the operation, the entity type and the target are read from it. A resolver
    fills in data — the concrete entity, the revision it was built on, the
    closure — and has no field in which to put a different mind or a different
    target.

    Shape is guaranteed here; agreement with what is already in the graph is
    not. Whether the entity's type matches the intent, whether the owner owns
    it, and whether it is still open are questions about stored state, and the
    application service answers them against the store.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    sanctioned: SanctionedWrite
    owner_id: UserId
    entity: Entity | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    close_status: RecordStatus | None = None
    closed_at: datetime | None = None

    @property
    def intent(self) -> GraphWriteIntent:
        return self.sanctioned.intent

    @property
    def proposed_by(self) -> AgentName:
        return self.sanctioned.agent

    @property
    def operation(self) -> WriteOperation:
        return self.intent.operation

    @property
    def entity_type(self) -> EntityType:
        return self.intent.entity_type

    @model_validator(mode="after")
    def _shape_matches_operation(self) -> Self:
        match self.intent.operation:
            case WriteOperation.CREATE:
                if self.entity is None:
                    raise ValueError("a CREATE must carry the entity to persist")
                if self.expected_revision is not None:
                    raise ValueError("a CREATE has no revision to build on")
                if self.entity.revision != 1:
                    raise ValueError("a CREATE persists the first revision")
            case WriteOperation.REVISE:
                if self.entity is None:
                    raise ValueError("a REVISE must carry the next version of the entity")
                if self.expected_revision is None:
                    raise ValueError("a REVISE must name the revision it was built on")
                if self.intent.entity_id is None:
                    raise ValueError("a REVISE must name the entity it changes")
                if self.entity.id != self.intent.entity_id:
                    raise ValueError("a revision must keep the entity id")
                if self.entity.revision != self.expected_revision + 1:
                    raise ValueError(
                        "a revision must follow the revision it was built on, "
                        f"{self.expected_revision} -> {self.entity.revision}"
                    )
            case WriteOperation.CLOSE:
                if self.intent.entity_id is None:
                    raise ValueError("a CLOSE must name the entity it closes")
                if self.entity is not None:
                    raise ValueError("a CLOSE is derived from the stored entity, not supplied")
                if self.close_status is None:
                    raise ValueError("a CLOSE must say which closure it is")
                if self.close_status is RecordStatus.ACTIVE:
                    raise ValueError("ACTIVE is not a closure")
                if self.closed_at is None:
                    raise ValueError("a CLOSE must say when it closed")
                if self.expected_revision is None:
                    # Closing is a write like any other. A close built against
                    # what she saw a minute ago must not silently close what
                    # someone else has written since.
                    raise ValueError("a CLOSE must name the revision it was built on")
        return self

    def logical_terms(self) -> dict[str, object]:
        """What makes this write the command it is.

        Left out on purpose: the entity id minted for a ``CREATE``, record time
        (``created_at``/``updated_at``), the derived ``revision``, and the
        capture bookkeeping on the source. All of them change between two
        attempts at the same command, and an idempotency key that changes on
        every retry protects nothing.

        ``closed_at`` is *not* one of them. It sets ``temporal.valid_until``, so
        it decides what the graph says about last Tuesday; closing at a
        different time is a different closure, not the same one retried.
        """
        terms: dict[str, object] = {
            "operation": str(self.intent.operation),
            "entity_type": str(self.intent.entity_type),
            "owner_id": str(self.owner_id),
            "proposed_by": str(self.proposed_by),
            "target_entity_id": self.intent.entity_id,
            "expected_revision": self.expected_revision,
            "close_status": None if self.close_status is None else str(self.close_status),
            "closed_at": (
                None if self.closed_at is None else ensure_utc(self.closed_at).isoformat()
            ),
        }
        if self.entity is not None:
            terms["entity"] = _entity_terms(self.entity)
        return terms


def _entity_terms(entity: Entity) -> dict[str, object]:
    attribution = entity.attribution
    return {
        "entity_type": str(entity.entity_type),
        "owner_id": str(entity.owner_id),
        "label": entity.label,
        "attributes": entity.attributes.model_dump(mode="json"),
        "markers": entity.markers.model_dump(mode="json"),
        "valid_from": entity.temporal.valid_from.isoformat(),
        "valid_until": (
            None if entity.temporal.valid_until is None else entity.temporal.valid_until.isoformat()
        ),
        "status": str(entity.status),
        "source_type": str(attribution.source.source_type),
        "confidence": attribution.confidence.model_dump(mode="json"),
        "sensitivity": str(attribution.sensitivity),
        "metadata": entity.metadata,
    }


def batch_fingerprint(owner_id: UserId, writes: tuple[ResolvedGraphWrite, ...]) -> str:
    """A digest of the logical batch behind a request.

    Order matters: the same two writes applied the other way round can leave a
    different graph, so a reordered batch is a different command rather than a
    retry of this one.
    """
    canonical = json.dumps(
        {"owner_id": str(owner_id), "writes": [write.logical_terms() for write in writes]},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AppliedWrite(BaseModel):
    """A reference to what one write left behind. No content, only where to read it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: EntityId
    entity_type: EntityType
    operation: WriteOperation
    revision: int = Field(ge=1)
    event_id: EventId
    event_type: EventType


class GraphWriteReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: GraphWriteOutcome
    request_id: RequestId
    correlation_id: CorrelationId
    idempotency_key: str
    writes: tuple[AppliedWrite, ...] = Field(default_factory=tuple)
    detail: str | None = None

    @property
    def persisted(self) -> bool:
        return self.outcome in {GraphWriteOutcome.APPLIED, GraphWriteOutcome.DUPLICATE}


class RuntimeRunRecord(BaseModel):
    """That a run happened, who it was for and what it left behind.

    Enough to recognise a completed run after a restart, and no more. The
    runtime trace stays out: it carries shapes and counts for debugging, and
    none of it is worth keeping forever next to a woman's life.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: RequestId
    correlation_id: CorrelationId
    owner_id: UserId
    status: RuntimeStatus
    started_at: datetime
    completed_at: datetime
    entity_ids: tuple[EntityId, ...] = Field(default_factory=tuple)
    event_ids: tuple[EventId, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _times_are_utc_and_ordered(self) -> Self:
        ensure_utc(self.started_at)
        ensure_utc(self.completed_at)
        if self.completed_at < self.started_at:
            raise ValueError("a run cannot complete before it started")
        return self


class GraphCommit(BaseModel):
    """One mutation and the event announcing it, ready to be written together."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: WriteOperation
    entity: Entity
    expected_revision: int | None = Field(default=None, ge=1)
    event: DomainEvent

    @model_validator(mode="after")
    def _event_is_about_this_entity(self) -> Self:
        if self.event.subject.entity_id != self.entity.id:
            raise ValueError("the event must be about the entity it announces")
        return self


class GraphWriteBatch(BaseModel):
    """Everything one submitted command changes, as a single unit of work."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    owner_id: UserId
    idempotency_key: str
    fingerprint: str
    run: RuntimeRunRecord
    commits: tuple[GraphCommit, ...] = Field(default_factory=tuple)


class StoredReceipt(BaseModel):
    """A receipt as the store kept it, next to the fingerprint that identifies it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fingerprint: str
    receipt: GraphWriteReceipt


class GraphWriteStore(Protocol):
    """The durable side of the Personal Life Graph.

    Reads return canonical :class:`Entity` values, never a storage shape: what
    comes back out of the database is the same model the domain put in, with the
    same invariants, or the boundary has leaked a second source of truth.
    """

    def current_entity(self, entity_id: EntityId) -> Entity | None: ...

    def entity_versions(self, entity_id: EntityId) -> tuple[Entity, ...]: ...

    def active_entities(self, *, owner_id: UserId, at: datetime) -> tuple[Entity, ...]: ...

    def receipt_for(self, *, owner_id: UserId, idempotency_key: str) -> StoredReceipt | None: ...

    def run_record(self, request_id: RequestId) -> RuntimeRunRecord | None: ...

    def commit(self, batch: GraphWriteBatch) -> GraphWriteReceipt:
        """Apply the whole batch, or none of it, in one transaction.

        Raises :class:`~wplos.shared.errors.ConcurrentModification` if any write
        was built on a revision that is no longer current. Returns a
        ``DUPLICATE`` receipt when this idempotency key has already been used
        for this exact batch, and a ``CONFLICT`` receipt — having written
        nothing — when it was used for a different one.
        """
        ...
