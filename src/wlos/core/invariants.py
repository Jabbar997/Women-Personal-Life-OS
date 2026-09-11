from __future__ import annotations

from wlos.core.errors import ProvenanceError
from wlos.shared.confidence import CERTAIN, DEFAULT_INFERRED_CONFIDENCE, MAX_INFERRED_CONFIDENCE
from wlos.shared.provenance import INFERENTIAL_SOURCES, SourceRef, SourceType

CERTAIN_ONLY_SOURCES: frozenset[SourceType] = frozenset(
    {SourceType.USER_DECLARED, SourceType.USER_ACTION, SourceType.OPERATOR_RESULT}
)
"""What the user said or did, and what the operator actually executed, are facts.

Attaching a probability to "my favourite activity is Pilates" would turn a
declaration into a guess, so the domain refuses it.
"""


def resolve_confidence(source: SourceRef, confidence: float | None) -> float:
    """Pair a claim's confidence with its provenance, or reject the pair."""
    if source.source_type in CERTAIN_ONLY_SOURCES:
        if confidence is not None and confidence != CERTAIN:
            raise ProvenanceError(
                f"{source.source_type} is a declaration, not an inference: "
                f"confidence must be {CERTAIN}, got {confidence}"
            )
        return CERTAIN

    if source.source_type in INFERENTIAL_SOURCES:
        resolved = DEFAULT_INFERRED_CONFIDENCE if confidence is None else confidence
        if resolved > MAX_INFERRED_CONFIDENCE:
            raise ProvenanceError(
                f"{source.source_type} is an inference: confidence must not exceed "
                f"{MAX_INFERRED_CONFIDENCE}, got {resolved}"
            )
        return resolved

    return CERTAIN if confidence is None else confidence
