"""Phase 05 — sanctioned writes become durable graph state.

The exit tests for this phase are numbered in the docstrings below. The theme
running through them: a decision that only exists inside one Python process has
not been remembered, and a graph mutation whose event was lost is a change
nobody downstream will ever hear about.
"""

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from runtime_harness import build_harness
from wplos.agents.contracts import AgentOutput, GraphWriteIntent, Intent, WriteOperation
from wplos.agents.registry import contract_for
from wplos.application.agent_port import AgentInvocation
from wplos.application.enforcement import ContractViolation
from wplos.application.graph_events import resolve_graph_event
from wplos.application.graph_write import (
    GraphCommit,
    GraphWriteBatch,
    GraphWriteOutcome,
    GraphWriteReceipt,
    ResolvedGraphWrite,
    RuntimeRunRecord,
    StoredReceipt,
)
from wplos.application.graph_write_service import GraphWriteService
from wplos.application.request import RuntimeRequest
from wplos.application.result import RuntimeStatus
from wplos.application.writes import SanctionedWrite
from wplos.core.attribution import Attribution
from wplos.core.confidence import Confidence
from wplos.core.identifiers import (
    CorrelationId,
    EntityId,
    RequestId,
    UserId,
    new_correlation_id,
    new_request_id,
)
from wplos.core.provenance import SourceRef, SourceType
from wplos.core.records import RecordStatus
from wplos.core.roles import AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.core.temporal import TemporalMarkers, TemporalValidity
from wplos.events.envelope import Actor, DomainEvent, Subject
from wplos.events.payloads import GraphMutationPayload
from wplos.events.types import EventType
from wplos.integration.graph_store import SQLiteGraphStore
from wplos.integration.store import OutboxState
from wplos.personal_life_graph.attributes import (
    BodySignalAttributes,
    BodySignalKind,
    CommitmentAttributes,
    CommitmentKind,
    OpenLoopState,
    TaskAttributes,
)
from wplos.personal_life_graph.entity import Entity
from wplos.personal_life_graph.entity_types import EntityType, default_sensitivity
from wplos.shared.errors import ConcurrentModification

NOW = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=1)
OWNER = UserId("usr_phase05")
STRANGER = UserId("usr_someone_else")


# --- fixtures and builders ---------------------------------------------------


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "graph.db"


@pytest.fixture
def store(db: Path) -> SQLiteGraphStore:
    return SQLiteGraphStore(db)


@pytest.fixture
def service(store: SQLiteGraphStore) -> GraphWriteService:
    return GraphWriteService(store=store)


PRIVATE = "she said she is leaving him and needs the dress money back"


def _source(*, reference: str | None = None, detail: str | None = None) -> SourceRef:
    return SourceRef(
        source_type=SourceType.USER_DECLARED,
        captured_at=NOW,
        reference=reference,
        detail=detail,
    )


def commitment(
    *,
    owner: UserId = OWNER,
    label: str = "Return the dress",
    state: OpenLoopState = OpenLoopState.CAPTURED,
    at: datetime = NOW,
    due_at: datetime | None = None,
    source: SourceRef | None = None,
) -> Entity:
    attribution = (
        Attribution.declared(at, default_sensitivity(EntityType.COMMITMENT))
        if source is None
        else Attribution(
            source=source,
            confidence=Confidence.certain(),
            sensitivity=default_sensitivity(EntityType.COMMITMENT),
        )
    )
    return Entity.create(
        owner_id=owner,
        entity_type=EntityType.COMMITMENT,
        label=label,
        attributes=CommitmentAttributes(kind=CommitmentKind.RETURN, state=state),
        attribution=attribution,
        at=at,
        markers=TemporalMarkers(due_at=due_at),
    )


def task(*, owner: UserId = OWNER, label: str = "Book the courier") -> Entity:
    return Entity.create(
        owner_id=owner,
        entity_type=EntityType.TASK,
        label=label,
        attributes=TaskAttributes(state=OpenLoopState.CAPTURED),
        attribution=Attribution.declared(NOW, default_sensitivity(EntityType.TASK)),
        at=NOW,
    )


def body_signal(*, owner: UserId = OWNER) -> Entity:
    return Entity.create(
        owner_id=owner,
        entity_type=EntityType.BODY_SIGNAL,
        label="Cramps since this morning",
        attributes=BodySignalAttributes(
            signal=BodySignalKind.PAIN, scale_value=7.0, note="worse than last cycle"
        ),
        attribution=Attribution.declared(NOW, default_sensitivity(EntityType.BODY_SIGNAL)),
        at=NOW,
    )


def sanctioned(
    intent: GraphWriteIntent, agent: AgentName = AgentName.LIFE_ADMIN
) -> SanctionedWrite:
    return SanctionedWrite(agent=agent, intent=intent)


def create_write(
    entity: Entity,
    *,
    agent: AgentName = AgentName.LIFE_ADMIN,
    owner: UserId = OWNER,
    declared_type: EntityType | None = None,
    summary: str = "she said it in passing",
) -> ResolvedGraphWrite:
    return ResolvedGraphWrite(
        sanctioned=sanctioned(
            GraphWriteIntent(
                entity_type=declared_type or entity.entity_type,
                operation=WriteOperation.CREATE,
                summary=summary,
            ),
            agent,
        ),
        owner_id=owner,
        entity=entity,
    )


def revise_write(
    current: Entity,
    *,
    at: datetime = LATER,
    label: str | None = None,
    state: OpenLoopState | None = None,
    owner: UserId = OWNER,
    agent: AgentName = AgentName.LIFE_ADMIN,
) -> ResolvedGraphWrite:
    attributes = (
        None
        if state is None
        else current.attributes_as(CommitmentAttributes).model_copy(update={"state": state})
    )
    return ResolvedGraphWrite(
        sanctioned=sanctioned(
            GraphWriteIntent(
                entity_type=current.entity_type,
                operation=WriteOperation.REVISE,
                entity_id=current.id,
                summary="she corrected it",
            ),
            agent,
        ),
        owner_id=owner,
        entity=current.revised(at=at, label=label, attributes=attributes),
        expected_revision=current.revision,
    )


def close_write(
    current: Entity,
    *,
    at: datetime = LATER,
    status: RecordStatus = RecordStatus.ARCHIVED,
    owner: UserId = OWNER,
    expected_revision: int | None = None,
) -> ResolvedGraphWrite:
    return ResolvedGraphWrite(
        sanctioned=sanctioned(
            GraphWriteIntent(
                entity_type=current.entity_type,
                operation=WriteOperation.CLOSE,
                entity_id=current.id,
                summary="it is done with",
            )
        ),
        owner_id=owner,
        close_status=status,
        closed_at=at,
        expected_revision=(current.revision if expected_revision is None else expected_revision),
    )


