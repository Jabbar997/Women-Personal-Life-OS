"""The one place a sanctioned intent becomes a durable change to the graph.

    mind proposes -> contract enforced -> intent resolved -> service validates
    -> graph mutation + domain event committed together

No mind holds a mutable graph. The runtime does not write either: it reports
what the minds asked for, and this service decides whether the graph will
accept it. Everything a run asks for lands as one unit, because half a decision
is a state no mind reached.
"""

from datetime import datetime
from typing import Protocol

from wplos.agents.contracts import WriteOperation
from wplos.agents.registry import contract_for
from wplos.application.enforcement import ContractViolation
from wplos.application.graph_events import resolve_graph_event
from wplos.application.graph_write import (
    GraphCommit,
    GraphWriteBatch,
    GraphWriteOutcome,
    GraphWriteReceipt,
    GraphWriteStore,
    ResolvedGraphWrite,
    RuntimeRunRecord,
    batch_fingerprint,
)
from wplos.application.result import RuntimeResult, RuntimeStatus
from wplos.application.writes import SanctionedWrite
from wplos.core.identifiers import CorrelationId, EntityId, EventId, RequestId, UserId
from wplos.core.records import RecordStatus
from wplos.events.envelope import Actor, DomainEvent, Subject
from wplos.personal_life_graph.entity import Entity
from wplos.shared.errors import ConcurrentModification, DomainError


class UnresolvableWrite(DomainError):
    """An intent could not be turned into a concrete typed mutation.

    A resolver that cannot resolve says so. Returning nothing would drop a
    mind's request silently, which is the one outcome nobody can debug.
    """


class GraphWriteResolver(Protocol):
    """Turns an intent into the mutation it asks for.

    Resolution is deterministic and belongs outside the service: knowing that
    "the dentist moved to Thursday" means revising *this* commitment is domain
    knowledge, while applying the revision safely is not.
    """

    def resolve(
        self, sanctioned: SanctionedWrite, *, owner_id: UserId, at: datetime
    ) -> ResolvedGraphWrite: ...


