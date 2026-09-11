"""Life simulation: ten real scenarios run against the foundation.

Each test starts from something the user actually said and ends at the state,
the events and the agent routing the architecture must produce.
"""

from datetime import UTC, datetime, timedelta

import pytest

from scenario_helpers import declare, emit, link
from wplos.agents.contracts import DecisionState, Intent, PriorityClass
from wplos.agents.life_admin import LIFE_ADMIN_CONTRACT
from wplos.agents.navigator import NAVIGATOR_CONTRACT
from wplos.agents.radar import RADAR_CONTRACT, RadarClassification
from wplos.agents.readiness import READINESS_CONTRACT
from wplos.agents.registry import contract_for
from wplos.core.attribution import Attribution
from wplos.core.confidence import Confidence
from wplos.core.identifiers import EntityId, UserId
from wplos.core.provenance import SourceType
from wplos.core.records import RecordStatus
from wplos.core.roles import AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.core.temporal import TemporalMarkers
from wplos.events.bus import InMemoryEventBus
from wplos.events.payloads import (
    CalendarConflictPayload,
    CalendarEventPayload,
    CaptureKind,
    CaptureParsedPayload,
    CapturePayload,
    CaptureRoutedPayload,
    DeadlinePayload,
    EntityRefPayload,
    OpenLoopPayload,
    PurchaseRecordedPayload,
    RadarItemPayload,
    RecommendationPayload,
    ReturnWindowClosingPayload,
    WardrobeItemStatusPayload,
)
from wplos.events.types import EventType
from wplos.orchestration.conflict import DEFAULT_CONFLICT_POLICY, Claim, ClaimNature
from wplos.orchestration.contract import ORCHESTRATOR_CONTRACT
from wplos.personal_life_graph.attributes import (
    AvailabilityState,
    AvailabilityStateAttributes,
    BodySignalAttributes,
    BodySignalKind,
    CalendarEventAttributes,
    CommitmentAttributes,
    CommitmentKind,
    EngagementLevel,
    GoalAttributes,
    GoalHorizon,
    IngredientAttributes,
    IngredientFlag,
    InterestAttributes,
    Kinship,
    LocationPrecision,
    OpenLoopState,
    PersonAttributes,
    PlaceAttributes,
    ProductAttributes,
    ProductCategory,
    PurchaseAttributes,
    RadarCategory,
    RadarItemAttributes,
    TaskAttributes,
    WardrobeCategory,
    WardrobeItemAttributes,
)
from wplos.personal_life_graph.context import project_context
from wplos.personal_life_graph.entity_types import EntityType, LifeDomain
from wplos.personal_life_graph.graph import PersonalLifeGraph
from wplos.personal_life_graph.memory import MemoryRecord, MemoryType
from wplos.personal_life_graph.relationship import RelationshipType
from wplos.policy.guardian import (
    GuardianAssessment,
    GuardianCheck,
    GuardianFinding,
    GuardianVerdict,
)

SAT_2000 = datetime(2026, 3, 7, 17, 0, tzinfo=UTC)


# --- Scenario 01 — event preparation -------------------------------------


