from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from wplos.core.identifiers import ActionId, AuthorizationId, UserId
from wplos.core.roles import AgentName
from wplos.integration import (
    ALLOWED_FROM,
    ActionSpec,
    ActionStatus,
    ConsumerEffect,
    ConsumerRegistry,
    EventSpec,
    ExecutionMode,
    IllegalTransition,
    IntegrationEventType,
    LookupOutcome,
    MutableGuardian,
    OfflinePolicy,
    OrderingPolicy,
    OutboxEvent,
    OutboxState,
    PostCommitFailurePolicy,
    ProviderOutcome,
    ProviderResult,
    ReauthorizationExpiryPolicy,
    SQLiteIntegrationStore,
    WalkingSkeleton,
)
from wplos.policy.execution import AuthorizationMethod, ExecutionAuthorization, ProposedAction
from wplos.policy.guardian import GuardianVerdict
from wplos.policy.permissions import ActionDomain, PermissionLevel, ReversibilityClass


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current


class FakeProvider:
    def __init__(
        self,
        *,
        outcome: ProviderOutcome = ProviderOutcome.SUCCEEDED,
        lookup_outcome: LookupOutcome = LookupOutcome.UNKNOWN,
        supports_idempotency: bool = True,
        supports_lookup: bool = True,
        supports_cancellation: bool = True,
    ) -> None:
        self.outcome = outcome
        self.lookup_outcome = lookup_outcome
        self.supports_idempotency = supports_idempotency
        self.supports_lookup = supports_lookup
        self.supports_cancellation = supports_cancellation
        self.calls: list[str] = []

    def execute(self, action: ProposedAction, external_reference: str) -> ProviderResult:
        self.calls.append(external_reference)
        return ProviderResult(self.outcome)

    def lookup(self, external_reference: str) -> LookupOutcome:
        self.calls.append(f"lookup:{external_reference}")
        return self.lookup_outcome


def make_action(now: datetime, *, price: int = 100, action_id: str = "act_walk") -> ProposedAction:
    return ProposedAction(
        action_id=ActionId(action_id),
        owner_id=UserId("usr_walk"),
        proposed_by=AgentName.OPERATOR,
        proposed_at=now,
        domain=ActionDomain.SCHEDULING,
        permission_level=PermissionLevel.A2,
        summary="book a test appointment",
        reversibility=ReversibilityClass.COMPENSATABLE,
        target_entity_id=None,
        offer_expires_at=now + timedelta(hours=1),
        material_terms={"price_minor": price, "currency": "SAR", "time": "19:00"},
    )


def make_authorization(action: ProposedAction, now: datetime) -> ExecutionAuthorization:
    return ExecutionAuthorization.for_action(
        action,
        authorization_id=AuthorizationId("aut_walk"),
        granted_at=now,
        method=AuthorizationMethod.EXPLICIT_CONFIRMATION,
        expires_at=now + timedelta(minutes=30),
    )


def make_spec() -> ActionSpec:
    return ActionSpec(
        name="TEST_BOOK",
        execution_mode=ExecutionMode.ASYNC,
        offline_policy=OfflinePolicy.SERVER_ONLY,
        permission_level=PermissionLevel.A2,
        idempotency_required=True,
        ordering_policy=OrderingPolicy.PER_AGGREGATE,
        reversibility=ReversibilityClass.COMPENSATABLE,
        post_commit_failure_policy=PostCommitFailurePolicy.NEEDS_ATTENTION,
        emitted_events=(
            IntegrationEventType.ACTION_ACCEPTED,
            IntegrationEventType.ACTION_SUCCEEDED,
            IntegrationEventType.ACTION_FAILED,
        ),
        affected_projections=("today",),
        reauthorization_ttl_seconds=60,
        reauthorization_expiry_policy=ReauthorizationExpiryPolicy.CANCEL,
    )


