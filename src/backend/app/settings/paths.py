"""Repo-root paths shared by the settings sections.

The module lives one directory deeper than ``app/config.py``, so the repo root is
``parents[4]`` here; ``tests/test_config.py`` pins that the derived values match the
ones ``app.config`` produced before the sections were extracted.
"""

from pathlib import Path

# ``src/backend/app/settings/paths.py`` -> repository root.
REPO_ROOT = Path(__file__).resolve().parents[4]

DEFAULT_SQLITE_DATABASE_URL = (
    f"sqlite+aiosqlite:///{(REPO_ROOT / 'data' / 'dev' / 'backtrader.db').as_posix()}"
)