def test_scenario_01_wedding_with_the_dress_at_the_laundry(
    graph: PersonalLifeGraph, owner: UserId, self_person, now: datetime
) -> None:
    cousin = declare(
        graph,
        owner,
        now,
        EntityType.PERSON,
        "Cousin",
        PersonAttributes(display_name="Cousin", kinship=Kinship.EXTENDED_FAMILY),
    )
    wedding = declare(
        graph,
        owner,
        now,
        EntityType.CALENDAR_EVENT,
        "Cousin's wedding",
        CalendarEventAttributes(ends_at=SAT_2000 + timedelta(hours=4)),
        markers=TemporalMarkers(scheduled_for=SAT_2000),
    )
    dress = declare(
        graph,
        owner,
        now,
        EntityType.WARDROBE_ITEM,
        "Navy gown",
        WardrobeItemAttributes(category=WardrobeCategory.DRESS, formality=5),
    )
    at_laundry = declare(
        graph,
        owner,
        now,
        EntityType.AVAILABILITY_STATE,
        "at the laundry",
        AvailabilityStateAttributes(state=AvailabilityState.IN_LAUNDRY),
        markers=TemporalMarkers(due_at=SAT_2000 - timedelta(days=1)),
    )

    link(graph, owner, now, self_person, RelationshipType.RELATED_TO, cousin)
    link(graph, owner, now, self_person, RelationshipType.ATTENDS, wedding)
    link(graph, owner, now, wedding, RelationshipType.REQUIRES, dress)
    link(graph, owner, now, dress, RelationshipType.HAS_STATUS, at_laundry)

    # The family tie, the event, its start, and the outfit dependency all stand.
    assert wedding.markers.scheduled_for == SAT_2000
    assert graph.relationships(
        owner_id=owner, from_entity_id=wedding.id, relationship_type=RelationshipType.REQUIRES
    )
    assert at_laundry.attributes_as(AvailabilityStateAttributes).state is (
        AvailabilityState.IN_LAUNDRY
    )
    # The blocker is derivable from the graph, not from prose.
    assert at_laundry.markers.due_at is not None
    assert at_laundry.markers.due_at < SAT_2000

    # Life Admin owns the collection loop; Readiness owns the outfit.
    collect = declare(
        graph,
        owner,
        now,
        EntityType.TASK,
        "Collect the gown",
        TaskAttributes(state=OpenLoopState.SCHEDULED, blocked_by_entity_id=at_laundry.id),
        markers=TemporalMarkers(due_at=SAT_2000 - timedelta(days=1)),
    )
    assert LIFE_ADMIN_CONTRACT.may_write(EntityType.TASK)
    assert READINESS_CONTRACT.may_write(EntityType.TASK)
    assert EntityType.WARDROBE_ITEM in READINESS_CONTRACT.reads
    assert EntityType.WARDROBE_ITEM not in LIFE_ADMIN_CONTRACT.writes
    assert collect.attributes_as(TaskAttributes).blocked_by_entity_id == at_laundry.id

    bus = InMemoryEventBus()
    bus.publish(
        emit(
            EventType.EVENT_CREATED,
            CalendarEventPayload(event_entity_id=wedding.id, starts_at=SAT_2000),
            owner,
            now,
            sensitivity=SensitivityLevel.S2,
        )
    )
    bus.publish(
        emit(
            EventType.WARDROBE_ITEM_STATUS_CHANGED,
            WardrobeItemStatusPayload(
                item_entity_id=dress.id,
                previous_state=AvailabilityState.AVAILABLE,
                current_state=AvailabilityState.IN_LAUNDRY,
            ),
            owner,
            now,
            agent=AgentName.LIFE_ADMIN,
        )
    )
    bus.publish(
        emit(
            EventType.TASK_CREATED,
            OpenLoopPayload(
                entity_id=collect.id,
                entity_type=EntityType.TASK,
                state=OpenLoopState.SCHEDULED,
                due_at=SAT_2000 - timedelta(days=1),
            ),
            owner,
            now,
            agent=AgentName.LIFE_ADMIN,
        )
    )
    assert len(bus.log) == 3


# --- Scenario 02 — school message capture --------------------------------


