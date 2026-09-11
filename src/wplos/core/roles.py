from enum import StrEnum


class AgentName(StrEnum):
    """The six minds. The user never picks one; the Orchestrator routes."""

    NAVIGATOR = "NAVIGATOR"
    RADAR = "RADAR"
    LIFE_ADMIN = "LIFE_ADMIN"
    GUARDIAN = "GUARDIAN"
    READINESS = "READINESS"
    OPERATOR = "OPERATOR"


class ActorRole(StrEnum):
    """Who caused something to happen.

    ORCHESTRATOR is a coordinator, not a seventh mind: it owns routing and
    enforcement, never a business domain of its own.
    """

    USER = "USER"
    AGENT = "AGENT"
    ORCHESTRATOR = "ORCHESTRATOR"
    CONNECTOR = "CONNECTOR"
    SYSTEM = "SYSTEM"