def apply(
    service: GraphWriteService,
    writes: tuple[ResolvedGraphWrite, ...],
    *,
    key: str,
    now: datetime = NOW,
    request_id: RequestId | None = None,
    correlation_id: CorrelationId | None = None,
    owner: UserId = OWNER,
):
    return service.apply(
        writes,
        owner_id=owner,
        request_id=request_id or new_request_id(),
        correlation_id=correlation_id or new_correlation_id(),
        idempotency_key=key,
        now=now,
    )


def _batch(entity: Entity, *, expected_revision: int | None, key: str) -> GraphWriteBatch:
    operation = WriteOperation.CREATE if expected_revision is None else WriteOperation.REVISE
    event = DomainEvent.emit(
        event_type=(
            EventType.GRAPH_ENTITY_CREATED
            if expected_revision is None
            else EventType.GRAPH_ENTITY_REVISED
        ),
        payload=GraphMutationPayload(
            entity_id=entity.id,
            entity_type=entity.entity_type,
            revision=entity.revision,
            status=entity.status,
        ),
        actor=Actor.agent_actor(AgentName.LIFE_ADMIN, OWNER),
        subject=Subject(owner_id=OWNER, entity_id=entity.id),
        source=entity.attribution.source,
        sensitivity=entity.attribution.sensitivity,
        occurred_at=NOW,
    )
    return GraphWriteBatch(
        owner_id=OWNER,
        idempotency_key=key,
        fingerprint=f"fingerprint-{key}",
        run=RuntimeRunRecord(
            request_id=new_request_id(),
            correlation_id=new_correlation_id(),
            owner_id=OWNER,
            status=RuntimeStatus.COMPLETED,
            started_at=NOW,
            completed_at=NOW,
        ),
        commits=(
            GraphCommit(
                operation=operation,
                entity=entity,
                expected_revision=expected_revision,
                event=event,
            ),
        ),
    )


class PowerCut(RuntimeError):
    """The process died between the last statement and COMMIT."""


class CrashingGraphStore(SQLiteGraphStore):
    """A store whose every transaction dies just before it would commit."""

    @contextmanager
    def transaction(self) -> Iterator[object]:
        with SQLiteGraphStore.transaction(self) as connection:
            yield connection
            raise PowerCut("the process died before COMMIT")


class WritingAgent:
    """A mind that asks for graph changes, so the runtime has writes to sanction."""

    def __init__(self, agent: AgentName, writes: tuple[GraphWriteIntent, ...]) -> None:
        self.agent = agent
        self.writes = writes

    @property
    def contract(self):
        return contract_for(self.agent)

    def run(self, invocation: AgentInvocation) -> AgentOutput:
        return AgentOutput(agent=self.agent, request_id=invocation.request_id, writes=self.writes)


class MappedResolver:
    """Turns each intent into the concrete typed entity the test prepared.

    It composes the resolved write around the ``SanctionedWrite`` it was handed,
    which is what a real resolver does: it supplies data, not authority.
    """

    def __init__(self, by_summary: dict[str, Entity]) -> None:
        self.by_summary = by_summary

    def resolve(
        self, request: SanctionedWrite, *, owner_id: UserId, at: datetime
    ) -> ResolvedGraphWrite:
        return ResolvedGraphWrite(
            sanctioned=request,
            owner_id=owner_id,
            entity=self.by_summary[request.intent.summary],
        )


class SubstitutingResolver:
    """A resolver that hands back a write attributed to something else."""

    def __init__(
        self,
        substitute: SanctionedWrite,
        entity: Entity,
        *,
        expected_revision: int | None = None,
    ) -> None:
        self.substitute = substitute
        self.entity = entity
        self.expected_revision = expected_revision

    def resolve(
        self, request: SanctionedWrite, *, owner_id: UserId, at: datetime
    ) -> ResolvedGraphWrite:
        return ResolvedGraphWrite(
            sanctioned=self.substitute,
            owner_id=owner_id,
            entity=self.entity,
            expected_revision=self.expected_revision,
        )


# --- 01 ----------------------------------------------------------------------


def test_01_create_survives_restart(service, store, db):
    """01 — a created entity is still there, canonical, after the process goes away."""
    entity = commitment()

    receipt = apply(service, (create_write(entity),), key="k-create")

    assert receipt.outcome is GraphWriteOutcome.APPLIED
    assert receipt.writes[0].entity_id == entity.id
    assert receipt.writes[0].revision == 1

    del service, store
    reopened = SQLiteGraphStore(db)
    found = reopened.current_entity(entity.id)

    assert found == entity
    assert isinstance(found.attributes, CommitmentAttributes)
    assert found.attribution == entity.attribution
    assert found.attribution.sensitivity is SensitivityLevel.S2
    assert found.temporal == entity.temporal
    assert found.status is RecordStatus.ACTIVE


# --- 02 ----------------------------------------------------------------------


def test_02_a_crash_before_commit_leaves_neither_the_entity_nor_the_event(db):
    entity = commitment()
    crashing = GraphWriteService(store=CrashingGraphStore(db))

    with pytest.raises(PowerCut):
        apply(crashing, (create_write(entity),), key="k-crash")

    after = SQLiteGraphStore(db)
    assert after.current_entity(entity.id) is None
    assert after.count_entity_versions() == 0
    assert after.count_events() == 0
    assert after.receipt_for(owner_id=OWNER, idempotency_key="k-crash") is None


def test_02_a_committed_write_leaves_both(service, store):
    entity = commitment()

    apply(service, (create_write(entity),), key="k-commit")

    assert store.current_entity(entity.id) is not None
    assert store.count_events() == 1
    assert store.pending_events()[0].event.subject.entity_id == entity.id


# --- 03 ----------------------------------------------------------------------


def test_03_a_retried_create_is_one_entity_and_one_event(service, store):
    """03 — the same command under the same key, sent twice.

    The retry rebuilds the entity, so it carries a freshly minted id. That is
    what a real retry looks like, and it is why the fingerprint ignores the id
    a ``CREATE`` mints.
    """
    first = apply(service, (create_write(commitment()),), key="k-retry")
    second = apply(service, (create_write(commitment()),), key="k-retry")

    assert first.outcome is GraphWriteOutcome.APPLIED
    assert second.outcome is GraphWriteOutcome.DUPLICATE
    assert second.writes == first.writes
    assert second.request_id == first.request_id
    assert store.count_entity_versions() == 1
    assert store.count_events() == 1