def make_registry() -> ConsumerRegistry:
    specs = tuple(
        EventSpec(event_type=event_type, schema_version=1, declared_consumers=("today_projection",))
        for event_type in (
            IntegrationEventType.ACTION_ACCEPTED,
            IntegrationEventType.ACTION_SUCCEEDED,
            IntegrationEventType.ACTION_FAILED,
        )
    )
    registry = ConsumerRegistry(specs)

    def project(payload: dict[str, object]) -> ConsumerEffect:
        projection_id = payload.get("projection_id")
        if not isinstance(projection_id, str):
            raise TypeError("projection_id must be a string")
        return ConsumerEffect(projection_id=projection_id)

    for event_type in (
        IntegrationEventType.ACTION_ACCEPTED,
        IntegrationEventType.ACTION_SUCCEEDED,
        IntegrationEventType.ACTION_FAILED,
    ):
        registry.register(event_type, "today_projection", project)
    registry.validate()
    return registry


def make_kernel(
    tmp_path: Path,
    *,
    provider: FakeProvider | None = None,
    clock: FixedClock | None = None,
) -> tuple[WalkingSkeleton, SQLiteIntegrationStore, MutableGuardian, FakeProvider, FixedClock]:
    now = datetime(2026, 9, 12, 12, tzinfo=UTC)
    fixed = clock or FixedClock(now)
    external = provider or FakeProvider()
    guardian = MutableGuardian()
    store = SQLiteIntegrationStore(tmp_path / "kernel.sqlite3")
    kernel = WalkingSkeleton(
        store=store,
        specs={"TEST_BOOK": make_spec()},
        registry=make_registry(),
        guardian=guardian,
        provider=external,
        clock=fixed,
    )
    return kernel, store, guardian, external, fixed


def accept(
    kernel: WalkingSkeleton,
    now: datetime,
    *,
    client_request_id: str = "cli_1",
    action_id: str = "act_walk",
) -> str:
    action = make_action(now, action_id=action_id)
    authorization = make_authorization(action, now)
    stored, _created = kernel.accept(
        action=action,
        authorization=authorization,
        client_request_id=client_request_id,
        spec_name="TEST_BOOK",
        projection_id="today",
        correlation_id="cor_1",
        command_id="cmd_1",
    )
    return stored.action_id


def test_01_worker_dies_after_commit_event_survives(tmp_path: Path) -> None:
    kernel, store, _guardian, _provider, clock = make_kernel(tmp_path)
    action_id = accept(kernel, clock.now())
    assert store.count_actions() == 1
    assert store.count_outbox() == 1

    # No worker ran before this point. A fresh worker view still finds the row.
    surviving = store.get_action(action_id)
    assert surviving is not None
    assert surviving.status is ActionStatus.PENDING
    kernel.dispatch_outbox()
    projection = store.projection_state("today")
    assert projection.last_applied_event_id is not None


def test_02_duplicate_delivery_has_one_logical_effect(tmp_path: Path) -> None:
    kernel, store, _guardian, _provider, clock = make_kernel(tmp_path)
    accept(kernel, clock.now())
    event = store.pending_events()[0]
    kernel.dispatch_outbox()
    assert store.processed_count("today_projection", event.event_id) == 1

    # Simulate broker redelivery of the same event id. The consumer is already
    # past this version, which is a replay rather than a hole in the stream: it
    # must reach the no-op path instead of being parked as a gap.
    store.mark_event_state(event.event_id, OutboxState.PENDING)
    kernel.dispatch_outbox()

    assert store.processed_count("today_projection", event.event_id) == 1
    assert store.count_actions() == 1
    assert store.pending_events() == ()
    assert store.last_consumer_version("today_projection", event.aggregate_id) == 1


def test_03_provider_timeout_becomes_unknown(tmp_path: Path) -> None:
    provider = FakeProvider(outcome=ProviderOutcome.TIMEOUT)
    kernel, store, _guardian, _provider, clock = make_kernel(tmp_path, provider=provider)
    action_id = accept(kernel, clock.now())
    assert kernel.execute(action_id) is ActionStatus.UNKNOWN
    assert store.get_action(action_id).status is ActionStatus.UNKNOWN  # type: ignore[union-attr]


