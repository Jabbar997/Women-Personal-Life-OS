"""The durable Personal Life Graph.

What is stored is the canonical :class:`Entity` document. The columns beside it
— owner, type, status, revision — are an index over that document so the
database can answer "whose" and "which version" without parsing every row; they
are never read back into a model. Reconstruction goes through
``Entity.model_validate_json`` alone, so what comes out is the same model with
the same invariants that went in, and there is no second, weaker shape of an
entity anywhere in the system.

History is the table. There is no separate "current" row to drift out of step
with it: the current version of an entity is its highest revision, and a write
is an insert. Nothing is updated and nothing is deleted, which is the same
promise the in-memory graph makes, kept across a restart.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from wplos.application.graph_write import (
    AppliedWrite,
    GraphCommit,
    GraphWriteBatch,
    GraphWriteOutcome,
    GraphWriteReceipt,
    RuntimeRunRecord,
    StoredReceipt,
)
from wplos.core.identifiers import EntityId, EventId, RequestId, UserId
from wplos.events.envelope import DomainEvent
from wplos.integration.sqlite_support import connect, now_iso
from wplos.integration.sqlite_support import transaction as write_transaction
from wplos.integration.store import OutboxState
from wplos.personal_life_graph.entity import Entity
from wplos.shared.errors import ConcurrentModification, InvariantViolation

SCHEMA = """
CREATE TABLE IF NOT EXISTS graph_entity_versions (
    entity_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    owner_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    status TEXT NOT NULL,
    entity_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY(entity_id, revision)
);
CREATE INDEX IF NOT EXISTS graph_entity_owner
    ON graph_entity_versions(owner_id, entity_id, revision);
CREATE TABLE IF NOT EXISTS graph_outbox (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    aggregate_version INTEGER NOT NULL,
    correlation_id TEXT NOT NULL,
    causation_id TEXT,
    envelope_json TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(aggregate_id, aggregate_version)
);
CREATE TABLE IF NOT EXISTS graph_write_requests (
    owner_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(owner_id, idempotency_key)
);
CREATE UNIQUE INDEX IF NOT EXISTS graph_write_request_run
    ON graph_write_requests(request_id);
