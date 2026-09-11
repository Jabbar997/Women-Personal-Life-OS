"""Test 10: knowing something is not a licence to hand it to whoever asks."""

from datetime import datetime

from wplos.agents.navigator import NAVIGATOR_CONTRACT
from wplos.agents.readiness import READINESS_CONTRACT
from wplos.core.identifiers import UserId
from wplos.core.purpose import Purpose
from wplos.core.roles import AgentName
from wplos.core.sensitivity import SensitivityLevel
from wplos.personal_life_graph.context import ContextScope, RedactionScope, project_context
from wplos.personal_life_graph.entity import Entity
from wplos.personal_life_graph.entity_types import EntityType
from wplos.personal_life_graph.graph import PersonalLifeGraph
from wplos.policy.decisions import ReasonCode
from wplos.policy.sensitivity_policy import (
    DEFAULT_SENSITIVITY_POLICY,
    ExposureRequest,
    SurfaceRequest,
)


def test_s3_data_is_withheld_from_a_consumer_that_does_not_require_it(
    graph: PersonalLifeGraph,
    owner: UserId,
    goal: Entity,
    cycle_state: Entity,
    now: datetime,
) -> None:
    broad_scope = ContextScope(
        consumer=AgentName.NAVIGATOR,
        purpose=Purpose.DIRECTION_CHECK,
        required_entity_types=frozenset(),
        max_sensitivity=SensitivityLevel.S3,
    )

    view = project_context(graph, owner_id=owner, scope=broad_scope, at=now)

    assert view.contains_entity_type(EntityType.GOAL)
    assert not view.contains_entity_type(EntityType.CYCLE_STATE)
    assert view.was_redacted
    redaction = next(item for item in view.redactions if item.scope is RedactionScope.ENTITY)
    assert redaction.sensitivity is SensitivityLevel.S3
    assert redaction.reason_code is ReasonCode.NEED_TO_KNOW_NOT_ESTABLISHED


def test_readiness_receives_cycle_context_because_its_contract_requires_it(
    graph: PersonalLifeGraph,
    owner: UserId,
    cycle_state: Entity,
    now: datetime,
) -> None:
    scope = READINESS_CONTRACT.context_scope(Purpose.GET_READY)

    view = project_context(graph, owner_id=owner, scope=scope, at=now)

    assert view.contains_entity_type(EntityType.CYCLE_STATE)
    assert view.max_sensitivity_present() is SensitivityLevel.S3


def test_navigator_never_reaches_cycle_context_at_all(
    graph: PersonalLifeGraph,
    owner: UserId,
    cycle_state: Entity,
    goal: Entity,
    now: datetime,
) -> None:
    scope = NAVIGATOR_CONTRACT.context_scope(Purpose.DIRECTION_CHECK)

    view = project_context(graph, owner_id=owner, scope=scope, at=now)

    assert not view.contains_entity_type(EntityType.CYCLE_STATE)
    assert NAVIGATOR_CONTRACT.max_sensitivity is SensitivityLevel.S2


def test_a_consumer_above_its_ceiling_is_denied_by_the_policy() -> None:
    decision = DEFAULT_SENSITIVITY_POLICY.evaluate_exposure(
        ExposureRequest(
            consumer=AgentName.RADAR,
            consumer_ceiling=SensitivityLevel.S2,
            record_sensitivity=SensitivityLevel.S3,
            explicitly_required=True,
            purpose=Purpose.FIND_LOCAL_EVENT,
        )
    )

    assert not decision.is_permitted
    assert decision.has_reason(ReasonCode.CONSUMER_CEILING_EXCEEDED)


def test_sensitive_context_is_never_surfaced_into_a_shared_setting() -> None:
    decision = DEFAULT_SENSITIVITY_POLICY.evaluate_surfacing(
        SurfaceRequest(
            record_sensitivity=SensitivityLevel.S3,
            user_initiated=True,
            shared_context=True,
        )
    )

    assert not decision.is_permitted
    assert decision.has_reason(ReasonCode.SHARED_CONTEXT_DISCLOSURE)


def test_s3_is_surfaced_only_in_a_turn_the_user_opened() -> None:
    unprompted = DEFAULT_SENSITIVITY_POLICY.evaluate_surfacing(
        SurfaceRequest(
            record_sensitivity=SensitivityLevel.S3,
            user_initiated=False,
            shared_context=False,
        )
    )
    asked = DEFAULT_SENSITIVITY_POLICY.evaluate_surfacing(
        SurfaceRequest(
            record_sensitivity=SensitivityLevel.S3,
            user_initiated=True,
            shared_context=False,
        )
    )

    assert not unprompted.is_permitted
    assert unprompted.has_reason(ReasonCode.NOT_USER_INITIATED)
    assert asked.is_permitted
