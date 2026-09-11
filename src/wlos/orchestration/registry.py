from __future__ import annotations

from wlos.agents import guardian, life_admin, navigator, operator, radar, readiness
from wlos.agents.contracts import AgentContract
from wlos.core.minds import Mind

MIND_CONTRACTS: dict[Mind, AgentContract] = {
    Mind.NAVIGATOR: navigator.CONTRACT,
    Mind.RADAR: radar.CONTRACT,
    Mind.LIFE_ADMIN: life_admin.CONTRACT,
    Mind.GUARDIAN: guardian.CONTRACT,
    Mind.READINESS: readiness.CONTRACT,
    Mind.OPERATOR: operator.CONTRACT,
}


def contract_for(mind: Mind) -> AgentContract:
    return MIND_CONTRACTS[mind]
