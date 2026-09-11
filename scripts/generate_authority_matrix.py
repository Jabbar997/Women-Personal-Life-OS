#!/usr/bin/env python
"""Render docs/domain/agent-authority-matrix.md from the contracts themselves.

The matrix is derived, never hand-maintained, so it cannot drift into fiction.
A test regenerates it and fails if the committed file disagrees.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wplos.agents.contracts import DecisionState  # noqa: E402
from wplos.agents.registry import AGENT_CONTRACTS  # noqa: E402
from wplos.core.roles import AgentName  # noqa: E402
from wplos.personal_life_graph.entity_types import DOMAIN_OF, EntityType  # noqa: E402

TARGET = ROOT / "docs" / "domain" / "agent-authority-matrix.md"
ORDER: tuple[AgentName, ...] = (
    AgentName.NAVIGATOR,
    AgentName.RADAR,
    AgentName.LIFE_ADMIN,
    AgentName.GUARDIAN,
    AgentName.READINESS,
    AgentName.OPERATOR,
)


def cell(agent: AgentName, entity_type: EntityType) -> str:
    contract = AGENT_CONTRACTS[agent]
    marks: list[str] = []
    if entity_type in contract.writes:
        marks.append("W")
    if entity_type in contract.reads:
        marks.append("R")
    if not marks:
        return "-"
    if contract.holds_veto:
        marks.append("V")
    if contract.may_decide(DecisionState.ACT) and entity_type in contract.writes:
        marks.append("X")
    elif entity_type in contract.reads and DecisionState.RECOMMEND in contract.decision_authority:
        marks.append("P")
    return "".join(marks)


def render() -> str:
    lines = [
        "# Agent Authority Matrix",
        "",
        "Generated from `AGENT_CONTRACTS` by `scripts/generate_authority_matrix.py`.",
        "Do not edit by hand: `tests/test_agent_authority.py` regenerates this file and",
        "fails if it disagrees with the contracts in code.",
        "",
        "## Legend",
        "",
        "```",
        "R = Read          W = Write         P = Propose (RECOMMEND authority)",
        "V = Veto          X = Execute       - = No access",
        "```",
        "",
        "Write implies read. `V` marks the mind that can stop an action outright.",
        "`X` marks the only mind that may act on the world.",
        "",
        "## Objects",
        "",
        "| Domain | Object | " + " | ".join(agent.value.title() for agent in ORDER) + " |",
        "| --- | --- | " + " | ".join("---" for _ in ORDER) + " |",
    ]
    for entity_type in sorted(EntityType, key=lambda item: (DOMAIN_OF[item].value, item.value)):
        cells = " | ".join(cell(agent, entity_type) for agent in ORDER)
        lines.append(f"| {DOMAIN_OF[entity_type].value} | `{entity_type.value}` | {cells} |")

    lines += [
        "",
        "## Authority summary",
        "",
        "| Capability | " + " | ".join(agent.value.title() for agent in ORDER) + " |",
        "| --- | " + " | ".join("---" for _ in ORDER) + " |",
    ]
    rows = (
        ("Max decision state", lambda c: max(c.decision_authority, key=lambda s: s.rank).value),
        ("Max permission level", lambda c: c.max_permission_level.value),
        ("Sensitivity ceiling", lambda c: c.max_sensitivity.value),
        ("Holds veto", lambda c: "yes" if c.holds_veto else "no"),
        ("May execute", lambda c: "yes" if c.max_permission_level.is_executable else "no"),
        ("Writable objects", lambda c: str(len(c.writes))),
        ("Readable objects", lambda c: str(len(c.reads))),
    )
    for label, getter in rows:
        values = " | ".join(getter(AGENT_CONTRACTS[agent]) for agent in ORDER)
        lines.append(f"| {label} | {values} |")

    lines += [
        "",
        "## Invariants this matrix must always satisfy",
        "",
        "- Exactly one `V` column: Guardian, and Guardian writes nothing.",
        "- Exactly one `X` column: the Operator.",
        "- No mind writes an object outside its contract's `writes`.",
        "- The Orchestrator appears nowhere: it owns no object and no domain.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    TARGET.write_text(render(), encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)}")
