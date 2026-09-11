from typing import Protocol

from wplos.application.result import RuntimeResult
from wplos.core.client import ClientEventId


class RuntimeLedger(Protocol):
    """Where a completed run is remembered, so a retry is not a second run.

    A port, not a store: the Orchestrator holds no state of its own, so the same
    request reaching two server instances resolves the same way.
    """

    def lookup(self, client_request_id: ClientEventId) -> RuntimeResult | None: ...

    def remember(self, client_request_id: ClientEventId, result: RuntimeResult) -> None: ...


class InMemoryRuntimeLedger:
    """Process-local implementation for tests and single-instance runs."""

    def __init__(self) -> None:
        self._results: dict[ClientEventId, RuntimeResult] = {}

    def lookup(self, client_request_id: ClientEventId) -> RuntimeResult | None:
        return self._results.get(client_request_id)

    def remember(self, client_request_id: ClientEventId, result: RuntimeResult) -> None:
        self._results.setdefault(client_request_id, result)

    def __len__(self) -> int:
        return len(self._results)
