"""ADV-15, 16, 17 — escalation, nested sensitive fields, and traversal leaks."""

from datetime import datetime

from scenario_helpers import declare, link
from wplos.agents.contracts import DecisionState
from wplos.agents.radar import RADAR_CONTRACT
from wplos.agents.registry import contract_for
from wplos.core.identifiers import UserId
from wplos.core.purpose import Purpose
from wplos.core.roles import AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.personal_life_graph.attributes import (
    EngagementLevel,
    InterestAttributes,
    Kinship,
    PersonAttributes,
    PlaceAttributes,
    PregnancyStage,
    PregnancyStateAttributes,
)
from wplos.personal_life_graph.context import ContextScope, RedactionScope, project_context
from wplos.personal_life_graph.entity_types import EntityType
from wplos.personal_life_graph.graph import PersonalLifeGraph
from wplos.personal_life_graph.memory import MemoryType
from wplos.personal_life_graph.relationship import RelationshipType
from wplos.policy.decisions import ReasonCode
from wplos.policy.permissions import PermissionLevel


def _place_with_everything(graph: PersonalLifeGraph, owner: UserId, now: datetime) -> object:
    return declare(
        graph,
        owner,
        now,
        EntityType.PLACE,
        "Home",
        PlaceAttributes(
            city="Al Ahsa",
            area="Al Hofuf",
            street_address="a specific street and building",
            latitude=25.3647,
            longitude=49.5872,
            is_home=True,
        ),
        sensitivity=SensitivityLevel.S3,
    )


# --- ADV-16 — a record whose fields are not all equally sensitive ---------


def test_a_place_carrying_an_address_cannot_be_stored_below_s3(
    graph: PersonalLifeGraph, owner: UserId, now: datetime
) -> None:
    import pytest

    with pytest.raises(ValueError, match="requires at least S3"):
        declare(
            graph,
            owner,
            now,
            EntityType.PLACE,
            "Home",
            PlaceAttributes(city="Al Ahsa", street_address="a specific street"),
            sensitivity=SensitivityLevel.S2,
        )


def test_asking_for_the_city_does_not_hand_over_the_street(
    graph: PersonalLifeGraph, owner: UserId, now: datetime
) -> None:
    """The heart of it: record-level sensitivity alone is not enough."""
    _place_with_everything(graph, owner, now)

    view = project_context(
        graph,
        owner_id=owner,
        scope=RADAR_CONTRACT.context_scope(Purpose.FIND_LOCAL_EVENT),
        at=now,
    )

    assert len(view.entities) == 1
    delivered = view.entities[0].attributes_as(PlaceAttributes)
    assert delivered.city == "Al Ahsa"
    assert delivered.area == "Al Hofuf"
    assert delivered.street_address is None
    assert delivered.latitude is None
    assert delivered.longitude is None
    assert view.entities[0].sensitivity.rank <= SensitivityLevel.S2.rank
    assert view.entities[0].redacted_fields == {"street_address", "latitude", "longitude"}


def test_the_withheld_field_names_are_recorded_but_not_their_values(
    graph: PersonalLifeGraph, owner: UserId, now: datetime
) -> None:
    _place_with_everything(graph, owner, now)

    view = project_context(
        graph,
        owner_id=owner,
        scope=RADAR_CONTRACT.context_scope(Purpose.FIND_LOCAL_EVENT),
        at=now,
    )

    dumped = view.model_dump_json()
    assert "a specific street and building" not in dumped
    assert "25.3647" not in dumped
    assert "Al Ahsa" in dumped


def test_over_redaction_is_avoided_without_under_redaction(
    graph: PersonalLifeGraph, owner: UserId, now: datetime
) -> None:
    """Neither losing the place entirely nor leaking where she lives."""
    _place_with_everything(graph, owner, now)

    cleared = project_context(
        graph,
        owner_id=owner,
        scope=ContextScope(
            consumer=AgentName.READINESS,
            purpose=Purpose.GET_READY,
            required_entity_types=frozenset({EntityType.PLACE}),
            max_sensitivity=SensitivityLevel.S3,
        ),
        at=now,
    )

    full = cleared.entities[0].attributes_as(PlaceAttributes)
    assert full.street_address is not None
    assert full.latitude is not None
    assert cleared.entities[0].redacted_fields == frozenset()


# --- ADV-17 — what a permitted edge might reveal --------------------------


def test_radar_never_reaches_a_sensitive_state_through_a_permitted_edge(
    graph: PersonalLifeGraph, owner: UserId, self_person, now: datetime
) -> None:
    running = declare(
        graph,
        owner,
        now,
        EntityType.INTEREST,
        "Running",
        InterestAttributes(engagement=EngagementLevel.ACTIVE),
    )
    pregnancy = declare(
        graph,
        owner,
        now,
        EntityType.PREGNANCY_STATE,
        "Pregnancy",
        PregnancyStateAttributes(stage=PregnancyStage.SECOND_TRIMESTER, week=18),
    )
    link(graph, owner, now, self_person, RelationshipType.LIKES, running)

    view = project_context(
        graph,
        owner_id=owner,
        scope=RADAR_CONTRACT.context_scope(Purpose.FIND_LOCAL_EVENT),
        at=now,
    )

    delivered_ids = {entity.id for entity in view.entities}
    assert running.id in delivered_ids
    assert pregnancy.id not in delivered_ids
    # No edge can point at something the mind was not given.
    for relationship in view.relationships:
        assert relationship.from_entity_id in delivered_ids
        assert relationship.to_entity_id in delivered_ids
    assert all(
        entity.sensitivity.rank <= RADAR_CONTRACT.max_sensitivity.rank for entity in view.entities
    )


