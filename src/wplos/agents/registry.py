from wplos.agents.contracts import AgentContract
from wplos.agents.guardian import GUARDIAN_CONTRACT
from wplos.agents.life_admin import LIFE_ADMIN_CONTRACT
from wplos.agents.navigator import NAVIGATOR_CONTRACT
from wplos.agents.operator import OPERATOR_CONTRACT
from wplos.agents.radar import RADAR_CONTRACT
from wplos.agents.readiness import READINESS_CONTRACT
from wplos.core.roles import AgentName
from wplos.shared.errors import InvariantViolation

AGENT_CONTRACTS: dict[AgentName, AgentContract] = {
    contract.agent: contract
    for contract in (
        NAVIGATOR_CONTRACT,
        RADAR_CONTRACT,
        LIFE_ADMIN_CONTRACT,
        GUARDIAN_CONTRACT,
        READINESS_CONTRACT,
        OPERATOR_CONTRACT,
    )
}


def contract_for(agent: AgentName) -> AgentContract:
    contract = AGENT_CONTRACTS.get(agent)
    if contract is None:
        raise InvariantViolation(f"no contract registered for {agent}")
    return contract
