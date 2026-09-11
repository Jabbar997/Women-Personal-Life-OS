from __future__ import annotations

from datetime import timedelta

import pytest

from wlos.core.errors import ProvenanceError
from wlos.personal_life_graph.domains import EntityType, LifeDomain
from wlos.personal_life_graph.entities import make_entity
from wlos.personal_life_graph.memory import MemoryType, make_memory
from wlos.personal_life_graph.relationships import RelationshipType, make_relationship
from wlos.shared.confidence import CERTAIN
from wlos.shared.provenance import SourceRef, SourceType
from wlos.shared.sensitivity import Sensitivity


def test_user_declared_preference_is_a_fact_not_a_guess(owner_id, graph, now):
    """Test 1: an explicit declaration keeps USER_DECLARED provenance and full confidence."""
    interest = graph.add_entity(
        make_entity(
            entity_type=EntityType.INTEREST,
            owner_id=owner_id,
            source=SourceRef.user_declared(note="said in chat"),
            attributes={"name": "Pilates"},
            at=now,
        )
    )
    memory = graph.add_memory(
        make_memory(
            owner_id=owner_id,
            memory_type=MemoryType.PREFERENCE,
            domain=LifeDomain.INTERESTS,
            statement="My favourite activity is Pilates",
            subject_entity_id=interest.id,
            source=SourceRef.user_declared(),
            at=now,
        )
    )

    assert memory.source.source_type is SourceType.USER_DECLARED
    assert memory.confidence == CERTAIN
    assert memory.source.is_inferential is False
    assert memory.last_confirmed_at == now
    assert graph.find_memories(memory_type=MemoryType.PREFERENCE, live_at=now) == (memory,)


def test_declared_facts_may_not_be_downgraded_to_probabilities(owner_id, now):
    with pytest.raises(ProvenanceError):
        make_memory(
            owner_id=owner_id,
            memory_type=MemoryType.PREFERENCE,
            domain=LifeDomain.INTERESTS,
            statement="My favourite activity is Pilates",
            source=SourceRef.user_declared(),
            confidence=0.7,
            at=now,
        )


def test_ai_inferred_preference_carries_confidence(owner_id, graph, now):
    """Test 2: an inference is stored as AI_INFERRED and never as certain."""
    memory = graph.add_memory(
        make_memory(
            owner_id=owner_id,
            memory_type=MemoryType.BEHAVIOR,
            domain=LifeDomain.BEHAVIORAL_HISTORY,
            statement="Usually skips morning workouts after a late night",
            source=SourceRef.ai_inferred(reference="pattern:sleep-vs-activity"),
            confidence=0.62,
            review_after=now + timedelta(days=30),
            at=now,
        )
    )

    assert memory.source.source_type is SourceType.AI_INFERRED
    assert memory.confidence == 0.62
    assert memory.last_confirmed_at is None
    assert memory.needs_review_at(now + timedelta(days=31)) is True

    with pytest.raises(ProvenanceError):
        make_memory(
            owner_id=owner_id,
            memory_type=MemoryType.BEHAVIOR,
            domain=LifeDomain.BEHAVIORAL_HISTORY,
            statement="Definitely hates mornings",
            source=SourceRef.ai_inferred(),
            confidence=1.0,
            at=now,
        )


def test_expired_relationship_keeps_its_history(owner_id, graph, now):
    """Test 3: expiry closes the validity window; nothing is deleted."""
    user = graph.add_entity(
        make_entity(
            entity_type=EntityType.IDENTITY,
            owner_id=owner_id,
            source=SourceRef.user_declared(),
            at=now,
        )
    )
    course = graph.add_entity(
        make_entity(
            entity_type=EntityType.COURSE,
            owner_id=owner_id,
            source=SourceRef.user_declared(),
            attributes={"title": "Financial modelling"},
            at=now,
        )
    )
    edge = graph.add_relationship(
        make_relationship(
            from_entity_id=user.id,
            relationship_type=RelationshipType.ENROLLED_IN,
            to_entity_id=course.id,
            source=SourceRef.user_declared(),
            at=now,
        )
    )

    ended = now + timedelta(days=60)
    expired = graph.expire_relationship(edge.id, ended)

    assert expired.valid_until == ended
    assert expired.is_active_at(now + timedelta(days=1)) is True
    assert expired.is_active_at(ended + timedelta(days=1)) is False
    assert graph.get_relationship(edge.id) is not None
    assert len(graph.relationship_history(edge.id)) == 2
    assert graph.relationship_history(edge.id)[0].valid_until is None
    assert graph.find_relationships(active_at=now) == (expired,)
    assert graph.find_relationships(active_at=ended + timedelta(days=1)) == ()


def test_sensitivity_floor_cannot_be_lowered(owner_id, now):
    cycle = make_entity(
        entity_type=EntityType.CYCLE_STATE,
        owner_id=owner_id,
        source=SourceRef.user_declared(),
        attributes={"phase": "LUTEAL", "cycle_day": 19},
        sensitivity=Sensitivity.S0,
        at=now,
    )
    assert cycle.sensitivity is Sensitivity.S3

    wardrobe = make_entity(
        entity_type=EntityType.WARDROBE_ITEM,
        owner_id=owner_id,
        source=SourceRef.user_declared(),
        attributes={"name": "Navy blazer"},
        at=now,
    )
    assert wardrobe.sensitivity is Sensitivity.S1


def test_typed_attributes_are_validated(owner_id, now):
    with pytest.raises(ValueError, match="progress"):
        make_entity(
            entity_type=EntityType.GOAL,
            owner_id=owner_id,
            source=SourceRef.user_declared(),
            attributes={"title": "Run a half marathon", "progress": 4.2},
            at=now,
        )


def test_entity_update_preserves_the_superseded_revision(owner_id, graph, now):
    goal = graph.add_entity(
        make_entity(
            entity_type=EntityType.GOAL,
            owner_id=owner_id,
            source=SourceRef.user_declared(),
            attributes={"title": "Run a half marathon", "progress": 0.1},
            at=now,
        )
    )
    later = now + timedelta(days=14)
    graph.put_entity(goal.with_attributes({"progress": 0.4}, at=later))

    history = graph.entity_history(goal.id)
    assert len(history) == 2
    assert history[0].attributes["progress"] == 0.1
    assert history[-1].attributes["progress"] == 0.4
    assert history[-1].updated_at == later
