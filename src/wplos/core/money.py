from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

from wplos.shared.errors import InvariantViolation
from wplos.shared.json import JsonValue


class Money(BaseModel):
    """An amount in minor units. Never a float: money is counted, not measured.

    The same primitive serves a Radar price, a purchase, a refund, an entry fee
    and an Operator material term, so a price can be compared and consented to
    rather than parsed out of a headline.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    amount_minor: int
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")

    @field_validator("currency")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()

    @classmethod
    def of(cls, amount_minor: int, currency: str) -> "Money":
        return cls(amount_minor=amount_minor, currency=currency.upper())

    @classmethod
    def zero(cls, currency: str) -> "Money":
        return cls(amount_minor=0, currency=currency.upper())

    def _same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise InvariantViolation(
                f"cannot combine {self.currency} with {other.currency}; convert explicitly"
            )

    def __add__(self, other: "Money") -> Self:
        self._same_currency(other)
        return type(self)(
            amount_minor=self.amount_minor + other.amount_minor, currency=self.currency
        )

    def __sub__(self, other: "Money") -> Self:
        self._same_currency(other)
        return type(self)(
            amount_minor=self.amount_minor - other.amount_minor, currency=self.currency
        )

    def exceeds(self, other: "Money") -> bool:
        self._same_currency(other)
        return self.amount_minor > other.amount_minor

    @property
    def is_zero(self) -> bool:
        return self.amount_minor == 0

    def as_terms(self) -> dict[str, JsonValue]:
        """The shape money takes inside an action's material terms."""
        return {"amount_minor": self.amount_minor, "currency": self.currency}
