from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from wplos.integration.specs import IntegrationEventType
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


ALLOWED_FROM: dict[ActionStatus, frozenset[ActionStatus]] = {
    ActionStatus.PROCESSING: frozenset(
        {ActionStatus.PENDING, ActionStatus.REAUTHORIZATION_REQUIRED}
    ),
    ActionStatus.SUCCEEDED: frozenset({ActionStatus.PROCESSING, ActionStatus.UNKNOWN}),
    ActionStatus.FAILED: frozenset({ActionStatus.PROCESSING, ActionStatus.UNKNOWN}),
    ActionStatus.UNKNOWN: frozenset({ActionStatus.PROCESSING}),
    ActionStatus.REAUTHORIZATION_REQUIRED: frozenset(
        {
            ActionStatus.PENDING,
            ActionStatus.PROCESSING,
            ActionStatus.REAUTHORIZATION_REQUIRED,
        }
    ),
    ActionStatus.BLOCKED: frozenset(
        {
            ActionStatus.PENDING,
            ActionStatus.PROCESSING,
            ActionStatus.REAUTHORIZATION_REQUIRED,
            ActionStatus.UNKNOWN,
        }
    ),
    ActionStatus.NEEDS_ATTENTION: frozenset(
        {
            ActionStatus.PROCESSING,
            ActionStatus.UNKNOWN,
            ActionStatus.REAUTHORIZATION_REQUIRED,
        }
    ),
    ActionStatus.CANCELLED: frozenset(
        {ActionStatus.PENDING, ActionStatus.REAUTHORIZATION_REQUIRED}
    ),
    ActionStatus.PENDING: frozenset({ActionStatus.UNKNOWN, ActionStatus.REAUTHORIZATION_REQUIRED}),
}
"""Which statuses a target may legally be reached from.

Every terminal status is absent from the value sets, so SUCCEEDED -> PENDING,
FAILED -> PROCESSING and CANCELLED -> PENDING cannot be expressed. The guard is
carried in the UPDATE's WHERE clause rather than checked beforehand, because a
check that happens before the write is a check two workers can both pass.
"""


class IllegalTransition(RuntimeError):
    """A status change the state machine does not permit, or lost to a racer."""


class IdempotencyConflict(RuntimeError):
    """A client request id was reused for a different command.

    Returning the first operation would execute something the caller did not
    ask for the second time, under a key that says the two are the same.
    """


