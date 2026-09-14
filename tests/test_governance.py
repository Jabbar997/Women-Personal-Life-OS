"""Phase 00A: the governance mechanism, tested by trying to get past it.

Every test here attacks the checks rather than the data. A registry that
happens to be valid today proves nothing about whether an invalid one would be
caught tomorrow, so each case takes the canonical registry, breaks exactly one
thing, and asserts that the break is what comes back.
"""

import ast
import re
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from wplos.governance.checks import (
    ProductionSurface,
    derive_reachable,
    init_files_are_re_exports_only,
    production_surface,
    validate,
)
from wplos.governance.model import (
    CapabilityStatus,
    ConceptOwner,
    CriticalConcept,
    GovernanceRegistry,
    GovernedCapability,
    GovernedOutput,
    Grounding,
    GroundingKind,
    InternalOnlyExemption,
    NoConsumerReason,
    OutputConsumer,
    ReviewerApproval,
    ReviewerExtension,
)
from wplos.governance.phases import CURRENT_PHASE, Phase
from wplos.governance.registry import CANONICAL_REGISTRY

PROJECT_ROOT = Path(__file__).resolve().parents[1]
THIS_FILE = Path(__file__).resolve()

APPROVAL = ReviewerApproval(
    reviewer="test reviewer", citation="AGENTS.md", approved_at=Phase.PHASE_05
)


def _registry(
    *,
    capabilities=None,
    concept_owners=None,
    outputs=None,
    output_consumers=None,
) -> GovernanceRegistry:
    return GovernanceRegistry(
        capabilities=(
            CANONICAL_REGISTRY.capabilities if capabilities is None else tuple(capabilities)
        ),
        concept_owners=(
            CANONICAL_REGISTRY.concept_owners if concept_owners is None else tuple(concept_owners)
        ),
        outputs=CANONICAL_REGISTRY.outputs if outputs is None else tuple(outputs),
        output_consumers=(
            CANONICAL_REGISTRY.output_consumers
            if output_consumers is None
            else tuple(output_consumers)
        ),
    )


def _without(module: str) -> tuple[GovernedCapability, ...]:
    return tuple(item for item in CANONICAL_REGISTRY.capabilities if item.module != module)


def _instead_of(module: str, capability: GovernedCapability) -> tuple[GovernedCapability, ...]:
    return (*_without(module), capability)


def _capability(module: str) -> GovernedCapability:
    return next(item for item in CANONICAL_REGISTRY.capabilities if item.module == module)


def _exemption(**overrides: object) -> InternalOnlyExemption:
    base = _capability("wplos.events.bus").exemption
    assert base is not None
    return replace(base, **overrides)


# --- T7: the accepted state ------------------------------------------------


def test_the_canonical_governance_registry_is_valid():
    assert validate(CANONICAL_REGISTRY) == ()


def test_every_production_module_carries_exactly_one_classification():
    surface = production_surface()
    classified = [item.module for item in CANONICAL_REGISTRY.capabilities]

    assert sorted(classified) == sorted(set(classified))
    assert set(classified) == set(surface.modules)


def test_only_three_statuses_exist():
    assert [status.value for status in CapabilityStatus] == [
        "REACHABLE",
        "INTERNAL_ONLY",
        "DELETE",
    ]


def test_the_current_phase_constant_matches_the_phase_the_brief_declares():
    brief = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    declared = re.search(r"\*\*Phase (\d{2}) —", brief)

    assert declared is not None
    assert CURRENT_PHASE is Phase(f"PHASE_{declared.group(1)}")


def test_package_init_files_stay_re_export_surface():
    """The inventory leaves them out, so they may not hold capability."""
    assert init_files_are_re_exports_only() == ()


# --- T1: an unclassified capability ----------------------------------------


def test_a_production_module_with_no_classification_fails():
    violations = validate(_registry(capabilities=_without("wplos.core.money")))

    assert violations == ("wplos.core.money is production capability with no classification",)


def test_a_classification_for_a_module_that_does_not_exist_fails():
    stray = GovernedCapability(
        module="wplos.core.invented",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(kind=GroundingKind.USED_BY, references=("wplos.core.money",)),
    )
    violations = validate(_registry(capabilities=(*CANONICAL_REGISTRY.capabilities, stray)))

    assert violations == ("wplos.core.invented is classified but is not a production module",)


