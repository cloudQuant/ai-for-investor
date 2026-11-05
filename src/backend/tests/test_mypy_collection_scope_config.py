"""`config/mypy_collection.ini` must stay a copy of the repo's mypy options, not a weaker one.

The collection scope exists only because `pyproject.toml` excludes `scripts/` and mypy matches
that as an unanchored substring, which also swallowed `app/data_fetch/scripts`. If the two
option sets drift apart, the plane would silently check something else.
"""

from __future__ import annotations

import configparser
import re
from pathlib import Path

import pytest

try:
    import tomllib as toml_module
except ModuleNotFoundError:  # Python 3.10
    try:
        import tomli as toml_module  # type: ignore[no-redef]
    except ModuleNotFoundError:
        toml_module = None  # type: ignore[assignment]

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
COLLECTION_CONFIG = REPO_ROOT / "config" / "mypy_collection.ini"

#: A file the default scope never reached and the collection scope must.
COLLECTION_SAMPLE = "app/data_fetch/scripts/futures/hourly/futures_spot_sys.py"

SHARED_OPTIONS = {
    "python_version": "python_version",
    "plugins": "plugins",
    "ignore_missing_imports": "ignore_missing_imports",
    "follow_imports": "follow_imports",
    "warn_redundant_casts": "warn_redundant_casts",
    "warn_unused_ignores": "warn_unused_ignores",
    "no_implicit_optional": "no_implicit_optional",
    "check_untyped_defs": "check_untyped_defs",
}


@pytest.mark.skipif(toml_module is None, reason="TOML parsing needs tomli on Python 3.10")
def test_the_collection_scope_repeats_the_repo_default_options_verbatim() -> None:
    default = _load_pyproject()["tool"]["mypy"]
    section: dict[str, str] = {}
    parser = configparser.ConfigParser()
    parser.read(COLLECTION_CONFIG, encoding="utf-8")
    section = dict(parser["mypy"])

    for key in SHARED_OPTIONS.values():
        assert section[key].strip().lower() == _as_ini(default[key]).lower(), (
            f"{key} drifted from pyproject"
        )


@pytest.mark.skipif(toml_module is None, reason="TOML parsing needs tomli on Python 3.10")
def test_the_collection_scope_reaches_the_file_the_default_scope_excludes() -> None:
    default = _load_pyproject()["tool"]["mypy"]
    parser = configparser.ConfigParser()
    parser.read(COLLECTION_CONFIG, encoding="utf-8")
    collection_pattern = parser["mypy"]["exclude"]

    assert any(re.search(p, COLLECTION_SAMPLE) for p in default["exclude"]), (
        "the default scope no longer excludes the collection tree, so this plane is redundant"
    )
    assert not re.search(collection_pattern, COLLECTION_SAMPLE)


def _load_pyproject() -> dict:
    """`tomllib` and the 3.10 `tomli` shim disagree on str vs bytes; both take a binary file."""
    with (BACKEND_ROOT / "pyproject.toml").open("rb") as handle:
        return toml_module.load(handle)


def _as_ini(value: object) -> str:
    """Render a pyproject value the way configparser would have written it."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)