def test_scenario_02_school_trip_screenshot(
    graph: PersonalLifeGraph, owner: UserId, self_person, now: datetime
) -> None:
    wednesday = datetime(2026, 3, 4, 5, 0, tzinfo=UTC)
    daughter = declare(
        graph,
        owner,
        now,
        EntityType.PERSON,
        "Daughter",
        PersonAttributes(display_name="Daughter", kinship=Kinship.CHILD, household_member=True),
    )
    trip = declare(
        graph,
        owner,
        now,
        EntityType.CALENDAR_EVENT,
        "School trip",
        CalendarEventAttributes(all_day=True),
        markers=TemporalMarkers(scheduled_for=wednesday),
    )
    sportswear = declare(
        graph,
        owner,
        now,
        EntityType.WARDROBE_ITEM,
        "PE kit",
        WardrobeItemAttributes(category=WardrobeCategory.ACTIVEWEAR),
    )
    water = declare(
        graph,
        owner,
        now,
        EntityType.PRODUCT,
        "Water bottle",
        ProductAttributes(category=ProductCategory.PERSONAL_ESSENTIAL),
    )
    money = declare(
        graph,
        owner,
        now,
        EntityType.TASK,
        "Send SAR 40 with her",
        TaskAttributes(state=OpenLoopState.CLARIFIED),
        markers=TemporalMarkers(due_at=wednesday),
    )
    duty = declare(
        graph,
        owner,
        now,
        EntityType.COMMITMENT,
        "Get her ready for the trip",
        CommitmentAttributes(
            kind=CommitmentKind.PROMISE_MADE,
            state=OpenLoopState.SCHEDULED,
            counterparty_entity_id=daughter.id,
        ),
        markers=TemporalMarkers(due_at=wednesday),
    )

    link(graph, owner, now, daughter, RelationshipType.ATTENDS, trip)
    link(graph, owner, now, trip, RelationshipType.REQUIRES, sportswear)
    link(graph, owner, now, trip, RelationshipType.REQUIRES, water)
    link(graph, owner, now, money, RelationshipType.PREPARES_FOR, trip)
    link(graph, owner, now, duty, RelationshipType.PREPARES_FOR, trip)

    required = graph.relationships(
        owner_id=owner, from_entity_id=trip.id, relationship_type=RelationshipType.REQUIRES
    )
    assert len(required) == 2
    assert money.markers.due_at == wednesday
    assert duty.attributes_as(CommitmentAttributes).counterparty_entity_id == daughter.id

    bus = InMemoryEventBus()
    received = bus.publish(
        emit(
            EventType.CAPTURE_RECEIVED,
            CapturePayload(capture_id="cap_school", kind=CaptureKind.SCREENSHOT),
            owner,
            now,
            source_type=SourceType.USER_ACTION,
        )
    )
    parsed = bus.publish(
        received.caused(
            event_type=EventType.CAPTURE_PARSED,
            payload=CaptureParsedPayload(capture_id="cap_school", extracted_count=5),
            actor=received.actor,
            source=received.source,
            sensitivity=SensitivityLevel.S2,
            occurred_at=now,
        )
    )
    routed = bus.publish(
        parsed.caused(
            event_type=EventType.CAPTURE_ROUTED,
            payload=CaptureRoutedPayload(
                capture_id="cap_school", routed_to=(AgentName.LIFE_ADMIN, AgentName.READINESS)
            ),
            actor=parsed.actor,
            source=parsed.source,
            sensitivity=SensitivityLevel.S2,
            occurred_at=now,
        )
    )
    created = bus.publish(
        routed.caused(
            event_type=EventType.COMMITMENT_CAPTURED,
            payload=OpenLoopPayload(
                entity_id=duty.id,
                entity_type=EntityType.COMMITMENT,
                state=OpenLoopState.SCHEDULED,
                due_at=wednesday,
            ),
            actor=routed.actor,
            source=routed.source,
            sensitivity=SensitivityLevel.S2,
            occurred_at=now,
        )
    )

    # One screenshot, one traceable chain from capture to commitment.
    chain = bus.causation_chain(created.event_id)
    assert [event.event_type for event in chain] == [
        EventType.CAPTURE_RECEIVED,
        EventType.CAPTURE_PARSED,
        EventType.CAPTURE_ROUTED,
        EventType.COMMITMENT_CAPTURED,
    ]
    assert len({event.correlation_id for event in chain}) == 1


# --- Scenario 03 — purchase and return window ----------------------------


def test_scenario_03_return_window_keeps_the_delivery_date(
    graph: PersonalLifeGraph, owner: UserId, now: datetime
) -> None:
    delivered = now
    window_closes = delivered + timedelta(days=14)
    day_ten = delivered + timedelta(days=10)

    purchase = declare(
        graph,
        owner,
        delivered,
        EntityType.PURCHASE,
        "Leather bag",
        PurchaseAttributes(returnable_until=window_closes, merchant="a boutique"),
        markers=TemporalMarkers(occurred_at=delivered),
    )
    loop = declare(
        graph,
        owner,
        delivered,
        EntityType.COMMITMENT,
        "Decide whether to keep the bag",
        CommitmentAttributes(kind=CommitmentKind.RETURN, state=OpenLoopState.WAITING),
        markers=TemporalMarkers(due_at=window_closes),
    )

    # Ten days on, still undecided: the state moves, the delivery date does not.
    still_waiting = loop.revised(
        at=day_ten,
        attributes=CommitmentAttributes(kind=CommitmentKind.RETURN, state=OpenLoopState.DUE),
    )
    graph.revise_entity(loop.id, still_waiting)

    versions = graph.entity_versions(loop.id)
    assert len(versions) == 2
    assert versions[0].attributes_as(CommitmentAttributes).state is OpenLoopState.WAITING
    assert versions[1].attributes_as(CommitmentAttributes).state is OpenLoopState.DUE
    assert versions[1].markers.due_at == window_closes
    assert graph.get_entity(purchase.id).markers.occurred_at == delivered
    assert purchase.attributes_as(PurchaseAttributes).amount is None

    bus = InMemoryEventBus()
    recorded = bus.publish(
        emit(
            EventType.PURCHASE_RECORDED,
            PurchaseRecordedPayload(purchase_entity_id=purchase.id, returnable_until=window_closes),
            owner,
            delivered,
            agent=AgentName.LIFE_ADMIN,
            sensitivity=SensitivityLevel.S3,
        )
    )
    bus.publish(
        recorded.caused(
            event_type=EventType.DEADLINE_CREATED,
            payload=DeadlinePayload(deadline_entity_id=loop.id, due_at=window_closes, hard=True),
            actor=recorded.actor,
            source=recorded.source,
            sensitivity=SensitivityLevel.S1,
            occurred_at=delivered,
        )
    )
    closing = bus.publish(
        recorded.caused(
            event_type=EventType.RETURN_WINDOW_CLOSING,
            payload=ReturnWindowClosingPayload(
                purchase_entity_id=purchase.id,
                returnable_until=window_closes,
                days_remaining=4,
            ),
            actor=recorded.actor,
            source=recorded.source,
            sensitivity=SensitivityLevel.S1,
            occurred_at=day_ten,
        )
    )

    # The remaining days are arithmetic on stored instants, not a model's guess.
    assert (window_closes - day_ten).days == 4
    assert closing.causation_id == recorded.event_id
    assert EntityType.PURCHASE in LIFE_ADMIN_CONTRACT.reads