class _Rejected(Exception):
    """Internal: a submitted command the graph will not accept."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class GraphWriteService:
    def __init__(self, *, store: GraphWriteStore) -> None:
        self.store = store

    def apply(
        self,
        writes: tuple[ResolvedGraphWrite, ...],
        *,
        owner_id: UserId,
        request_id: RequestId,
        correlation_id: CorrelationId,
        idempotency_key: str,
        now: datetime,
        started_at: datetime | None = None,
        status: RuntimeStatus = RuntimeStatus.COMPLETED,
    ) -> GraphWriteReceipt:
        """Validate and durably apply a whole batch, or none of it."""
        fingerprint = batch_fingerprint(owner_id, writes)
        settled = self._already_answered(
            owner_id=owner_id,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        if settled is not None:
            return settled
        try:
            commits = self._commits(
                writes, owner_id=owner_id, correlation_id=correlation_id, at=now
            )
        except _Rejected as rejected:
            return GraphWriteReceipt(
                outcome=GraphWriteOutcome.REJECTED,
                request_id=request_id,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                detail=rejected.detail,
            )

        batch = GraphWriteBatch(
            owner_id=owner_id,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            run=RuntimeRunRecord(
                request_id=request_id,
                correlation_id=correlation_id,
                owner_id=owner_id,
                status=status,
                started_at=started_at or now,
                completed_at=now,
                entity_ids=tuple(commit.entity.id for commit in commits),
                event_ids=tuple(EventId(commit.event.event_id) for commit in commits),
            ),
            commits=commits,
        )
        return self.store.commit(batch)

    def apply_runtime_result(
        self,
        result: RuntimeResult,
        *,
        owner_id: UserId,
        resolver: GraphWriteResolver,
        idempotency_key: str,
        now: datetime,
        started_at: datetime | None = None,
    ) -> GraphWriteReceipt:
        """Persist what the minds asked for during one run.

        The source is ``sanctioned_writes``, which the runtime fills from output
        that already passed ``enforce_output``. Nothing here reads an agent's
        internals or re-derives a write from composed prose.
        """
        if result.status is RuntimeStatus.BLOCKED:
            return GraphWriteReceipt(
                outcome=GraphWriteOutcome.REJECTED,
                request_id=result.request_id,
                correlation_id=result.correlation_id,
                idempotency_key=idempotency_key,
                detail="the run was blocked, so nothing it asked for is applied",
            )
        resolved = tuple(
            resolver.resolve(sanctioned, owner_id=owner_id, at=now)
            for sanctioned in result.sanctioned_writes
        )
        return self.apply(
            resolved,
            owner_id=owner_id,
            request_id=result.request_id,
            correlation_id=result.correlation_id,
            idempotency_key=idempotency_key,
            now=now,
            started_at=started_at,
            status=result.status,
        )

    # --- validation ---------------------------------------------------------

    def _already_answered(
        self,
        *,
        owner_id: UserId,
        idempotency_key: str,
        fingerprint: str,
        request_id: RequestId,
        correlation_id: CorrelationId,
    ) -> GraphWriteReceipt | None:
        """The answer this key was already given, if it was given one.

        This runs before validation because a retry must not be re-validated
        against the state its own first attempt produced: a ``CREATE`` sent
        twice would otherwise be refused the second time for having succeeded
        the first.

        It is a fast path, not the protection. Two retries arriving together
        both see nothing here and both go on to ``commit``, where the unique
        constraint on the key decides which of them is the one that happened.
        """
        stored = self.store.receipt_for(owner_id=owner_id, idempotency_key=idempotency_key)
        if stored is None:
            return None
        if stored.fingerprint != fingerprint:
            return GraphWriteReceipt(
                outcome=GraphWriteOutcome.CONFLICT,
                request_id=request_id,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                detail=(
                    f"idempotency key {idempotency_key} was already used "
                    "for a different set of writes"
                ),
            )
        return stored.receipt.model_copy(update={"outcome": GraphWriteOutcome.DUPLICATE})

    def _commits(
        self,
        writes: tuple[ResolvedGraphWrite, ...],
        *,
        owner_id: UserId,
        correlation_id: CorrelationId,
        at: datetime,
    ) -> tuple[GraphCommit, ...]:
        seen: set[EntityId] = set()
        commits: list[GraphCommit] = []
        for write in writes:
            self._check_contract(write)
            if write.owner_id != owner_id:
                raise _Rejected(f"{write.intent.operation} belongs to a different owner")
            entity, previous = self._resolve_versions(write)
            if entity.id in seen:
                # Two writes to one entity in one batch would need the second to
                # be built on a revision the first has not produced yet. Refusing
                # is honest; guessing the order is not.
                raise _Rejected(f"{entity.id} is written twice in one batch")
            seen.add(entity.id)
            commits.append(
                GraphCommit(
                    operation=write.intent.operation,
                    entity=entity,
                    expected_revision=(None if previous is None else previous.revision),
                    event=self._event(
                        write,
                        entity=entity,
                        previous=previous,
                        correlation_id=correlation_id,
                        at=at,
                    ),
                )
            )
        return tuple(commits)

    def _check_contract(self, write: ResolvedGraphWrite) -> None:
        contract = contract_for(write.proposed_by)
        if not contract.may_write(write.entity_type):
            raise ContractViolation(
                f"{write.proposed_by} tried to write {write.entity_type}, "
                "which its contract does not allow"
            )

    def _resolve_versions(self, write: ResolvedGraphWrite) -> tuple[Entity, Entity | None]:
        """The version to persist and the version it replaces."""
        match write.intent.operation:
            case WriteOperation.CREATE:
                return self._for_create(write), None
            case WriteOperation.REVISE:
                stored = self._stored(write)
                self._check_agreement(write, stored)
                if write.entity is None:
                    raise _Rejected("a REVISE must carry the next version of the entity")
                if stored.revision != write.expected_revision:
                    raise ConcurrentModification(
                        f"{stored.id} is at revision {stored.revision}, "
                        f"the write was built on revision {write.expected_revision}"
                    )
                if write.entity.entity_type is not stored.entity_type:
                    raise _Rejected("an entity's type cannot change")
                return write.entity, stored
            case WriteOperation.CLOSE:
                stored = self._stored(write)
                self._check_agreement(write, stored)
                if stored.status is not RecordStatus.ACTIVE:
                    raise _Rejected(f"{stored.id} is already {stored.status}")
                if write.close_status is None or write.closed_at is None:
                    raise _Rejected("a CLOSE must say which closure it is, and when")
                return stored.closed(at=write.closed_at, status=write.close_status), stored

    def _for_create(self, write: ResolvedGraphWrite) -> Entity:
        entity = write.entity
        if entity is None:
            raise _Rejected("a CREATE must carry the entity to persist")
        if entity.entity_type is not write.intent.entity_type:
            raise _Rejected(
                f"the intent asks for {write.intent.entity_type} "
                f"but the entity is a {entity.entity_type}"
            )
        if entity.owner_id != write.owner_id:
            raise _Rejected("the entity belongs to a different owner")
        if self.store.current_entity(entity.id) is not None:
            raise _Rejected(f"{entity.id} already exists")
        return entity

    def _stored(self, write: ResolvedGraphWrite) -> Entity:
        entity_id = write.intent.entity_id
        if entity_id is None:
            raise _Rejected(f"a {write.intent.operation} must name the entity it changes")
        stored = self.store.current_entity(entity_id)
        if stored is None:
            raise _Rejected(f"{entity_id} is not in the graph")
        return stored

    def _check_agreement(self, write: ResolvedGraphWrite, stored: Entity) -> None:
        """What is already in the graph decides, not what the command claims."""
        if stored.owner_id != write.owner_id:
            raise _Rejected(f"{stored.id} belongs to someone else")
        if stored.entity_type is not write.intent.entity_type:
            raise _Rejected(
                f"the intent asks for {write.intent.entity_type} "
                f"but {stored.id} is a {stored.entity_type}"
            )

    def _event(
        self,
        write: ResolvedGraphWrite,
        *,
        entity: Entity,
        previous: Entity | None,
        correlation_id: CorrelationId,
        at: datetime,
    ) -> DomainEvent:
        """The announcement, classified as sharply as the record it is about.

        Sensitivity comes from the entity, not from the payload's shape. An
        event about an S3 record stays S3 even though it carries only a
        reference: what a mutation is *about* is itself something to withhold.
        """
        resolution = resolve_graph_event(
            operation=write.intent.operation, entity=entity, previous=previous
        )
        return DomainEvent.emit(
            event_type=resolution.event_type,
            payload=resolution.payload,
            actor=Actor.agent_actor(write.proposed_by, entity.owner_id),
            subject=Subject(owner_id=entity.owner_id, entity_id=entity.id),
            source=entity.attribution.source,
            sensitivity=entity.attribution.sensitivity,
            occurred_at=at,
            correlation_id=correlation_id,
        )