def test_03_a_retry_of_the_identical_command_object_is_also_one_entity(service, store):
    write = create_write(commitment())

    first = apply(service, (write,), key="k-same")
    second = apply(service, (write,), key="k-same")

    assert first.outcome is GraphWriteOutcome.APPLIED
    assert second.outcome is GraphWriteOutcome.DUPLICATE
    assert store.count_entity_versions() == 1
    assert store.count_events() == 1


# --- 04 ----------------------------------------------------------------------


def test_04_the_same_key_for_a_different_write_conflicts(service, store):
    applied = apply(service, (create_write(commitment(label="Return the dress")),), key="k-shared")
    reused = apply(service, (create_write(commitment(label="Return the boots")),), key="k-shared")

    assert applied.outcome is GraphWriteOutcome.APPLIED
    assert reused.outcome is GraphWriteOutcome.CONFLICT
    assert reused.writes == ()
    assert store.count_entity_versions() == 1
    assert store.count_events() == 1


def test_04_a_conflicting_retry_does_not_disturb_what_was_stored(service, store):
    entity = commitment(label="Return the dress")
    apply(service, (create_write(entity),), key="k-shared")

    apply(service, (create_write(commitment(label="Return the boots")),), key="k-shared")

    assert store.current_entity(entity.id) == entity


def test_04_two_workers_that_both_validated_still_produce_one_write(store):
    """The key is enforced by the database, not by the look-up before it.

    Two attempts that both found nothing stored still both reach ``commit``.
    Exactly one of them inserts the request row, and the other writes nothing
    whatever it was carrying.
    """
    first = _batch(commitment(), expected_revision=None, key="k-race")
    second = _batch(commitment(), expected_revision=None, key="k-race")

    applied = store.commit(first)
    lost = store.commit(second)

    assert applied.outcome is GraphWriteOutcome.APPLIED
    assert lost.outcome is GraphWriteOutcome.DUPLICATE
    assert lost.writes == applied.writes
    assert store.count_entity_versions() == 1
    assert store.count_events() == 1


def test_04_the_database_refuses_a_reused_key_carrying_something_else(store):
    applied = store.commit(_batch(commitment(), expected_revision=None, key="k-race"))
    different = _batch(commitment(), expected_revision=None, key="k-race").model_copy(
        update={"fingerprint": "a completely different command"}
    )

    lost = store.commit(different)

    assert applied.outcome is GraphWriteOutcome.APPLIED
    assert lost.outcome is GraphWriteOutcome.CONFLICT
    assert store.count_entity_versions() == 1
    assert store.count_events() == 1


# --- 05 ----------------------------------------------------------------------


def test_05_a_revision_is_appended_and_the_earlier_version_stays_readable(service, store):
    entity = commitment(label="Return the dress")
    apply(service, (create_write(entity),), key="k1")

    apply(service, (revise_write(entity, label="Return the dress to the shop"),), key="k2")

    versions = store.entity_versions(entity.id)
    assert [version.revision for version in versions] == [1, 2]
    assert versions[0].label == "Return the dress"
    assert versions[1].label == "Return the dress to the shop"
    assert store.current_entity(entity.id).revision == 2


# --- 06 ----------------------------------------------------------------------


def test_06_a_second_write_built_on_the_same_revision_loses(service, store):
    entity = commitment()
    apply(service, (create_write(entity),), key="k1")
    read_by_both_devices = store.current_entity(entity.id)

    apply(service, (revise_write(read_by_both_devices, label="from the phone"),), key="k-a")

    with pytest.raises(ConcurrentModification):
        apply(service, (revise_write(read_by_both_devices, label="from the laptop"),), key="k-b")

    assert store.current_entity(entity.id).label == "from the phone"
    assert len(store.entity_versions(entity.id)) == 2
    assert store.count_events() == 2


def test_06_the_concurrency_guard_is_in_the_database_not_only_in_the_service(store):
    """The service checks the revision, but so does the write itself.

    A racer that got past the check — two workers reading the same revision at
    the same moment — still has to insert, and the insert is conditional.
    """
    entity = commitment()
    store.commit(_batch(entity, expected_revision=None, key="k-first"))
    stale = entity.revised(at=LATER, label="from the phone")
    store.commit(_batch(stale, expected_revision=1, key="k-second"))

    racer = entity.revised(at=LATER, label="from the laptop")
    with pytest.raises(ConcurrentModification):
        store.commit(_batch(racer, expected_revision=1, key="k-third"))

    assert store.current_entity(entity.id).label == "from the phone"


# --- 07 ----------------------------------------------------------------------


def test_07_a_revision_and_its_history_survive_restart(service, store, db):
    entity = commitment(label="Return the dress")
    apply(service, (create_write(entity),), key="k1")
    apply(service, (revise_write(entity, label="Return the dress to the shop"),), key="k2")

    del service, store
    reopened = SQLiteGraphStore(db)

    assert reopened.current_entity(entity.id).revision == 2
    assert reopened.current_entity(entity.id).label == "Return the dress to the shop"
    history = reopened.entity_versions(entity.id)
    assert [version.revision for version in history] == [1, 2]
    assert history[0].label == "Return the dress"


# --- 08 ----------------------------------------------------------------------


def test_08_a_closed_entity_survives_restart_and_leaves_the_active_view(service, store, db):
    entity = commitment()
    apply(service, (create_write(entity),), key="k1")

    apply(service, (close_write(entity, at=LATER),), key="k2")

    del service, store
    reopened = SQLiteGraphStore(db)
    current = reopened.current_entity(entity.id)

    assert current.status is RecordStatus.ARCHIVED
    assert current.temporal.valid_until == LATER
    assert reopened.active_entities(owner_id=OWNER, at=LATER) == ()
    assert len(reopened.entity_versions(entity.id)) == 2


def test_08_closing_does_not_rewrite_what_the_graph_said_yesterday(service, store):
    entity = commitment()
    apply(service, (create_write(entity),), key="k1")
    apply(service, (close_write(entity, at=LATER),), key="k2")

    still_open_then = store.active_entities(owner_id=OWNER, at=NOW)

    assert [item.id for item in still_open_then] == [entity.id]


