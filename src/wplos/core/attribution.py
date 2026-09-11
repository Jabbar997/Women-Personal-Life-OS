from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from wplos.core.confidence import Certainty, Confidence
from wplos.core.provenance import SourceRef, SourceType
from wplos.core.sensitivity import SensitivityLevel


class Attribution(BaseModel):
    """Provenance, confidence and sensitivity travel together or not at all.

    Splitting them invites records that know where a fact came from but not how
    far it may travel, which is exactly the failure mode ``Known != Shown`` is
    meant to prevent.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: SourceRef
    confidence: Confidence
    sensitivity: SensitivityLevel

    @model_validator(mode="after")
    def _confidence_matches_source(self) -> Self:
        if self.source.is_inferential and self.confidence.is_certain:
            raise ValueError(
                f"{self.source.source_type} is inferential and requires a probabilistic confidence"
            )
        return self

    @classmethod
    def declared(
        cls,
        captured_at: datetime,
        sensitivity: SensitivityLevel,
        detail: str | None = None,
    ) -> "Attribution":
        return cls(
            source=SourceRef.user_declared(captured_at, detail),
            confidence=Confidence.certain(),
            sensitivity=sensitivity,
        )

    @classmethod
    def inferred(
        cls,
        captured_at: datetime,
        sensitivity: SensitivityLevel,
        value: float,
        source_type: SourceType = SourceType.AI_INFERRED,
        detail: str | None = None,
    ) -> "Attribution":
        return cls(
            source=SourceRef(source_type=source_type, captured_at=captured_at, detail=detail),
            confidence=Confidence.probabilistic(value),
            sensitivity=sensitivity,
        )

    @classmethod
    def observed(
        cls,
        captured_at: datetime,
        sensitivity: SensitivityLevel,
        source_type: SourceType,
        reference: str | None = None,
    ) -> "Attribution":
        return cls(
            source=SourceRef(source_type=source_type, captured_at=captured_at, reference=reference),
            confidence=Confidence.certain(),
            sensitivity=sensitivity,
        )

    @property
    def is_inferred(self) -> bool:
        return self.confidence.certainty is Certainty.PROBABILISTIC
