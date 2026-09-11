from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from wplos.policy.permissions import PermissionLevel, ReversibilityClass


class IntegrationEventType(StrEnum):
    """Lifecycle events of the integration kernel.

    Deliberately separate from the Personal Life Graph event catalog: these
    record what the delivery machinery did, not what happened in her life, and
    mixing the two would put worker bookkeeping into her history.
    """

    ACTION_ACCEPTED = "ACTION_ACCEPTED"
    ACTION_SUCCEEDED = "ACTION_SUCCEEDED"
    ACTION_FAILED = "ACTION_FAILED"
    ACTION_CANCELLED = "ACTION_CANCELLED"
    ACTION_NEEDS_ATTENTION = "ACTION_NEEDS_ATTENTION"


class ExecutionMode(StrEnum):
    SYNC = "SYNC"
    ASYNC = "ASYNC"


class OfflinePolicy(StrEnum):
    QUEUEABLE = "QUEUEABLE"
    SERVER_ONLY = "SERVER_ONLY"


class OrderingPolicy(StrEnum):
    PER_AGGREGATE = "PER_AGGREGATE"


class PostCommitFailurePolicy(StrEnum):
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    COMPENSATE_IF_SUPPORTED = "COMPENSATE_IF_SUPPORTED"


class ReauthorizationExpiryPolicy(StrEnum):
    CANCEL = "CANCEL"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


@dataclass(frozen=True, slots=True)
class ActionSpec:
    name: str
    execution_mode: ExecutionMode
    offline_policy: OfflinePolicy
    permission_level: PermissionLevel
    idempotency_required: bool
    ordering_policy: OrderingPolicy
    reversibility: ReversibilityClass
    post_commit_failure_policy: PostCommitFailurePolicy
    emitted_events: tuple[IntegrationEventType, ...]
    affected_projections: tuple[str, ...]
    reauthorization_ttl_seconds: int = 900
    reauthorization_expiry_policy: ReauthorizationExpiryPolicy = ReauthorizationExpiryPolicy.CANCEL
    processing_lease_seconds: int = 300
    """How long a worker may hold a claim before the claim is assumed abandoned."""

    def __post_init__(self) -> None:
        if self.execution_mode is ExecutionMode.ASYNC and not self.idempotency_required:
            raise ValueError("async side-effect actions must declare idempotency")
        if (
            self.permission_level.requires_authorization
            and self.offline_policy is not OfflinePolicy.SERVER_ONLY
        ):
            raise ValueError("authorized external actions must be server-only")
        if self.reauthorization_ttl_seconds <= 0:
            raise ValueError("reauthorization TTL must be positive")
        if self.processing_lease_seconds <= 0:
            raise ValueError("processing lease must be positive")


@dataclass(frozen=True, slots=True)
class EventSpec:
    event_type: IntegrationEventType
    schema_version: int
    declared_consumers: tuple[str, ...] = ()
    no_consumers_by_design: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version < 1:
            raise ValueError("schema_version must start at 1")
        if self.declared_consumers and self.no_consumers_by_design is not None:
            raise ValueError("an event cannot both declare consumers and declare none by design")
        if not self.declared_consumers and not self.no_consumers_by_design:
            raise ValueError("events without consumers require an explicit reviewed reason")

    def accepts_version(self, version: int) -> bool:
        """Consumers support the current schema and N-1 during migration."""
        return version == self.schema_version or (
            self.schema_version > 1 and version == self.schema_version - 1
        )


@dataclass(frozen=True, slots=True)
class ConsumerEffect:
    projection_id: str | None = None


Consumer = Callable[[Mapping[str, object]], ConsumerEffect]


class ConsumerRegistry:
    """Executable registry: declarations are checked against actual registrations."""

    def __init__(self, specs: tuple[EventSpec, ...]) -> None:
        self._specs: dict[IntegrationEventType, EventSpec] = {
            spec.event_type: spec for spec in specs
        }
        if len(self._specs) != len(specs):
            raise ValueError("duplicate event spec")
        self._handlers: dict[IntegrationEventType, dict[str, Consumer]] = {}

    def register(
        self, event_type: IntegrationEventType, consumer_name: str, handler: Consumer
    ) -> None:
        spec = self._specs.get(event_type)
        if spec is None:
            raise KeyError(f"unregistered event type {event_type}")
        if consumer_name not in spec.declared_consumers:
            raise ValueError(f"{consumer_name} is not declared for {event_type}")
        self._handlers.setdefault(event_type, {})[consumer_name] = handler

    def validate(self) -> None:
        errors: list[str] = []
        for event_type, spec in self._specs.items():
            actual = frozenset(self._handlers.get(event_type, {}))
            declared = frozenset(spec.declared_consumers)
            if actual != declared:
                errors.append(f"{event_type}: declared={sorted(declared)} actual={sorted(actual)}")
        if errors:
            raise ValueError("consumer registry mismatch: " + "; ".join(errors))

    def handlers_for(
        self, event_type: IntegrationEventType, schema_version: int
    ) -> tuple[tuple[str, Consumer], ...]:
        self.validate()
        spec = self._specs[event_type]
        if not spec.accepts_version(schema_version):
            raise ValueError(
                f"unsupported schema version {schema_version} for {event_type}; "
                f"current={spec.schema_version}"
            )
        handlers = self._handlers.get(event_type, {})
        return tuple(sorted(handlers.items(), key=lambda item: item[0]))

    def spec_for(self, event_type: IntegrationEventType) -> EventSpec:
        return self._specs[event_type]
