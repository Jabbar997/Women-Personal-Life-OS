from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from wplos.agents.contracts import AgentContract
from wplos.agents.registry import contract_for
from wplos.core.purpose import Purpose
from wplos.core.roles import AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.personal_life_graph.context import ContextScope
from wplos.personal_life_graph.entity_types import EntityType
from wplos.personal_life_graph.memory import MemoryType


class PurposeScope(BaseModel):
    """A contract narrowed to one job.

    A contract says the widest a mind may ever read. A purpose says what this
    particular job needs, which is usually far less. Narrowing only: a purpose
    can never reach past the contract that owns it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: AgentName
    purpose: Purpose
    entity_types: frozenset[EntityType]
    memory_types: frozenset[MemoryType] = frozenset()
    max_sensitivity: SensitivityLevel | None = None

    @model_validator(mode="after")
    def _narrows_never_widens(self) -> Self:
        contract = contract_for(self.agent)
        outside = self.entity_types - contract.reads
        if outside:
            raise ValueError(
                f"{self.purpose} would let {self.agent} read {sorted(outside)}, "
                "which its contract does not allow"
            )
        outside_memory = self.memory_types - contract.reads_memory
        if outside_memory:
            raise ValueError(
                f"{self.purpose} would let {self.agent} read {sorted(outside_memory)} memory"
            )
        if self.max_sensitivity is not None and not contract.max_sensitivity.dominates(
            self.max_sensitivity
        ):
            raise ValueError(f"{self.purpose} would raise {self.agent} above its ceiling")
        return self

    def to_context_scope(self, contract: AgentContract) -> ContextScope:
        return ContextScope(
            consumer=self.agent,
            purpose=self.purpose,
            required_entity_types=self.entity_types,
            required_memory_types=self.memory_types,
            max_sensitivity=self.max_sensitivity or contract.max_sensitivity,
        )


PURPOSE_SCOPES: dict[tuple[AgentName, Purpose], PurposeScope] = {
    (scope.agent, scope.purpose): scope
    for scope in (
        PurposeScope(
            agent=AgentName.RADAR,
            purpose=Purpose.FIND_LOCAL_EVENT,
            entity_types=frozenset(
                {
                    EntityType.PLACE,
                    EntityType.INTEREST,
                    EntityType.CALENDAR_EVENT,
                    EntityType.RADAR_ITEM,
                }
            ),
            memory_types=frozenset({MemoryType.PREFERENCE}),
            max_sensitivity=SensitivityLevel.S2,
        ),
        PurposeScope(
            agent=AgentName.RADAR,
            purpose=Purpose.WELLNESS_OPPORTUNITY,
            entity_types=frozenset({EntityType.INTEREST, EntityType.GOAL, EntityType.RADAR_ITEM}),
            memory_types=frozenset({MemoryType.PREFERENCE, MemoryType.BEHAVIOR}),
            max_sensitivity=SensitivityLevel.S1,
        ),
        PurposeScope(
            agent=AgentName.LIFE_ADMIN,
            purpose=Purpose.CLOSE_OPEN_LOOPS,
            entity_types=frozenset(
                {
                    EntityType.COMMITMENT,
                    EntityType.TASK,
                    EntityType.DEADLINE,
                    EntityType.CALENDAR_EVENT,
                    EntityType.PURCHASE,
                    EntityType.SUBSCRIPTION,
                }
            ),
            memory_types=frozenset({MemoryType.TEMPORAL}),
            max_sensitivity=SensitivityLevel.S3,
        ),
        PurposeScope(
            agent=AgentName.LIFE_ADMIN,
            purpose=Purpose.PLAN_DAY,
            entity_types=frozenset(
                {
                    EntityType.COMMITMENT,
                    EntityType.TASK,
                    EntityType.DEADLINE,
                    EntityType.CALENDAR_EVENT,
                }
            ),
            max_sensitivity=SensitivityLevel.S2,
        ),
        PurposeScope(
            agent=AgentName.READINESS,
            purpose=Purpose.GET_READY,
            entity_types=frozenset(
                {
                    EntityType.CALENDAR_EVENT,
                    EntityType.WARDROBE_ITEM,
                    EntityType.PRODUCT,
                    EntityType.AVAILABILITY_STATE,
                    EntityType.PLACE,
                    EntityType.CYCLE_STATE,
                    EntityType.BODY_SIGNAL,
                }
            ),
            max_sensitivity=SensitivityLevel.S3,
        ),
        PurposeScope(
            agent=AgentName.READINESS,
            purpose=Purpose.PLAN_DAY,
            entity_types=frozenset(
                {
                    EntityType.CALENDAR_EVENT,
                    EntityType.WARDROBE_ITEM,
                    EntityType.AVAILABILITY_STATE,
                    EntityType.ROUTINE,
                }
            ),
            max_sensitivity=SensitivityLevel.S2,
        ),
        PurposeScope(
            agent=AgentName.NAVIGATOR,
            purpose=Purpose.DIRECTION_CHECK,
            entity_types=frozenset(
                {
                    EntityType.GOAL,
                    EntityType.PRIORITY,
                    EntityType.MILESTONE,
                    EntityType.RADAR_ITEM,
                    EntityType.CALENDAR_EVENT,
                }
            ),
            max_sensitivity=SensitivityLevel.S2,
        ),
        PurposeScope(
            agent=AgentName.NAVIGATOR,
            purpose=Purpose.PLAN_DAY,
            entity_types=frozenset({EntityType.GOAL, EntityType.PRIORITY, EntityType.COMMITMENT}),
            max_sensitivity=SensitivityLevel.S2,
        ),
    )
}


def scope_for(agent: AgentName, purpose: Purpose) -> ContextScope:
    """The narrowest scope declared for this job, falling back to the contract."""
    contract = contract_for(agent)
    narrowed = PURPOSE_SCOPES.get((agent, purpose))
    if narrowed is None:
        return contract.context_scope(purpose)
    return narrowed.to_context_scope(contract)