def test_08_closing_something_already_closed_is_refused(service, store):
    entity = commitment()
    apply(service, (create_write(entity),), key="k1")
    apply(service, (close_write(entity, at=LATER),), key="k2")

    again = apply(service, (close_write(entity, at=LATER),), key="k3")

    assert again.outcome is GraphWriteOutcome.REJECTED
    assert "already ARCHIVED" in (again.detail or "")
    assert len(store.entity_versions(entity.id)) == 2


# --- 09 ----------------------------------------------------------------------


def test_09_a_write_outside_a_contract_is_refused_by_the_service(service, store):
    """09 — Navigator does not write commitments, and the persistence boundary
    refuses it even if something upstream did not."""
    with pytest.raises(ContractViolation):
        apply(service, (create_write(commitment(), agent=AgentName.NAVIGATOR),), key="k-rogue")

    assert store.count_entity_versions() == 0
    assert store.count_events() == 0


def test_09_a_run_containing_an_out_of_contract_write_never_reaches_persistence(store):
    harness = build_harness()
    harness.runtime.agents[AgentName.LIFE_ADMIN] = WritingAgent(
        AgentName.LIFE_ADMIN,
        (
            GraphWriteIntent(
                entity_type=EntityType.RADAR_ITEM,
                operation=WriteOperation.CREATE,
                summary="a deal Life Admin has no business recording",
            ),
        ),
    )
    request = RuntimeRequest.from_user(user_id=OWNER, at=NOW, utterance="save this")

    with pytest.raises(ContractViolation):
        harness.runtime.run(request, graph=harness.graph, intent=Intent.CAPTURE, now=NOW)

    assert store.count_entity_versions() == 0
    assert store.count_events() == 0


# --- 10 ----------------------------------------------------------------------


def test_10_an_entity_that_is_not_the_type_the_intent_asked_for_is_rejected(service, store):
    receipt = apply(
        service,
        (create_write(task(), declared_type=EntityType.COMMITMENT),),
        key="k-mismatch",
    )

    assert receipt.outcome is GraphWriteOutcome.REJECTED
    assert "COMMITMENT" in (receipt.detail or "")
    assert store.count_entity_versions() == 0
    assert store.count_events() == 0


def test_10_a_revision_cannot_change_what_an_entity_is(service, store):
    entity = commitment()
    apply(service, (create_write(entity),), key="k1")

    receipt = apply(
        service,
        (
            ResolvedGraphWrite(
                sanctioned=sanctioned(
                    GraphWriteIntent(
                        entity_type=EntityType.TASK,
                        operation=WriteOperation.REVISE,
                        entity_id=entity.id,
                        summary="call it a task instead",
                    )
                ),
                owner_id=OWNER,
                entity=entity.revised(at=LATER, label="now a task"),
                expected_revision=1,
            ),
        ),
        key="k-retype",
    )

    assert receipt.outcome is GraphWriteOutcome.REJECTED
    assert store.current_entity(entity.id).entity_type is EntityType.COMMITMENT
    assert len(store.entity_versions(entity.id)) == 1


def test_10_a_revision_carrying_a_different_kind_of_entity_is_rejected(service, store):
    """Even when the intent agrees with what is stored, the entity itself must."""
    entity = commitment()
    apply(service, (create_write(entity),), key="k1")
    impostor = task().model_copy(update={"id": entity.id, "revision": 2})

    receipt = apply(
        service,
        (
            ResolvedGraphWrite(
                sanctioned=sanctioned(
                    GraphWriteIntent(
                        entity_type=EntityType.COMMITMENT,
                        operation=WriteOperation.REVISE,
                        entity_id=entity.id,
                        summary="quietly a task now",
                    )
                ),
                owner_id=OWNER,
                entity=impostor,
                expected_revision=1,
            ),
        ),
        key="k-swap",
    )

    assert receipt.outcome is GraphWriteOutcome.REJECTED
    assert "type cannot change" in (receipt.detail or "")
    assert store.current_entity(entity.id).entity_type is EntityType.COMMITMENT


# --- 11 ----------------------------------------------------------------------


def test_11_a_write_cannot_reach_an_entity_someone_else_owns(service, store):
    hers = commitment(owner=STRANGER)
    apply(
        service,
        (create_write(hers, owner=STRANGER),),
        key="k-hers",
        owner=STRANGER,
    )

    receipt = apply(service, (revise_write(hers, label="mine now"),), key="k-theft")

    assert receipt.outcome is GraphWriteOutcome.REJECTED
    assert "belongs to someone else" in (receipt.detail or "")
    assert len(store.entity_versions(hers.id)) == 1
    assert store.count_events() == 1


def test_11_a_create_for_another_owner_is_rejected(service, store):
    receipt = apply(service, (create_write(commitment(owner=STRANGER)),), key="k-owner")

    assert receipt.outcome is GraphWriteOutcome.REJECTED
    assert store.count_entity_versions() == 0
    assert store.count_events() == 0


def test_11_a_write_naming_a_different_owner_than_the_batch_is_rejected(service, store):
    receipt = apply(
        service,
        (create_write(commitment(owner=STRANGER), owner=STRANGER),),
        key="k-mixed",
        owner=OWNER,
    )

    assert receipt.outcome is GraphWriteOutcome.REJECTED
    assert "different owner" in (receipt.detail or "")
    assert store.count_entity_versions() == 0


# --- 12 ----------------------------------------------------------------------


def test_12_one_invalid_write_stops_the_whole_batch(service, store):
    """12 — writes from one run are applied as one unit.

    They came from one decision. Persisting half of it would leave the graph in
    a state no mind reached and nothing downstream could interpret.
    """
    good = create_write(commitment())
    bad = create_write(task(), declared_type=EntityType.COMMITMENT)

    receipt = apply(service, (good, bad), key="k-batch")

    assert receipt.outcome is GraphWriteOutcome.REJECTED
    assert store.count_entity_versions() == 0
    assert store.count_events() == 0
    assert store.run_record(receipt.request_id) is None


def test_12_a_valid_batch_applies_every_write_together(service, store):
    request_id = new_request_id()

    receipt = apply(
        service,
        (create_write(commitment()), create_write(task())),
        key="k-both",
        request_id=request_id,
    )

    assert receipt.outcome is GraphWriteOutcome.APPLIED
    assert len(receipt.writes) == 2
    assert store.count_entity_versions() == 2
    assert store.count_events() == 2
    assert len(store.run_record(request_id).entity_ids) == 2


