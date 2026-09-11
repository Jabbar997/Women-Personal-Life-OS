"""The three gaps left open by the previous validation pass.

G-A money as a typed value, G-B a monetary requirement of an event, G-C an
event whose required item stops being available.
"""

from datetime import datetime, timedelta

import pytest

from scenario_helpers import declare, emit, link
from wplos.core.identifiers import UserId
from wplos.core.money import Money
from wplos.core.temporal import TemporalMarkers
from wplos.events.bus import InMemoryEventBus
from wplos.events.payloads import RequirementPayload, RequirementStatusChangedPayload
from wplos.events.types import EventType
from wplos.personal_life_graph.attributes import (
    AvailabilityState,
    AvailabilityStateAttributes,
    CalendarEventAttributes,
    PurchaseAttributes,
    RadarCategory,
    RadarItemAttributes,
    RequirementAttributes,
    RequirementKind,
    RequirementStatus,
    WardrobeCategory,
    WardrobeItemAttributes,
)
from wplos.personal_life_graph.entity import Entity
from wplos.personal_life_graph.entity_types import EntityType
from wplos.personal_life_graph.graph import PersonalLifeGraph
from wplos.personal_life_graph.relationship import RelationshipType
from wplos.shared.errors import InvariantViolation

# --- G-A: money is a typed value, never a number inside a sentence --------


def test_money_is_counted_in_minor_units_not_measured_in_floats() -> None:
    price = Money.of(35000, "SAR")

    assert price.amount_minor == 35000
    assert price.currency == "SAR"
    assert isinstance(price.amount_minor, int)
    assert (price + Money.of(5000, "SAR")).amount_minor == 40000
    assert (price - Money.of(5000, "SAR")).amount_minor == 30000
    assert price.exceeds(Money.of(10000, "SAR"))
    assert Money.zero("SAR").is_zero


def test_money_refuses_to_mix_currencies_silently() -> None:
    with pytest.raises(InvariantViolation, match="convert explicitly"):
        Money.of(100, "SAR") + Money.of(100, "USD")


def test_a_radar_find_carries_its_price_as_a_value(
    graph: PersonalLifeGraph, owner: UserId, now: datetime
) -> None:
    workshop = declare(
        graph,
        owner,
        now,
        EntityType.RADAR_ITEM,
        "UX Portfolio Workshop",
        RadarItemAttributes(
            category=RadarCategory.LEARNING,
            headline="UX Portfolio Workshop",
            price=Money.of(35000, "SAR"),
        ),
    )

    price = workshop.attributes_as(RadarItemAttributes).price
    assert price == Money.of(35000, "SAR")
    assert price is not None
    assert price.exceeds(Money.of(20000, "SAR"))
    # The same primitive goes into an action's material terms.
    assert price.as_terms() == {"amount_minor": 35000, "currency": "SAR"}


def test_a_purchase_uses_the_same_money_primitive(
    graph: PersonalLifeGraph, owner: UserId, now: datetime
) -> None:
    bag = declare(
        graph,
        owner,
        now,
        EntityType.PURCHASE,
        "Leather bag",
        PurchaseAttributes(amount=Money.of(89900, "SAR"), merchant="a boutique"),
    )

    assert bag.attributes_as(PurchaseAttributes).amount == Money.of(89900, "SAR")


# --- G-B: an event can require money, and which kind of money matters -----


def test_a_school_trip_can_require_cash_to_be_carried(
    graph: PersonalLifeGraph, owner: UserId, now: datetime
) -> None:
    wednesday = now + timedelta(days=3)
    trip = declare(
        graph,
        owner,
        now,
        EntityType.CALENDAR_EVENT,
        "School trip",
        CalendarEventAttributes(all_day=True),
        markers=TemporalMarkers(scheduled_for=wednesday),
    )
    cash = declare(
        graph,
        owner,
        now,
        EntityType.REQUIREMENT,
        "Send SAR 40 with her",
        RequirementAttributes(
            kind=RequirementKind.CARRY_CASH,
            status=RequirementStatus.UNSATISFIED,
            amount=Money.of(4000, "SAR"),
        ),
        markers=TemporalMarkers(due_at=wednesday),
    )
    link(graph, owner, now, trip, RelationshipType.REQUIRES, cash)

    attributes = cash.attributes_as(RequirementAttributes)
    assert attributes.amount == Money.of(4000, "SAR")
    assert attributes.kind.is_monetary
    assert not attributes.kind.settled_before_the_event
    assert attributes.status.blocks_readiness
    assert graph.relationships(
        owner_id=owner, from_entity_id=trip.id, relationship_type=RelationshipType.REQUIRES
    )