# --- Scenario 04 — career goal meets a Radar find -------------------------


def test_scenario_04_radar_offers_navigator_judges(
    graph: PersonalLifeGraph, owner: UserId, self_person, now: datetime
) -> None:
    thursday = datetime(2026, 3, 5, 16, 0, tzinfo=UTC)
    goal = declare(
        graph,
        owner,
        now,
        EntityType.GOAL,
        "Move into UX within six months",
        GoalAttributes(
            horizon=GoalHorizon.QUARTER,
            domain=LifeDomain.WORK,
            measurable_outcome="a UX role offer",
        ),
    )
    workshop = graph.put_entity(
        declare(
            graph,
            owner,
            now,
            EntityType.RADAR_ITEM,
            "UX Portfolio Workshop",
            RadarItemAttributes(
                category=RadarCategory.LEARNING, headline="UX Portfolio Workshop, SAR 350"
            ),
            markers=TemporalMarkers(scheduled_for=thursday),
        ).model_copy(
            update={
                "attribution": Attribution.inferred(
                    now, SensitivityLevel.S0, value=0.6, source_type=SourceType.RADAR
                )
            }
        )
    )
    link(graph, owner, now, self_person, RelationshipType.HAS_GOAL, goal)
    link(graph, owner, now, goal, RelationshipType.SUPPORTED_BY, workshop)

    # Radar's find is a claim, not a fact, and it says so.
    assert workshop.source.source_type is SourceType.RADAR
    assert workshop.source.is_inferential
    assert not workshop.confidence.is_certain
    assert workshop.attributes_as(RadarItemAttributes).claimed_by_source is True
    # The user's goal is hers, stated, and certain.
    assert goal.source.source_type is SourceType.USER_DECLARED
    assert goal.confidence.is_certain

    # Radar may surface and recommend; only the Operator may act.
    assert RADAR_CONTRACT.may_decide(DecisionState.RECOMMEND)
    assert not RADAR_CONTRACT.may_decide(DecisionState.ACT)
    assert RadarClassification.ACT_NOW in RadarClassification
    # Radar does not own goals, Navigator does not invent opportunities.
    assert EntityType.GOAL not in RADAR_CONTRACT.writes
    assert EntityType.RADAR_ITEM not in NAVIGATOR_CONTRACT.writes
    assert EntityType.RADAR_ITEM in NAVIGATOR_CONTRACT.reads
    assert ORCHESTRATOR_CONTRACT.agents_for(Intent.DISCOVER)[:2] == (
        AgentName.RADAR,
        AgentName.NAVIGATOR,
    )


# --- Scenario 05 — conflicting commitments -------------------------------