CREATE TABLE IF NOT EXISTS graph_runs (
    request_id TEXT PRIMARY KEY,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS graph_processed_events (
    consumer_name TEXT NOT NULL,
    event_id TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    PRIMARY KEY(consumer_name, event_id)
);
"""


@dataclass(frozen=True, slots=True)
class StoredGraphEvent:
    """An event as the outbox holds it: the canonical envelope plus its delivery state."""

    event: DomainEvent
    aggregate_id: str
    aggregate_version: int
    state: OutboxState


class SQLiteGraphStore:
    """The durable side of the graph, on the stdlib driver and nothing else."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._initialize()

    def _initialize(self) -> None:
        with connect(self.path) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA)

    # --- reads --------------------------------------------------------------

    def current_entity(self, entity_id: EntityId) -> Entity | None:
        with connect(self.path) as connection:
            row = connection.execute(
                """
                SELECT entity_json FROM graph_entity_versions
                WHERE entity_id=? ORDER BY revision DESC LIMIT 1
                """,
                (str(entity_id),),
            ).fetchone()
        return None if row is None else _entity(row)

    def entity_versions(self, entity_id: EntityId) -> tuple[Entity, ...]:
        with connect(self.path) as connection:
            rows = connection.execute(
                """
                SELECT entity_json FROM graph_entity_versions
                WHERE entity_id=? ORDER BY revision
                """,
                (str(entity_id),),
            ).fetchall()
        return tuple(_entity(row) for row in rows)

    def active_entities(self, *, owner_id: UserId, at: datetime) -> tuple[Entity, ...]:
        """Her graph as it stands, at that instant.

        Which records count as active is a domain question — an invalidated
        record was never true, an expired one was true once — so the answer
        comes from ``Entity.is_active_at`` rather than from a second copy of
        that rule written in SQL.
        """
        with connect(self.path) as connection:
            rows = connection.execute(
                """
                SELECT version.entity_json FROM graph_entity_versions AS version
                JOIN (
                    SELECT entity_id, MAX(revision) AS revision
                    FROM graph_entity_versions WHERE owner_id=? GROUP BY entity_id
                ) AS latest
                  ON version.entity_id=latest.entity_id AND version.revision=latest.revision
                ORDER BY version.entity_id
                """,
                (str(owner_id),),
            ).fetchall()
        return tuple(entity for row in rows if (entity := _entity(row)).is_active_at(at))

    def receipt_for(self, *, owner_id: UserId, idempotency_key: str) -> StoredReceipt | None:
        with connect(self.path) as connection:
            row = connection.execute(
                "SELECT * FROM graph_write_requests WHERE owner_id=? AND idempotency_key=?",
                (str(owner_id), idempotency_key),
            ).fetchone()
        return None if row is None else _stored_receipt(row)

    def receipt_for_request(self, request_id: RequestId) -> StoredReceipt | None:
        with connect(self.path) as connection:
            row = connection.execute(
                "SELECT * FROM graph_write_requests WHERE request_id=?", (str(request_id),)
            ).fetchone()
        return None if row is None else _stored_receipt(row)

    def run_record(self, request_id: RequestId) -> RuntimeRunRecord | None:
        with connect(self.path) as connection:
            row = connection.execute(
                "SELECT record_json FROM graph_runs WHERE request_id=?", (str(request_id),)
            ).fetchone()
        if row is None:
            return None
        return RuntimeRunRecord.model_validate_json(str(row["record_json"]))

    def pending_events(self) -> tuple[StoredGraphEvent, ...]:
        with connect(self.path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM graph_outbox WHERE state=?
                ORDER BY aggregate_id, aggregate_version, created_at
                """,
                (OutboxState.PENDING,),
            ).fetchall()
        return tuple(_stored_event(row) for row in rows)

    def event(self, event_id: EventId) -> StoredGraphEvent | None:
        with connect(self.path) as connection:
            row = connection.execute(
                "SELECT * FROM graph_outbox WHERE event_id=?", (str(event_id),)
            ).fetchone()
        return None if row is None else _stored_event(row)

    def count_events(self) -> int:
        with connect(self.path) as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM graph_outbox").fetchone()
        return int(row["count"])

    def count_entity_versions(self) -> int:
        with connect(self.path) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM graph_entity_versions"
            ).fetchone()
        return int(row["count"])

    # --- writes -------------------------------------------------------------

    def commit(self, batch: GraphWriteBatch) -> GraphWriteReceipt:
        """Apply every mutation in the batch with its event, or apply none of them."""
        receipt = _receipt(batch)
        stamp = now_iso()
        with self.transaction() as connection:
            claimed = connection.execute(
                """
                INSERT INTO graph_write_requests(
                    owner_id, idempotency_key, request_id, fingerprint, receipt_json, created_at
                ) VALUES(?,?,?,?,?,?)
                ON CONFLICT DO NOTHING
                """,
                (
                    str(batch.owner_id),
                    batch.idempotency_key,
                    str(batch.run.request_id),
                    batch.fingerprint,
                    receipt.model_dump_json(),
                    stamp,
                ),
            )
            if claimed.rowcount == 0:
                # Two uniqueness rules can send us here, and the database owns
                # both: the idempotency key, and the request id that names the
                # run. Either way another attempt already holds this request, so
                # this one writes nothing whatever it was carrying.
                return self._already_seen(connection, batch)
            for commit in batch.commits:
                self._write_version(connection, commit, stamp)
                self._write_event(connection, batch, commit, stamp)
            # A plain insert. A claimed request id cannot already have a run, so
            # a clash here is a contradiction and should be loud rather than
            # quietly leaving the first run record describing the second batch.
            connection.execute(
                "INSERT INTO graph_runs(request_id, record_json, created_at) VALUES(?,?,?)",
                (str(batch.run.request_id), batch.run.model_dump_json(), stamp),
            )
        return receipt

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """The unit of work. A method, so a test can subclass it and cut power before COMMIT."""
        with write_transaction(self.path) as connection:
            yield connection

    def _already_seen(
        self, connection: sqlite3.Connection, batch: GraphWriteBatch
    ) -> GraphWriteReceipt:
        by_key = connection.execute(
            "SELECT * FROM graph_write_requests WHERE owner_id=? AND idempotency_key=?",
            (str(batch.owner_id), batch.idempotency_key),
        ).fetchone()
        if by_key is not None:
            return self._answer(
                _stored_receipt(by_key),
                batch,
                clash=f"idempotency key {batch.idempotency_key}",
            )
        by_run = connection.execute(
            "SELECT * FROM graph_write_requests WHERE request_id=?",
            (str(batch.run.request_id),),
        ).fetchone()
        if by_run is None:
            raise RuntimeError("the conflicting request vanished before it could be read")
        return self._answer(_stored_receipt(by_run), batch, clash=f"request {batch.run.request_id}")

    def _answer(
        self, stored: StoredReceipt, batch: GraphWriteBatch, *, clash: str
    ) -> GraphWriteReceipt:
        """The same work is the same answer; different work under one name is not."""
        if stored.owner_id != batch.owner_id or stored.fingerprint != batch.fingerprint:
            # An owner mismatch answers the same way and says no more than that.
            # Whose the request is, and what it did, are not this caller's to
            # learn from a receipt they asked for by guessing an id.
            return GraphWriteReceipt(
                outcome=GraphWriteOutcome.CONFLICT,
                request_id=batch.run.request_id,
                correlation_id=batch.run.correlation_id,
                idempotency_key=batch.idempotency_key,
                detail=f"{clash} was already used for a different set of writes",
            )
        return stored.receipt.model_copy(update={"outcome": GraphWriteOutcome.DUPLICATE})

    def _write_version(
        self, connection: sqlite3.Connection, commit: GraphCommit, stamp: str
    ) -> None:
        """Append the successor of the exact version this write was built on.

        The guard is in the statement rather than in a read beforehand: two
        writers built on the same revision both reach here, both run this, and
        the one that arrives second inserts nothing. ``PRIMARY KEY(entity_id,
        revision)`` stands behind it as the constraint that cannot be raced at
        all.

        It names the predecessor rather than merely refusing to go backwards.
        "Nothing at or beyond revision N" would also accept revision 4 written
        onto an empty entity, leaving a history with a hole in it that no
        as-of query could read honestly.
        """
        entity = commit.entity
        expected = commit.expected_revision
        if expected is not None and entity.revision != expected + 1:
            raise InvariantViolation(
                f"a revision must be the successor of the one it was built on, "
                f"{expected} -> {entity.revision}"
            )
        if expected is None and entity.revision != 1:
            raise InvariantViolation("a first version must be revision 1")
        values = (
            str(entity.id),
            entity.revision,
            str(entity.owner_id),
            str(entity.entity_type),
            str(entity.status),
            entity.model_dump_json(),
            stamp,
        )
        if expected is None:
            cursor = connection.execute(
                """
                INSERT INTO graph_entity_versions(
                    entity_id, revision, owner_id, entity_type, status, entity_json, recorded_at
                )
                SELECT ?,?,?,?,?,?,?
                WHERE NOT EXISTS (
                    SELECT 1 FROM graph_entity_versions WHERE entity_id=?
                )
                """,
                (*values, str(entity.id)),
            )
            if cursor.rowcount == 1:
                return
            raise ConcurrentModification(f"{entity.id} already exists in the graph")
        cursor = connection.execute(
            """
            INSERT INTO graph_entity_versions(
                entity_id, revision, owner_id, entity_type, status, entity_json, recorded_at
            )
            SELECT ?,?,?,?,?,?,?
            WHERE (
                SELECT MAX(revision) FROM graph_entity_versions WHERE entity_id=?
            ) IS ?
            """,
            (*values, str(entity.id), expected),
        )
        if cursor.rowcount == 1:
            return
        raise ConcurrentModification(
            f"{entity.id} is not at revision {expected}; "
            "the write was built on a version that is no longer current"
        )

    def _write_event(
        self,
        connection: sqlite3.Connection,
        batch: GraphWriteBatch,
        commit: GraphCommit,
        stamp: str,
    ) -> None:
        """The announcement, in the same transaction as the change it announces.

        ``UNIQUE(aggregate_id, aggregate_version)`` means one entity revision
        can only ever have one event: a mutation cannot be announced twice, and
        an event cannot exist for a revision that was never written.
        """
        event = commit.event
        connection.execute(
            """
            INSERT INTO graph_outbox(
                event_id, event_type, owner_id, aggregate_id, aggregate_version,
                correlation_id, causation_id, envelope_json, state, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                str(event.event_id),
                str(event.event_type),
                str(batch.owner_id),
                str(commit.entity.id),
                commit.entity.revision,
                str(event.correlation_id),
                None if event.causation_id is None else str(event.causation_id),
                event.model_dump_json(),
                OutboxState.PENDING,
                stamp,
            ),
        )

    def mark_event_applied(self, event_id: EventId) -> None:
        with write_transaction(self.path) as connection:
            connection.execute(
                "UPDATE graph_outbox SET state=? WHERE event_id=?",
                (OutboxState.APPLIED, str(event_id)),
            )

    def apply_once(self, *, consumer_name: str, event_id: EventId) -> bool:
        """Claim an event for a consumer. The second delivery claims nothing.

        Delivery is at-least-once, so the second arrival is expected rather than
        exceptional. Only the insert into ``graph_processed_events`` is guarded:
        anything else failing here is a bug, and swallowing it would hide one.
        """
        with write_transaction(self.path) as connection:
            try:
                connection.execute(
                    "INSERT INTO graph_processed_events VALUES(?,?,?)",
                    (consumer_name, str(event_id), now_iso()),
                )
            except sqlite3.IntegrityError:
                return False
        return True


