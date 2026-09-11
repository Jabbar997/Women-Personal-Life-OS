from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from wplos.policy.execution import ExecutionAuthorization, ProposedAction


class ActionStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    REAUTHORIZATION_REQUIRED = "REAUTHORIZATION_REQUIRED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            ActionStatus.SUCCEEDED,
            ActionStatus.FAILED,
            ActionStatus.NEEDS_ATTENTION,
            ActionStatus.BLOCKED,
            ActionStatus.CANCELLED,
        }


class OutboxState(StrEnum):
    PENDING = "PENDING"
    PARKED_FOR_GAP = "PARKED_FOR_GAP"
    APPLIED = "APPLIED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


@dataclass(frozen=True, slots=True)
class StoredAction:
    action_id: str
    user_id: str
    client_request_id: str
    status: ActionStatus
    spec_name: str
    projection_id: str
    proposed_action: ProposedAction
    authorization: ExecutionAuthorization | None
    correlation_id: str
    command_id: str
    external_reference: str
    reauthorization_expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    event_id: str
    event_type: str
    schema_version: int
    aggregate_id: str
    aggregate_version: int
    action_id: str
    client_request_id: str
    correlation_id: str
    command_id: str
    causation_id: str | None
    payload: dict[str, object]
    state: OutboxState
    parked_at: datetime | None


@dataclass(frozen=True, slots=True)
class ProjectionState:
    projection_id: str
    last_applied_event_id: str | None
    updated_at: datetime | None
    active_action_ids: tuple[str, ...]

    @property
    def is_stale(self) -> bool:
        return bool(self.active_action_ids)


