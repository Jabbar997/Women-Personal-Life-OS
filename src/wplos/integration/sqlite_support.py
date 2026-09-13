"""The one SQLite mechanism this system uses.

Both durable stores — the action kernel and the Personal Life Graph — sit on
the same connection settings and the same transaction shape. Two subsystems
each inventing their own would be two reliability stories to reason about, and
only one of them would get reviewed twice.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime


def connect(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=10.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


@contextmanager
def transaction(path: str) -> Iterator[sqlite3.Connection]:
    """A write transaction that commits on a clean exit and rolls back on any exit that is not.

    ``BEGIN IMMEDIATE`` takes the write lock up front, so two workers reaching
    the same conditional UPDATE serialise in the database rather than in a
    process-level lock that stops working the moment there are two processes.
    """
    connection = connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_dt(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)