def test_04_unknown_without_safe_lookup_needs_attention(tmp_path: Path) -> None:
    provider = FakeProvider(
        outcome=ProviderOutcome.TIMEOUT,
        supports_idempotency=False,
        supports_lookup=False,
    )
    kernel, store, _guardian, _provider, clock = make_kernel(tmp_path, provider=provider)
    action_id = accept(kernel, clock.now())
    assert kernel.execute(action_id) is ActionStatus.UNKNOWN
    assert kernel.reconcile_unknown(action_id) is ActionStatus.NEEDS_ATTENTION
    assert store.list_actions(ActionStatus.NEEDS_ATTENTION)[0].action_id == action_id


def test_05_material_terms_change_requires_fresh_authorization(tmp_path: Path) -> None:
    kernel, store, _guardian, provider, clock = make_kernel(tmp_path)
    action_id = accept(kernel, clock.now())
    stored = store.get_action(action_id)
    assert stored is not None
    store.update_action_terms(stored.proposed_action.with_terms(price_minor=125))
    assert kernel.execute(action_id) is ActionStatus.REAUTHORIZATION_REQUIRED
    assert provider.calls == []


def test_06_guardian_block_at_execution_stops_provider(tmp_path: Path) -> None:
    kernel, store, guardian, provider, clock = make_kernel(tmp_path)
    action_id = accept(kernel, clock.now())
    guardian.verdict = GuardianVerdict.BLOCK
    assert kernel.execute(action_id) is ActionStatus.BLOCKED
    assert provider.calls == []
    assert store.get_action(action_id).status is ActionStatus.BLOCKED  # type: ignore[union-attr]


def test_07_projection_staleness_follows_active_action_not_promised_version(tmp_path: Path) -> None:
    provider = FakeProvider(outcome=ProviderOutcome.FAILED)
    kernel, store, _guardian, _provider, clock = make_kernel(tmp_path, provider=provider)
    action_id = accept(kernel, clock.now())
    kernel.dispatch_outbox()
    before = store.projection_state("today")
    assert action_id in before.active_action_ids
    assert before.is_stale

    # C: a failing action still terminates. It is stale while its result event is
    # in flight, and fresh once that event lands — not stale forever.
    assert kernel.execute(action_id) is ActionStatus.FAILED
    settled = store.projection_state("today")
    assert settled.active_action_ids == ()
    assert settled.is_stale

    kernel.dispatch_outbox()
    after = store.projection_state("today")
    assert not after.is_stale
    assert after.unapplied_event_ids == ()


def test_projection_is_not_fresh_while_the_success_event_is_still_queued(
    tmp_path: Path,
) -> None:
    """A: the action is SUCCEEDED but the projection has not seen it yet.

    Reporting fresh here would tell a reader the view is current while it still
    shows the state from before the action ran.
    """
    kernel, store, _guardian, _provider, clock = make_kernel(tmp_path)
    action_id = accept(kernel, clock.now())
    kernel.dispatch_outbox()
    assert kernel.execute(action_id) is ActionStatus.SUCCEEDED

    state = store.projection_state("today")

    assert state.active_action_ids == ()
    assert state.unapplied_event_ids != ()
    assert state.is_stale


def test_projection_becomes_fresh_once_the_success_event_is_applied(tmp_path: Path) -> None:
    """B: and fresh only then, pointing at the success event."""
    kernel, store, _guardian, _provider, clock = make_kernel(tmp_path)
    action_id = accept(kernel, clock.now())
    kernel.dispatch_outbox()
    assert kernel.execute(action_id) is ActionStatus.SUCCEEDED
    success_event_id = store.last_event_id(action_id)

    kernel.dispatch_outbox()
    state = store.projection_state("today")

    assert not state.is_stale
    assert state.unapplied_event_ids == ()
    assert state.last_applied_event_id == success_event_id


def test_08_tolerant_reader_ignores_new_event_field(tmp_path: Path) -> None:
    kernel, store, _guardian, _provider, _clock = make_kernel(tmp_path)
    event = OutboxEvent(
        event_id="evt_extra",
        event_type=IntegrationEventType.ACTION_ACCEPTED,
        schema_version=1,
        aggregate_id="agg_extra",
        aggregate_version=1,
        action_id="act_extra",
        client_request_id="cli_extra",
        correlation_id="cor_extra",
        command_id="cmd_extra",
        causation_id=None,
        payload={
            "action_id": "act_extra",
            "status": "PENDING",
            "projection_id": "today",
            "future_field": "ignored",
        },
        state=OutboxState.PENDING,
        parked_at=None,
    )
    store.inject_event(event)
    kernel.dispatch_outbox()
    assert store.projection_state("today").last_applied_event_id == "evt_extra"