def test_the_four_kinds_of_money_requirement_are_distinguishable() -> None:
    carry = RequirementAttributes(kind=RequirementKind.CARRY_CASH, amount=Money.of(4000, "SAR"))
    ahead = RequirementAttributes(kind=RequirementKind.PAY_BEFORE, amount=Money.of(4000, "SAR"))
    fee = RequirementAttributes(kind=RequirementKind.ENTRY_FEE, amount=Money.of(2000, "SAR"))
    buy = RequirementAttributes(kind=RequirementKind.PURCHASE, amount=Money.of(9000, "SAR"))

    assert not carry.kind.settled_before_the_event
    assert ahead.kind.settled_before_the_event
    assert buy.kind.settled_before_the_event
    assert fee.kind.is_monetary
    assert not fee.kind.settled_before_the_event


def test_a_monetary_requirement_without_an_amount_is_refused() -> None:
    with pytest.raises(ValueError, match="requires an amount"):
        RequirementAttributes(kind=RequirementKind.CARRY_CASH)

    with pytest.raises(ValueError, match="not a monetary requirement"):
        RequirementAttributes(kind=RequirementKind.WEAR, amount=Money.of(100, "SAR"))


# --- G-C: a required item stops being available ---------------------------


def test_an_event_requirement_breaks_when_its_item_becomes_unavailable(
    graph: PersonalLifeGraph, owner: UserId, now: datetime, later: datetime
) -> None:
    saturday = now + timedelta(days=6)
    wedding = declare(
        graph,
        owner,
        now,
        EntityType.CALENDAR_EVENT,
        "Cousin's wedding",
        CalendarEventAttributes(),
        markers=TemporalMarkers(scheduled_for=saturday),
    )
    gown = declare(
        graph,
        owner,
        now,
        EntityType.WARDROBE_ITEM,
        "Navy gown",
        WardrobeItemAttributes(category=WardrobeCategory.DRESS, formality=5),
    )
    requirement = declare(
        graph,
        owner,
        now,
        EntityType.REQUIREMENT,
        "Wear the navy gown",
        RequirementAttributes(
            kind=RequirementKind.WEAR,
            status=RequirementStatus.SATISFIED,
            item_entity_id=gown.id,
        ),
    )
    link(graph, owner, now, wedding, RelationshipType.REQUIRES, requirement)
    link(graph, owner, now, requirement, RelationshipType.REQUIRES, gown)

    assert not requirement.attributes_as(RequirementAttributes).status.blocks_readiness

    # The gown goes to the laundry: the dependency breaks, explicitly.
    laundry = declare(
        graph,
        owner,
        later,
        EntityType.AVAILABILITY_STATE,
        "at the laundry",
        AvailabilityStateAttributes(state=AvailabilityState.IN_LAUNDRY),
        markers=TemporalMarkers(due_at=saturday + timedelta(days=2)),
    )
    link(graph, owner, later, gown, RelationshipType.HAS_STATUS, laundry)

    broken: Entity = requirement.revised(
        at=later,
        attributes=RequirementAttributes(
            kind=RequirementKind.WEAR,
            status=RequirementStatus.AT_RISK,
            item_entity_id=gown.id,
            note="the gown is at the laundry until after the event",
        ),
    )
    graph.revise_entity(requirement.id, broken, expected_revision=requirement.revision)

    current = graph.get_entity(requirement.id).attributes_as(RequirementAttributes)
    assert current.status is RequirementStatus.AT_RISK
    assert current.status.blocks_readiness
    # The earlier, satisfied version is still readable.
    versions = graph.entity_versions(requirement.id)
    assert versions[0].attributes_as(RequirementAttributes).status is RequirementStatus.SATISFIED
    assert laundry.markers.due_at is not None
    assert laundry.markers.due_at > saturday

    bus = InMemoryEventBus()
    created = bus.publish(
        emit(
            EventType.REQUIREMENT_CREATED,
            RequirementPayload(
                requirement_entity_id=requirement.id,
                event_entity_id=wedding.id,
                kind=RequirementKind.WEAR,
                status=RequirementStatus.SATISFIED,
            ),
            owner,
            now,
        )
    )
    changed = bus.publish(
        created.caused(
            event_type=EventType.REQUIREMENT_STATUS_CHANGED,
            payload=RequirementStatusChangedPayload(
                requirement_entity_id=requirement.id,
                event_entity_id=wedding.id,
                kind=RequirementKind.WEAR,
                status=RequirementStatus.AT_RISK,
                previous_status=RequirementStatus.SATISFIED,
                cause_entity_id=laundry.id,
            ),
            actor=created.actor,
            source=created.source,
            sensitivity=created.sensitivity,
            occurred_at=later,
        )
    )

    # The break is an event with a cause, not something to be re-derived later.
    payload = changed.payload
    assert isinstance(payload, RequirementStatusChangedPayload)
    assert payload.previous_status is RequirementStatus.SATISFIED
    assert payload.cause_entity_id == laundry.id
    assert changed.causation_id == created.event_id
