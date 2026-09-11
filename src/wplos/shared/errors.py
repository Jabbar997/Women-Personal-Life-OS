class DomainError(Exception):
    """Base class for every error raised by the domain core."""


class InvariantViolation(DomainError):
    """A domain rule that must always hold was violated."""


class RecordNotFound(DomainError):
    """A referenced entity, relationship or memory record does not exist."""


class UnknownEventType(DomainError):
    """An event type has no registered payload schema."""


class AuthorizationRequired(DomainError):
    """An action was attempted without the authorization its permission level requires."""
