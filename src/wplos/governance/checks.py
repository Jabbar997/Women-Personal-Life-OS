"""The executable consumer of everything declared in :mod:`wplos.governance`.

Nothing here trusts a declaration. The import graph is derived from the source
first, and the registry is then compared against it: a capability may claim to
be reached only if the code agrees, and a capability that claims to be internal
may not turn out to be wired in after all. Both directions matter, because a
stale exemption is how an audit quietly stops being true.

Reachability here means a real path through the architecture as it stands, from
a declared entry path to the module. Being importable is not reachability, and
neither is being mentioned by another module that nothing reaches; a ring of
modules citing one another is grounded in nothing and is derived as such.
"""

import ast
import importlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from wplos.governance.model import (
    CapabilityStatus,
    CriticalConcept,
    GovernanceRegistry,
    GovernedCapability,
    GroundingKind,
    ReviewerApproval,
)
from wplos.governance.phases import CURRENT_PHASE, Phase

SOURCE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
GOVERNANCE_PACKAGE = "wplos.governance"

_ALLOWED_INIT_ASSIGNMENTS = frozenset({"__all__", "__version__"})


@dataclass(frozen=True, eq=False)
class ProductionSurface:
    """The production modules and how they actually use one another.

    Package ``__init__`` files are not modules in this sense. They re-export and
    nothing else — :func:`init_files_are_re_exports_only` is what makes that
    claim checkable rather than assumed — so counting them as importers would
    make every module in the package look used by the package itself, which is
    the cheapest possible way to fake reachability.

    The governance package is excluded too. It describes production code; it is
    not production code, and governing itself would be circular.
    """

    modules: frozenset[str]
    imports: Mapping[str, frozenset[str]]

    def importers_of(self, module: str) -> frozenset[str]:
        return frozenset(name for name, used in self.imports.items() if module in used)


def _module_name(path: Path, source_root: Path) -> str:
    return ".".join(path.relative_to(source_root.parent).with_suffix("").parts)


def _wplos_imports(path: Path) -> frozenset[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("wplos."):
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if alias.name.startswith("wplos."))
    return frozenset(found)


def production_surface(source_root: Path = SOURCE_ROOT) -> ProductionSurface:
    paths = [
        path
        for path in sorted(source_root.rglob("*.py"))
        if path.name != "__init__.py"
        and not _module_name(path, source_root).startswith(f"{GOVERNANCE_PACKAGE}.")
    ]
    modules = frozenset(_module_name(path, source_root) for path in paths)
    imports = {
        _module_name(path, source_root): frozenset(_wplos_imports(path) & modules) for path in paths
    }
    return ProductionSurface(modules=modules, imports=imports)


