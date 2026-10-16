"""Verify the analytics and managed-paper migration heads preserve existing rows."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from alembic import command
from alembic.config import Config


_BASE_REVISION = "20261016_approved_target_http_operations"
_MERGED_REVISION = "20261016_afi04_analytics_paper_merge"
_FINAL_REVISION = "20261016_legacy_paper_import"


def _alembic_config(backend_root: Path, database_path: Path) -> Config:
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    alembic_config = Config(str(backend_root / "alembic.ini"))
    alembic_config.set_main_option("sqlalchemy.url", database_url)
    alembic_config.set_main_option("script_location", str(backend_root / "alembic"))
    return alembic_config


def _upgrade_without_user_settings(alembic_config: Config, revision: str) -> None:
    # Alembic env.py imports application settings even though this test supplies
    # its own URL. Avoid loading either a developer .env or credentials.
    safe_settings = SimpleNamespace(DATABASE_URL="sqlite+aiosqlite:///unused.sqlite")
    with patch("app.config.get_settings", return_value=safe_settings):
        command.upgrade(alembic_config, revision)


def test_upgrade_to_merged_head_preserves_existing_portfolio_composition(tmp_path: Path) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "analytics-migration-preserves-existing.sqlite"
    alembic_config = _alembic_config(backend_root, database_path)

    _upgrade_without_user_settings(alembic_config, _BASE_REVISION)
    with sqlite3.connect(database_path) as connection:
        tables_before = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "portfolio_composition_versions" in tables_before
        assert "portfolio_analytics_datasets_v1" not in tables_before
        connection.execute(
            """
            INSERT INTO portfolio_composition_versions (
                id, owner_subject, portfolio_ref, membership_version, source_type,
                base_currency, members, membership_sha256, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "migration-preserved-composition-id",
                "migration-preserved-owner",
                "migration-preserved-portfolio",
                7,
                "imported",
                "USD",
                json.dumps([{"member_ref": "migration-preserved-member"}], separators=(",", ":")),
                "a" * 64,
                "2026-10-16T00:00:00+00:00",
            ),
        )
        connection.commit()
        before = connection.execute(
            """
            SELECT id, owner_subject, portfolio_ref, membership_version, source_type,
                   base_currency, members, membership_sha256, created_at
            FROM portfolio_composition_versions
            WHERE id = ?
            """,
            ("migration-preserved-composition-id",),
        ).fetchone()
        assert before is not None

    _upgrade_without_user_settings(alembic_config, _MERGED_REVISION)

    with sqlite3.connect(database_path) as connection:
        tables_after = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "portfolio_analytics_datasets_v1" in tables_after
        assert "legacy_paper_cutover_receipts" in tables_after
        after = connection.execute(
            """
            SELECT id, owner_subject, portfolio_ref, membership_version, source_type,
                   base_currency, members, membership_sha256, created_at
            FROM portfolio_composition_versions
            WHERE id = ?
            """,
            ("migration-preserved-composition-id",),
        ).fetchone()
        assert after == before
        assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [
            (_MERGED_REVISION,)
        ]

    _upgrade_without_user_settings(alembic_config, "head")

    with sqlite3.connect(database_path) as connection:
        tables_after_head = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "legacy_paper_import_receipts" in tables_after_head
        after_full_upgrade = connection.execute(
            """
            SELECT id, owner_subject, portfolio_ref, membership_version, source_type,
                   base_currency, members, membership_sha256, created_at
            FROM portfolio_composition_versions
            WHERE id = ?
            """,
            ("migration-preserved-composition-id",),
        ).fetchone()
        assert after_full_upgrade == before
        assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [
            (_FINAL_REVISION,)
        ]


def test_fresh_database_upgrades_to_the_single_merged_head(tmp_path: Path) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "analytics-migration-fresh.sqlite"
    alembic_config = _alembic_config(backend_root, database_path)

    _upgrade_without_user_settings(alembic_config, "head")

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "portfolio_composition_versions",
            "portfolio_analytics_datasets_v1",
            "legacy_paper_cutover_receipts",
            "legacy_paper_import_receipts",
        }.issubset(tables)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [
            (_FINAL_REVISION,)
        ]

