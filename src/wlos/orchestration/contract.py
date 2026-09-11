from __future__ import annotations

from wlos.core.base import DomainModel


class OrchestratorContract(DomainModel):
    """What the orchestrator is responsible for, stated as data.

    It is not a seventh mind: every responsibility here is coordination, never
    domain judgement.
    """

    responsibilities: tuple[str, ...]
    forbidden: tuple[str, ...]


ORCHESTRATOR_CONTRACT = OrchestratorContract(
    responsibilities=(
        "intent classification",
        "context retrieval",
        "agent selection",
        "ordering",
        "conflict handling",
        "guardian enforcement",
        "priority aggregation",
        "action composition",
        "authorization routing",
        "event emission",
    ),
    forbidden=(
        "owning a business domain of its own",
        "overriding a Guardian verdict",
        "executing external actions directly",
        "exposing the choice of mind to the user",
    ),
)