def test_12_two_writes_to_one_entity_in_one_batch_are_refused(service, store):
    entity = commitment()
    apply(service, (create_write(entity),), key="k1")

    receipt = apply(
        service,
        (revise_write(entity, label="first"), revise_write(entity, label="second")),
        key="k-double",
    )

    assert receipt.outcome is GraphWriteOutcome.REJECTED
    assert "twice in one batch" in (receipt.detail or "")
    assert len(store.entity_versions(entity.id)) == 1


# --- 13 ----------------------------------------------------------------------


def test_13_the_run_record_survives_restart(service, store, db):
    request_id = new_request_id()
    correlation_id = new_correlation_id()
    entity = commitment()

    receipt = apply(
        service,
        (create_write(entity),),
        key="k-run",
        request_id=request_id,
        correlation_id=correlation_id,
    )

    del service, store
    run = SQLiteGraphStore(db).run_record(request_id)

    assert run.request_id == request_id
    assert run.correlation_id == correlation_id
    assert run.status is RuntimeStatus.COMPLETED
    assert run.entity_ids == (entity.id,)
    assert run.event_ids == (receipt.writes[0].event_id,)


def test_13_a_run_record_carries_identity_and_references_and_nothing_else():
    """No trace, no utterance, no composed items. A run is remembered by what it
    changed, not by how it thought."""
    assert set(RuntimeRunRecord.model_fields) == {
        "request_id",
        "correlation_id",
        "owner_id",
        "status",
        "started_at",
        "completed_at",
        "entity_ids",
        "event_ids",
    }


# --- 14 ----------------------------------------------------------------------


def test_14_a_crash_after_commit_loses_neither_the_mutation_nor_the_event(service, store, db):
    entity = commitment()
    receipt = apply(service, (create_write(entity),), key="k-after")

    del service, store
    fresh = SQLiteGraphStore(db)

    assert fresh.current_entity(entity.id) == entity
    pending = fresh.pending_events()
    assert [item.event.event_id for item in pending] == [receipt.writes[0].event_id]
    assert pending[0].state is OutboxState.PENDING


def test_14_an_applied_event_leaves_the_pending_set(service, store):
    entity = commitment()
    receipt = apply(service, (create_write(entity),), key="k-applied")

    store.mark_event_applied(receipt.writes[0].event_id)

    assert store.pending_events() == ()
    assert store.event(receipt.writes[0].event_id).state is OutboxState.APPLIED


# --- 15 ----------------------------------------------------------------------


def test_15_a_second_delivery_of_the_same_event_has_no_second_effect(service, store):
    receipt = apply(service, (create_write(commitment()),), key="k-once")
    event_id = receipt.writes[0].event_id

    assert store.apply_once(consumer_name="today", event_id=event_id) is True
    assert store.apply_once(consumer_name="today", event_id=event_id) is False


def test_15_each_consumer_gets_the_event_once_of_its_own(service, store):
    receipt = apply(service, (create_write(commitment()),), key="k-once")
    event_id = receipt.writes[0].event_id

    assert store.apply_once(consumer_name="today", event_id=event_id) is True
    assert store.apply_once(consumer_name="weekly_digest", event_id=event_id) is True
    assert store.apply_once(consumer_name="weekly_digest", event_id=event_id) is False


# --- the runtime connection --------------------------------------------------


def test_the_runtime_reports_the_writes_its_minds_asked_for():
    harness = build_harness()
    intent = GraphWriteIntent(
        entity_type=EntityType.COMMITMENT,
        operation=WriteOperation.CREATE,
        summary="the dress goes back on Thursday",
    )
    harness.runtime.agents[AgentName.LIFE_ADMIN] = WritingAgent(AgentName.LIFE_ADMIN, (intent,))
    request = RuntimeRequest.from_user(user_id=OWNER, at=NOW, utterance="the dress goes back")

    result = harness.runtime.run(request, graph=harness.graph, intent=Intent.CAPTURE, now=NOW)

    assert result.sanctioned_writes == (SanctionedWrite(agent=AgentName.LIFE_ADMIN, intent=intent),)


def test_a_sanctioned_runtime_write_is_persisted_through_the_service(service, store):
    harness = build_harness()
    intent = GraphWriteIntent(
        entity_type=EntityType.COMMITMENT,
        operation=WriteOperation.CREATE,
        summary="the dress goes back on Thursday",
    )
    harness.runtime.agents[AgentName.LIFE_ADMIN] = WritingAgent(AgentName.LIFE_ADMIN, (intent,))
    request = RuntimeRequest.from_user(user_id=OWNER, at=NOW, utterance="the dress goes back")
    result = harness.runtime.run(request, graph=harness.graph, intent=Intent.CAPTURE, now=NOW)
    entity = commitment()

    receipt = service.apply_runtime_result(
        result,
        owner_id=OWNER,
        resolver=MappedResolver({intent.summary: entity}),
        idempotency_key="k-runtime",
        now=NOW,
    )

    assert receipt.outcome is GraphWriteOutcome.APPLIED
    assert store.current_entity(entity.id) == entity
    assert store.run_record(result.request_id).correlation_id == result.correlation_id


def test_a_blocked_run_persists_nothing(service, store):
    harness = build_harness(guardian_available=False)
    intent = GraphWriteIntent(
        entity_type=EntityType.COMMITMENT,
        operation=WriteOperation.CREATE,
        summary="the dress goes back on Thursday",
    )
    harness.runtime.agents[AgentName.LIFE_ADMIN] = WritingAgent(AgentName.LIFE_ADMIN, (intent,))
    request = RuntimeRequest.from_user(user_id=OWNER, at=NOW, utterance="the dress goes back")
    result = harness.runtime.run(request, graph=harness.graph, intent=Intent.CAPTURE, now=NOW)

    receipt = service.apply_runtime_result(
        result,
        owner_id=OWNER,
        resolver=MappedResolver({intent.summary: commitment()}),
        idempotency_key="k-blocked",
        now=NOW,
    )

    assert result.status is RuntimeStatus.BLOCKED
    assert receipt.outcome is GraphWriteOutcome.REJECTED
    assert store.count_entity_versions() == 0
    assert store.count_events() == 0


# --- the events a mutation announces -----------------------------------------


def test_a_canonical_event_is_used_where_the_catalog_has_one(service, store):
    entity = commitment()
    created = apply(service, (create_write(entity),), key="k1")

    completed = apply(service, (revise_write(entity, state=OpenLoopState.COMPLETED),), key="k2")

    assert created.writes[0].event_type is EventType.COMMITMENT_CAPTURED
    assert completed.writes[0].event_type is EventType.COMMITMENT_COMPLETED