def test_scenario_05_two_commitments_collide_on_thursday(
    graph: PersonalLifeGraph, owner: UserId, now: datetime
) -> None:
    clinic_at = datetime(2026, 3, 5, 15, 30, tzinfo=UTC)
    talk_at = datetime(2026, 3, 5, 16, 0, tzinfo=UTC)

    clinic = declare(
        graph,
        owner,
        now,
        EntityType.CALENDAR_EVENT,
        "Doctor's appointment",
        CalendarEventAttributes(ends_at=clinic_at + timedelta(minutes=45)),
        markers=TemporalMarkers(scheduled_for=clinic_at),
        sensitivity=SensitivityLevel.S3,
    )
    talk = declare(
        graph,
        owner,
        now,
        EntityType.CALENDAR_EVENT,
        "Professional evening",
        CalendarEventAttributes(ends_at=talk_at + timedelta(hours=2)),
        markers=TemporalMarkers(scheduled_for=talk_at),
    )
    clash = link(
        graph,
        owner,
        now,
        clinic,
        RelationshipType.CONFLICTS_WITH,
        talk,
        sensitivity=SensitivityLevel.S2,
    )

    # The clash is durable state, not just a transient event.
    assert clash.relationship_type is RelationshipType.CONFLICTS_WITH
    assert graph.relationships(
        owner_id=owner,
        from_entity_id=clinic.id,
        relationship_type=RelationshipType.CONFLICTS_WITH,
        at=now,
    )
    overlap = (clinic_at + timedelta(minutes=45)) - talk_at
    assert overlap == timedelta(minutes=15)

    bus = InMemoryEventBus()
    bus.publish(
        emit(
            EventType.CALENDAR_CONFLICT_DETECTED,
            CalendarConflictPayload(
                first_event_entity_id=clinic.id,
                second_event_entity_id=talk.id,
                overlap_minutes=15,
            ),
            owner,
            now,
            agent=AgentName.LIFE_ADMIN,
            sensitivity=SensitivityLevel.S3,
        )
    )
    assert bus.events_of(EventType.CALENDAR_CONFLICT_DETECTED)

    # A Radar find cannot displace either commitment.
    health_claim = Claim(
        claim_id="claim_clinic",
        agent=AgentName.LIFE_ADMIN,
        subject="thursday-evening",
        nature=ClaimNature.COMMITMENT,
        decision_state=DecisionState.SURFACE,
        priority=PriorityClass.P1,
        statement="Doctor's appointment at 18:30",
        confidence=Confidence.certain(),
    )
    radar_claim = Claim(
        claim_id="claim_radar",
        agent=AgentName.RADAR,
        subject="thursday-evening",
        nature=ClaimNature.OPPORTUNITY,
        decision_state=DecisionState.RECOMMEND,
        priority=PriorityClass.P2,
        statement="A networking evening at 19:00",
        confidence=Confidence.probabilistic(0.8),
    )
    resolution = DEFAULT_CONFLICT_POLICY.resolve((health_claim, radar_claim))
    winner = resolution.winner_for("thursday-evening")
    assert winner is not None and winner.agent is AgentName.LIFE_ADMIN
    assert resolution.was_suppressed("claim_radar")


# --- Scenario 06 — irritated skin and a risky product --------------------


def test_scenario_06_guardian_blocks_the_routine_suggestion(
    graph: PersonalLifeGraph, owner: UserId, self_person, now: datetime
) -> None:
    signal = declare(
        graph,
        owner,
        now,
        EntityType.BODY_SIGNAL,
        "Skin feels irritated",
        BodySignalAttributes(signal=BodySignalKind.SKIN, scale_value=7.0),
        markers=TemporalMarkers(occurred_at=now),
    )
    serum = declare(
        graph,
        owner,
        now,
        EntityType.PRODUCT,
        "Night serum",
        ProductAttributes(category=ProductCategory.SKINCARE),
    )
    acid = declare(
        graph,
        owner,
        now,
        EntityType.INGREDIENT,
        "An exfoliating acid",
        IngredientAttributes(flags=frozenset({IngredientFlag.KNOWN_IRRITANT})),
    )
    link(graph, owner, now, serum, RelationshipType.CONTAINS, acid)
    link(graph, owner, now, self_person, RelationshipType.USES, serum)

    assert signal.sensitivity is SensitivityLevel.S3
    assert signal.source.source_type is SourceType.USER_DECLARED
    assert IngredientFlag.KNOWN_IRRITANT in acid.attributes_as(IngredientAttributes).flags

    from wplos.core.identifiers import ActionId

    action_id = ActionId("act_routine_step")
    assessment = GuardianAssessment.from_findings(
        (
            GuardianFinding(
                check=GuardianCheck.HEALTH_BOUNDARY,
                verdict=GuardianVerdict.BLOCK,
                explanation="the product's active conflicts with a reported skin state",
            ),
            GuardianFinding(
                check=GuardianCheck.SAFETY,
                verdict=GuardianVerdict.CAUTION,
                explanation="recent irritation reported by the user",
            ),
        ),
        subject_action_id=action_id,
    )

    # The strictest finding decides; Guardian does not average its warnings.
    assert assessment.verdict is GuardianVerdict.BLOCK
    assert assessment.is_veto
    # Guardian reads body context but writes nothing, and Readiness must adjust.
    assert EntityType.BODY_SIGNAL in contract_for(AgentName.GUARDIAN).reads
    assert contract_for(AgentName.GUARDIAN).writes == frozenset()
    assert EntityType.PRODUCT in READINESS_CONTRACT.reads
    assert EventType.READINESS_PLAN_UPDATED in READINESS_CONTRACT.events_produced


# --- Scenario 07 — behavioural learning ----------------------------------


