from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Certainty(StrEnum):
    """Whether a fact carries a probability at all.

    A declaration ("my favourite activity is Pilates") is CERTAIN: attaching a
    probability to it would be noise dressed up as rigour. Only inferred facts
    are PROBABILISTIC.
    """

    CERTAIN = "CERTAIN"
    PROBABILISTIC = "PROBABILISTIC"


class Confidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    certainty: Certainty
    value: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _value_matches_certainty(self) -> Self:
        if self.certainty is Certainty.CERTAIN and self.value is not None:
            raise ValueError("a CERTAIN fact must not carry a probability value")
        if self.certainty is Certainty.PROBABILISTIC and self.value is None:
            raise ValueError("a PROBABILISTIC fact must carry a value in [0.0, 1.0]")
        return self

    @classmethod
    def certain(cls) -> "Confidence":
        return cls(certainty=Certainty.CERTAIN, value=None)

    @classmethod
    def probabilistic(cls, value: float) -> "Confidence":
        return cls(certainty=Certainty.PROBABILISTIC, value=value)

    @property
    def is_certain(self) -> bool:
        return self.certainty is Certainty.CERTAIN

    @property
    def score(self) -> float:
        """A comparable scalar; certainty scores 1.0 without pretending to be a probability."""
        return 1.0 if self.value is None else self.value

    def at_least(self, threshold: float) -> bool:
        return self.score >= threshold