def test_a_revision_that_is_not_a_completion_says_so(service):
    entity = commitment()
    apply(service, (create_write(entity),), key="k1")

    revised = apply(service, (revise_write(entity, label="the shop moved"),), key="k2")

    assert revised.writes[0].event_type is EventType.COMMITMENT_UPDATED


def test_life_admin_cannot_write_a_body_signal(service):
    with pytest.raises(ContractViolation):
        apply(service, (create_write(body_signal()),), key="k-signal")


def test_the_generic_vocabulary_covers_a_close_that_no_event_names(service):
    entity = commitment()
    apply(service, (create_write(entity),), key="k1")

    closed = apply(service, (close_write(entity),), key="k2")

    assert closed.writes[0].event_type is EventType.GRAPH_ENTITY_CLOSED


def test_a_body_signal_records_under_its_canonical_event():
    entity = Entity.create(
        owner_id=OWNER,
        entity_type=EntityType.BODY_SIGNAL,
        label="Slept badly",
        attributes=BodySignalAttributes(signal=BodySignalKind.SLEEP, scale_value=3.0),
        attribution=Attribution.declared(NOW, default_sensitivity(EntityType.BODY_SIGNAL)),
        at=NOW,
    )

    resolution = resolve_graph_event(operation=WriteOperation.CREATE, entity=entity, previous=None)

    assert resolution.event_type is EventType.SLEEP_UPDATED


def test_a_signal_the_catalog_does_not_name_falls_back_rather_than_borrowing_one():
    resolution = resolve_graph_event(
        operation=WriteOperation.CREATE, entity=body_signal(), previous=None
    )

    assert resolution.event_type is EventType.GRAPH_ENTITY_CREATED


# --- what an event may carry -------------------------------------------------


def test_a_mutation_event_carries_a_reference_and_never_the_content():
    """The privacy boundary. An event says *that* something changed and where to
    read it; the note she wrote stays in the graph behind context projection."""
    entity = body_signal()

    resolution = resolve_graph_event(operation=WriteOperation.CREATE, entity=entity, previous=None)
    serialized = resolution.payload.model_dump_json()

    assert entity.label not in serialized
    assert "worse than last cycle" not in serialized
    assert set(resolution.payload.model_dump()) == {
        "entity_id",
        "entity_type",
        "revision",
        "status",
    }


def test_an_event_is_classified_as_sharply_as_the_record_it_is_about(service, store):
    entity = commitment()
    apply(service, (create_write(entity),), key="k1")

    event = store.pending_events()[0].event

    assert event.sensitivity is SensitivityLevel.S2
    assert event.subject.entity_id == entity.id
    assert event.actor.agent is AgentName.LIFE_ADMIN
    assert entity.label not in event.model_dump_json()


def test_an_event_carries_the_provenance_of_the_record_it_announces(service, store):
    entity = commitment(source=_source(reference="msg_42", detail=PRIVATE))
    apply(service, (create_write(entity),), key="k1")

    event = store.pending_events()[0].event

    assert event.source.source_type is entity.source.source_type
    assert event.source.captured_at == entity.source.captured_at
    assert event.source.reference == "msg_42"
    assert event.source.detail is None


def test_the_event_and_the_revision_it_announces_are_one_to_one(service, store):
    entity = commitment()
    apply(service, (create_write(entity),), key="k1")
    apply(service, (revise_write(entity, label="corrected"),), key="k2")

    versions = [item.aggregate_version for item in store.pending_events()]

    assert versions == [1, 2]
    assert all(item.aggregate_id == entity.id for item in store.pending_events())


# --- the store returns canonical models --------------------------------------


def test_what_comes_back_out_of_the_database_is_the_domain_model(service, store):
    entity = commitment(due_at=LATER)
    apply(service, (create_write(entity),), key="k1")

    found = store.current_entity(entity.id)

    assert type(found) is Entity
    assert type(found.attributes) is CommitmentAttributes
    assert found.markers.due_at == LATER
    assert found.attributes_as(CommitmentAttributes).kind is CommitmentKind.RETURN
    assert found.is_active_at(NOW)


def test_a_reconstructed_entity_still_enforces_its_invariants(service, store):
    entity = commitment()
    apply(service, (create_write(entity),), key="k1")
    apply(service, (close_write(entity, status=RecordStatus.SUPERSEDED),), key="k2")

    closed = store.current_entity(entity.id)

    with pytest.raises(Exception, match="cannot be revised"):
        closed.revised(at=LATER, label="too late")


def test_an_unknown_entity_reads_back_as_absent_rather_than_as_an_empty_record(store):
    assert store.current_entity(EntityId("ent_nothing")) is None
    assert store.entity_versions(EntityId("ent_nothing")) == ()
    assert store.active_entities(owner_id=OWNER, at=NOW) == ()


# --- review round 1: B01-B08 and N01 -----------------------------------------


class RacingGraphStore(SQLiteGraphStore):
    """A store that lets another caller commit inside this one's idempotency look-up.

    The interleaving that matters is: A looks up the key and finds nothing, B
    commits the identical request, A then validates against the state B left.
    The hook fires on the first miss and A still receives the answer its look-up
    actually saw, which is what makes the race deterministic without a sleep.
    """

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.on_first_miss: Callable[[], None] | None = None

    def receipt_for(self, *, owner_id: UserId, idempotency_key: str) -> StoredReceipt | None:
        found = super().receipt_for(owner_id=owner_id, idempotency_key=idempotency_key)
        if found is None and self.on_first_miss is not None:
            hook, self.on_first_miss = self.on_first_miss, None
            hook()
        return found


def _apply_one(
    service: GraphWriteService, write: ResolvedGraphWrite, *, key: str
) -> GraphWriteReceipt:
    return service.apply(
        (write,),
        owner_id=OWNER,
        request_id=new_request_id(),
        correlation_id=new_correlation_id(),
        idempotency_key=key,
        now=NOW,
    )