def test_classifying_one_module_twice_fails():
    duplicate = _capability("wplos.core.money")
    violations = validate(_registry(capabilities=(*CANONICAL_REGISTRY.capabilities, duplicate)))

    assert violations == ("wplos.core.money is classified twice",)


# --- T2: an invalid INTERNAL_ONLY ------------------------------------------


@pytest.mark.parametrize(
    "missing",
    ["canonical_owner", "reason", "future_consumer", "expires_after", "reviewer_approval"],
)
def test_an_exemption_missing_any_required_field_cannot_be_built(missing):
    complete = {
        "canonical_owner": "wplos.events.envelope",
        "reason": "a reason",
        "future_consumer": "a future consumer",
        "expires_after": Phase.PHASE_06,
        "reviewer_approval": APPROVAL,
    }
    del complete[missing]

    with pytest.raises(TypeError):
        InternalOnlyExemption(**complete)


@pytest.mark.parametrize("blank", ["canonical_owner", "reason", "future_consumer"])
def test_an_exemption_with_a_blank_required_field_is_refused(blank):
    with pytest.raises(ValueError):
        _exemption(**{blank: "   "})


def test_an_internal_only_capability_without_an_exemption_is_refused():
    with pytest.raises(ValueError):
        GovernedCapability(module="wplos.events.bus", status=CapabilityStatus.INTERNAL_ONLY)


def test_a_reviewer_approval_needs_a_reviewer_and_a_citation():
    with pytest.raises(ValueError):
        ReviewerApproval(reviewer=" ", citation="AGENTS.md", approved_at=Phase.PHASE_05)
    with pytest.raises(ValueError):
        ReviewerApproval(reviewer="someone", citation="", approved_at=Phase.PHASE_05)


def test_an_approval_citing_a_document_that_is_not_in_the_repository_fails():
    forged = ReviewerApproval(
        reviewer="test reviewer",
        citation="docs/approvals/trust-me.md",
        approved_at=Phase.PHASE_05,
    )
    broken = GovernedCapability(
        module="wplos.events.bus",
        status=CapabilityStatus.INTERNAL_ONLY,
        exemption=_exemption(reviewer_approval=forged),
    )
    violations = validate(_registry(capabilities=_instead_of("wplos.events.bus", broken)))

    assert violations == (
        "wplos.events.bus: reviewer approval cites docs/approvals/trust-me.md, "
        "which is not in the repository",
    )


def test_an_exemption_whose_canonical_owner_is_not_governed_fails():
    broken = GovernedCapability(
        module="wplos.events.bus",
        status=CapabilityStatus.INTERNAL_ONLY,
        exemption=_exemption(canonical_owner="wplos.some.other.system"),
    )
    violations = validate(_registry(capabilities=_instead_of("wplos.events.bus", broken)))

    assert violations == (
        "wplos.events.bus: canonical owner wplos.some.other.system is not a governed "
        "production module",
    )


def test_an_exemption_for_a_capability_production_actually_reaches_is_stale():
    """INTERNAL_ONLY is a claim about the code, and the code gets the last word."""
    broken = GovernedCapability(
        module="wplos.core.money",
        status=CapabilityStatus.INTERNAL_ONLY,
        exemption=_exemption(canonical_owner="wplos.core.money"),
    )
    violations = validate(_registry(capabilities=_instead_of("wplos.core.money", broken)))

    assert violations == (
        "wplos.core.money is declared INTERNAL_ONLY but production code reaches it; "
        "the exemption is stale",
    )


# --- T3: an expired INTERNAL_ONLY ------------------------------------------


def test_an_expired_exemption_fails_on_its_own():
    expired = [
        item
        for item in validate(CANONICAL_REGISTRY, current_phase=Phase.PHASE_07)
        if "expired" in item
    ]

    assert len(expired) == len(
        [
            item
            for item in CANONICAL_REGISTRY.capabilities
            if item.status is CapabilityStatus.INTERNAL_ONLY
        ]
    )
    assert validate(CANONICAL_REGISTRY, current_phase=Phase.PHASE_06) == ()


