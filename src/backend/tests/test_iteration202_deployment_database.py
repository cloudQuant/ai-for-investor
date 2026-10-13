"""Iteration 202 migration and read-only startup regression tests."""

import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy import event, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.schema_readiness import get_alembic_heads, verify_database_revision

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_PREVIOUS_RELEASE_REVISION = "20260911_market_data_b2_completeness_evidence"
_DEPLOY_DB_URL = os.environ.get("ITER202_DEPLOY_DB_URL")


@pytest.mark.asyncio
async def test_readiness_reads_current_heads_without_ddl():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    heads = sorted(get_alembic_heads())
    statements: list[str] = []
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(255) NOT NULL)")
            )
            for head in heads:
                await connection.execute(
                    text("INSERT INTO alembic_version (version_num) VALUES (:head)"),
                    {"head": head},
                )

        event.listen(
            engine.sync_engine,
            "before_cursor_execute",
            lambda _conn, _cursor, statement, *_args: statements.append(statement),
        )
        await verify_database_revision(engine)
    finally:
        await engine.dispose()

    assert statements
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)


@pytest.mark.asyncio
async def test_readiness_rejects_missing_or_stale_revision_without_creating_table():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        with pytest.raises(RuntimeError, match="not versioned"):
            await verify_database_revision(engine)

        async with engine.begin() as connection:
            await connection.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(255) NOT NULL)")
            )
            await connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES ('stale-revision')")
            )

        with pytest.raises(RuntimeError, match="revision mismatch"):
            await verify_database_revision(engine)
    finally:
        await engine.dispose()


def _validated_deployment_url() -> tuple[URL, str]:
    if not _DEPLOY_DB_URL:
        pytest.skip("set ITER202_DEPLOY_DB_URL to an isolated local deployment database")
    url = make_url(_DEPLOY_DB_URL)
    expected_database = {
        "mysql+aiomysql": "iter202_deploy",
        "postgresql+asyncpg": "iter202_deploy_pg",
    }.get(url.drivername)
    if (
        expected_database is None
        or url.host not in {"127.0.0.1", "localhost"}
        or url.database != expected_database
    ):
        pytest.fail(
            "ITER202_DEPLOY_DB_URL must point to local iter202_deploy MySQL or "
            "iter202_deploy_pg PostgreSQL only"
        )
    return url, url.render_as_string(hide_password=False)


