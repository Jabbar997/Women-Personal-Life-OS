from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DomainModel(BaseModel):
    """Base for every domain value object.

    Frozen by design: history is never edited in place. A change produces a new
    value plus a new domain event, which is what makes the event log trustworthy.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_default=True,
        use_enum_values=False,
        arbitrary_types_allowed=False,
    )