def test_a_newly_approved_extension_carries_an_exemption_past_its_expiry():
    extended = GovernedCapability(
        module="wplos.events.bus",
        status=CapabilityStatus.INTERNAL_ONLY,
        exemption=_exemption(
            extension=ReviewerExtension(extends_to=Phase.PHASE_07, approval=APPROVAL)
        ),
    )
    registry = _registry(capabilities=_instead_of("wplos.events.bus", extended))

    still_expired = [
        item for item in validate(registry, current_phase=Phase.PHASE_07) if "expired" in item
    ]
    assert not any("wplos.events.bus" in item for item in still_expired)

    expired_again = [
        item for item in validate(registry, current_phase=Phase.PHASE_08) if "expired" in item
    ]
    assert any("wplos.events.bus" in item for item in expired_again)


def test_an_extension_that_does_not_reach_past_the_expiry_is_not_an_extension():
    with pytest.raises(ValueError):
        _exemption(
            expires_after=Phase.PHASE_06,
            extension=ReviewerExtension(extends_to=Phase.PHASE_06, approval=APPROVAL),
        )


# --- T4: conflicting canonical ownership -----------------------------------


def test_two_canonical_owners_for_one_concept_fail():
    rival = ConceptOwner(
        concept=CriticalConcept.GRAPH_MUTATION_PATH,
        owner="wplos.integration.graph_store:SQLiteGraphStore",
        detail="a second claim on the one mutation path",
    )
    violations = validate(_registry(concept_owners=(*CANONICAL_REGISTRY.concept_owners, rival)))

    assert violations == (
        "GRAPH_MUTATION_PATH declares two canonical owners: "
        "wplos.application.graph_write_service:GraphWriteService and "
        "wplos.integration.graph_store:SQLiteGraphStore",
    )


def test_a_critical_concept_with_no_owner_fails():
    thinned = [
        item
        for item in CANONICAL_REGISTRY.concept_owners
        if item.concept is not CriticalConcept.GUARDIAN_AUTHORITY
    ]
    violations = validate(_registry(concept_owners=thinned))

    assert violations == ("GUARDIAN_AUTHORITY has no canonical owner",)


def test_an_owner_that_does_not_resolve_fails():
    ghost = ConceptOwner(
        concept=CriticalConcept.GUARDIAN_AUTHORITY,
        owner="wplos.policy.guardian_authority:NoSuchAuthority",
        detail="names a symbol that is not there",
    )
    thinned = [
        item
        for item in CANONICAL_REGISTRY.concept_owners
        if item.concept is not CriticalConcept.GUARDIAN_AUTHORITY
    ]
    violations = validate(_registry(concept_owners=[*thinned, ghost]))

    assert len(violations) == 1
    assert violations[0].startswith(
        "GUARDIAN_AUTHORITY: wplos.policy.guardian_authority:NoSuchAuthority does not resolve"
    )


# --- T5: a consumer with no producer ---------------------------------------


def test_a_consumer_of_an_output_nothing_produces_fails():
    orphan = OutputConsumer(
        output="today.projection",
        consumer="wplos.application.orchestrator:OrchestratorRuntime",
        detail="reads a projection that no producer in this phase writes",
    )
    violations = validate(
        _registry(output_consumers=(*CANONICAL_REGISTRY.output_consumers, orphan))
    )

    assert violations == (
        "wplos.application.orchestrator:OrchestratorRuntime consumes today.projection, "
        "which no producer produces",
    )


def test_a_test_module_is_not_a_production_consumer():
    pretend = OutputConsumer(
        output="runtime.result",
        consumer="tests.test_runtime_e2e:test_a_run_completes",
        detail="a test exercising the output is not a consumer of it",
    )
    violations = validate(
        _registry(output_consumers=(*CANONICAL_REGISTRY.output_consumers, pretend))
    )

    assert violations == (
        "consumer of runtime.result: tests.test_runtime_e2e:test_a_run_completes is not "
        "production code in wplos",
    )


# --- T6: a producer with no consumer and no reason -------------------------