def idempotency_fingerprint(action: ProposedAction, *, spec_name: str, projection_id: str) -> str:
    """A digest of the logical command behind a request.

    Everything here can change what the operation *is*: who it belongs to, what
    it acts on, what authority it needs, and the terms it carries.

    Four things are deliberately left out. ``action_id``, ``proposed_at``,
    ``correlation_id``, ``command_id`` and ``external_reference`` are generated
    per attempt, so including them would make every retry a different command —
    which is the opposite of an idempotency key. ``offer_expires_at`` is derived
    from server time at the moment the offer is built, so two retries seconds
    apart would collide on it. ``summary`` is display text describing the
    operation rather than defining it.

    ``parameters`` *is* included. Consent deliberately ignores it (ADR-006: an
    incidental retry counter must not revoke an authorization), but request
    identity is a different question from consent, and a request that differs
    at all is better refused than silently answered with an earlier one.
    """
    canonical = json.dumps(
        {
            "owner_id": str(action.owner_id),
            "spec_name": spec_name,
            "projection_id": projection_id,
            "domain": str(action.domain),
            "permission_level": str(action.permission_level),
            "reversibility": str(action.reversibility),
            "target_entity_id": action.target_entity_id,
            "material_terms": action.material_terms,
            "parameters": action.parameters,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
    idempotency_fingerprint: str = ""
    processing_deadline: datetime | None = None


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    event_id: str
    event_type: IntegrationEventType
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
    projection_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectionState:
    projection_id: str
    last_applied_event_id: str | None
    updated_at: datetime | None
    active_action_ids: tuple[str, ...]
    unapplied_event_ids: tuple[str, ...] = ()

    @property
    def is_stale(self) -> bool:
        """Fresh means nothing is still coming *and* everything has landed.

        An action reaching SUCCEEDED does not make the projection current: its
        result event is still sitting in the outbox, so a reader would be told
        the view is up to date while it still shows the old state.
        """
        return bool(self.active_action_ids) or bool(self.unapplied_event_ids)


def _dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _placeholders(values: frozenset[ActionStatus]) -> str:
    return ",".join("?" for _ in values)


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
                    idempotency_fingerprint TEXT NOT NULL,
                    processing_claimed_at TEXT,
                    processing_deadline TEXT,
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
                    projection_id TEXT,
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
        event_type: IntegrationEventType,
        schema_version: int,
        payload: dict[str, object],
    ) -> tuple[StoredAction, bool]:
        """Write the action and its first event in one transaction.

        Only a clash on ``(user_id, client_request_id)`` means "I have seen this
        request before". Every other integrity error — a reused action id, a
        reused event id, a duplicate aggregate version — is a bug, and
        swallowing it as a duplicate would hide the bug and silently drop the
        outbox event with it.
        """
        now = _now_iso()
        fingerprint = idempotency_fingerprint(
            action, spec_name=spec_name, projection_id=projection_id
        )
        duplicate = False
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO actions(
                    action_id,user_id,client_request_id,status,spec_name,projection_id,
                    proposed_action_json,authorization_json,correlation_id,command_id,
                    external_reference,idempotency_fingerprint,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(user_id, client_request_id) DO NOTHING
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
                    fingerprint,
                    now,
                    now,
                ),
            )
            if cursor.rowcount == 0:
                duplicate = True
            else:
                version = self.next_aggregate_version(connection, str(action.action_id))
                connection.execute(
                    """
                    INSERT INTO outbox(
                        event_id,event_type,schema_version,projection_id,aggregate_id,
                        aggregate_version,action_id,client_request_id,correlation_id,
                        command_id,causation_id,payload_json,state,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        event_id,
                        event_type,
                        schema_version,
                        projection_id,
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
        if duplicate:
            existing = self.get_by_client_request(str(action.owner_id), client_request_id)
            if existing is None:
                raise RuntimeError("conflicting request vanished before it could be read")
            if existing.idempotency_fingerprint != fingerprint:
                raise IdempotencyConflict(
                    f"client request {client_request_id} was already used for a different command"
                )
            return existing, False
        stored = self.get_action(str(action.action_id))
        if stored is None:
            raise RuntimeError("action disappeared after committed insert")
        return stored, True

    def settle_action_with_event(
        self,
        *,
        action_id: str,
        status: ActionStatus,
        allowed_from: frozenset[ActionStatus] | None = None,
        projection_id: str,
        event_id: str,
        event_type: IntegrationEventType,
        schema_version: int,
        client_request_id: str,
        correlation_id: str,
        command_id: str,
        causation_id: str | None,
        payload: dict[str, object],
    ) -> None:
        """Persist the terminal state and its result event atomically.

        The transition guard lives in the WHERE clause, so a settle that races
        another worker loses in the database rather than overwriting it.
        """
        sources = ALLOWED_FROM[status] if allowed_from is None else allowed_from
        now = _now_iso()
        with self.transaction() as connection:
            cursor = connection.execute(
                f"""
                UPDATE actions SET status=?, updated_at=?
                WHERE action_id=? AND status IN ({_placeholders(sources)})
                """,
                (status, now, action_id, *sorted(sources)),
            )
            if cursor.rowcount != 1:
                raise IllegalTransition(
                    f"{action_id} cannot become {status} from its current state"
                )
            version = self.next_aggregate_version(connection, action_id)
            connection.execute(
                """
                INSERT INTO outbox(
                    event_id,event_type,schema_version,projection_id,aggregate_id,
                    aggregate_version,action_id,client_request_id,correlation_id,
                    command_id,causation_id,payload_json,state,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    event_id,
                    event_type,
                    schema_version,
                    projection_id,
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

    def claim_for_processing(self, action_id: str, *, now: datetime, lease: timedelta) -> bool:
        """Take exclusive ownership of an action, or lose the race.

        A conditional UPDATE inside BEGIN IMMEDIATE is the whole mechanism: two
        workers both reach here, both attempt it, and exactly one changes a row.
        Nothing here depends on a process-level lock, so it still holds when the
        workers are separate processes or separate machines.

        The claim carries a deadline so that a worker which dies mid-flight
        leaves something recoverable rather than an action stuck in PROCESSING.
        """
        sources = ALLOWED_FROM[ActionStatus.PROCESSING]
        with self.transaction() as connection:
            cursor = connection.execute(
                f"""
                UPDATE actions
                SET status=?, processing_claimed_at=?, processing_deadline=?, updated_at=?
                WHERE action_id=? AND status IN ({_placeholders(sources)})
                """,
                (
                    ActionStatus.PROCESSING,
                    now.isoformat(),
                    (now + lease).isoformat(),
                    _now_iso(),
                    action_id,
                    *sorted(sources),
                ),
            )
            return cursor.rowcount == 1

    def stale_processing(self, now: datetime) -> tuple[StoredAction, ...]:
        """Claims whose lease has run out. Server time only; no device clock."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM actions
                WHERE status=? AND processing_deadline IS NOT NULL AND processing_deadline<=?
                ORDER BY processing_deadline
                """,
                (ActionStatus.PROCESSING, now.isoformat()),
            ).fetchall()
        return tuple(self._action_from_row(row) for row in rows)

    def _transition(
        self,
        action_id: str,
        status: ActionStatus,
        *,
        reauthorization_expires_at: datetime | None = None,
    ) -> bool:
        sources = ALLOWED_FROM[status]
        with self.transaction() as connection:
            cursor = connection.execute(
                f"""
                UPDATE actions SET status=?, reauthorization_expires_at=?, updated_at=?
                WHERE action_id=? AND status IN ({_placeholders(sources)})
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
                    *sorted(sources),
                ),
            )
            return cursor.rowcount == 1

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
                    event_id,event_type,schema_version,projection_id,aggregate_id,
                    aggregate_version,action_id,client_request_id,correlation_id,
                    command_id,causation_id,payload_json,state,parked_at,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    event.event_id,
                    event.event_type,
                    event.schema_version,
                    event.projection_id,
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
        if not self._transition(
            action_id, status, reauthorization_expires_at=reauthorization_expires_at
        ):
            raise IllegalTransition(f"{action_id} cannot become {status} from its current state")

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
                DO UPDATE SET last_version=MAX(consumer_offsets.last_version,
                                               excluded.last_version)
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
            unapplied_rows = connection.execute(
                """
                SELECT event_id FROM outbox
                WHERE projection_id=? AND state IN (?,?,?)
                ORDER BY aggregate_id, aggregate_version
                """,
                (
                    projection_id,
                    OutboxState.PENDING,
                    OutboxState.PARKED_FOR_GAP,
                    OutboxState.NEEDS_ATTENTION,
                ),
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
            unapplied_event_ids=tuple(str(item["event_id"]) for item in unapplied_rows),
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
            idempotency_fingerprint=str(row["idempotency_fingerprint"]),
            processing_deadline=_dt(row["processing_deadline"]),
        )

    def _event_from_row(self, row: sqlite3.Row) -> OutboxEvent:
        raw_payload = json.loads(str(row["payload_json"]))
        if not isinstance(raw_payload, dict):
            raise TypeError("event payload must be an object")
        payload: dict[str, object] = {str(key): value for key, value in raw_payload.items()}
        return OutboxEvent(
            event_id=str(row["event_id"]),
            event_type=IntegrationEventType(str(row["event_type"])),
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
            projection_id=(None if row["projection_id"] is None else str(row["projection_id"])),
        )
