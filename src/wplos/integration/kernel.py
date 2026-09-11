from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from wplos.integration.specs import (
    ActionSpec,
    ConsumerRegistry,
    IntegrationEventType,
    ReauthorizationExpiryPolicy,
)
from wplos.integration.store import (
    ActionStatus,
    OutboxEvent,
    OutboxState,
    SQLiteIntegrationStore,
    StoredAction,
)
from wplos.policy.decisions import PolicyDecision, PolicyOutcome, ReasonCode
from wplos.policy.execution import ExecutionAuthorization, ExecutionPolicy, ProposedAction
from wplos.policy.guardian import GuardianAssessment, GuardianVerdict
from wplos.policy.guardian_authority import GuardianAuthority

EVENT_SCHEMA_VERSION = 1


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class ProviderOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class LookupOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ProviderResult:
    outcome: ProviderOutcome


class ExternalProvider(Protocol):
    supports_idempotency: bool
    supports_lookup: bool
    supports_cancellation: bool

    def execute(self, action: ProposedAction, external_reference: str) -> ProviderResult: ...

    def lookup(self, external_reference: str) -> LookupOutcome: ...


class GuardianRevalidator(Protocol):
    authority: GuardianAuthority

    def assess(self, action: ProposedAction, at: datetime) -> GuardianAssessment: ...


class MutableGuardian:
    """Deterministic Guardian used by the walking skeleton tests."""

    def __init__(self, authority: GuardianAuthority | None = None) -> None:
        self.authority = authority or GuardianAuthority(max_age=timedelta(hours=1))
        self.verdict = GuardianVerdict.ALLOW

    def assess(self, action: ProposedAction, at: datetime) -> GuardianAssessment:
        return self.authority.assess(
            action_id=action.action_id,
            fingerprint=action.terms_fingerprint,
            at=at,
            verdict=self.verdict,
        )