def test_scenario_07_ignored_once_is_not_a_preference(
    graph: PersonalLifeGraph, owner: UserId, now: datetime
) -> None:
    bus = InMemoryEventBus()
    surfaced: list[str] = []

    for day in range(8):
        offered = bus.publish(
            emit(
                EventType.RECOMMENDATION_SURFACED,
                RecommendationPayload(
                    recommendation_id=f"rec_morning_{day}",
                    offered_by=AgentName.READINESS,
                    title="A morning workout",
                ),
                owner,
                now + timedelta(days=day),
                agent=AgentName.READINESS,
            )
        )
        surfaced.append(offered.event_id)
        if day < 7:
            bus.publish(
                offered.caused(
                    event_type=EventType.RECOMMENDATION_IGNORED,
                    payload=RecommendationPayload(
                        recommendation_id=f"rec_morning_{day}",
                        offered_by=AgentName.READINESS,
                        title="A morning workout",
                    ),
                    actor=offered.actor,
                    source=offered.source,
                    sensitivity=SensitivityLevel.S1,
                    occurred_at=now + timedelta(days=day, hours=12),
                )
            )

    # The raw signal is in the log and every outcome traces to its offer.
    assert len(bus.events_of(EventType.RECOMMENDATION_SURFACED)) == 8
    assert len(bus.events_of(EventType.RECOMMENDATION_IGNORED)) == 7
    first_ignored = bus.events_of(EventType.RECOMMENDATION_IGNORED)[0]
    assert first_ignored.causation_id == surfaced[0]

    # One skip is an observation. A pattern is an inference, and says so.
    single_skip = MemoryRecord.create(
        owner_id=owner,
        memory_type=MemoryType.BEHAVIOR,
        statement="Skipped the morning workout on day one",
        attribution=Attribution.observed(
            now, SensitivityLevel.S1, source_type=SourceType.USER_ACTION
        ),
        at=now,
    )
    pattern = MemoryRecord.create(
        owner_id=owner,
        memory_type=MemoryType.PREFERENCE,
        statement="Prefers evening movement to morning movement",
        attribution=Attribution.inferred(
            now + timedelta(days=14),
            SensitivityLevel.S1,
            value=0.78,
            source_type=SourceType.BEHAVIORAL_INFERENCE,
        ),
        at=now + timedelta(days=14),
        review_after=now + timedelta(days=44),
    )
    graph.put_memory(single_skip)
    graph.put_memory(pattern)

    assert single_skip.memory_type is MemoryType.BEHAVIOR
    assert single_skip.confidence.is_certain
    assert pattern.memory_type is MemoryType.PREFERENCE
    assert not pattern.confidence.is_certain
    assert pattern.confidence.value == pytest.approx(0.78)
    assert pattern.last_confirmed_at is None
    assert pattern.needs_review_at(now + timedelta(days=45))

    # She changes: the inference stops being true, it does not become a lie.
    later = now + timedelta(days=60)
    graph.supersede_memory(pattern.id, at=later, reason="she started morning classes")
    revised = graph.get_memory(pattern.id)
    assert revised.status is RecordStatus.SUPERSEDED
    assert revised.temporal.valid_until == later
    assert revised.is_usable_at(now + timedelta(days=20))
    assert not revised.is_usable_at(later)
    assert graph.get_memory(single_skip.id).is_usable_at(later)
    assert revised.metadata["closure_reason"] == "she started morning classes"

    # A reading that was simply wrong is retained but never read back as history.
    mistake = graph.put_memory(
        MemoryRecord.create(
            owner_id=owner,
            memory_type=MemoryType.PREFERENCE,
            statement="Dislikes movement altogether",
            attribution=Attribution.inferred(
                now, SensitivityLevel.S1, value=0.3, source_type=SourceType.AI_INFERRED
            ),
            at=now,
        )
    )
    graph.invalidate_memory(mistake.id, at=later, reason="the inference was unfounded")
    withdrawn = graph.get_memory(mistake.id)
    assert withdrawn.status is RecordStatus.INVALIDATED
    assert not withdrawn.is_usable_at(now + timedelta(days=20))
    assert graph.get_memory(mistake.id).statement == "Dislikes movement altogether"


# --- Scenario 09 — context minimization ----------------------------------