def test_revise_must_not_transfer_owner(service, store):
    """B01 — a revision changes what a record says, never whose it is."""
    entity = commitment()
    apply(service, (create_write(entity),), key="k1")
    hijacked = entity.revised(at=LATER, label="same loop").model_copy(update={"owner_id": STRANGER})

    receipt = apply(
        service,
        (
            ResolvedGraphWrite(
                sanctioned=sanctioned(
                    GraphWriteIntent(
                        entity_type=EntityType.COMMITMENT,
                        operation=WriteOperation.REVISE,
                        entity_id=entity.id,
                        summary="quietly hers now",
                    )
                ),
                owner_id=OWNER,
                entity=hijacked,
                expected_revision=1,
            ),
        ),
        key="k-transfer",
    )

    assert receipt.outcome is GraphWriteOutcome.REJECTED
    assert "owner" in (receipt.detail or "")
    assert len(store.entity_versions(entity.id)) == 1
    assert store.current_entity(entity.id).owner_id == OWNER
    assert store.count_events() == 1


def test_close_must_honor_expected_revision(service, store):
    """B02 — closing is a write, and a write names the version it saw."""
    entity = commitment()
    apply(service, (create_write(entity),), key="k1")
    read_before = store.current_entity(entity.id)
    apply(service, (revise_write(read_before, label="the shop moved"),), key="k2")

    with pytest.raises(ConcurrentModification):
        apply(service, (close_write(read_before, expected_revision=1),), key="k3")

    assert store.current_entity(entity.id).status is RecordStatus.ACTIVE
    assert len(store.entity_versions(entity.id)) == 2
    assert store.count_events() == 2

    closed = apply(service, (close_write(store.current_entity(entity.id)),), key="k4")

    assert closed.outcome is GraphWriteOutcome.APPLIED
    assert store.current_entity(entity.id).status is RecordStatus.ARCHIVED
    assert len(store.entity_versions(entity.id)) == 3


def test_close_time_is_part_of_idempotency(service, store):
    """B03 — the closure time sets valid_until, so it is part of the command."""
    entity = commitment()
    apply(service, (create_write(entity),), key="k1")
    current = store.current_entity(entity.id)

    first = apply(service, (close_write(current, at=LATER),), key="k-close")
    same_time = apply(service, (close_write(current, at=LATER),), key="k-close")
    other_time = apply(
        service, (close_write(current, at=LATER + timedelta(hours=3)),), key="k-close"
    )

    assert first.outcome is GraphWriteOutcome.APPLIED
    assert same_time.outcome is GraphWriteOutcome.DUPLICATE
    assert same_time.writes == first.writes
    assert other_time.outcome is GraphWriteOutcome.CONFLICT
    assert store.current_entity(entity.id).temporal.valid_until == LATER
    assert len(store.entity_versions(entity.id)) == 2


def test_close_time_in_another_zone_is_the_same_closure(service, store):
    """The fingerprint normalises to UTC, so an offset is not a new command."""
    entity = commitment()
    apply(service, (create_write(entity),), key="k1")
    current = store.current_entity(entity.id)
    elsewhere = LATER.astimezone(ZoneInfo("Asia/Riyadh"))

    first = apply(service, (close_write(current, at=LATER),), key="k-zone")
    again = apply(service, (close_write(current, at=elsewhere),), key="k-zone")

    assert first.outcome is GraphWriteOutcome.APPLIED
    assert again.outcome is GraphWriteOutcome.DUPLICATE


def test_retry_after_lookup_race_returns_duplicate(db):
    """B04 — a retry that loses the race is a duplicate, never a rejection."""
    racing = RacingGraphStore(db)
    late = GraphWriteService(store=racing)
    winner = GraphWriteService(store=SQLiteGraphStore(db))
    write = create_write(commitment())
    won: list[GraphWriteReceipt] = []
    racing.on_first_miss = lambda: won.append(_apply_one(winner, write, key="k-race"))

    answer = _apply_one(late, write, key="k-race")

    assert won[0].outcome is GraphWriteOutcome.APPLIED
    assert answer.outcome is GraphWriteOutcome.DUPLICATE
    assert answer.writes == won[0].writes
    assert racing.count_entity_versions() == 1
    assert racing.count_events() == 1


def test_retry_after_lookup_race_returns_duplicate_for_a_revision(db):
    """The same race on a REVISE, where the loser's read is now stale."""
    setup = GraphWriteService(store=SQLiteGraphStore(db))
    entity = commitment()
    _apply_one(setup, create_write(entity), key="k-setup")

    racing = RacingGraphStore(db)
    late = GraphWriteService(store=racing)
    winner = GraphWriteService(store=SQLiteGraphStore(db))
    write = revise_write(entity, label="the shop moved")
    won: list[GraphWriteReceipt] = []
    racing.on_first_miss = lambda: won.append(_apply_one(winner, write, key="k-race"))

    answer = _apply_one(late, write, key="k-race")

    assert won[0].outcome is GraphWriteOutcome.APPLIED
    assert answer.outcome is GraphWriteOutcome.DUPLICATE
    assert answer.writes == won[0].writes
    assert len(racing.entity_versions(entity.id)) == 2
    assert racing.count_events() == 2


def test_a_genuinely_stale_revision_under_its_own_key_still_raises(db):
    """The re-check answers a retry, not every failure. A different request that
    lost a revision race is still a conflict the caller must see."""
    service = GraphWriteService(store=SQLiteGraphStore(db))
    entity = commitment()
    _apply_one(service, create_write(entity), key="k-setup")
    _apply_one(service, revise_write(entity, label="from the phone"), key="k-a")

    with pytest.raises(ConcurrentModification):
        _apply_one(service, revise_write(entity, label="from the laptop"), key="k-b")


def test_event_does_not_copy_free_text_source_detail(service, store, db):
    """B05 — the announcement names where a fact came from, not what she said."""
    entity = commitment(source=_source(reference="msg_42", detail=PRIVATE))

    apply(service, (create_write(entity),), key="k1")

    with sqlite3.connect(db) as raw:
        rows = raw.execute("SELECT envelope_json FROM graph_outbox").fetchall()
    persisted = "".join(str(row[0]) for row in rows)

    assert rows
    assert PRIVATE not in persisted
    assert PRIVATE in store.current_entity(entity.id).model_dump_json()
    assert "msg_42" in persisted
    assert store.pending_events()[0].event.source.detail is None


