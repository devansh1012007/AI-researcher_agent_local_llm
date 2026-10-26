"""Packaging contract: the built distribution must contain everything the code
imports and everything the prompt registry reads.

P0-1: `fastapi`/`uvicorn` were imported but undeclared, and the 16 prompt
template data files were excluded from the wheel, so `research serve` and every
prompt render died in a clean install. An editable install (what dev uses)
hides both defects, so they are only observable from a built artifact.

These tests assert the *source of truth* (pyproject.toml) rather than a built
artifact, so they run in the fast unit suite. `scripts/check_dist.py` asserts
the same properties against a real wheel.
"""
from __future__ import annotations

import ast
import glob
import re
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SRC = ROOT / "src" / "research_engine"
PYPROJECT = ROOT / "pyproject.toml"
TEMPLATES_DIR = SRC / "prompts" / "templates"

# Import name -> distribution name when they differ.
IMPORT_TO_DIST = {
    "yaml": "pyyaml",
}


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text())


def _declared_distributions() -> set[str]:
    out = set()
    for spec in _pyproject()["project"]["dependencies"]:
        name = re.split(r"[<>=!~;\[ ]", spec, maxsplit=1)[0]
        out.add(name.lower().replace("_", "-"))
    return out


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import
                continue
            if node.module:
                names.add(node.module.split(".")[0])
    return names


def test_every_third_party_import_is_a_declared_dependency():
    """An import that is not in [project.dependencies] breaks a clean install.

    The whole point of this file: `api/app.py` imported fastapi and
    `cli/main.py` imported uvicorn while neither was declared, and the
    resulting ModuleNotFoundError only appeared in a fresh environment.
    """
    declared = _declared_distributions()
    missing: dict[str, list[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        for module in _top_level_imports(path):
            if module in sys.stdlib_module_names or module.startswith("_"):
                continue
            if module == "research_engine":
                continue
            dist = IMPORT_TO_DIST.get(module, module).lower().replace("_", "-")
            if dist not in declared:
                missing.setdefault(module, []).append(
                    str(path.relative_to(ROOT)))
    assert not missing, (
        "third-party imports missing from [project.dependencies]: "
        f"{missing}. Add them to pyproject.toml or map them in "
        "IMPORT_TO_DIST."
    )


def test_package_data_covers_every_prompt_template():
    """Every template file must be matched by a package-data glob.

    setuptools expands package-data patterns with glob.glob(..., recursive=True)
    (setuptools/command/build_py.py), so the declared patterns are evaluated
    the same way here.
    """
    package_data = (
        _pyproject().get("tool", {}).get("setuptools", {}).get("package-data", {})
    )
    assert package_data, (
        "no [tool.setuptools.package-data] declared — the prompt templates are "
        "not modules and would be excluded from the wheel"
    )
    covered: set[Path] = set()
    for package, patterns in package_data.items():
        assert isinstance(patterns, list), (
            f"package-data entry {package!r} is {type(patterns).__name__}, "
            "expected a list of glob patterns. An unquoted dotted key "
            "(research_engine.prompts = [...]) parses as a NESTED table, and "
            "setuptools then rejects the build outright — quote the key."
        )
        pkg_dir = SRC.parent / Path(*package.split("."))
        assert pkg_dir.is_dir(), f"package-data key {package!r} is not a package dir"
        for pattern in patterns:
            for match in glob.glob(pattern, root_dir=str(pkg_dir), recursive=True):
                covered.add((pkg_dir / match).resolve())
    actual = {
        p.resolve() for p in TEMPLATES_DIR.rglob("*") if p.is_file()
    }
    assert actual, f"no prompt templates found under {TEMPLATES_DIR}"
    missing = actual - covered
    assert not missing, (
        "prompt template files not covered by package-data (they would be "
        f"excluded from the wheel): {sorted(str(p) for p in missing)}"
    )


def test_packages_are_discovered_under_src():
    """The package root must be `src`, or the wheel ships nothing.

    Regression: `where = ["."]` still passes every other check in this file,
    but the built wheel then contains ZERO prompt templates (the package data
    lives under src/, which is no longer the package root).
    """
    find = _pyproject()["tool"]["setuptools"]["packages"]["find"]
    assert find.get("where") == ["src"], (
        f"[tool.setuptools.packages.find] where is {find.get('where')!r}, "
        "expected ['src'] — otherwise the package (and its data files) is not "
        "where the build looks for it"
    )
    assert (ROOT / "src" / "research_engine" / "__init__.py").exists(), (
        "src/research_engine is not a package — the src layout is broken"
    )


def test_every_template_loads_with_a_system_prompt():
    """A template whose .meta.yaml is missing loads with an EMPTY system
    prompt — the LLM then receives the task with no role instruction. Assert
    the sidecar exists and is used, so the .yaml files must ship too."""
    from research_engine.prompts.registry import get_prompt, record_versions

    versions = record_versions()
    assert versions, "no prompt templates recorded"
    for name, version in versions.items():
        spec = get_prompt(name)
        assert spec.template.strip(), f"template {name} is empty"
        assert spec.system.strip(), (
            f"template {name} has no system prompt — is {name}/{version}"
            ".meta.yaml missing?"
        )


def test_missing_templates_dir_reports_an_incomplete_installation():
    """The registry must distinguish 'template not found' from 'the package
    data was never installed' — the two need different fixes."""
    from research_engine.prompts import registry

    original = registry.TEMPLATES_DIR
    registry.TEMPLATES_DIR = original.parent / "does_not_exist"
    registry._load.cache_clear()
    try:
        with pytest.raises(FileNotFoundError, match="installation is incomplete"):
            registry.record_versions()
        with pytest.raises(FileNotFoundError, match="installation is incomplete"):
            registry.get_prompt("synthesizer")
    finally:
        registry.TEMPLATES_DIR = original
        registry._load.cache_clear()


def test_package_data_covers_every_builtin_engine_pack_file():
    builtin_dir = SRC / "engines" / "builtin"
    package_data = (
        _pyproject().get("tool", {}).get("setuptools", {}).get("package-data", {})
    )
    covered: set[Path] = set()
    for package, patterns in package_data.items():
        pkg_dir = SRC.parent / Path(*package.split("."))
        for pattern in patterns:
            for match in glob.glob(pattern, root_dir=str(pkg_dir), recursive=True):
                covered.add((pkg_dir / match).resolve())
    actual = {p.resolve() for p in builtin_dir.rglob("*") if p.is_file()}
    assert actual, f"no builtin engine files found under {builtin_dir}"
    missing = actual - covered
    assert not missing, f"builtin engine files not covered by package-data: {sorted(str(p) for p in missing)}"