def test_scenario_09_radar_gets_the_city_and_nothing_else(
    graph: PersonalLifeGraph, owner: UserId, cycle_state, now: datetime
) -> None:
    area = declare(
        graph,
        owner,
        now,
        EntityType.PLACE,
        "Riyadh, Al Nakheel",
        PlaceAttributes(city="Riyadh", area="Al Nakheel"),
    )
    home = declare(
        graph,
        owner,
        now,
        EntityType.PLACE,
        "Home",
        PlaceAttributes(
            city="Riyadh",
            area="Al Nakheel",
            street_address="a specific street",
            latitude=24.7,
            is_home=True,
        ),
        sensitivity=SensitivityLevel.S3,
    )
    declare(
        graph,
        owner,
        now,
        EntityType.INTEREST,
        "Pottery",
        InterestAttributes(engagement=EngagementLevel.ACTIVE),
    )
    declare(
        graph,
        owner,
        now,
        EntityType.CALENDAR_EVENT,
        "Thursday meeting",
        CalendarEventAttributes(),
        markers=TemporalMarkers(scheduled_for=now + timedelta(days=4)),
    )

    view = project_context(
        graph,
        owner_id=owner,
        scope=RADAR_CONTRACT.context_scope("rank nearby events this week"),
        at=now,
    )
    delivered = {entity.entity_type for entity in view.entities}

    assert EntityType.PLACE in delivered
    assert EntityType.INTEREST in delivered
    assert EntityType.CALENDAR_EVENT in delivered
    assert EntityType.CYCLE_STATE not in delivered
    assert EntityType.PREGNANCY_STATE not in delivered
    assert EntityType.HEALTH_CONDITION not in delivered

    # The area reaches Radar whole; the home place reaches it with its precise
    # fields stripped, rather than being lost entirely or leaking.
    delivered_by_id = {entity.id: entity for entity in view.entities}
    assert area.id in delivered_by_id
    assert all(entity.sensitivity.rank <= SensitivityLevel.S2.rank for entity in view.entities)

    seen_home = delivered_by_id.get(home.id)
    assert seen_home is not None
    home_attributes = seen_home.attributes_as(PlaceAttributes)
    assert home_attributes.city == "Riyadh"
    assert home_attributes.street_address is None
    assert home_attributes.latitude is None
    assert home_attributes.precision is LocationPrecision.AREA
    assert seen_home.redacted_fields >= {"street_address"}
    assert view.was_redacted


def test_scenario_09_an_address_cannot_be_stored_below_s3(
    graph: PersonalLifeGraph, owner: UserId, now: datetime
) -> None:
    with pytest.raises(ValueError, match="requires at least S3"):
        declare(
            graph,
            owner,
            now,
            EntityType.PLACE,
            "Home",
            PlaceAttributes(city="Riyadh", street_address="a specific street"),
            sensitivity=SensitivityLevel.S2,
        )


# --- Scenario 10 — one input, several minds ------------------------------