def _dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class SQLiteIntegrationStore:
    """Small durable store used to prove transactional integration semantics."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS actions (
                    action_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    client_request_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    spec_name TEXT NOT NULL,
                    projection_id TEXT NOT NULL,
                    proposed_action_json TEXT NOT NULL,
                    authorization_json TEXT,
                    correlation_id TEXT NOT NULL,
                    command_id TEXT NOT NULL,
                    external_reference TEXT NOT NULL,
                    reauthorization_expires_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, client_request_id)
                );
                CREATE TABLE IF NOT EXISTS aggregate_heads (
                    aggregate_id TEXT PRIMARY KEY,
                    last_version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS outbox (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    aggregate_id TEXT NOT NULL,
                    aggregate_version INTEGER NOT NULL,
                    action_id TEXT NOT NULL,
                    client_request_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    command_id TEXT NOT NULL,
                    causation_id TEXT,
                    payload_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    parked_at TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(aggregate_id, aggregate_version)
                );
                CREATE TABLE IF NOT EXISTS processed_events (
                    consumer_name TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    processed_at TEXT NOT NULL,
                    PRIMARY KEY(consumer_name, event_id)
                );
                CREATE TABLE IF NOT EXISTS consumer_offsets (
                    consumer_name TEXT NOT NULL,
                    aggregate_id TEXT NOT NULL,
                    last_version INTEGER NOT NULL,
                    PRIMARY KEY(consumer_name, aggregate_id)
                );
                CREATE TABLE IF NOT EXISTS projections (
                    projection_id TEXT PRIMARY KEY,
                    last_applied_event_id TEXT,
                    updated_at TEXT
                );
                """
            )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def next_aggregate_version(self, connection: sqlite3.Connection, aggregate_id: str) -> int:
        row = connection.execute(
            "SELECT last_version FROM aggregate_heads WHERE aggregate_id=?", (aggregate_id,)
        ).fetchone()
        following = 1 if row is None else int(row["last_version"]) + 1
        connection.execute(
            """
            INSERT INTO aggregate_heads(aggregate_id, last_version) VALUES(?, ?)
            ON CONFLICT(aggregate_id) DO UPDATE SET last_version=excluded.last_version
            """,
            (aggregate_id, following),
        )
        return following

    def insert_action_with_event(
        self,
        *,
        action: ProposedAction,
        authorization: ExecutionAuthorization | None,
        client_request_id: str,
        spec_name: str,
        projection_id: str,
        correlation_id: str,
        command_id: str,
        external_reference: str,
        event_id: str,
        event_type: str,
        schema_version: int,
        payload: dict[str, object],
    ) -> tuple[StoredAction, bool]:
        now = _now_iso()
        try:
            with self.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO actions(
                        action_id,user_id,client_request_id,status,spec_name,projection_id,
                        proposed_action_json,authorization_json,correlation_id,command_id,
                        external_reference,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        str(action.action_id),
                        str(action.owner_id),
                        client_request_id,
                        ActionStatus.PENDING,
                        spec_name,
                        projection_id,
                        action.model_dump_json(),
                        None if authorization is None else authorization.model_dump_json(),
                        correlation_id,
                        command_id,
                        external_reference,
                        now,
                        now,
                    ),
                )
                version = self.next_aggregate_version(connection, str(action.action_id))
                connection.execute(
                    """
                    INSERT INTO outbox(
                        event_id,event_type,schema_version,aggregate_id,aggregate_version,
                        action_id,client_request_id,correlation_id,command_id,causation_id,
                        payload_json,state,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        event_id,
                        event_type,
                        schema_version,
                        str(action.action_id),
                        version,
                        str(action.action_id),
                        client_request_id,
                        correlation_id,
                        command_id,
                        None,
                        json.dumps(payload, sort_keys=True, separators=(",", ":")),
                        OutboxState.PENDING,
                        now,
                    ),
                )
        except sqlite3.IntegrityError:
            existing = self.get_by_client_request(str(action.owner_id), client_request_id)
            if existing is None:
                raise
            return existing, False
        stored = self.get_action(str(action.action_id))
        if stored is None:
            raise RuntimeError("action disappeared after committed insert")
        return stored, True

    def append_event(
        self,
        *,
        event_id: str,
        event_type: str,
        schema_version: int,
        action_id: str,
        client_request_id: str,
        correlation_id: str,
        command_id: str,
        causation_id: str | None,
        payload: dict[str, object],
    ) -> None:
        now = _now_iso()
        with self.transaction() as connection:
            version = self.next_aggregate_version(connection, action_id)
            connection.execute(
                """
                INSERT INTO outbox(
                    event_id,event_type,schema_version,aggregate_id,aggregate_version,
                    action_id,client_request_id,correlation_id,command_id,causation_id,
                    payload_json,state,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    event_id,
                    event_type,
                    schema_version,
                    action_id,
                    version,
                    action_id,
                    client_request_id,
                    correlation_id,
                    command_id,
                    causation_id,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    OutboxState.PENDING,
                    now,
                ),
            )

    def settle_action_with_event(
        self,
        *,
        action_id: str,
        status: ActionStatus,
        event_id: str,
        event_type: str,
        schema_version: int,
        client_request_id: str,
        correlation_id: str,
        command_id: str,
        causation_id: str | None,
        payload: dict[str, object],
    ) -> None:
        """Persist the terminal state and its result event atomically."""
        now = _now_iso()
        with self.transaction() as connection:
            connection.execute(
                "UPDATE actions SET status=?, updated_at=? WHERE action_id=?",
                (status, now, action_id),
            )
            version = self.next_aggregate_version(connection, action_id)
            connection.execute(
                """
                INSERT INTO outbox(
                    event_id,event_type,schema_version,aggregate_id,aggregate_version,
                    action_id,client_request_id,correlation_id,command_id,causation_id,
                    payload_json,state,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    event_id,
                    event_type,
                    schema_version,
                    action_id,
                    version,
                    action_id,
                    client_request_id,
                    correlation_id,
                    command_id,
                    causation_id,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    OutboxState.PENDING,
                    now,
                ),
            )

    def last_event_id(self, action_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT event_id FROM outbox WHERE action_id=?
                ORDER BY aggregate_version DESC LIMIT 1
                """,
                (action_id,),
            ).fetchone()
        return None if row is None else str(row["event_id"])

    def inject_event(self, event: OutboxEvent) -> None:
        """Test-only seam for ordering/gap validation."""
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO outbox(
                    event_id,event_type,schema_version,aggregate_id,aggregate_version,
                    action_id,client_request_id,correlation_id,command_id,causation_id,
                    payload_json,state,parked_at,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    event.event_id,
                    event.event_type,
                    event.schema_version,
                    event.aggregate_id,
                    event.aggregate_version,
                    event.action_id,
                    event.client_request_id,
                    event.correlation_id,
                    event.command_id,
                    event.causation_id,
                    json.dumps(event.payload, sort_keys=True, separators=(",", ":")),
                    event.state,
                    None if event.parked_at is None else event.parked_at.isoformat(),
                    _now_iso(),
                ),
            )

    def get_by_client_request(self, user_id: str, client_request_id: str) -> StoredAction | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM actions WHERE user_id=? AND client_request_id=?",
                (user_id, client_request_id),
            ).fetchone()
        return None if row is None else self._action_from_row(row)

    def get_action(self, action_id: str) -> StoredAction | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM actions WHERE action_id=?", (action_id,)
            ).fetchone()
        return None if row is None else self._action_from_row(row)

    def list_actions(self, status: ActionStatus) -> tuple[StoredAction, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM actions WHERE status=? ORDER BY created_at", (status,)
            ).fetchall()
        return tuple(self._action_from_row(row) for row in rows)

    def update_action_status(
        self,
        action_id: str,
        status: ActionStatus,
        *,
        reauthorization_expires_at: datetime | None = None,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE actions SET status=?, reauthorization_expires_at=?, updated_at=?
                WHERE action_id=?
                """,
                (
                    status,
                    (
                        None
                        if reauthorization_expires_at is None
                        else reauthorization_expires_at.isoformat()
                    ),
                    _now_iso(),
                    action_id,
                ),
            )

    def update_action_terms(self, action: ProposedAction) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE actions SET proposed_action_json=?, updated_at=? WHERE action_id=?",
                (action.model_dump_json(), _now_iso(), str(action.action_id)),
            )

    def update_authorization(
        self, action_id: str, authorization: ExecutionAuthorization | None
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE actions SET authorization_json=?, updated_at=? WHERE action_id=?",
                (
                    None if authorization is None else authorization.model_dump_json(),
                    _now_iso(),
                    action_id,
                ),
            )

    def pending_events(self) -> tuple[OutboxEvent, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM outbox
                WHERE state IN (?, ?)
                ORDER BY aggregate_id, aggregate_version, created_at
                """,
                (OutboxState.PENDING, OutboxState.PARKED_FOR_GAP),
            ).fetchall()
        return tuple(self._event_from_row(row) for row in rows)

    def mark_event_state(
        self, event_id: str, state: OutboxState, *, parked_at: datetime | None = None
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE outbox SET state=?, parked_at=? WHERE event_id=?",
                (state, None if parked_at is None else parked_at.isoformat(), event_id),
            )

    def last_consumer_version(self, consumer_name: str, aggregate_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT last_version FROM consumer_offsets
                WHERE consumer_name=? AND aggregate_id=?
                """,
                (consumer_name, aggregate_id),
            ).fetchone()
        return 0 if row is None else int(row["last_version"])

    def apply_once(
        self,
        *,
        consumer_name: str,
        event: OutboxEvent,
        projection_id: str | None,
    ) -> bool:
        with self.transaction() as connection:
            try:
                connection.execute(
                    "INSERT INTO processed_events VALUES(?,?,?)",
                    (consumer_name, event.event_id, _now_iso()),
                )
            except sqlite3.IntegrityError:
                return False
            connection.execute(
                """
                INSERT INTO consumer_offsets(consumer_name,aggregate_id,last_version)
                VALUES(?,?,?)
                ON CONFLICT(consumer_name,aggregate_id)
                DO UPDATE SET last_version=excluded.last_version
                """,
                (consumer_name, event.aggregate_id, event.aggregate_version),
            )
            if projection_id is not None:
                connection.execute(
                    """
                    INSERT INTO projections(projection_id,last_applied_event_id,updated_at)
                    VALUES(?,?,?)
                    ON CONFLICT(projection_id) DO UPDATE SET
                        last_applied_event_id=excluded.last_applied_event_id,
                        updated_at=excluded.updated_at
                    """,
                    (projection_id, event.event_id, _now_iso()),
                )
        return True

    def projection_state(self, projection_id: str) -> ProjectionState:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM projections WHERE projection_id=?", (projection_id,)
            ).fetchone()
            active_rows = connection.execute(
                "SELECT action_id,status FROM actions WHERE projection_id=?", (projection_id,)
            ).fetchall()
        active = tuple(
            str(item["action_id"])
            for item in active_rows
            if not ActionStatus(str(item["status"])).is_terminal
        )
        # Both columns are nullable, so a row can exist with neither set. Coercing
        # through str() first turned a NULL into the string "None" and made
        # updated_at unparseable.
        applied = None if row is None else row["last_applied_event_id"]
        return ProjectionState(
            projection_id=projection_id,
            last_applied_event_id=None if applied is None else str(applied),
            updated_at=None if row is None else _dt(row["updated_at"]),
            active_action_ids=active,
        )

    def processed_count(self, consumer_name: str, event_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count FROM processed_events
                WHERE consumer_name=? AND event_id=?
                """,
                (consumer_name, event_id),
            ).fetchone()
        return int(row["count"])

    def count_actions(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM actions").fetchone()
        return int(row["count"])

    def count_outbox(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM outbox").fetchone()
        return int(row["count"])

    def _action_from_row(self, row: sqlite3.Row) -> StoredAction:
        authorization_json = row["authorization_json"]
        return StoredAction(
            action_id=str(row["action_id"]),
            user_id=str(row["user_id"]),
            client_request_id=str(row["client_request_id"]),
            status=ActionStatus(str(row["status"])),
            spec_name=str(row["spec_name"]),
            projection_id=str(row["projection_id"]),
            proposed_action=ProposedAction.model_validate_json(str(row["proposed_action_json"])),
            authorization=(
                None
                if authorization_json is None
                else ExecutionAuthorization.model_validate_json(str(authorization_json))
            ),
            correlation_id=str(row["correlation_id"]),
            command_id=str(row["command_id"]),
            external_reference=str(row["external_reference"]),
            reauthorization_expires_at=_dt(row["reauthorization_expires_at"]),
        )

    def _event_from_row(self, row: sqlite3.Row) -> OutboxEvent:
        raw_payload = json.loads(str(row["payload_json"]))
        if not isinstance(raw_payload, dict):
            raise TypeError("event payload must be an object")
        payload: dict[str, object] = {str(key): value for key, value in raw_payload.items()}
        return OutboxEvent(
            event_id=str(row["event_id"]),
            event_type=str(row["event_type"]),
            schema_version=int(row["schema_version"]),
            aggregate_id=str(row["aggregate_id"]),
            aggregate_version=int(row["aggregate_version"]),
            action_id=str(row["action_id"]),
            client_request_id=str(row["client_request_id"]),
            correlation_id=str(row["correlation_id"]),
            command_id=str(row["command_id"]),
            causation_id=None if row["causation_id"] is None else str(row["causation_id"]),
            payload=payload,
            state=OutboxState(str(row["state"])),
            parked_at=_dt(row["parked_at"]),
        )