def _receipt(batch: GraphWriteBatch) -> GraphWriteReceipt:
    return GraphWriteReceipt(
        outcome=GraphWriteOutcome.APPLIED,
        request_id=batch.run.request_id,
        correlation_id=batch.run.correlation_id,
        idempotency_key=batch.idempotency_key,
        writes=tuple(
            AppliedWrite(
                entity_id=commit.entity.id,
                entity_type=commit.entity.entity_type,
                operation=commit.operation,
                revision=commit.entity.revision,
                event_id=EventId(commit.event.event_id),
                event_type=commit.event.event_type,
            )
            for commit in batch.commits
        ),
    )


def _entity(row: sqlite3.Row) -> Entity:
    return Entity.model_validate_json(str(row["entity_json"]))


def _stored_receipt(row: sqlite3.Row) -> StoredReceipt:
    return StoredReceipt(
        owner_id=UserId(str(row["owner_id"])),
        idempotency_key=str(row["idempotency_key"]),
        request_id=RequestId(str(row["request_id"])),
        fingerprint=str(row["fingerprint"]),
        receipt=GraphWriteReceipt.model_validate_json(str(row["receipt_json"])),
    )


def _stored_event(row: sqlite3.Row) -> StoredGraphEvent:
    return StoredGraphEvent(
        event=DomainEvent.model_validate_json(str(row["envelope_json"])),
        aggregate_id=str(row["aggregate_id"]),
        aggregate_version=int(row["aggregate_version"]),
        state=OutboxState(str(row["state"])),
    )
