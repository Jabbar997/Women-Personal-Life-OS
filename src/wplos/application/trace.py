from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from wplos.core.purpose import Purpose
from wplos.core.roles import AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.personal_life_graph.entity_types import EntityType
from wplos.policy.decisions import PolicyOutcome, ReasonCode


class RuntimePhase(StrEnum):
    INTAKE = "INTAKE"
    ROUTING = "ROUTING"
    PLANNING = "PLANNING"
    CONTEXT = "CONTEXT"
    AGENT_EXECUTION = "AGENT_EXECUTION"
    GUARDIAN_ENFORCEMENT = "GUARDIAN_ENFORCEMENT"
    CONFLICT_RESOLUTION = "CONFLICT_RESOLUTION"
    COMPOSITION = "COMPOSITION"
    AUTHORIZATION = "AUTHORIZATION"
    EMISSION = "EMISSION"


class ScopeTrace(BaseModel):
    """What a mind was allowed to see, by shape and count — never by value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: AgentName
    purpose: Purpose
    entity_types: tuple[EntityType, ...]
    max_sensitivity: SensitivityLevel
    entities_delivered: int
    memories_delivered: int
    redactions: int


class PolicyTrace(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy: str
    outcome: PolicyOutcome
    reason_codes: tuple[ReasonCode, ...] = Field(default_factory=tuple)


class TraceStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    phase: RuntimePhase
    agent: AgentName | None = None
    detail: str | None = None


class RuntimeTrace(BaseModel):
    """How the answer was reached, for debugging.

    Deliberately not domain history: this is an application artefact, it carries
    no raw values, and nothing in it is a record of what happened to her life.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    routed_agents: tuple[AgentName, ...] = Field(default_factory=tuple)
    matched_rules: tuple[str, ...] = Field(default_factory=tuple)
    execution_order: tuple[AgentName, ...] = Field(default_factory=tuple)
    waves: tuple[tuple[AgentName, ...], ...] = Field(default_factory=tuple)
    scopes: tuple[ScopeTrace, ...] = Field(default_factory=tuple)
    policy_decisions: tuple[PolicyTrace, ...] = Field(default_factory=tuple)
    conflicts: tuple[str, ...] = Field(default_factory=tuple)
    suppressions: tuple[str, ...] = Field(default_factory=tuple)
    steps: tuple[TraceStep, ...] = Field(default_factory=tuple)
    candidates_considered: int = 0
    items_composed: int = 0
