from __future__ import annotations

from typing import Annotated

from pydantic import Field

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]

CERTAIN: float = 1.0
"""Reserved for facts the user stated or the system observed deterministically."""

MAX_INFERRED_CONFIDENCE: float = 0.99
"""An inference is never certain; that ceiling keeps the two kinds distinguishable."""

DEFAULT_INFERRED_CONFIDENCE: float = 0.6