def test_resolver_must_preserve_sanctioned_agent_and_intent(service, store):
    """B06 — a resolver resolves data. It does not decide who authorized it."""
    harness = build_harness()
    intent = GraphWriteIntent(
        entity_type=EntityType.COMMITMENT,
        operation=WriteOperation.CREATE,
        summary="the dress goes back on Thursday",
    )
    harness.runtime.agents[AgentName.LIFE_ADMIN] = WritingAgent(AgentName.LIFE_ADMIN, (intent,))
    request = RuntimeRequest.from_user(user_id=OWNER, at=NOW, utterance="the dress goes back")
    result = harness.runtime.run(request, graph=harness.graph, intent=Intent.CAPTURE, now=NOW)
    # A substitution the contract check alone would wave through: the Operator
    # may write commitments too. Only the binding to what was sanctioned catches
    # it.
    substitute = SanctionedWrite(
        agent=AgentName.OPERATOR,
        intent=GraphWriteIntent(
            entity_type=EntityType.COMMITMENT,
            operation=WriteOperation.CREATE,
            summary="something nobody asked for",
        ),
    )

    with pytest.raises(ContractViolation):
        service.apply_runtime_result(
            result,
            owner_id=OWNER,
            resolver=SubstitutingResolver(substitute, commitment()),
            idempotency_key="k-substitute",
            now=NOW,
        )

    assert store.count_entity_versions() == 0
    assert store.count_events() == 0


def test_resolver_must_preserve_the_target_of_a_revision(service, store):
    entity = commitment()
    apply(service, (create_write(entity),), key="k1")
    elsewhere = commitment(label="a different loop entirely")
    apply(service, (create_write(elsewhere),), key="k2")

    harness = build_harness()
    intent = GraphWriteIntent(
        entity_type=EntityType.COMMITMENT,
        operation=WriteOperation.REVISE,
        entity_id=entity.id,
        summary="she corrected it",
    )
    harness.runtime.agents[AgentName.LIFE_ADMIN] = WritingAgent(AgentName.LIFE_ADMIN, (intent,))
    request = RuntimeRequest.from_user(user_id=OWNER, at=NOW, utterance="correct it")
    result = harness.runtime.run(request, graph=harness.graph, intent=Intent.CAPTURE, now=NOW)
    swapped = SanctionedWrite(
        agent=AgentName.LIFE_ADMIN,
        intent=GraphWriteIntent(
            entity_type=EntityType.COMMITMENT,
            operation=WriteOperation.REVISE,
            entity_id=elsewhere.id,
            summary="she corrected it",
        ),
    )

    with pytest.raises(ContractViolation):
        service.apply_runtime_result(
            result,
            owner_id=OWNER,
            resolver=SubstitutingResolver(
                swapped,
                elsewhere.revised(at=LATER, label="not what she meant"),
                expected_revision=1,
            ),
            idempotency_key="k-swap-target",
            now=NOW,
        )

    assert len(store.entity_versions(elsewhere.id)) == 1
    assert store.count_events() == 2


def test_run_record_does_not_silently_drop_second_batch(service, store):
    """B07 — one request id is one run. A second, different batch under it is a
    contradiction, not a write whose run record quietly describes something else."""
    request_id = new_request_id()
    kept = commitment(label="Return the dress")

    first = apply(service, (create_write(kept),), key="k1", request_id=request_id)
    second = apply(
        service,
        (create_write(commitment(label="Cancel the gym")),),
        key="k2",
        request_id=request_id,
    )

    assert first.outcome is GraphWriteOutcome.APPLIED
    assert second.outcome is GraphWriteOutcome.CONFLICT
    assert store.count_entity_versions() == 1
    assert store.count_events() == 1
    run = store.run_record(request_id)
    assert run.entity_ids == (kept.id,)
    assert run.event_ids == (first.writes[0].event_id,)


def test_the_same_batch_under_one_request_id_is_a_retry_even_with_a_new_key(service, store):
    request_id = new_request_id()

    first = apply(service, (create_write(commitment()),), key="k1", request_id=request_id)
    again = apply(service, (create_write(commitment()),), key="k2", request_id=request_id)

    assert first.outcome is GraphWriteOutcome.APPLIED
    assert again.outcome is GraphWriteOutcome.DUPLICATE
    assert again.writes == first.writes
    assert store.count_entity_versions() == 1
    assert store.count_events() == 1


def test_revise_cannot_reopen_closed_record(service, store):
    """B08 — the lifecycle rule holds at the service boundary, not only in the
    helper a caller may have gone around."""
    entity = commitment()
    apply(service, (create_write(entity),), key="k1")
    apply(service, (close_write(store.current_entity(entity.id)),), key="k2")
    closed = store.current_entity(entity.id)
    reopened = closed.model_copy(
        update={
            "status": RecordStatus.ACTIVE,
            "revision": 3,
            "temporal": TemporalValidity.open_from(NOW),
        }
    )

    receipt = apply(
        service,
        (
            ResolvedGraphWrite(
                sanctioned=sanctioned(
                    GraphWriteIntent(
                        entity_type=EntityType.COMMITMENT,
                        operation=WriteOperation.REVISE,
                        entity_id=entity.id,
                        summary="open it again",
                    )
                ),
                owner_id=OWNER,
                entity=reopened,
                expected_revision=2,
            ),
        ),
        key="k-reopen",
    )

    assert receipt.outcome is GraphWriteOutcome.REJECTED
    assert "cannot be revised" in (receipt.detail or "")
    assert len(store.entity_versions(entity.id)) == 2
    assert store.current_entity(entity.id).status is RecordStatus.ARCHIVED
    assert store.count_events() == 2


def test_store_requires_exact_predecessor(store):
    """N01 — the adapter appends the successor of a named version, not merely
    something newer. A history with a hole cannot be read honestly."""
    entity = commitment()

    ahead = entity.model_copy(update={"revision": 4})
    with pytest.raises(ConcurrentModification):
        store.commit(_batch(ahead, expected_revision=3, key="k-ahead"))
    assert store.count_entity_versions() == 0

    store.commit(_batch(entity, expected_revision=None, key="k-create"))

    gap = entity.model_copy(update={"revision": 3})
    with pytest.raises(ConcurrentModification):
        store.commit(_batch(gap, expected_revision=2, key="k-gap"))
    assert [version.revision for version in store.entity_versions(entity.id)] == [1]

    store.commit(_batch(entity.revised(at=LATER, label="moved"), expected_revision=1, key="k-next"))

    assert [version.revision for version in store.entity_versions(entity.id)] == [1, 2]


def test_a_rejected_predecessor_leaves_no_event_behind(store):
    entity = commitment()
    store.commit(_batch(entity, expected_revision=None, key="k-create"))

    with pytest.raises(ConcurrentModification):
        store.commit(
            _batch(entity.model_copy(update={"revision": 3}), expected_revision=2, key="k-gap")
        )

    assert store.count_events() == 1
