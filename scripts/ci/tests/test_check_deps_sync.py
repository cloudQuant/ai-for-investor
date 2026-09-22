"""Regression tests for fail-closed dependency/lock synchronization checks."""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType

import pytest
from packaging.requirements import Requirement

try:
    import tomli
except (
    ImportError
):  # Python 3.11+ environments may not install the Python 3.10 fallback.
    tomli = None

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKER_PATH = REPO_ROOT / "scripts" / "ci" / "check_deps_sync.py"


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_deps_sync_under_test", CHECKER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def test_requirement_parser_resolves_nested_includes_relative_to_each_file(
    tmp_path: Path,
) -> None:
    checker = _load_checker()
    nested = tmp_path / "nested"
    nested.mkdir()
    lock = nested / "prod.lock"
    lock.write_text("fastapi==0.136.1\n", encoding="utf-8")
    included = tmp_path / "included.txt"
    included.write_text("-r nested/prod.lock\n", encoding="utf-8")
    wrapper = tmp_path / "requirements.txt"
    wrapper.write_text("-r included.txt\n", encoding="utf-8")
    included_files: set[Path] = set()

    requirements = checker.parse_requirements_file(
        wrapper, included_files=included_files
    )

    assert [requirement.name for requirement in requirements] == ["fastapi"]
    assert lock.resolve() in included_files


def test_requirement_parser_rejects_missing_nested_include(tmp_path: Path) -> None:
    checker = _load_checker()
    wrapper = tmp_path / "requirements.txt"
    wrapper.write_text("-r missing.lock\n", encoding="utf-8")

    try:
        checker.parse_requirements_file(wrapper)
    except checker.DependencySyncError as error:
        assert "missing.lock" in str(error)
    else:
        raise AssertionError("missing nested lock include should fail closed")


def test_requirement_parser_rejects_include_cycles(tmp_path: Path) -> None:
    checker = _load_checker()
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("-r second.txt\n", encoding="utf-8")
    second.write_text("-r first.txt\n", encoding="utf-8")

    try:
        checker.parse_requirements_file(first)
    except checker.DependencySyncError as error:
        assert "cycle" in str(error)
    else:
        raise AssertionError("recursive include cycle should fail closed")


def test_dependency_comparison_rejects_a_pin_outside_the_pyproject_specifier() -> None:
    checker = _load_checker()
    source = [Requirement("fastapi>=0.109.0")]
    locked = [Requirement("fastapi==0.108.0")]

    errors = checker.compare_direct_dependencies(
        source,
        locked,
        {"python_version": "3.11", "python_full_version": "3.11.0"},
    )

    assert any("fastapi" in error and "0.108.0" in error for error in errors)


def test_legacy_requirements_is_the_marker_aware_project_source_projection() -> None:
    checker = _load_checker()
    included_files: set[Path] = set()
    requirements = checker.parse_requirements_file(
        REPO_ROOT / "src/backend/requirements.txt",
        included_files=included_files,
    )
    source = checker.parse_pyproject_requirements(
        REPO_ROOT / "src/backend/pyproject.toml",
        extras=checker.PRODUCTION_EXTRAS,
    )

    assert not included_files
    assert checker.check_sync() == []
    assert Counter(checker._requirement_key(item) for item in requirements) == (
        Counter(checker._requirement_key(item) for item in source)
    )


def test_legacy_requirements_rejects_a_python_311_lock_include(
    tmp_path: Path,
) -> None:
    checker = _load_checker()
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        f"-r {REPO_ROOT / 'config/requirements-prod.lock'}\n", encoding="utf-8"
    )

    errors = checker.check_sync(legacy_requirements_path=requirements)

    assert any("must contain direct PEP 508 requirements" in error for error in errors)


@pytest.mark.parametrize(
    ("python_version", "lock_lines", "expected_specifiers"),
    [
        (
            "3.10",
            ["akshare==1.18.88"],
            {"akshare": "<1.18.89,>=1.18.88"},
        ),
        (
            "3.11",
            ["akshare==1.18.97", "fincore==0.5.0"],
            {"akshare": ">=1.18.96", "fincore": "<0.6.0,>=0.5.0"},
        ),
    ],
    ids=["python-310-fallback", "python-311-current"],
)
def test_production_extras_markers_match_active_python_lock_entries(
    python_version: str,
    lock_lines: list[str],
    expected_specifiers: dict[str, str],
) -> None:
    checker = _load_checker()
    source = checker.parse_pyproject_requirements(
        REPO_ROOT / "src/backend/pyproject.toml",
        extras=checker.PRODUCTION_EXTRAS,
    )
    environment = {
        "python_version": python_version,
        "python_full_version": f"{python_version}.0",
    }
    names = {"akshare", "fincore"}
    active_source = [
        requirement
        for requirement in source
        if requirement.name.lower() in names
        and (
            requirement.marker is None
            or requirement.marker.evaluate(environment=environment)
        )
    ]
    locked = [Requirement(line) for line in lock_lines]

    assert {
        requirement.name.lower(): str(requirement.specifier)
        for requirement in active_source
    } == expected_specifiers
    assert checker.compare_direct_dependencies(active_source, locked, environment) == []


def test_check_sync_rejects_drift_in_a_canonical_production_extra(
    tmp_path: Path,
) -> None:
    checker = _load_checker()
    pyproject = tmp_path / "pyproject.toml"
    project_text = (REPO_ROOT / "src/backend/pyproject.toml").read_text(
        encoding="utf-8"
    )
    pyproject.write_text(
        project_text.replace(
            '"akshare>=1.18.96; python_version >= \'3.11\'"',
            '"akshare>=1.19.0; python_version >= \'3.11\'"',
            1,
        ),
        encoding="utf-8",
    )

    errors = checker.check_sync(
        pyproject_path=pyproject,
        production_lock_path=REPO_ROOT / "config/requirements-prod.lock",
        legacy_requirements_path=REPO_ROOT / "src/backend/requirements.txt",
    )

    assert any("akshare" in error and "does not satisfy" in error for error in errors)


@pytest.mark.skipif(
    tomli is None, reason="tomli is only required by the Python 3.10 fallback"
)
def test_pyproject_parser_accepts_tomli_fallback_for_python_310(monkeypatch) -> None:
    checker = _load_checker()
    monkeypatch.setattr(checker, "toml_module", tomli)

    requirements = checker.parse_pyproject_requirements(
        REPO_ROOT / "src/backend/pyproject.toml"
    )

    assert any(requirement.name == "fastapi" for requirement in requirements)
