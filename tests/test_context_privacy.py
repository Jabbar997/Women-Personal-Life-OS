from __future__ import annotations

from wlos.personal_life_graph.context import project_context
from wlos.personal_life_graph.domains import EntityType, LifeDomain
from wlos.personal_life_graph.entities import make_entity
from wlos.personal_life_graph.memory import MemoryType, make_memory
from wlos.policy.decisions import ReasonCode
from wlos.policy.sensitivity_policy import ConsumerKind, ContextConsumer, SensitivityPolicy
from wlos.shared.provenance import SourceRef
from wlos.shared.sensitivity import Sensitivity


def _seed(graph, owner_id, now):
    cycle = graph.add_entity(
        make_entity(
            entity_type=EntityType.CYCLE_STATE,
            owner_id=owner_id,
            source=SourceRef.user_declared(),
            attributes={"phase": "LUTEAL", "cycle_day": 21},
            at=now,
        )
    )
    wardrobe = graph.add_entity(
        make_entity(
            entity_type=EntityType.WARDROBE_ITEM,
            owner_id=owner_id,
            source=SourceRef.user_declared(),
            attributes={"name": "Linen dress"},
            at=now,
        )
    )
    graph.add_memory(
        make_memory(
            owner_id=owner_id,
            memory_type=MemoryType.FACT,
            domain=LifeDomain.CYCLE,
            statement="Cramps are usually worst on day 2",
            subject_entity_id=cycle.id,
            source=SourceRef.user_declared(),
            sensitivity=Sensitivity.S3,
            at=now,
        )
    )
    return cycle, wardrobe


def test_s3_context_is_not_exposed_to_a_consumer_that_does_not_require_it(graph, owner_id, now):
    """Test 10: known is not shown — need-to-know and clearance are both required."""
    cycle, wardrobe = _seed(graph, owner_id, now)

    styling_consumer = ContextConsumer(
        name="radar",
        kind=ConsumerKind.MIND,
        clearance=Sensitivity.S1,
        required_domains=frozenset({LifeDomain.WARDROBE, LifeDomain.INTERESTS}),
    )
    projection = project_context(graph, owner_id=owner_id, consumer=styling_consumer, as_of=now)

    assert wardrobe in projection.view.entities
    assert cycle not in projection.view.entities
    assert projection.view.memories == ()
    assert projection.view.withheld_count == 2

    withheld_codes = {code for decision in projection.audit for code in decision.reason_codes}
    assert ReasonCode.NOT_NEED_TO_KNOW in withheld_codes
    assert ReasonCode.SENSITIVITY_ABOVE_CLEARANCE in withheld_codes


def test_a_cleared_consumer_that_needs_the_domain_receives_it(graph, owner_id, now):
    cycle, _ = _seed(graph, owner_id, now)

    readiness_consumer = ContextConsumer(
        name="readiness",
        kind=ConsumerKind.MIND,
        clearance=Sensitivity.S3,
        required_domains=frozenset({LifeDomain.CYCLE, LifeDomain.WARDROBE}),
    )
    projection = project_context(graph, owner_id=owner_id, consumer=readiness_consumer, as_of=now)

    assert cycle in projection.view.entities
    assert len(projection.view.memories) == 1
    assert projection.view.withheld_count == 0


def test_clearance_alone_is_not_enough_without_need_to_know(graph, owner_id, now):
    cycle, _ = _seed(graph, owner_id, now)

    over_cleared = ContextConsumer(
        name="life_admin",
        kind=ConsumerKind.MIND,
        clearance=Sensitivity.S3,
        required_domains=frozenset({LifeDomain.TASKS}),
    )
    decision = SensitivityPolicy.evaluate_entity(over_cleared, cycle, at=now)

    assert decision.is_permitted is False
    assert decision.reason_codes == (ReasonCode.NOT_NEED_TO_KNOW,)


def test_external_recipients_start_with_the_lowest_clearance(graph, owner_id, now):
    _seed(graph, owner_id, now)
    external = ContextConsumer(
        name="booking-connector",
        kind=ConsumerKind.EXTERNAL_RECIPIENT,
        clearance=Sensitivity.S0,
        required_domains=frozenset({LifeDomain.CALENDAR}),
    )
    projection = project_context(graph, owner_id=owner_id, consumer=external, as_of=now)

    assert projection.view.entities == ()
    assert projection.view.memories == ()
