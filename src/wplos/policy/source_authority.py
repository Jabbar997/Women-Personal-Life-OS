from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from wplos.core.attribution import Attribution
from wplos.core.provenance import SourceType
from wplos.core.temporal import ensure_utc
from wplos.policy.decisions import PolicyDecision, ReasonCode, reason

POLICY_NAME = "source.authority"


class SourceAuthority(StrEnum):
    """How much weight a source carries when two of them disagree."""

    USER_EXPLICIT = "USER_EXPLICIT"
    USER_ACTION = "USER_ACTION"
    CONNECTOR = "CONNECTOR"
    DERIVED = "DERIVED"
    INFERRED = "INFERRED"

    @property
    def rank(self) -> int:
        return _RANKS[self]

    def outranks(self, other: "SourceAuthority") -> bool:
        return self.rank > other.rank


_RANKS: dict[SourceAuthority, int] = {
    SourceAuthority.INFERRED: 0,
    SourceAuthority.DERIVED: 1,
    SourceAuthority.CONNECTOR: 2,
    SourceAuthority.USER_ACTION: 3,
    SourceAuthority.USER_EXPLICIT: 4,
}

AUTHORITY_OF: dict[SourceType, SourceAuthority] = {
    SourceType.USER_DECLARED: SourceAuthority.USER_EXPLICIT,
    SourceType.USER_ACTION: SourceAuthority.USER_ACTION,
    SourceType.OPERATOR_RESULT: SourceAuthority.USER_ACTION,
    SourceType.CALENDAR: SourceAuthority.CONNECTOR,
    SourceType.EXTERNAL_CONNECTOR: SourceAuthority.CONNECTOR,
    SourceType.SYSTEM_DERIVED: SourceAuthority.DERIVED,
    SourceType.AI_INFERRED: SourceAuthority.INFERRED,
    SourceType.BEHAVIORAL_INFERENCE: SourceAuthority.INFERRED,
    SourceType.RADAR: SourceAuthority.INFERRED,
}


def authority_of(source_type: SourceType) -> SourceAuthority:
    return AUTHORITY_OF[source_type]


class OverrideRequest(BaseModel):
    """An incoming fact proposing to replace one already held."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    incoming: Attribution
    existing: Attribution
    subject: str


class SourceAuthorityPolicy:
    """Who wins when two sources disagree about the same fact.

    A calendar feed replaying last week's time must not quietly erase the time
    the user confirmed herself. Lower authority never overwrites higher
    authority; it raises a conflict instead, which is a thing the user can be
    asked about rather than a change she never sees.
    """

    name = POLICY_NAME

    def evaluate(self, request: OverrideRequest) -> PolicyDecision:
        incoming = authority_of(request.incoming.source.source_type)
        existing = authority_of(request.existing.source.source_type)

        if incoming.outranks(existing):
            return PolicyDecision.permit(
                POLICY_NAME,
                reason(ReasonCode.ALLOWED, f"{incoming} outranks {existing}"),
            )
        if existing.outranks(incoming):
            return PolicyDecision.deny(
                POLICY_NAME,
                reason(
                    ReasonCode.SOURCE_AUTHORITY_TOO_LOW,
                    f"{incoming} may not overwrite {existing} for {request.subject}",
                ),
            )
        return self._same_authority(request)

    def _same_authority(self, request: OverrideRequest) -> PolicyDecision:
        incoming_at = ensure_utc(request.incoming.source.captured_at)
        existing_at = ensure_utc(request.existing.source.captured_at)
        if incoming_at > existing_at:
            return PolicyDecision.permit(
                POLICY_NAME, reason(ReasonCode.ALLOWED, "same authority, newer observation")
            )
        return PolicyDecision.deny(
            POLICY_NAME,
            reason(
                ReasonCode.SOURCE_STALE,
                f"observation from {incoming_at.isoformat()} is older than the one held",
            ),
        )

    def would_conflict(self, request: OverrideRequest) -> bool:
        """A refusal is a conflict to surface, not an error to swallow."""
        return not self.evaluate(request).is_permitted


DEFAULT_SOURCE_AUTHORITY_POLICY = SourceAuthorityPolicy()


def freshness_seconds(attribution: Attribution, at: datetime) -> float:
    return (ensure_utc(at) - ensure_utc(attribution.source.captured_at)).total_seconds()
