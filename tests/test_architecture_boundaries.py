"""Phase 01 constraints, enforced by the suite instead of by memory.

No provider SDK, no UI, and a layering that only ever points one way.
"""

import ast
import tomllib
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "wplos"
PROJECT_ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_PACKAGES = frozenset(
    {
        "openai",
        "anthropic",
        "deepseek",
        "google",
        "cohere",
        "litellm",
        "langchain",
        "llama_index",
        "transformers",
        "chromadb",
        "pinecone",
        "qdrant_client",
        "weaviate",
        "faiss",
        "neo4j",
        "kafka",
        "confluent_kafka",
        "redis",
        "celery",
        "fastapi",
        "flask",
        "django",
        "sqlalchemy",
    }
)

LAYERS: dict[str, int] = {
    "shared": 0,
    "core": 1,
    "policy": 2,
    "personal_life_graph": 3,
    "events": 4,
    "agents": 5,
    "orchestration": 6,
    "application": 7,
    "integration": 8,
}


def _modules() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def _wplos_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    packages: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("wplos."):
            packages.add(node.module.split(".")[1])
        elif isinstance(node, ast.Import):
            packages.update(
                alias.name.split(".")[1]
                for alias in node.names
                if alias.name.startswith("wplos.") and alias.name.count(".") >= 1
            )
    return packages


@pytest.mark.parametrize("module", _modules(), ids=lambda path: path.name)
def test_no_module_imports_a_provider_or_infrastructure_sdk(module: Path) -> None:
    offending = _imported_roots(module) & FORBIDDEN_PACKAGES
    assert not offending, f"{module.relative_to(SRC)} imports {sorted(offending)}"


def test_the_only_runtime_dependency_is_pydantic() -> None:
    manifest = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = manifest["project"]["dependencies"]

    assert [item.split(">")[0].strip() for item in dependencies] == ["pydantic"]


def test_layering_only_points_one_way() -> None:
    violations: list[str] = []
    for module in _modules():
        relative = module.relative_to(SRC)
        layer = relative.parts[0] if len(relative.parts) > 1 else None
        if layer not in LAYERS:
            continue
        for imported in _wplos_imports(module):
            if imported not in LAYERS:
                continue
            if LAYERS[imported] > LAYERS[layer]:
                violations.append(f"{relative} imports wplos.{imported}")

    assert not violations, violations


def test_nothing_below_integration_may_import_it() -> None:
    """The integration kernel is the outermost layer.

    It may lean on the domain and the runtime; nothing they contain may reach
    back into sqlite, the outbox or the worker. Without a rank in LAYERS the
    one-way rule silently skipped the package entirely.
    """
    assert LAYERS["integration"] > LAYERS["application"]

    offenders: list[str] = []
    for module in _modules():
        relative = module.relative_to(SRC)
        layer = relative.parts[0] if len(relative.parts) > 1 else None
        if layer is None or layer == "integration":
            continue
        if "integration" in _wplos_imports(module):
            offenders.append(relative.as_posix())

    assert not offenders, offenders


def test_no_user_interface_has_been_built() -> None:
    ui_markers = ("*.dart", "*.jsx", "*.tsx", "*.vue", "*.html", "pubspec.yaml", "package.json")
    found = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for pattern in ui_markers
        for path in PROJECT_ROOT.rglob(pattern)
        if ".venv" not in path.parts and ".git" not in path.parts
    ]

    assert not found, f"Phase 01 builds no UI, found {found}"
