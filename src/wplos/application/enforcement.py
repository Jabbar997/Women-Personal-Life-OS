from wplos.agents.contracts import AgentContract, AgentOutput, DecisionState
from wplos.core.roles import AgentName
from wplos.shared.errors import DomainError


class ContractViolation(DomainError):
    """A mind returned something its contract does not permit."""


def enforce_output(contract: AgentContract, output: AgentOutput) -> AgentOutput:
    """Check a mind's output against its own contract before anyone acts on it.

    A contract that is only checked when the implementation feels like it is a
    contract in name. This runs on every result, including the reference
    implementations, because the point is to catch the implementation that gets
    it wrong.
    """
    if output.agent is not contract.agent:
        raise ContractViolation(f"{output.agent} answered for {contract.agent}")

    for decision in output.decisions:
        _check_state(contract, decision.decision_state)
    for recommendation in output.recommendations:
        _check_state(contract, recommendation.decision_state)
        action = recommendation.proposed_action
        if action is None:
            continue
        if action.proposed_by is not contract.agent:
            raise ContractViolation(
                f"{contract.agent} returned an action proposed by {action.proposed_by}"
            )
        if action.permission_level.rank > contract.max_permission_level.rank:
            raise ContractViolation(
                f"{contract.agent} proposed {action.permission_level}, "
                f"above its {contract.max_permission_level}"
            )

    if output.assessments and not contract.holds_veto:
        raise ContractViolation(f"{contract.agent} returned a Guardian assessment")

    for write in output.writes:
        if not contract.may_write(write.entity_type):
            raise ContractViolation(
                f"{contract.agent} tried to write {write.entity_type}, "
                "which its contract does not allow"
            )

    for event in output.events:
        if event.event_type not in contract.events_produced:
            raise ContractViolation(
                f"{contract.agent} emitted {event.event_type}, which it does not produce"
            )
        if event.actor.agent is not None and event.actor.agent is not contract.agent:
            raise ContractViolation(f"{contract.agent} emitted an event as {event.actor.agent}")

    return output


def _check_state(contract: AgentContract, state: DecisionState) -> None:
    if not contract.may_decide(state):
        raise ContractViolation(f"{contract.agent} is not permitted to decide {state}")


def enforce_guardian_is_guardian(agent: AgentName) -> None:
    if agent is not AgentName.GUARDIAN:
        raise ContractViolation(f"{agent} cannot stand in for Guardian")
