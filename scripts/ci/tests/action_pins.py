"""Central registry of the immutable GitHub Action pins the CI contract tests accept.

Every workflow ``uses: owner/repo@<40-hex>`` pin must appear here before the pin is
accepted. Entries are added only after re-verifying the SHA against the action's
upstream tag refs (``GET /repos/<owner>/<repo>/git/refs/tags``) so a bump to an
unreviewed commit cannot slip through any contract test.

This module stays stdlib-only so it is importable from
``scripts/ci/tests/test_check_deps_sync.py``, which is currently the only
``scripts/ci/tests`` file the GitHub Actions CI (``.github/workflows/ci.yml``)
executes. Keeping the drift guard here means the next unreviewed pin bump trips a
test that actually runs.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 is upstream refs/tags/v7.0.1
# (also refs/tags/v7), verified via GET /repos/actions/checkout/git/refs/tags.
CHECKOUT_PIN = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
# actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a is upstream
# refs/tags/v7.0.1, verified via GET /repos/actions/upload-artifact/git/refs/tags.
UPLOAD_PIN = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"

ACCEPTED_SHA_PINS: frozenset[str] = frozenset({CHECKOUT_PIN, UPLOAD_PIN})

_SHA_PINNED_USE = re.compile(r"uses:\s*([^\s#@]+@[0-9a-f]{40})(?=[\s#]|$)")


def sha_pinned_uses(workflow_text: str) -> list[str]:
    """Return every ``owner/repo@<40-hex-SHA>`` action pin in one workflow document."""
    return _SHA_PINNED_USE.findall(workflow_text)


def all_workflow_sha_pins() -> set[str]:
    """Return every SHA-pinned ``uses:`` value across the repository workflows."""
    pins: set[str] = set()
    for path in sorted(WORKFLOWS.glob("*.yml")):
        pins.update(sha_pinned_uses(path.read_text(encoding="utf-8")))
    return pins
