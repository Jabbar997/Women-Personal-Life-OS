from __future__ import annotations


class DomainError(Exception):
    """Base class for violations of a domain rule."""


class ProvenanceError(DomainError):
    """A fact's confidence contradicts where it came from."""


class TemporalError(DomainError):
    """A validity window or timestamp ordering is impossible."""


class GraphIntegrityError(DomainError):
    """An entity, relationship or memory would break the graph's invariants."""


class EventIntegrityError(DomainError):
    """An attempt to rewrite recorded history, or to record a malformed event."""


class PolicyViolationError(DomainError):
    """An action was attempted that policy does not permit."""


class AuthorizationRequiredError(PolicyViolationError):
    """An external or high-impact action lacked a valid user authorization."""


class GuardianVetoError(PolicyViolationError):
    """Guardian blocked the action; no other mind can overrule it."""


class ContractViolationError(DomainError):
    """A mind attempted something outside its declared contract."""