class ActionLifecyclePayload(BaseModel):
    """Tolerant event payload.

    A consumer written against schema N must not break when a producer on N+1
    adds a field. Tolerance is applied by :meth:`tolerant`, which keeps the
    fields this version knows about and drops the rest, rather than by relaxing
    the model: every model in this codebase forbids extras, and a model that
    quietly accepts anything is the wrong place to express forward
    compatibility.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: str
    status: str
    projection_id: str

    @classmethod
    def tolerant(cls, payload: Mapping[str, object]) -> ActionLifecyclePayload:
        known = {key: payload[key] for key in cls.model_fields if key in payload}
        return cls.model_validate(known)


class WalkingSkeleton:
    def __init__(
        self,
        *,
        store: SQLiteIntegrationStore,
        specs: dict[str, ActionSpec],
        registry: ConsumerRegistry,
        guardian: GuardianRevalidator,
        provider: ExternalProvider,
        clock: Clock | None = None,
    ) -> None:
        self.store = store
        self.specs = specs
        self.registry = registry
        self.guardian = guardian
        self.provider = provider
        self.clock = clock or SystemClock()
        self.execution_policy = ExecutionPolicy(guardian.authority)

    def accept(
        self,
        *,
        action: ProposedAction,
        authorization: ExecutionAuthorization | None,
        client_request_id: str,
        spec_name: str,
        projection_id: str,
        correlation_id: str,
        command_id: str,
    ) -> tuple[StoredAction, bool]:
        spec = self.specs[spec_name]
        if spec.permission_level != action.permission_level:
            raise ValueError("action permission level does not match ActionSpec")
        event_id = self._id("evt")
        return self.store.insert_action_with_event(
            action=action,
            authorization=authorization,
            client_request_id=client_request_id,
            spec_name=spec_name,
            projection_id=projection_id,
            correlation_id=correlation_id,
            command_id=command_id,
            external_reference=self._id("ext"),
            event_id=event_id,
            event_type=IntegrationEventType.ACTION_ACCEPTED,
            schema_version=EVENT_SCHEMA_VERSION,
            payload={
                "action_id": str(action.action_id),
                "status": ActionStatus.PENDING,
                "projection_id": projection_id,
            },
        )

    def execute(self, action_id: str) -> ActionStatus:
        """Claim the action, then decide, then act.

        The claim comes first for two reasons. It is the only thing that makes
        exactly one worker proceed, and it means Guardian is consulted once by
        the winner rather than once per racer — two assessments of the same
        action retire each other, so the loser's verdict would arrive stale
        through no fault of its own.
        """
        stored = self._require_action(action_id)
        if stored.status.is_terminal:
            return stored.status
        if not self.store.claim_for_processing(action_id):
            return self._require_action(action_id).status

        # Re-read under ownership: the terms may have moved between the first
        # look and the claim.
        stored = self._require_action(action_id)
        now = self.clock.now()
        action = stored.proposed_action
        current_guardian = self.guardian.assess(action, now)
        decision = self.execution_policy.authorize(
            action,
            current_guardian,
            stored.authorization,
            now,
        )
        if decision.outcome is not PolicyOutcome.PERMIT:
            return self._refuse(stored, decision, now)

        result = self.provider.execute(action, stored.external_reference)
        if result.outcome is ProviderOutcome.TIMEOUT:
            self.store.update_action_status(action_id, ActionStatus.UNKNOWN)
            return ActionStatus.UNKNOWN
        if result.outcome is ProviderOutcome.FAILED:
            return self._settle(stored, ActionStatus.FAILED, IntegrationEventType.ACTION_FAILED)
        return self._settle(stored, ActionStatus.SUCCEEDED, IntegrationEventType.ACTION_SUCCEEDED)

    def _refuse(
        self, stored: StoredAction, decision: PolicyDecision, now: datetime
    ) -> ActionStatus:
        if decision.has_reason(ReasonCode.GUARDIAN_BLOCKED):
            return self._settle(stored, ActionStatus.BLOCKED, IntegrationEventType.ACTION_FAILED)
        if decision.outcome is PolicyOutcome.REQUIRE_CONFIRMATION or decision.has_reason(
            ReasonCode.MATERIAL_TERMS_CHANGED
        ):
            spec = self.specs[stored.spec_name]
            expiry = now + timedelta(seconds=spec.reauthorization_ttl_seconds)
            self.store.update_action_status(
                stored.action_id,
                ActionStatus.REAUTHORIZATION_REQUIRED,
                reauthorization_expires_at=expiry,
            )
            return ActionStatus.REAUTHORIZATION_REQUIRED
        return self._settle(stored, ActionStatus.BLOCKED, IntegrationEventType.ACTION_FAILED)

    def reconcile_unknown(self, action_id: str) -> ActionStatus:
        stored = self._require_action(action_id)
        if stored.status is not ActionStatus.UNKNOWN:
            return stored.status
        if not self.provider.supports_lookup:
            if self.provider.supports_idempotency:
                self.store.update_action_status(action_id, ActionStatus.PENDING)
                return ActionStatus.PENDING
            self.store.update_action_status(action_id, ActionStatus.NEEDS_ATTENTION)
            return ActionStatus.NEEDS_ATTENTION
        outcome = self.provider.lookup(stored.external_reference)
        if outcome is LookupOutcome.SUCCEEDED:
            return self._settle(
                stored, ActionStatus.SUCCEEDED, IntegrationEventType.ACTION_SUCCEEDED
            )
        if outcome is LookupOutcome.FAILED:
            return self._settle(stored, ActionStatus.FAILED, IntegrationEventType.ACTION_FAILED)
        if outcome is LookupOutcome.NOT_FOUND and self.provider.supports_idempotency:
            self.store.update_action_status(action_id, ActionStatus.PENDING)
            return ActionStatus.PENDING
        self.store.update_action_status(action_id, ActionStatus.NEEDS_ATTENTION)
        return ActionStatus.NEEDS_ATTENTION

    def expire_reauthorizations(self) -> tuple[str, ...]:
        now = self.clock.now()
        changed: list[str] = []
        for stored in self.store.list_actions(ActionStatus.REAUTHORIZATION_REQUIRED):
            expiry = stored.reauthorization_expires_at
            if expiry is None or now < expiry:
                continue
            spec = self.specs[stored.spec_name]
            status = (
                ActionStatus.CANCELLED
                if spec.reauthorization_expiry_policy is ReauthorizationExpiryPolicy.CANCEL
                else ActionStatus.NEEDS_ATTENTION
            )
            self.store.update_action_status(stored.action_id, status)
            changed.append(stored.action_id)
        return tuple(changed)

    def dispatch_outbox(self, *, gap_timeout: timedelta = timedelta(minutes=5)) -> None:
        self.registry.validate()
        now = self.clock.now()
        for event in self.store.pending_events():
            handlers = self.registry.handlers_for(event.event_type, event.schema_version)
            if not handlers:
                self.store.mark_event_state(event.event_id, OutboxState.APPLIED)
                continue
            if self._blocked_by_gap(event, handlers):
                self._park(event, now, gap_timeout)
                continue
            payload = ActionLifecyclePayload.tolerant(event.payload)
            normalized = payload.model_dump()
            for consumer_name, handler in handlers:
                if not self._is_next_for(consumer_name, event):
                    # This consumer is already past this version: the delivery is a
                    # replay, and the durable dedupe key has already recorded it.
                    continue
                effect = handler(normalized)
                self.store.apply_once(
                    consumer_name=consumer_name,
                    event=event,
                    projection_id=effect.projection_id,
                )
            self.store.mark_event_state(event.event_id, OutboxState.APPLIED)

    def _park(self, event: OutboxEvent, now: datetime, gap_timeout: timedelta) -> None:
        if event.parked_at is not None and now - event.parked_at >= gap_timeout:
            self.store.mark_event_state(event.event_id, OutboxState.NEEDS_ATTENTION)
        elif event.state is not OutboxState.PARKED_FOR_GAP:
            self.store.mark_event_state(event.event_id, OutboxState.PARKED_FOR_GAP, parked_at=now)

    def _blocked_by_gap(
        self,
        event: OutboxEvent,
        handlers: tuple[tuple[str, object], ...],
    ) -> bool:
        """True only when a consumer is still waiting for an earlier version.

        Three cases, and only one of them is a gap. A version *ahead* of what a
        consumer expects means something earlier has not arrived, so the event
        waits. A version *behind* is a redelivery, which must reach the durable
        dedupe rather than be parked forever. Treating both as gaps is what made
        an ordinary duplicate look like a hole in the stream.
        """
        return any(
            event.aggregate_version > self._expected_for(consumer_name, event)
            for consumer_name, _handler in handlers
        )

    def _expected_for(self, consumer_name: str, event: OutboxEvent) -> int:
        return self.store.last_consumer_version(consumer_name, event.aggregate_id) + 1

    def _is_next_for(self, consumer_name: str, event: OutboxEvent) -> bool:
        """Whether this consumer still owes this version.

        Consumers advance independently, so one failing after another succeeded
        must be able to catch up on a retry instead of the event parking.
        """
        return event.aggregate_version == self._expected_for(consumer_name, event)

    def _settle(
        self,
        stored: StoredAction,
        status: ActionStatus,
        event_type: IntegrationEventType,
    ) -> ActionStatus:
        causation_id = self.store.last_event_id(stored.action_id)
        self.store.settle_action_with_event(
            action_id=stored.action_id,
            status=status,
            projection_id=stored.projection_id,
            event_id=self._id("evt"),
            event_type=event_type,
            schema_version=EVENT_SCHEMA_VERSION,
            client_request_id=stored.client_request_id,
            correlation_id=stored.correlation_id,
            command_id=stored.command_id,
            causation_id=causation_id,
            payload={
                "action_id": stored.action_id,
                "status": status,
                "projection_id": stored.projection_id,
            },
        )
        return status

    def _require_action(self, action_id: str) -> StoredAction:
        stored = self.store.get_action(action_id)
        if stored is None:
            raise KeyError(action_id)
        return stored

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"
