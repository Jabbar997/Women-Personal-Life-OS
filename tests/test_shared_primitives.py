from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from wlos.core.errors import TemporalError
from wlos.personal_life_graph.domains import EntityType, default_sensitivity, domain_of
from wlos.shared.clock import ensure_utc
from wlos.shared.sensitivity import Sensitivity
from wlos.shared.temporal import TemporalWindow


def test_naive_timestamps_are_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        ensure_utc(datetime(2026, 9, 11, 9, 0))


def test_temporal_window_covers_and_closes(now):
    window = TemporalWindow(valid_from=now)

    assert window.is_open is True
    assert window.covers(now) is True
    assert window.covers(now - timedelta(seconds=1)) is False

    closed = window.closed_at(now + timedelta(days=1))
    assert closed.is_open is False
    assert closed.covers(now + timedelta(hours=12)) is True
    assert closed.covers(now + timedelta(days=2)) is False


def test_temporal_window_rejects_an_impossible_range(now):
    with pytest.raises(TemporalError):
        TemporalWindow(valid_from=now, valid_until=now - timedelta(hours=1))


def test_temporal_window_overlap(now):
    morning = TemporalWindow(valid_from=now, valid_until=now + timedelta(hours=2))
    midday = TemporalWindow(
        valid_from=now + timedelta(hours=1), valid_until=now + timedelta(hours=3)
    )
    evening = TemporalWindow(
        valid_from=now + timedelta(hours=8), valid_until=now + timedelta(hours=9)
    )
    open_ended = TemporalWindow(valid_from=now + timedelta(hours=1))

    assert morning.overlaps(midday) is True
    assert morning.overlaps(evening) is False
    assert morning.overlaps(open_ended) is True
    assert evening.overlaps(open_ended) is True


def test_sensitivity_is_ordered_and_clearance_aware():
    assert Sensitivity.S1 < Sensitivity.S3
    assert Sensitivity.S3.is_readable_at(Sensitivity.S2) is False
    assert Sensitivity.S2.is_readable_at(Sensitivity.S3) is True
    assert Sensitivity.S3.label == "highly-sensitive"


def test_every_entity_type_has_a_domain_and_a_sensitivity_floor():
    for entity_type in EntityType:
        assert domain_of(entity_type) is not None
        assert isinstance(default_sensitivity(entity_type), Sensitivity)

    assert default_sensitivity(EntityType.CYCLE_STATE) is Sensitivity.S3
    assert default_sensitivity(EntityType.PREGNANCY_CONTEXT) is Sensitivity.S3
    assert default_sensitivity(EntityType.MONEY_CONTEXT) is Sensitivity.S3
    assert default_sensitivity(EntityType.CALENDAR_EVENT) is Sensitivity.S2
    assert default_sensitivity(EntityType.INTEREST) is Sensitivity.S1