def test_09_concurrent_idempotency_is_database_enforced(tmp_path: Path) -> None:
    """Two callers, two different action ids, one client request id.

    The action primary key cannot decide this: the ids differ. Only
    UNIQUE(user_id, client_request_id) can, which is the constraint that is
    actually supposed to carry idempotency.
    """
    kernel, store, _guardian, _provider, clock = make_kernel(tmp_path)
    barrier = threading.Barrier(2)
    ids: list[str] = []
    errors: list[BaseException] = []

    def submit(action_id: str) -> None:
        try:
            barrier.wait()
            ids.append(
                accept(
                    kernel,
                    clock.now(),
                    client_request_id="same_request",
                    action_id=action_id,
                )
            )
        except BaseException as exc:  # test captures thread errors for assertion
            errors.append(exc)

    threads = [threading.Thread(target=submit, args=(name,)) for name in ("act_A", "act_B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(ids) == 2
    assert len(set(ids)) == 1
    winner = ids[0]
    assert winner in {"act_A", "act_B"}
    assert store.count_actions() == 1
    assert store.count_outbox() == 1
    assert store.get_action(winner) is not None


def test_gap_is_parked_then_recovers_when_missing_version_arrives(tmp_path: Path) -> None:
    kernel, store, _guardian, _provider, _clock = make_kernel(tmp_path)
    base: dict[str, object] = {
        "event_type": IntegrationEventType.ACTION_ACCEPTED,
        "schema_version": 1,
        "aggregate_id": "agg_gap",
        "action_id": "act_gap",
        "client_request_id": "cli_gap",
        "correlation_id": "cor_gap",
        "command_id": "cmd_gap",
        "causation_id": None,
        "payload": {"action_id": "act_gap", "status": "PENDING", "projection_id": "today"},
        "state": OutboxState.PENDING,
        "parked_at": None,
    }
    store.inject_event(OutboxEvent(event_id="evt_2", aggregate_version=2, **base))
    kernel.dispatch_outbox()
    assert store.pending_events()[0].state is OutboxState.PARKED_FOR_GAP

    store.inject_event(OutboxEvent(event_id="evt_1", aggregate_version=1, **base))
    kernel.dispatch_outbox()
    assert store.last_consumer_version("today_projection", "agg_gap") == 2
    assert store.pending_events() == ()


def test_reauthorization_ttl_uses_server_clock_and_expires(tmp_path: Path) -> None:
    kernel, store, _guardian, _provider, clock = make_kernel(tmp_path)
    action_id = accept(kernel, clock.now())
    stored = store.get_action(action_id)
    assert stored is not None
    store.update_action_terms(stored.proposed_action.with_terms(price_minor=999))
    assert kernel.execute(action_id) is ActionStatus.REAUTHORIZATION_REQUIRED
    clock.current += timedelta(seconds=61)
    assert kernel.expire_reauthorizations() == (action_id,)
    assert store.get_action(action_id).status is ActionStatus.CANCELLED  # type: ignore[union-attr]


def test_registry_validation_catches_declared_runtime_drift() -> None:
    registry = ConsumerRegistry(
        (
            EventSpec(
                IntegrationEventType.ACTION_ACCEPTED, 1, declared_consumers=("today_projection",)
            ),
        )
    )
    with pytest.raises(ValueError, match="consumer registry mismatch"):
        registry.validate()


def test_projection_state_reads_an_empty_row_without_inventing_values(tmp_path: Path) -> None:
    """The schema allows both projection columns to be NULL, and ProjectionState
    declares them optional. Reading one must not produce the string "None"."""
    _kernel, store, _guardian, _provider, _clock = make_kernel(tmp_path)
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO projections(projection_id,last_applied_event_id,updated_at)"
            " VALUES('empty',NULL,NULL)"
        )

    state = store.projection_state("empty")

    assert state.last_applied_event_id is None
    assert state.updated_at is None
    assert not state.is_stale


def test_concurrent_execute_calls_the_provider_once(tmp_path: Path) -> None:
    """Two workers, one side effect.

    Without a claim both pass the policy and both reach the provider, which for
    a booking means two bookings. The winner is decided by a conditional UPDATE,
    so this holds across processes, not just across threads in one interpreter.
    """
    kernel, store, _guardian, provider, clock = make_kernel(tmp_path)
    action_id = accept(kernel, clock.now())
    barrier = threading.Barrier(2)
    outcomes: list[ActionStatus] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            barrier.wait()
            outcomes.append(kernel.execute(action_id))
        except BaseException as exc:  # test captures thread errors for assertion
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(provider.calls) == 1
    assert ActionStatus.SUCCEEDED in outcomes
    assert store.get_action(action_id).status is ActionStatus.SUCCEEDED  # type: ignore[union-attr]
    # Exactly one accepted event and one result event: no double settle.
    assert store.count_outbox() == 2


def test_a_consumer_that_failed_catches_up_without_a_permanent_park(
    tmp_path: Path,
) -> None:
    """One consumer applied, the next raised. The retry must let it catch up.

    Parking here would be wrong twice over: nothing is missing from the stream,
    and the consumer that is behind would never be given the event again.
    """
    specs = (
        EventSpec(
            event_type=IntegrationEventType.ACTION_ACCEPTED,
            schema_version=1,
            declared_consumers=("a_projection", "b_audit"),
        ),
    )
    registry = ConsumerRegistry(specs)
    attempts: list[str] = []

    def a_projection(payload: dict[str, object]) -> ConsumerEffect:
        attempts.append("a")
        return ConsumerEffect(projection_id="today")

    def b_audit(payload: dict[str, object]) -> ConsumerEffect:
        attempts.append("b")
        if attempts.count("b") == 1:
            raise RuntimeError("audit sink unavailable")
        return ConsumerEffect(projection_id=None)

    registry.register(IntegrationEventType.ACTION_ACCEPTED, "a_projection", a_projection)
    registry.register(IntegrationEventType.ACTION_ACCEPTED, "b_audit", b_audit)

    store = SQLiteIntegrationStore(tmp_path / "catchup.sqlite3")
    kernel = WalkingSkeleton(
        store=store,
        specs={"TEST_BOOK": make_spec()},
        registry=registry,
        guardian=MutableGuardian(),
        provider=FakeProvider(),
        clock=FixedClock(datetime(2026, 9, 12, 12, tzinfo=UTC)),
    )
    accept(kernel, kernel.clock.now())

    with pytest.raises(RuntimeError, match="audit sink unavailable"):
        kernel.dispatch_outbox()

    event = store.pending_events()[0]
    assert event.state is OutboxState.PENDING
    assert store.last_consumer_version("a_projection", event.aggregate_id) == 1
    assert store.last_consumer_version("b_audit", event.aggregate_id) == 0

    kernel.dispatch_outbox()

    assert store.pending_events() == ()
    assert store.last_consumer_version("b_audit", event.aggregate_id) == 1
    # The consumer that had already applied it did not apply it twice.
    assert store.processed_count("a_projection", event.event_id) == 1
    assert store.processed_count("b_audit", event.event_id) == 1


def test_a_succeeded_action_cannot_be_moved_back_to_pending(tmp_path: Path) -> None:
    kernel, store, _guardian, _provider, clock = make_kernel(tmp_path)
    action_id = accept(kernel, clock.now())
    assert kernel.execute(action_id) is ActionStatus.SUCCEEDED

    with pytest.raises(IllegalTransition):
        store.update_action_status(action_id, ActionStatus.PENDING)

    assert store.get_action(action_id).status is ActionStatus.SUCCEEDED  # type: ignore[union-attr]


def test_a_failed_action_cannot_be_moved_back_to_processing(tmp_path: Path) -> None:
    kernel, store, _guardian, _provider, clock = make_kernel(
        tmp_path, provider=FakeProvider(outcome=ProviderOutcome.FAILED)
    )
    action_id = accept(kernel, clock.now())
    assert kernel.execute(action_id) is ActionStatus.FAILED

    with pytest.raises(IllegalTransition):
        store.update_action_status(action_id, ActionStatus.PROCESSING)
    assert store.claim_for_processing(action_id) is False

    assert store.get_action(action_id).status is ActionStatus.FAILED  # type: ignore[union-attr]


def test_a_cancelled_action_cannot_be_moved_back_to_pending(tmp_path: Path) -> None:
    kernel, store, _guardian, _provider, clock = make_kernel(tmp_path)
    action_id = accept(kernel, clock.now())
    stored = store.get_action(action_id)
    assert stored is not None
    store.update_action_terms(stored.proposed_action.with_terms(price_minor=777))
    assert kernel.execute(action_id) is ActionStatus.REAUTHORIZATION_REQUIRED
    clock.current += timedelta(seconds=61)
    assert kernel.expire_reauthorizations() == (action_id,)

    with pytest.raises(IllegalTransition):
        store.update_action_status(action_id, ActionStatus.PENDING)

    assert store.get_action(action_id).status is ActionStatus.CANCELLED  # type: ignore[union-attr]


def test_no_transition_can_leave_a_terminal_status() -> None:
    """The map is the state machine: a terminal status appears as no one's source."""
    terminal = {status for status in ActionStatus if status.is_terminal}
    reachable_from = {source for sources in ALLOWED_FROM.values() for source in sources}

    assert not (terminal & reachable_from)


def test_a_claim_cannot_be_taken_twice(tmp_path: Path) -> None:
    kernel, store, _guardian, _provider, clock = make_kernel(tmp_path)
    action_id = accept(kernel, clock.now())

    assert store.claim_for_processing(action_id) is True
    assert store.claim_for_processing(action_id) is False


def test_a_reused_action_id_is_not_mistaken_for_a_duplicate_request(
    tmp_path: Path,
) -> None:
    """Only the idempotency key means "seen before".

    Swallowing a primary-key clash as a duplicate would silently drop a genuine
    second request, and its outbox event with it.
    """
    kernel, store, _guardian, _provider, clock = make_kernel(tmp_path)
    accept(kernel, clock.now(), client_request_id="cli_first", action_id="act_same")

    with pytest.raises(sqlite3.IntegrityError):
        accept(kernel, clock.now(), client_request_id="cli_second", action_id="act_same")

    assert store.count_actions() == 1
    assert store.count_outbox() == 1


def test_a_reused_event_id_is_not_mistaken_for_a_duplicate_request(
    tmp_path: Path,
) -> None:
    kernel, store, _guardian, _provider, clock = make_kernel(tmp_path)
    accept(kernel, clock.now())
    existing = store.pending_events()[0]

    with pytest.raises(sqlite3.IntegrityError):
        store.inject_event(
            OutboxEvent(
                event_id=existing.event_id,
                event_type=IntegrationEventType.ACTION_ACCEPTED,
                schema_version=1,
                aggregate_id="agg_other",
                aggregate_version=1,
                action_id="act_other",
                client_request_id="cli_other",
                correlation_id="cor_other",
                command_id="cmd_other",
                causation_id=None,
                payload={"action_id": "act_other", "status": "PENDING", "projection_id": "today"},
                state=OutboxState.PENDING,
                parked_at=None,
            )
        )


def test_a_duplicate_aggregate_version_is_not_mistaken_for_a_duplicate_request(
    tmp_path: Path,
) -> None:
    kernel, store, _guardian, _provider, clock = make_kernel(tmp_path)
    action_id = accept(kernel, clock.now())

    with pytest.raises(sqlite3.IntegrityError):
        store.inject_event(
            OutboxEvent(
                event_id="evt_clash",
                event_type=IntegrationEventType.ACTION_ACCEPTED,
                schema_version=1,
                aggregate_id=action_id,
                aggregate_version=1,
                action_id=action_id,
                client_request_id="cli_1",
                correlation_id="cor_1",
                command_id="cmd_1",
                causation_id=None,
                payload={"action_id": action_id, "status": "PENDING", "projection_id": "today"},
                state=OutboxState.PENDING,
                parked_at=None,
            )
        )
