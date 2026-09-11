from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from wlos.core.base import DomainModel
from wlos.personal_life_graph.domains import LifeDomain, domain_of
from wlos.personal_life_graph.entities import Entity
from wlos.personal_life_graph.memory import MemoryRecord
from wlos.policy.decisions import PolicyDecision, PolicyOutcome, PolicyReason, ReasonCode
from wlos.shared.sensitivity import Sensitivity

POLICY_ID = "sensitivity.need-to-know.v1"


class ConsumerKind(StrEnum):
    MIND = "MIND"
    ORCHESTRATOR = "ORCHESTRATOR"
    CONNECTOR = "CONNECTOR"
    EXTERNAL_RECIPIENT = "EXTERNAL_RECIPIENT"
    USER_SURFACE = "USER_SURFACE"


class ContextConsumer(DomainModel):
    """Whoever is asking to read part of the graph, and what it is cleared for.

    Knowing something is not permission to show it: a consumer sees a domain
    only if it declared a need for that domain *and* is cleared for its level.
    """

    name: str
    kind: ConsumerKind
    clearance: Sensitivity = Sensitivity.S1
    required_domains: frozenset[LifeDomain] = frozenset()

    def needs(self, domain: LifeDomain) -> bool:
        return domain in self.required_domains


class SensitivityPolicy:
    @staticmethod
    def evaluate(
        consumer: ContextConsumer,
        *,
        domain: LifeDomain,
        sensitivity: Sensitivity,
        subject: str | None = None,
        at: datetime | None = None,
    ) -> PolicyDecision:
        reasons: list[PolicyReason] = []
        if not consumer.needs(domain):
            reasons.append(
                PolicyReason(
                    code=ReasonCode.NOT_NEED_TO_KNOW,
                    message=f"{consumer.name} did not declare a need for {domain}",
                    subject=subject,
                )
            )
        if not sensitivity.is_readable_at(consumer.clearance):
            reasons.append(
                PolicyReason(
                    code=ReasonCode.SENSITIVITY_ABOVE_CLEARANCE,
                    message=(
                        f"{sensitivity.name} exceeds {consumer.name} clearance "
                        f"{consumer.clearance.name}"
                    ),
                    subject=subject,
                )
            )
        if reasons:
            return PolicyDecision.refuse(POLICY_ID, PolicyOutcome.DENY, tuple(reasons), at=at)
        return PolicyDecision.permit(POLICY_ID, at=at)

    @classmethod
    def evaluate_entity(
        cls, consumer: ContextConsumer, entity: Entity, *, at: datetime | None = None
    ) -> PolicyDecision:
        return cls.evaluate(
            consumer,
            domain=entity.domain,
            sensitivity=entity.sensitivity,
            subject=str(entity.id),
            at=at,
        )

    @classmethod
    def evaluate_memory(
        cls,
        consumer: ContextConsumer,
        memory: MemoryRecord,
        *,
        domain: LifeDomain,
        at: datetime | None = None,
    ) -> PolicyDecision:
        return cls.evaluate(
            consumer,
            domain=domain,
            sensitivity=memory.sensitivity,
            subject=str(memory.id),
            at=at,
        )


def entity_domain(entity: Entity) -> LifeDomain:
    return domain_of(entity.entity_type)