def test_scenario_10_one_long_day_becomes_one_coordinated_answer(
    graph: PersonalLifeGraph, owner: UserId, self_person, now: datetime
) -> None:
    morning = now + timedelta(days=1, hours=1)
    clinic = now + timedelta(days=1, hours=7)
    shop_closes = now + timedelta(days=1, hours=13)

    daughter = declare(
        graph,
        owner,
        now,
        EntityType.PERSON,
        "Daughter",
        PersonAttributes(display_name="Daughter", kinship=Kinship.CHILD),
    )
    meeting = declare(
        graph,
        owner,
        now,
        EntityType.CALENDAR_EVENT,
        "Morning meeting",
        CalendarEventAttributes(ends_at=morning + timedelta(hours=1)),
        markers=TemporalMarkers(scheduled_for=morning),
    )
    appointment = declare(
        graph,
        owner,
        now,
        EntityType.CALENDAR_EVENT,
        "Daughter's appointment",
        CalendarEventAttributes(ends_at=clinic + timedelta(hours=1)),
        markers=TemporalMarkers(scheduled_for=clinic),
    )
    dress = declare(
        graph,
        owner,
        now,
        EntityType.WARDROBE_ITEM,
        "The dress to return",
        WardrobeItemAttributes(category=WardrobeCategory.DRESS),
    )
    ret = declare(
        graph,
        owner,
        now,
        EntityType.COMMITMENT,
        "Return the dress before the shop closes",
        CommitmentAttributes(kind=CommitmentKind.RETURN, state=OpenLoopState.DUE),
        markers=TemporalMarkers(due_at=shop_closes),
    )
    link(graph, owner, now, daughter, RelationshipType.ATTENDS, appointment)
    link(graph, owner, now, ret, RelationshipType.REQUIRES, dress)

    # Extracted entities and open loops.
    entities = graph.entities(owner_id=owner, at=now)
    assert {entity.entity_type for entity in entities} >= {
        EntityType.PERSON,
        EntityType.CALENDAR_EVENT,
        EntityType.WARDROBE_ITEM,
        EntityType.COMMITMENT,
    }
    assert ret.attributes_as(CommitmentAttributes).state.is_open

    # Ordering is real time arithmetic, not a model's opinion.
    ordered = sorted(
        (meeting, appointment, ret),
        key=lambda item: item.markers.scheduled_for or item.markers.due_at or now,
    )
    assert [item.id for item in ordered] == [meeting.id, appointment.id, ret.id]

    # Routing: several minds, Guardian before any execution.
    route = ORCHESTRATOR_CONTRACT.agents_for(Intent.PLAN_DAY)
    assert AgentName.LIFE_ADMIN in route
    assert AgentName.READINESS in route
    assert route[-1] is AgentName.GUARDIAN
    assert ORCHESTRATOR_CONTRACT.owns_business_domain is False

    # Several internal claims, arbitrated into one coherent set.
    claims = (
        Claim(
            claim_id="claim_meeting",
            agent=AgentName.LIFE_ADMIN,
            subject="tomorrow-morning",
            nature=ClaimNature.COMMITMENT,
            decision_state=DecisionState.SURFACE,
            priority=PriorityClass.P1,
            statement="Morning meeting",
            confidence=Confidence.certain(),
        ),
        Claim(
            claim_id="claim_prep",
            agent=AgentName.READINESS,
            subject="tomorrow-morning",
            nature=ClaimNature.PREPARATION,
            decision_state=DecisionState.RECOMMEND,
            priority=PriorityClass.P2,
            statement="Lay the dress by the door tonight",
            confidence=Confidence.certain(),
        ),
        Claim(
            claim_id="claim_return",
            agent=AgentName.LIFE_ADMIN,
            subject="tomorrow-afternoon",
            nature=ClaimNature.COMMITMENT,
            decision_state=DecisionState.SURFACE,
            priority=PriorityClass.P1,
            statement="Return the dress before closing",
            confidence=Confidence.certain(),
        ),
        Claim(
            claim_id="claim_workshop",
            agent=AgentName.RADAR,
            subject="tomorrow-afternoon",
            nature=ClaimNature.OPPORTUNITY,
            decision_state=DecisionState.RECOMMEND,
            priority=PriorityClass.P3,
            statement="A pottery taster nearby",
            confidence=Confidence.probabilistic(0.5),
        ),
    )
    resolution = DEFAULT_CONFLICT_POLICY.resolve(claims)

    # Many internal decisions collapse into one ordered answer, not four messages.
    assert resolution.was_suppressed("claim_workshop")
    surviving = {claim.claim_id for claim in resolution.surviving}
    assert surviving == {"claim_meeting", "claim_prep", "claim_return"}
    subjects = {claim.subject for claim in resolution.surviving}
    assert subjects == {"tomorrow-morning", "tomorrow-afternoon"}

    bus = InMemoryEventBus()
    root = bus.publish(
        emit(
            EventType.CAPTURE_RECEIVED,
            CapturePayload(capture_id="cap_day", kind=CaptureKind.TEXT),
            owner,
            now,
            source_type=SourceType.USER_DECLARED,
        )
    )
    for entity in (meeting, appointment):
        bus.publish(
            root.caused(
                event_type=EventType.EVENT_CREATED,
                payload=CalendarEventPayload(
                    event_entity_id=entity.id, starts_at=entity.markers.scheduled_for
                ),
                actor=root.actor,
                source=root.source,
                sensitivity=SensitivityLevel.S2,
                occurred_at=now,
            )
        )
    bus.publish(
        root.caused(
            event_type=EventType.COMMITMENT_CAPTURED,
            payload=OpenLoopPayload(
                entity_id=ret.id,
                entity_type=EntityType.COMMITMENT,
                state=OpenLoopState.DUE,
                due_at=shop_closes,
            ),
            actor=root.actor,
            source=root.source,
            sensitivity=SensitivityLevel.S2,
            occurred_at=now,
        )
    )

    # One turn, one correlation, every consequence traceable to the sentence.
    assert len(bus.correlation(root.correlation_id)) == 4
    assert all(
        event.causation_id == root.event_id for event in bus.log if event.event_id != root.event_id
    )


def test_scenario_08_radar_item_stays_a_claim(now: datetime) -> None:
    payload = RadarItemPayload(radar_entity_id=EntityId("ent_radar"), category=RadarCategory.DEAL)
    assert payload.category is RadarCategory.DEAL
    assert EventType.RADAR_ITEM_DISCOVERED in RADAR_CONTRACT.events_produced
    assert (
        EntityRefPayload(entity_id=EntityId("ent_goal"), entity_type=EntityType.GOAL).entity_type
        is EntityType.GOAL
    )