def test_an_edge_is_only_delivered_when_both_ends_were_needed(
    graph: PersonalLifeGraph, owner: UserId, self_person, now: datetime
) -> None:
    sister = declare(
        graph,
        owner,
        now,
        EntityType.PERSON,
        "Sister",
        PersonAttributes(display_name="Sister", kinship=Kinship.SIBLING),
    )
    link(
        graph,
        owner,
        now,
        self_person,
        RelationshipType.RELATED_TO,
        sister,
        sensitivity=SensitivityLevel.S2,
    )

    radar_view = project_context(
        graph,
        owner_id=owner,
        scope=RADAR_CONTRACT.context_scope(Purpose.FIND_LOCAL_EVENT),
        at=now,
    )

    # Radar reads PERSON, so the edge is within its remit; nothing S3 rides along.
    for relationship in radar_view.relationships:
        assert relationship.sensitivity.rank <= RADAR_CONTRACT.max_sensitivity.rank


def test_an_edge_whose_endpoint_types_are_not_required_is_withheld(
    graph: PersonalLifeGraph, owner: UserId, self_person, now: datetime
) -> None:
    sister = declare(
        graph,
        owner,
        now,
        EntityType.PERSON,
        "Sister",
        PersonAttributes(display_name="Sister", kinship=Kinship.SIBLING),
    )
    link(
        graph,
        owner,
        now,
        self_person,
        RelationshipType.RELATED_TO,
        sister,
        sensitivity=SensitivityLevel.S3,
    )

    view = project_context(
        graph,
        owner_id=owner,
        scope=ContextScope(
            consumer=AgentName.LIFE_ADMIN,
            purpose=Purpose.CLOSE_OPEN_LOOPS,
            required_entity_types=frozenset({EntityType.PERSON}),
            max_sensitivity=SensitivityLevel.S3,
        ),
        at=now,
    )

    assert len(view.entities) == 2
    assert all(
        relationship.sensitivity.rank <= SensitivityLevel.S3.rank
        for relationship in view.relationships
    )


# --- ADV-15 — an agent reaching past its contract ------------------------


def test_radar_cannot_write_anywhere_near_health(owner: UserId) -> None:
    radar = contract_for(AgentName.RADAR)

    for forbidden in (
        EntityType.HEALTH_CONDITION,
        EntityType.CYCLE_STATE,
        EntityType.PREGNANCY_STATE,
        EntityType.BODY_SIGNAL,
    ):
        assert not radar.may_write(forbidden)
        assert forbidden not in radar.reads
    assert radar.writes == frozenset({EntityType.RADAR_ITEM})


def test_radar_cannot_authorize_or_execute_anything(owner: UserId) -> None:
    radar = contract_for(AgentName.RADAR)

    assert radar.max_permission_level is PermissionLevel.A0
    assert not radar.max_permission_level.is_executable
    assert not radar.may_decide(DecisionState.ACT)
    assert not radar.holds_veto


def test_radar_cannot_read_cycle_history_even_at_its_own_ceiling(
    graph: PersonalLifeGraph, owner: UserId, cycle_state, now: datetime
) -> None:
    greedy = ContextScope(
        consumer=AgentName.RADAR,
        purpose=Purpose.FIND_LOCAL_EVENT,
        required_entity_types=frozenset({EntityType.CYCLE_STATE}),
        max_sensitivity=RADAR_CONTRACT.max_sensitivity,
    )

    view = project_context(graph, owner_id=owner, scope=greedy, at=now)

    # Even asking for it directly does not get it past the ceiling.
    assert view.entities == ()
    assert view.was_redacted
    assert any(
        redaction.reason_code is ReasonCode.CONSUMER_CEILING_EXCEEDED
        for redaction in view.redactions
    )
    assert all(redaction.scope is RedactionScope.ENTITY for redaction in view.redactions)


def test_a_minds_scope_is_exactly_its_contract_and_never_wider() -> None:
    """A scope is derived, so a mind cannot widen its own reach by asking."""
    for agent in AgentName:
        contract = contract_for(agent)
        scope = contract.context_scope(Purpose.PLAN_DAY)

        assert scope.consumer is agent
        assert scope.max_sensitivity is contract.max_sensitivity
        assert scope.required_entity_types == contract.reads
        assert scope.required_memory_types == contract.reads_memory
        assert all(scope.requires(entity_type) for entity_type in contract.writes)
        assert MemoryType.BEHAVIOR not in scope.required_memory_types or (
            MemoryType.BEHAVIOR in contract.reads_memory
        )
