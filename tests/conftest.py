from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wlos.events.bus import InMemoryEventBus
from wlos.personal_life_graph.graph import InMemoryPersonalLifeGraph
from wlos.shared.identifiers import OwnerId

NOW = datetime(2026, 9, 11, 9, 0, tzinfo=UTC)


@pytest.fixture
def owner_id() -> OwnerId:
    return OwnerId("own_test_user")


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def graph(owner_id: OwnerId) -> InMemoryPersonalLifeGraph:
    return InMemoryPersonalLifeGraph(owner_id)


@pytest.fixture
def bus() -> InMemoryEventBus:
    return InMemoryEventBus()