def test_a_durable_producer_with_no_consumer_and_no_reason_fails():
    unexplained = GovernedOutput(
        name="graph.relationship_version",
        producer="wplos.integration.graph_store:SQLiteGraphStore.commit",
        durable=True,
        detail="a durable output nobody reads and nobody explained",
    )
    violations = validate(_registry(outputs=(*CANONICAL_REGISTRY.outputs, unexplained)))

    assert violations == (
        "graph.relationship_version is produced by "
        "wplos.integration.graph_store:SQLiteGraphStore.commit and nothing consumes it; "
        "a no-consumer case needs an explicitly approved reason",
    )


def test_stripping_the_approved_reason_from_a_consumerless_output_fails():
    bare = replace(
        next(item for item in CANONICAL_REGISTRY.outputs if item.name == "graph.domain_event"),
        no_consumers_by_design=None,
    )
    others = [item for item in CANONICAL_REGISTRY.outputs if item.name != "graph.domain_event"]
    violations = validate(_registry(outputs=[*others, bare]))

    assert len(violations) == 1
    assert violations[0].startswith("graph.domain_event is produced by")


def test_an_output_cannot_both_declare_consumers_and_declare_none_by_design():
    contradiction = OutputConsumer(
        output="graph.domain_event",
        consumer="wplos.application.orchestrator:OrchestratorRuntime",
        detail="a consumer for an output that says it has none",
    )
    violations = validate(
        _registry(output_consumers=(*CANONICAL_REGISTRY.output_consumers, contradiction))
    )

    assert violations == (
        "graph.domain_event declares consumers "
        "['wplos.application.orchestrator:OrchestratorRuntime'] and also declares none "
        "by design",
    )


def test_an_unapproved_no_consumer_reason_fails():
    forged = replace(
        next(item for item in CANONICAL_REGISTRY.outputs if item.name == "graph.run_record"),
        no_consumers_by_design=NoConsumerReason(
            reason="nobody needs it",
            approval=ReviewerApproval(
                reviewer="test reviewer",
                citation="docs/approvals/none.md",
                approved_at=Phase.PHASE_05,
            ),
        ),
    )
    others = [item for item in CANONICAL_REGISTRY.outputs if item.name != "graph.run_record"]
    violations = validate(_registry(outputs=[*others, forged]))

    assert violations == (
        "graph.run_record: reviewer approval cites docs/approvals/none.md, which is not "
        "in the repository",
    )


# --- reachability may not be faked -----------------------------------------


def test_delete_is_never_an_accepted_production_capability():
    condemned = GovernedCapability(
        module="wplos.policy.source_authority",
        status=CapabilityStatus.DELETE,
        finding="nothing consults it",
    )
    violations = validate(
        _registry(capabilities=_instead_of("wplos.policy.source_authority", condemned))
    )

    assert violations == (
        "wplos.policy.source_authority is classified DELETE: it is not accepted "
        "production capability. Remove it or reclassify it. Finding: nothing consults it",
    )


def test_a_ring_of_modules_citing_each_other_reaches_nothing():
    """Two internal functions referring to one another is not a production path."""
    surface = ProductionSurface(
        modules=frozenset({"wplos.core.money", "wplos.core.confidence"}),
        imports={
            "wplos.core.money": frozenset({"wplos.core.confidence"}),
            "wplos.core.confidence": frozenset({"wplos.core.money"}),
        },
    )
    registry = _registry(
        capabilities=[
            GovernedCapability(
                module="wplos.core.money",
                status=CapabilityStatus.REACHABLE,
                grounding=Grounding(
                    kind=GroundingKind.USED_BY, references=("wplos.core.confidence",)
                ),
            ),
            GovernedCapability(
                module="wplos.core.confidence",
                status=CapabilityStatus.REACHABLE,
                grounding=Grounding(kind=GroundingKind.USED_BY, references=("wplos.core.money",)),
            ),
        ]
    )
    violations = validate(registry, surface=surface)

    assert derive_reachable(registry, surface) == frozenset()
    assert (
        "wplos.core.money is declared REACHABLE but no path from a declared entry path "
        "reaches it" in violations
    )


def test_naming_a_caller_that_does_not_call_fails():
    lying = GovernedCapability(
        module="wplos.core.money",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(kind=GroundingKind.USED_BY, references=("wplos.core.roles",)),
    )
    violations = validate(_registry(capabilities=_instead_of("wplos.core.money", lying)))

    assert violations == (
        "wplos.core.money names wplos.core.roles as a caller, but wplos.core.roles does "
        "not import it",
        "wplos.core.money names no caller that is itself reached from an entry path",
    )


