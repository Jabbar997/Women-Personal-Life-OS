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
    ReauthorizationExpiryPolicy,
)
from wplos.integration.store import (
    ActionStatus,
    OutboxEvent,
    OutboxState,
    SQLiteIntegrationStore,
    StoredAction,
)
from wplos.policy.decisions import PolicyOutcome, ReasonCode
from wplos.policy.execution import ExecutionAuthorization, ExecutionPolicy, ProposedAction
from wplos.policy.guardian import GuardianAssessment, GuardianVerdict
from wplos.policy.guardian_authority import GuardianAuthority

ACTION_ACCEPTED = "ACTION_ACCEPTED"
ACTION_SUCCEEDED = "ACTION_SUCCEEDED"
ACTION_FAILED = "ACTION_FAILED"
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
            event_type=ACTION_ACCEPTED,
            schema_version=EVENT_SCHEMA_VERSION,
            payload={
                "action_id": str(action.action_id),
                "status": ActionStatus.PENDING,
                "projection_id": projection_id,
            },
        )

    def execute(self, action_id: str) -> ActionStatus:
        stored = self._require_action(action_id)
        if stored.status.is_terminal:
            return stored.status
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
            if decision.has_reason(ReasonCode.GUARDIAN_BLOCKED):
                return self._settle(stored, ActionStatus.BLOCKED, ACTION_FAILED)
            if decision.outcome is PolicyOutcome.REQUIRE_CONFIRMATION or decision.has_reason(
                ReasonCode.MATERIAL_TERMS_CHANGED
            ):
                spec = self.specs[stored.spec_name]
                expiry = now + timedelta(seconds=spec.reauthorization_ttl_seconds)
                self.store.update_action_status(
                    action_id,
                    ActionStatus.REAUTHORIZATION_REQUIRED,
                    reauthorization_expires_at=expiry,
                )
                return ActionStatus.REAUTHORIZATION_REQUIRED
            return self._settle(stored, ActionStatus.BLOCKED, ACTION_FAILED)

        self.store.update_action_status(action_id, ActionStatus.PROCESSING)
        result = self.provider.execute(action, stored.external_reference)
        if result.outcome is ProviderOutcome.TIMEOUT:
            self.store.update_action_status(action_id, ActionStatus.UNKNOWN)
            return ActionStatus.UNKNOWN
        if result.outcome is ProviderOutcome.FAILED:
            return self._settle(stored, ActionStatus.FAILED, ACTION_FAILED)
        return self._settle(stored, ActionStatus.SUCCEEDED, ACTION_SUCCEEDED)

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
            return self._settle(stored, ActionStatus.SUCCEEDED, ACTION_SUCCEEDED)
        if outcome is LookupOutcome.FAILED:
            return self._settle(stored, ActionStatus.FAILED, ACTION_FAILED)
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
            if self._has_gap(event, handlers):
                if event.parked_at is not None and now - event.parked_at >= gap_timeout:
                    self.store.mark_event_state(event.event_id, OutboxState.NEEDS_ATTENTION)
                elif event.state is not OutboxState.PARKED_FOR_GAP:
                    self.store.mark_event_state(
                        event.event_id, OutboxState.PARKED_FOR_GAP, parked_at=now
                    )
                continue
            payload = ActionLifecyclePayload.tolerant(event.payload)
            normalized = payload.model_dump()
            for consumer_name, handler in handlers:
                effect = handler(normalized)
                self.store.apply_once(
                    consumer_name=consumer_name,
                    event=event,
                    projection_id=effect.projection_id,
                )
            self.store.mark_event_state(event.event_id, OutboxState.APPLIED)

    def _has_gap(
        self,
        event: OutboxEvent,
        handlers: tuple[tuple[str, object], ...],
    ) -> bool:
        for consumer_name, _handler in handlers:
            expected = self.store.last_consumer_version(consumer_name, event.aggregate_id) + 1
            if event.aggregate_version != expected:
                return True
        return False

    def _settle(self, stored: StoredAction, status: ActionStatus, event_type: str) -> ActionStatus:
        causation_id = self.store.last_event_id(stored.action_id)
        self.store.settle_action_with_event(
            action_id=stored.action_id,
            status=status,
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