def init_files_are_re_exports_only(source_root: Path = SOURCE_ROOT) -> tuple[str, ...]:
    """Every ``__init__.py`` holds a docstring, imports and ``__all__``, nothing else.

    This is the price of leaving them out of the inventory. The moment one of
    them defines something, it stops being a re-export surface and starts being
    production capability that nobody classified.
    """
    offenders: list[str] = []
    for path in sorted(source_root.rglob("__init__.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Import | ast.ImportFrom):
                continue
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else []
            names = {target.id for target in targets if isinstance(target, ast.Name)}
            if names and names <= _ALLOWED_INIT_ASSIGNMENTS:
                continue
            offenders.append(
                f"{path.relative_to(source_root.parent)} line {node.lineno} defines "
                f"{type(node).__name__}; a package __init__ re-exports and nothing else"
            )
    return tuple(offenders)


def _resolve(reference: str) -> object:
    """Import a ``module:Symbol`` reference and return what it names."""
    module_name, separator, attribute_path = reference.partition(":")
    if not separator or not attribute_path:
        raise ValueError(f"{reference} is not a module:Symbol reference")
    target: object = importlib.import_module(module_name)
    for part in attribute_path.split("."):
        target = getattr(target, part)
    return target


def _reference_module(reference: str) -> str:
    return reference.partition(":")[0]


def _unresolved(reference: str) -> str | None:
    try:
        _resolve(reference)
    except (ImportError, AttributeError, ValueError) as error:
        return f"{reference} does not resolve ({error})"
    return None


def _port_members(port: object) -> frozenset[str]:
    return frozenset(
        name for name, value in vars(port).items() if not name.startswith("_") and callable(value)
    )


def _implements_port(port_reference: str, implementation_reference: str) -> tuple[str, ...]:
    port = _resolve(port_reference)
    implementation = _resolve(implementation_reference)
    members = _port_members(port)
    if not members:
        return (f"{port_reference} declares no members, so implementing it proves nothing",)
    missing = sorted(name for name in members if not hasattr(implementation, name))
    if missing:
        return (
            f"{implementation_reference} does not implement {port_reference}: missing {missing}",
        )
    return ()


def derive_reachable(registry: GovernanceRegistry, surface: ProductionSurface) -> frozenset[str]:
    """What is genuinely reached, computed from the code rather than the claims.

    Entry paths seed the closure. A port implementation joins it only once the
    port it satisfies is itself reached, which is why this runs to a fixpoint
    instead of in one pass.
    """
    seeds = {
        capability.module
        for capability in registry.capabilities
        if capability.grounding is not None
        and capability.grounding.kind is GroundingKind.ENTRY_PATH
        and capability.module in surface.modules
    }
    adapters = tuple(
        capability
        for capability in registry.capabilities
        if capability.grounding is not None
        and capability.grounding.kind is GroundingKind.IMPLEMENTS_PORT
        and capability.module in surface.modules
    )
    reached = _closure(seeds, surface)
    while True:
        joined = {
            capability.module
            for capability in adapters
            if capability.module not in reached and _adapter_is_wired(capability, reached)
        }
        if not joined:
            return reached
        reached = _closure(reached | joined, surface)


def _adapter_is_wired(capability: GovernedCapability, reached: frozenset[str]) -> bool:
    grounding = capability.grounding
    if grounding is None or len(grounding.references) != 2:
        return False
    port_reference, implementation_reference = grounding.references
    if _reference_module(port_reference) not in reached:
        return False
    if _reference_module(implementation_reference) != capability.module:
        return False
    try:
        return not _implements_port(port_reference, implementation_reference)
    except (ImportError, AttributeError, ValueError):
        return False


def _closure(seeds: Iterable[str], surface: ProductionSurface) -> frozenset[str]:
    reached: set[str] = set()
    pending = list(seeds)
    while pending:
        module = pending.pop()
        if module in reached:
            continue
        reached.add(module)
        pending.extend(surface.imports.get(module, frozenset()))
    return frozenset(reached)


def _citation_violation(approval: ReviewerApproval, where: str, repo_root: Path) -> str | None:
    if not (repo_root / approval.citation).is_file():
        return (
            f"{where}: reviewer approval cites {approval.citation}, which is not in the repository"
        )
    return None


def _capability_violations(
    registry: GovernanceRegistry,
    surface: ProductionSurface,
    reached: frozenset[str],
    current_phase: Phase,
    repo_root: Path,
) -> list[str]:
    violations: list[str] = []
    declared: dict[str, GovernedCapability] = {}
    for capability in registry.capabilities:
        if capability.module in declared:
            violations.append(f"{capability.module} is classified twice")
            continue
        declared[capability.module] = capability
        if capability.module not in surface.modules:
            violations.append(f"{capability.module} is classified but is not a production module")

    for module in sorted(surface.modules - set(declared)):
        violations.append(f"{module} is production capability with no classification")

    for capability in registry.capabilities:
        if capability.module not in surface.modules:
            continue
        violations.extend(
            _one_capability(capability, surface, reached, current_phase, repo_root, declared)
        )
    return violations


def _one_capability(
    capability: GovernedCapability,
    surface: ProductionSurface,
    reached: frozenset[str],
    current_phase: Phase,
    repo_root: Path,
    declared: Mapping[str, GovernedCapability],
) -> list[str]:
    module = capability.module
    violations: list[str] = []
    match capability.status:
        case CapabilityStatus.REACHABLE:
            if module not in reached:
                violations.append(
                    f"{module} is declared REACHABLE but no path from a declared entry "
                    "path reaches it"
                )
            violations.extend(_grounding_violations(capability, surface, reached))
        case CapabilityStatus.INTERNAL_ONLY:
            exemption = capability.exemption
            if exemption is None:
                return [f"{module} is INTERNAL_ONLY without an exemption"]
            if module in reached:
                violations.append(
                    f"{module} is declared INTERNAL_ONLY but production code reaches it; "
                    "the exemption is stale"
                )
            owner = exemption.canonical_owner
            if owner not in declared:
                violations.append(
                    f"{module}: canonical owner {owner} is not a governed production module"
                )
            elif declared[owner].status is CapabilityStatus.DELETE:
                violations.append(f"{module}: canonical owner {owner} is classified DELETE")
            citation = _citation_violation(exemption.reviewer_approval, module, repo_root)
            if citation is not None:
                violations.append(citation)
            if exemption.extension is not None:
                extended = _citation_violation(
                    exemption.extension.approval, f"{module} extension", repo_root
                )
                if extended is not None:
                    violations.append(extended)
            if exemption.is_expired(current_phase) and module not in reached:
                violations.append(
                    f"{module}: INTERNAL_ONLY exemption expired after "
                    f"{exemption.effective_expiry}, the phase is {current_phase}, the "
                    "capability is still not REACHABLE and no newer reviewer extension "
                    "was approved"
                )
        case CapabilityStatus.DELETE:
            violations.append(
                f"{module} is classified DELETE: it is not accepted production capability. "
                f"Remove it or reclassify it. Finding: {capability.finding}"
            )
            if module in reached:
                violations.append(
                    f"{module} is classified DELETE but production code still reaches it"
                )
    return violations


def _grounding_violations(
    capability: GovernedCapability, surface: ProductionSurface, reached: frozenset[str]
) -> list[str]:
    grounding = capability.grounding
    if grounding is None:
        return [f"{capability.module} is REACHABLE but names no path to it"]
    module = capability.module
    match grounding.kind:
        case GroundingKind.ENTRY_PATH:
            above = sorted(surface.importers_of(module))
            if above:
                return [
                    f"{module} is declared an entry path, but {above} import it, so "
                    "it is not the top of anything; declare what reaches it instead"
                ]
            return []
        case GroundingKind.USED_BY:
            violations: list[str] = []
            importers = surface.importers_of(module)
            for reference in grounding.references:
                if reference not in importers:
                    violations.append(
                        f"{module} names {reference} as a caller, but {reference} does "
                        "not import it"
                    )
            grounded = [
                reference
                for reference in grounding.references
                if reference in importers and reference in reached
            ]
            if not grounded:
                violations.append(
                    f"{module} names no caller that is itself reached from an entry path"
                )
            return violations
        case GroundingKind.IMPLEMENTS_PORT:
            port_reference, implementation_reference = grounding.references
            unresolved = [
                problem
                for problem in (
                    _unresolved(port_reference),
                    _unresolved(implementation_reference),
                )
                if problem is not None
            ]
            if unresolved:
                return [f"{module}: {problem}" for problem in unresolved]
            if _reference_module(implementation_reference) != module:
                return [
                    f"{module} claims to implement {port_reference} through "
                    f"{implementation_reference}, which lives somewhere else"
                ]
            if _reference_module(port_reference) not in reached:
                return [
                    f"{module} implements {port_reference}, but nothing reaches the port "
                    "either, so implementing it reaches nothing"
                ]
            return [
                f"{module}: {problem}"
                for problem in _implements_port(port_reference, implementation_reference)
            ]


def _ownership_violations(
    registry: GovernanceRegistry, declared: Mapping[str, GovernedCapability]
) -> list[str]:
    violations: list[str] = []
    owners: dict[CriticalConcept, str] = {}
    for record in registry.concept_owners:
        existing = owners.get(record.concept)
        if existing is not None:
            violations.append(
                f"{record.concept} declares two canonical owners: {existing} and {record.owner}"
            )
            continue
        owners[record.concept] = record.owner
        unresolved = _unresolved(record.owner)
        if unresolved is not None:
            violations.append(f"{record.concept}: {unresolved}")
            continue
        module = _reference_module(record.owner)
        if module not in declared:
            violations.append(
                f"{record.concept}: owner {record.owner} is not a governed production module"
            )
        elif declared[module].status is CapabilityStatus.DELETE:
            violations.append(f"{record.concept}: owner {record.owner} is classified DELETE")

    for concept in CriticalConcept:
        if concept not in owners:
            violations.append(f"{concept} has no canonical owner")
    return violations


def _producer_consumer_violations(
    registry: GovernanceRegistry,
    declared: Mapping[str, GovernedCapability],
    repo_root: Path,
) -> list[str]:
    violations: list[str] = []
    outputs: dict[str, str] = {}
    for output in registry.outputs:
        if output.name in outputs:
            violations.append(f"{output.name} is declared by two producers")
            continue
        outputs[output.name] = output.producer
        violations.extend(_reference_is_production(output.producer, output.name, declared))

    consumers: dict[str, list[str]] = {}
    for record in registry.output_consumers:
        if record.output not in outputs:
            violations.append(
                f"{record.consumer} consumes {record.output}, which no producer produces"
            )
            continue
        consumers.setdefault(record.output, []).append(record.consumer)
        violations.extend(
            _reference_is_production(record.consumer, f"consumer of {record.output}", declared)
        )

    for output in registry.outputs:
        reading = consumers.get(output.name, [])
        if reading and output.no_consumers_by_design is not None:
            violations.append(
                f"{output.name} declares consumers {sorted(reading)} and also declares "
                "none by design"
            )
        if not reading:
            if output.no_consumers_by_design is None:
                violations.append(
                    f"{output.name} is produced by {output.producer} and nothing consumes "
                    "it; a no-consumer case needs an explicitly approved reason"
                )
                continue
            citation = _citation_violation(
                output.no_consumers_by_design.approval, output.name, repo_root
            )
            if citation is not None:
                violations.append(citation)
    return violations


def _reference_is_production(
    reference: str, where: str, declared: Mapping[str, GovernedCapability]
) -> list[str]:
    if not reference.startswith("wplos."):
        return [f"{where}: {reference} is not production code in wplos"]
    unresolved = _unresolved(reference)
    if unresolved is not None:
        return [f"{where}: {unresolved}"]
    module = _reference_module(reference)
    if module not in declared:
        return [f"{where}: {reference} is not a governed production module"]
    if declared[module].status is CapabilityStatus.DELETE:
        return [f"{where}: {reference} is classified DELETE"]
    return []


def validate(
    registry: GovernanceRegistry,
    *,
    surface: ProductionSurface | None = None,
    current_phase: Phase = CURRENT_PHASE,
    repo_root: Path = REPO_ROOT,
) -> tuple[str, ...]:
    """Every way this registry contradicts the code, the clock or itself."""
    resolved_surface = surface if surface is not None else production_surface()
    reached = derive_reachable(registry, resolved_surface)
    declared = {capability.module: capability for capability in registry.capabilities}
    violations = _capability_violations(
        registry, resolved_surface, reached, current_phase, repo_root
    )
    violations.extend(_ownership_violations(registry, declared))
    violations.extend(_producer_consumer_violations(registry, declared, repo_root))
    return tuple(violations)
