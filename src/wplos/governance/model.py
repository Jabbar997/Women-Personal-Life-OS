"""The shapes a governance declaration may take, and what each one must carry.

Every field defined here is read by :mod:`wplos.governance.checks`, which is run
by the architecture suite, which is run by ``./scripts/check.sh``. A field that
nothing reads does not belong in this module.

The vocabulary is deliberately borrowed rather than invented. ``EventSpec`` in
:mod:`wplos.integration.specs` already says that an event without consumers
needs an explicit reviewed reason and that declaring both is a contradiction;
the producer/consumer part of this model says the same thing in the same words,
one layer up, about outputs the kernel's own registry does not cover.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from wplos.governance.phases import Phase


class CapabilityStatus(StrEnum):
    """The only three answers to "is this production capability wanted?".

    There is no fourth state and no ``UNKNOWN``: an unclassified capability is
    a missing answer, which the checks report, not a status anybody may hold.
    """

    REACHABLE = "REACHABLE"
    INTERNAL_ONLY = "INTERNAL_ONLY"
    DELETE = "DELETE"


class GroundingKind(StrEnum):
    """How a ``REACHABLE`` claim is proved against the code.

    ``USED_BY`` is the ordinary case. ``ENTRY_PATH`` is the top of a call stack
    and has nothing above it to name. ``IMPLEMENTS_PORT`` is the one honest way
    a module with no importer at all is still reached: dependency inversion
    means the adapter is never imported by the code that calls it, so the port
    it satisfies is checked instead.
    """

    ENTRY_PATH = "ENTRY_PATH"
    USED_BY = "USED_BY"
    IMPLEMENTS_PORT = "IMPLEMENTS_PORT"


class CriticalConcept(StrEnum):
    """The Phase 01-05 concepts that must have exactly one owner.

    These describe the code that exists. None of them was invented to give the
    registry something to hold.
    """

    PLG_ENTITY_MODEL = "PLG_ENTITY_MODEL"
    GRAPH_MUTATION_PATH = "GRAPH_MUTATION_PATH"
    DURABLE_GRAPH_STORE = "DURABLE_GRAPH_STORE"
    AUTHORIZATION_AUTHORITY = "AUTHORIZATION_AUTHORITY"
    GUARDIAN_AUTHORITY = "GUARDIAN_AUTHORITY"
    RUNTIME_ORCHESTRATION = "RUNTIME_ORCHESTRATION"
    DOMAIN_EVENT_DEFINITION = "DOMAIN_EVENT_DEFINITION"
    DOMAIN_EVENT_PRODUCTION = "DOMAIN_EVENT_PRODUCTION"
    INTEGRATION_EVENT_DEFINITION = "INTEGRATION_EVENT_DEFINITION"
    INTEGRATION_EVENT_PRODUCTION = "INTEGRATION_EVENT_PRODUCTION"
    RUNTIME_ACTION_EXECUTION = "RUNTIME_ACTION_EXECUTION"
    DURABLE_ACTION_EXECUTION = "DURABLE_ACTION_EXECUTION"


def _require_text(value: str, what: str) -> None:
    if not value.strip():
        raise ValueError(f"a governance declaration needs a {what}")


@dataclass(frozen=True, slots=True)
class ReviewerApproval:
    """Who accepted an exemption, and the reviewed document that records it.

    ``citation`` is a repository-relative path and the checks open it. An
    approval that cites nothing readable is the thing this field exists to
    prevent: without it, "approved" is whatever the last author typed.
    """

    reviewer: str
    citation: str
    approved_at: Phase

    def __post_init__(self) -> None:
        _require_text(self.reviewer, "reviewer")
        _require_text(self.citation, "citation")
        if self.citation.startswith("/") or ".." in Path(self.citation).parts:
            raise ValueError(
                "a citation is a repository-relative path to a document in this repository"
            )


@dataclass(frozen=True, slots=True)
class ReviewerExtension:
    """A newly approved deadline, past the one it replaces.

    An extension carries its own approval. Re-approving is a decision someone
    has to make again; editing the original expiry in place would leave no
    trace that anyone did.
    """

    extends_to: Phase
    approval: ReviewerApproval


@dataclass(frozen=True, slots=True)
class InternalOnlyExemption:
    """Everything an ``INTERNAL_ONLY`` classification has to say for itself.

    All five of owner, reason, future consumer, expiry and reviewer approval
    are mandatory arguments, so an exemption missing one cannot be built at
    all, and the blank-string forms are refused here.
    """

    canonical_owner: str
    reason: str
    future_consumer: str
    expires_after: Phase
    reviewer_approval: ReviewerApproval
    extension: ReviewerExtension | None = None

    def __post_init__(self) -> None:
        _require_text(self.canonical_owner, "canonical owner")
        _require_text(self.reason, "reason")
        _require_text(self.future_consumer, "future consumer")
        if self.extension is not None and not self.extension.extends_to.is_after(
            self.expires_after
        ):
            raise ValueError(
                f"an extension to {self.extension.extends_to} does not reach past "
                f"the expiry it extends, {self.expires_after}"
            )

    @property
    def effective_expiry(self) -> Phase:
        return self.expires_after if self.extension is None else self.extension.extends_to

    def is_expired(self, current: Phase) -> bool:
        return current.is_after(self.effective_expiry)


@dataclass(frozen=True, slots=True)
class Grounding:
    """What a ``REACHABLE`` capability points at to prove the claim.

    The references are checked against the import graph the checks derive from
    the source, never against each other, so a ring of modules citing one
    another proves nothing.
    """

    kind: GroundingKind
    references: tuple[str, ...] = ()
    detail: str = ""

    def __post_init__(self) -> None:
        if self.kind is GroundingKind.ENTRY_PATH:
            if self.references:
                raise ValueError("an entry path has nothing above it to reference")
            _require_text(self.detail, "statement of what invokes this entry path")
            return
        if not self.references:
            raise ValueError(f"{self.kind} must name what grounds it")
        if self.kind is GroundingKind.IMPLEMENTS_PORT:
            if len(self.references) != 2:
                raise ValueError("IMPLEMENTS_PORT names the port, then the implementation")
            _require_text(self.detail, "statement of which port this satisfies")


@dataclass(frozen=True, slots=True)
class GovernedCapability:
    """One production module, and the answer to whether it is wanted."""

    module: str
    status: CapabilityStatus
    grounding: Grounding | None = None
    exemption: InternalOnlyExemption | None = None
    finding: str = ""

    def __post_init__(self) -> None:
        _require_text(self.module, "module")
        match self.status:
            case CapabilityStatus.REACHABLE:
                if self.grounding is None:
                    raise ValueError(f"{self.module} is REACHABLE but names no path to it")
                if self.exemption is not None:
                    raise ValueError(f"{self.module} is REACHABLE and needs no exemption")
            case CapabilityStatus.INTERNAL_ONLY:
                if self.exemption is None:
                    raise ValueError(f"{self.module} is INTERNAL_ONLY without an exemption")
                if self.grounding is not None:
                    raise ValueError(
                        f"{self.module} is INTERNAL_ONLY, so it has no production path"
                    )
            case CapabilityStatus.DELETE:
                if self.grounding is not None or self.exemption is not None:
                    raise ValueError(f"{self.module} is DELETE and justifies nothing")
                _require_text(self.finding, "finding explaining the DELETE")


@dataclass(frozen=True, slots=True)
class ConceptOwner:
    """The one place a critical concept lives."""

    concept: CriticalConcept
    owner: str
    detail: str

    def __post_init__(self) -> None:
        _require_text(self.owner, "owner reference")
        _require_text(self.detail, "statement of what the owner owns")


@dataclass(frozen=True, slots=True)
class NoConsumerReason:
    """Why a governed output is allowed to have nothing reading it."""

    reason: str
    approval: ReviewerApproval

    def __post_init__(self) -> None:
        _require_text(self.reason, "reason")


@dataclass(frozen=True, slots=True)
class GovernedOutput:
    """Something the current system produces that outlives the call producing it."""

    name: str
    producer: str
    durable: bool
    detail: str
    no_consumers_by_design: NoConsumerReason | None = None

    def __post_init__(self) -> None:
        _require_text(self.name, "name")
        _require_text(self.producer, "producer reference")
        _require_text(self.detail, "statement of what is produced")


@dataclass(frozen=True, slots=True)
class OutputConsumer:
    """Production code that reads a governed output.

    ``consumer`` resolves inside ``wplos``, which is the whole point: a test
    exercising an output is not a consumer of it, and there is no spelling of a
    test module that this field will accept.
    """

    output: str
    consumer: str
    detail: str

    def __post_init__(self) -> None:
        _require_text(self.output, "output name")
        _require_text(self.consumer, "consumer reference")
        _require_text(self.detail, "statement of what the consumer does with it")


@dataclass(frozen=True)
class GovernanceRegistry:
    """Everything Phase 05G needs to ask its questions, in one object."""

    capabilities: tuple[GovernedCapability, ...]
    concept_owners: tuple[ConceptOwner, ...]
    outputs: tuple[GovernedOutput, ...]
    output_consumers: tuple[OutputConsumer, ...]
