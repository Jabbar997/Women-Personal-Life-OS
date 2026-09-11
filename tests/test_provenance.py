"""Tests 1 and 2: a declaration and an inference are not the same kind of fact."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from wplos.core.attribution import Attribution
from wplos.core.confidence import Certainty, Confidence
from wplos.core.identifiers import UserId
from wplos.core.provenance import SourceRef, SourceType
from wplos.core.sensitivity import SensitivityLevel
from wplos.personal_life_graph.memory import MemoryRecord, MemoryType


def test_declared_preference_is_certain_and_attributed_to_the_user(
    owner: UserId, now: datetime
) -> None:
    memory = MemoryRecord.create(
        owner_id=owner,
        memory_type=MemoryType.PREFERENCE,
        statement="My favourite activity is Pilates",
        attribution=Attribution.declared(now, SensitivityLevel.S1),
        at=now,
    )

    assert memory.source.source_type is SourceType.USER_DECLARED
    assert memory.confidence.certainty is Certainty.CERTAIN
    assert memory.confidence.value is None
    assert memory.confidence.score == 1.0
    assert memory.last_confirmed_at == now
    assert memory.is_usable_at(now)


def test_inferred_preference_carries_a_probability(owner: UserId, now: datetime) -> None:
    memory = MemoryRecord.create(
        owner_id=owner,
        memory_type=MemoryType.PREFERENCE,
        statement="Prefers morning workouts",
        attribution=Attribution.inferred(now, SensitivityLevel.S1, value=0.72),
        at=now,
    )

    assert memory.source.source_type is SourceType.AI_INFERRED
    assert memory.confidence.certainty is Certainty.PROBABILISTIC
    assert memory.confidence.value == pytest.approx(0.72)
    assert memory.last_confirmed_at is None
    assert memory.attribution.is_inferred


def test_behavioural_inference_is_also_probabilistic(now: datetime) -> None:
    attribution = Attribution.inferred(
        now,
        SensitivityLevel.S2,
        value=0.4,
        source_type=SourceType.BEHAVIORAL_INFERENCE,
    )

    assert attribution.source.is_inferential
    assert not attribution.confidence.is_certain


def test_an_inferential_source_may_not_claim_certainty(now: datetime) -> None:
    with pytest.raises(ValidationError, match="inferential"):
        Attribution(
            source=SourceRef.ai_inferred(now),
            confidence=Confidence.certain(),
            sensitivity=SensitivityLevel.S1,
        )


def test_a_certain_confidence_may_not_carry_a_probability() -> None:
    with pytest.raises(ValidationError, match="must not carry a probability"):
        Confidence(certainty=Certainty.CERTAIN, value=0.9)


def test_a_probabilistic_confidence_must_carry_a_value() -> None:
    with pytest.raises(ValidationError, match="must carry a value"):
        Confidence(certainty=Certainty.PROBABILISTIC, value=None)