def _run_alembic(database_url: str, revision: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    # This fixture owns a disposable empty database, so it can confirm every
    # historical DDL fence while reconstructing the prior released schema.
    for migration in (_BACKEND_ROOT / "alembic" / "versions").glob("*.py"):
        source = migration.read_text(encoding="utf-8")
        for name in re.findall(
            r'^_MYSQL_MAINTENANCE_FENCE_ENV\s*=\s*["\']([^"\']+)["\']',
            source,
            re.MULTILINE,
        ):
            environment[name] = "confirmed"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=_BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        pytest.fail(
            f"alembic upgrade {revision} failed ({result.returncode}):\n"
            f"{result.stdout}\n{result.stderr}"
        )


async def _drop_iter202_tables(database_url: str) -> None:
    url = make_url(database_url)
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            if url.drivername == "mysql+aiomysql":
                await connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS=0")
            else:
                # Native PostgreSQL enum types survive table-only cleanup and
                # make the baseline CREATE TYPE migration fail on the next run.
                await connection.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
                await connection.exec_driver_sql("CREATE SCHEMA public AUTHORIZATION CURRENT_USER")
                return
            table_names = await connection.run_sync(
                lambda sync_conn: sa.inspect(sync_conn).get_table_names()
            )
            for table_name in table_names:
                escaped_name = table_name.replace("`", "``")
                await connection.exec_driver_sql(f"DROP TABLE `{escaped_name}`")
            await connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS=1")
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upgrade_previous_schema_then_start_without_ddl(monkeypatch):
    url, database_url = _validated_deployment_url()
    await _drop_iter202_tables(database_url)
    root_engine = create_async_engine(database_url)
    try:
        _run_alembic(database_url, _PREVIOUS_RELEASE_REVISION)
        async with root_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, username, email, hashed_password, principal_kind) "
                    "VALUES ('iter202-user', 'iter202-user', 'iter202-user@example.test', "
                    "'test-hash', 'HUMAN')"
                )
            )
            results = "JSON_ARRAY()" if url.drivername == "mysql+aiomysql" else "'[]'::json"
            await connection.execute(
                text(
                    "INSERT INTO optimization_tasks "
                    "(id, user_id, strategy_id, status, total, completed, failed, "
                    "results, param_ranges, n_workers, created_at, updated_at) "
                    "VALUES ('iter202-task', 'iter202-user', 'iter202-strategy', 'completed', "
                    f"1, 1, 0, {results}, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )

        _run_alembic(database_url, "head")

        async with root_engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT user_id, objective, direction FROM optimization_tasks "
                        "WHERE id = 'iter202-task'"
                    )
                )
            ).one()
            revisions = frozenset(
                (await connection.execute(text("SELECT version_num FROM alembic_version")))
                .scalars()
                .all()
            )
            columns = {
                column["name"]: column
                for column in await connection.run_sync(
                    lambda sync_conn: sa.inspect(sync_conn).get_columns("optimization_tasks")
                )
            }
        assert row == ("iter202-user", None, None)
        assert revisions == get_alembic_heads()
        assert columns["objective"]["nullable"] is True
        assert columns["direction"]["nullable"] is True

        async with root_engine.begin() as connection:
            if url.drivername == "mysql+aiomysql":
                await connection.exec_driver_sql(
                    "CREATE USER IF NOT EXISTS 'iter202_readonly'@'%%' IDENTIFIED BY 'iter202-read'"
                )
                await connection.exec_driver_sql(
                    "GRANT SELECT ON iter202_deploy.* TO 'iter202_readonly'@'%%'"
                )
            else:
                existing_role = await connection.execute(
                    text("SELECT 1 FROM pg_roles WHERE rolname = 'iter202_readonly'")
                )
                if existing_role.scalar_one_or_none():
                    await connection.exec_driver_sql("DROP OWNED BY iter202_readonly")
                    await connection.exec_driver_sql("DROP ROLE iter202_readonly")
                await connection.exec_driver_sql(
                    "CREATE ROLE iter202_readonly LOGIN PASSWORD 'iter202-read'"
                )
                await connection.exec_driver_sql(
                    f'GRANT CONNECT ON DATABASE "{url.database}" TO iter202_readonly'
                )
                await connection.exec_driver_sql("GRANT USAGE ON SCHEMA public TO iter202_readonly")
                await connection.exec_driver_sql(
                    "GRANT SELECT ON ALL TABLES IN SCHEMA public TO iter202_readonly"
                )

        readonly_url = url.set(username="iter202_readonly", password="iter202-read")
        readonly_engine = create_async_engine(readonly_url.render_as_string(hide_password=False))
        from app.db import database as database_module

        monkeypatch.setattr(
            database_module,
            "settings",
            SimpleNamespace(DB_AUTO_CREATE_SCHEMA=False, DB_AUTO_CREATE_DEFAULT_ADMIN=False),
        )
        monkeypatch.setattr(database_module, "_get_engine", lambda: readonly_engine)
        try:
            await asyncio.gather(
                database_module.ensure_database_ready(),
                database_module.ensure_database_ready(),
            )
        finally:
            await readonly_engine.dispose()
    finally:
        async with root_engine.begin() as connection:
            if url.drivername == "mysql+aiomysql":
                await connection.exec_driver_sql("DROP USER IF EXISTS 'iter202_readonly'@'%%'")
            else:
                existing_role = await connection.execute(
                    text("SELECT 1 FROM pg_roles WHERE rolname = 'iter202_readonly'")
                )
                if existing_role.scalar_one_or_none():
                    await connection.exec_driver_sql("DROP OWNED BY iter202_readonly")
                    await connection.exec_driver_sql("DROP ROLE iter202_readonly")
        await root_engine.dispose()
        await _drop_iter202_tables(database_url)