def test_claiming_a_port_a_module_does_not_implement_fails():
    pretend = GovernedCapability(
        module="wplos.policy.source_authority",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.IMPLEMENTS_PORT,
            references=(
                "wplos.application.graph_write:GraphWriteStore",
                "wplos.policy.source_authority:SourceAuthorityPolicy",
            ),
            detail="claims a port it has none of the methods of",
        ),
    )
    violations = validate(
        _registry(capabilities=_instead_of("wplos.policy.source_authority", pretend))
    )

    assert any("does not implement" in item for item in violations)
    assert any("no path from a declared entry path reaches it" in item for item in violations)


def test_an_entry_path_must_say_what_invokes_it():
    with pytest.raises(ValueError):
        Grounding(kind=GroundingKind.ENTRY_PATH)


# --- T8: the checks are in the canonical quality gate ----------------------


def _calls_validate_on_the_canonical_registry(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "validate" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Name) and first.id == "CANONICAL_REGISTRY":
            return True
    return False


def test_the_canonical_check_script_runs_these_governance_tests():
    """check.sh -> pytest -> testpaths -> this module -> validate(CANONICAL_REGISTRY)."""
    check = (PROJECT_ROOT / "scripts" / "check.sh").read_text(encoding="utf-8")
    manifest = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    testpaths = manifest["tool"]["pytest"]["ini_options"]["testpaths"]

    assert "pytest" in check
    assert THIS_FILE.parent.name in testpaths
    assert _calls_validate_on_the_canonical_registry(THIS_FILE)


def test_continuous_integration_runs_the_same_suite():
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "pytest" in workflow


def test_an_entry_path_that_something_imports_is_not_an_entry_path():
    """Otherwise any leaf could be declared a root and launder its whole subtree."""
    laundered = GovernedCapability(
        module="wplos.core.money",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.ENTRY_PATH,
            detail="claims to be entered directly, while the runtime imports it",
        ),
    )
    violations = validate(_registry(capabilities=_instead_of("wplos.core.money", laundered)))
    importers = sorted(production_surface().importers_of("wplos.core.money"))

    assert importers
    assert violations == (
        f"wplos.core.money is declared an entry path, but {importers} import it, so it "
        "is not the top of anything; declare what reaches it instead",
    )


def test_the_governance_package_imports_nothing_from_the_system_it_describes():
    """It is left out of the inventory, so it must not be able to hold capability.

    A module parked under ``wplos/governance`` escapes the reachability closure by
    construction. It cannot become smuggled production code while it is forbidden
    both to import the system and, by the architecture suite, to be imported by it.
    """
    package = Path(production_surface.__module__.replace(".", "/")).parent
    root = PROJECT_ROOT / "src" / package

    reaching_out: list[str] = []
    for module in sorted(root.rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported = ""
            if isinstance(node, ast.ImportFrom) and node.module:
                imported = node.module
            elif isinstance(node, ast.Import):
                imported = node.names[0].name
            if imported.startswith("wplos.") and not imported.startswith("wplos.governance"):
                reaching_out.append(f"{module.relative_to(PROJECT_ROOT)} imports {imported}")

    assert not reaching_out, reaching_out


@pytest.mark.parametrize("citation", ["/etc/passwd", "../../../etc/passwd", "docs/../AGENTS.md"])
def test_an_approval_cannot_cite_its_way_out_of_the_repository(citation):
    with pytest.raises(ValueError):
        ReviewerApproval(reviewer="test reviewer", citation=citation, approved_at=Phase.PHASE_05)


def test_an_approval_citing_a_directory_rather_than_a_document_fails():
    vague = GovernedCapability(
        module="wplos.events.bus",
        status=CapabilityStatus.INTERNAL_ONLY,
        exemption=_exemption(
            reviewer_approval=ReviewerApproval(
                reviewer="test reviewer", citation="docs", approved_at=Phase.PHASE_05
            )
        ),
    )
    violations = validate(_registry(capabilities=_instead_of("wplos.events.bus", vague)))

    assert violations == (
        "wplos.events.bus: reviewer approval cites docs, which is not in the repository",
    )
