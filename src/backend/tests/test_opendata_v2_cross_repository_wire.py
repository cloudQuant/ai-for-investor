"""Opt-in AFI-to-OpenData v2 wire test against a private synthetic fixture.

Set ``AFI_OPENDATA_WIRE_TEST=1``, ``OPENDATA_REPO`` and ``OPENDATA_PYTHON`` to
run this test. The fixture starts the real OpenData v2 router in a separate
process with private temporary databases and a synthetic API key. It contacts
only that process over IPv4 loopback. Its ``passed`` quality and ``complete``
coverage are synthetic test inputs; this test establishes no real-source
rights, production data quality, or real historical coverage.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

if os.environ.get("AFI_OPENDATA_WIRE_TEST") == "1":
    # ``--noconftest`` intentionally avoids app.main and the repository-wide
    # test database overrides. Keep settings imports hermetic even though the
    # app's Settings can load a repository-level .env file.
    os.environ.update(
        {
            "DATABASE_URL": "sqlite+aiosqlite://",
            "DEBUG": "true",
            "SECRET_KEY": secrets.token_urlsafe(48),
            "JWT_SECRET_KEY": secrets.token_urlsafe(48),
            "SQL_ECHO": "false",
            "MARKET_DATA_QUERY_V2_ENABLED": "false",
            "MARKET_DATA_ONLINE_FETCH_ENABLED": "false",
            "MARKET_DATA_RESEARCH_CACHE_FILL_ENABLED": "false",
            "MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_ENABLED": "false",
        }
    )

    # Register relationship targets for User mapper configuration without
    # loading app.main or the shared pytest conftest. Only the three tables
    # needed by this test are created in its private in-memory database below.
    import app.models as _registered_models  # noqa: F401
    from app.db.database import Base
    from app.models.asset_research import AssetDataSourceRegistry
    from app.models.permission import Role, user_roles
    from app.models.user import User
    from app.services.market_data.access import (
        MarketDataAccessAuthorizer,
        MarketDataPrincipal,
        MarketDataQueryAccess,
    )
    from app.services.market_data.opendata_contracts import (
        OPENDATA_INDEX_BENCHMARK_FAMILY_ID,
        OPENDATA_INDEX_BENCHMARK_FAMILY_VERSION,
        OPENDATA_INDEX_BENCHMARK_PROVIDER_ENDPOINT,
        OPENDATA_INDEX_BENCHMARK_ROUTE_ID,
    )
    from app.services.market_data.opendata_credentials import OpendataCredentials
    from app.services.market_data.opendata_provider import OpendataProvider
    from app.services.market_data.source_policy import (
        MarketDataProviderRoute,
        MarketDataSourcePolicy,
    )
    from app.services.risk_analytics.benchmark import BenchmarkService
    from app.services.risk_analytics.opendata_index_benchmark import (
        OPENDATA_INDEX_DAILY_POLICY_ID,
        OpenDataIndexBenchmarkError,
        OpenDataIndexBenchmarkReader,
    )

pytestmark = pytest.mark.skipif(
    os.environ.get("AFI_OPENDATA_WIRE_TEST") != "1",
    reason="set AFI_OPENDATA_WIRE_TEST=1 to run the isolated cross-repository wire test",
)

_DATASET_ID = "cn.csi300.index.daily"
_PUBLICATION_ID = re.compile(r"[0-9a-f]{32}")
_SHA256_REF = re.compile(r"[0-9a-f]{64}")
_FIXTURE_START = "2024-01-01"
_FIXTURE_END_EXCLUSIVE = "2024-01-05"
_FIXTURE_END_INCLUSIVE = "2024-01-04"
_FIXTURE_READY_TIMEOUT_SECONDS = 20.0
_FIXTURE_SHUTDOWN_TIMEOUT_SECONDS = 8.0
_FIXTURE_REAP_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class _FixtureEndpoint:
    """Non-logging view of private readiness metadata."""

    base_url: str
    port: int
    api_key: str = field(repr=False)
    publication_id: str


@dataclass(slots=True)
class _FixtureProcess:
    """Subprocess resources owned by the AFI test harness."""

    process: subprocess.Popen[bytes]
    endpoint: _FixtureEndpoint
    directory: Path
    log_file: Any = field(repr=False)


def _is_allowed_fixture_url(url: httpx.URL, port: int) -> bool:
    """Accept only an unauthenticated HTTP URL for the exact fixture socket."""
    return (
        url.scheme == "http" and url.host == "127.0.0.1" and url.port == port and not url.userinfo
    )


class _LoopbackOnlyTransport(httpx.AsyncBaseTransport):
    """Permit real HTTP only to one exact loopback fixture port."""

    def __init__(self, port: int) -> None:
        self._port = port
        self._transport = httpx.AsyncHTTPTransport(trust_env=False, retries=0)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if not _is_allowed_fixture_url(url, self._port):
            raise httpx.ConnectError("cross-repository fixture transport is loopback-only")
        return await self._transport.handle_async_request(request)

    async def aclose(self) -> None:
        await self._transport.aclose()


@pytest.mark.parametrize(
    ("raw_url", "expected"),
    [
        ("http://127.0.0.1:43481/_fixture/health", True),
        ("http://fixture-user@127.0.0.1:43481/_fixture/health", False),
        ("http://:fixture-pass@127.0.0.1:43481/_fixture/health", False),
        ("http://fixture-user:fixture-pass@127.0.0.1:43481/_fixture/health", False),
        ("https://127.0.0.1:43481/_fixture/health", False),
        ("http://127.0.0.2:43481/_fixture/health", False),
        ("http://localhost:43481/_fixture/health", False),
        ("http://127.0.0.1:43482/_fixture/health", False),
    ],
)
def test_loopback_url_policy_rejects_non_fixture_targets_and_userinfo(
    raw_url: str,
    expected: bool,
) -> None:
    """Normal fixture URLs pass; credentials and alternate targets fail closed."""
    assert _is_allowed_fixture_url(httpx.URL(raw_url), 43481) is expected


@pytest.fixture
def opendata_fixture(tmp_path: Path) -> Iterator[_FixtureEndpoint]:
    """Start and always stop the isolated OpenData REST fixture subprocess."""
    repository_value = os.environ.get("OPENDATA_REPO")
    python_value = os.environ.get("OPENDATA_PYTHON")
    if not repository_value or not python_value:
        pytest.fail("OPENDATA_REPO and OPENDATA_PYTHON are required for the wire test")

    repository = Path(repository_value).resolve()
    python = Path(python_value).resolve()
    fixture_script = repository / "tests" / "test_cross_repository_fixture_server.py"
    if not fixture_script.is_file() or not python.is_file():
        pytest.fail("the configured OpenData fixture script or Python executable is unavailable")

    fixture_directory = tmp_path / "opendata-cross-repository-client"
    fixture_directory.mkdir(mode=0o700)
    fixture_directory.chmod(0o700)
    working_directory = tmp_path / "opendata-fixture-empty-cwd"
    working_directory.mkdir(mode=0o700)
    working_directory.chmod(0o700)
    ready_file = fixture_directory / "ready.json"
    log_path = fixture_directory / "fixture.log"
    log_descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    log_file = os.fdopen(log_descriptor, "wb")

    process = subprocess.Popen(
        [str(python), str(fixture_script), "--ready-file", str(ready_file)],
        cwd=working_directory,
        env={},
        stdin=subprocess.PIPE,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        shell=False,
        close_fds=True,
    )
    fixture = _FixtureProcess(
        process=process,
        endpoint=_FixtureEndpoint(base_url="", port=0, api_key="", publication_id=""),
        directory=fixture_directory,
        log_file=log_file,
    )
    try:
        endpoint = _wait_for_fixture_ready(process, ready_file)
        fixture.endpoint = endpoint
        yield endpoint
    finally:
        _stop_fixture(fixture, ready_file, log_path)


def _wait_for_fixture_ready(
    process: subprocess.Popen[bytes],
    ready_file: Path,
) -> _FixtureEndpoint:
    """Read an owner-only readiness file without exposing its API key."""
    deadline = time.monotonic() + _FIXTURE_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("OpenData fixture process exited before readiness")
        if ready_file.exists():
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("OpenData fixture did not become ready before the deadline")

    metadata = ready_file.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size > 4096
    ):
        raise RuntimeError("OpenData fixture readiness file has unsafe permissions or size")
    descriptor = os.open(ready_file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        with os.fdopen(descriptor, "r", encoding="utf-8") as source:
            payload = json.load(source)
    except Exception:
        raise RuntimeError("OpenData fixture readiness metadata is invalid") from None
    finally:
        ready_file.unlink(missing_ok=True)

    if not isinstance(payload, dict):
        raise RuntimeError("OpenData fixture readiness metadata is invalid")
    base_url = payload.get("base_url")
    api_key = payload.get("api_key")
    publication_id = payload.get("publication_id")
    parsed_url = urlsplit(base_url) if isinstance(base_url, str) else None
    if (
        not isinstance(api_key, str)
        or not api_key
        or payload.get("dataset_id") != _DATASET_ID
        or payload.get("start_date") != _FIXTURE_START
        or payload.get("end_date") != _FIXTURE_END_EXCLUSIVE
        or not isinstance(publication_id, str)
        or _PUBLICATION_ID.fullmatch(publication_id) is None
        or parsed_url is None
        or parsed_url.scheme != "http"
        or parsed_url.hostname != "127.0.0.1"
        or parsed_url.port is None
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.path
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise RuntimeError("OpenData fixture readiness metadata does not match the safe protocol")
    return _FixtureEndpoint(
        base_url=base_url,
        port=parsed_url.port,
        api_key=api_key,
        publication_id=publication_id,
    )


def _stop_fixture(fixture: _FixtureProcess, ready_file: Path, log_path: Path) -> None:
    """Stop/reap the child, retain redacted logs privately, and clean its state.

    Logs are retained at ``<system-temp>/afi-opendata-wire-logs-<uid>`` with
    owner-only directory/file modes so failures remain diagnosable after pytest
    removes its temporary directory.
    """
    process = fixture.process
    pending_interruption: BaseException | None = None
    stdin_failure = False
    try:
        if process.poll() is None and process.stdin is not None:
            try:
                process.stdin.write(b"shutdown\n")
                process.stdin.flush()
            except BaseException as exc:
                stdin_failure = True
                if isinstance(exc, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                    pending_interruption = exc
            try:
                process.stdin.close()
            except BaseException as exc:
                stdin_failure = True
                if pending_interruption is None and isinstance(
                    exc, (KeyboardInterrupt, SystemExit, GeneratorExit)
                ):
                    pending_interruption = exc
        if stdin_failure and process.poll() is None:
            try:
                process.terminate()
            except (OSError, ProcessLookupError):
                pass
        try:
            process.wait(timeout=_FIXTURE_SHUTDOWN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                pending_interruption = pending_interruption or exc
        if process.poll() is None:
            try:
                process.terminate()
            except (OSError, ProcessLookupError):
                pass
            try:
                process.wait(timeout=_FIXTURE_REAP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                pass
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                    pending_interruption = pending_interruption or exc
        if process.poll() is None:
            try:
                process.kill()
            except (OSError, ProcessLookupError):
                pass
            try:
                process.wait(timeout=_FIXTURE_REAP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                pass
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                    pending_interruption = pending_interruption or exc
    finally:
        try:
            fixture.log_file.flush()
        except BaseException as exc:
            if pending_interruption is None and isinstance(
                exc, (KeyboardInterrupt, SystemExit, GeneratorExit)
            ):
                pending_interruption = exc
        try:
            fixture.log_file.close()
        except BaseException as exc:
            if pending_interruption is None and isinstance(
                exc, (KeyboardInterrupt, SystemExit, GeneratorExit)
            ):
                pending_interruption = exc
        retained_log = _retain_fixture_log(log_path, fixture.endpoint.api_key)
        leftovers: tuple[Path, ...] = ()
        try:
            ready_file.unlink(missing_ok=True)
            log_path.unlink(missing_ok=True)
            leftovers = tuple(fixture.directory.glob("opendata-cross-repository-*"))
            for leftover in leftovers:
                if leftover.is_dir() and not leftover.is_symlink():
                    shutil.rmtree(leftover, ignore_errors=True)
                else:
                    leftover.unlink(missing_ok=True)
        finally:
            ready_file.unlink(missing_ok=True)
        if leftovers:
            raise AssertionError(
                "OpenData fixture left temporary database state after shutdown; "
                f"redacted log retained at {retained_log}"
            )
    if process.poll() is None:
        raise RuntimeError("OpenData fixture child could not be reaped")
    if pending_interruption is not None:
        raise pending_interruption


def _retain_fixture_log(log_path: Path, api_key: str) -> Path:
    """Persist redacted child diagnostics in an owner-only cache directory."""
    try:
        log_bytes = log_path.read_bytes()
    except FileNotFoundError:
        log_bytes = b""
    if api_key:
        log_bytes = log_bytes.replace(api_key.encode("utf-8"), b"<redacted>")
    # OpenData API keys use ``od-`` plus a 43-character URL-safe token. Redact
    # that shape as well in case startup failed before readiness was published.
    log_bytes = re.sub(rb"od-[A-Za-z0-9_-]{40,50}", b"od-<redacted>", log_bytes)

    owner_id = os.getuid()
    retained_directory = Path(tempfile.gettempdir()) / f"afi-opendata-wire-logs-{owner_id}"
    retained_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if retained_directory.is_symlink() or not retained_directory.is_dir():
        raise RuntimeError("private OpenData fixture log directory is unsafe")
    directory_stat = retained_directory.stat()
    if directory_stat.st_uid != owner_id:
        raise RuntimeError("private OpenData fixture log directory has the wrong owner")
    retained_directory.chmod(0o700)

    descriptor, retained_path_text = tempfile.mkstemp(
        prefix="fixture-",
        suffix=".log",
        dir=retained_directory,
    )
    retained_path = Path(retained_path_text)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as retained_file:
            retained_file.write(log_bytes)
            retained_file.flush()
            os.fsync(retained_file.fileno())
    except BaseException:
        retained_path.unlink(missing_ok=True)
        raise
    return retained_path


async def _new_reader(
    *,
    endpoint: _FixtureEndpoint,
    api_key: str,
    access: MarketDataQueryAccess,
    authorizer: MarketDataAccessAuthorizer,
    principal: MarketDataPrincipal,
) -> tuple[httpx.AsyncClient, OpenDataIndexBenchmarkReader]:
    """Bind the real AFI provider and reader to a loopback-only HTTP client."""
    client = httpx.AsyncClient(
        base_url=endpoint.base_url,
        transport=_LoopbackOnlyTransport(endpoint.port),
        trust_env=False,
        follow_redirects=False,
        timeout=2.0,
    )
    provider = OpendataProvider(
        client=client,
        credentials=OpendataCredentials(api_key, base_url=endpoint.base_url),
        timeout_seconds=2.0,
        total_deadline_seconds=10.0,
        max_retries=0,
        retry_backoff_seconds=0.0,
    )
    route = MarketDataProviderRoute(
        route_id=OPENDATA_INDEX_BENCHMARK_ROUTE_ID,
        request_provider="opendata",
        expected_result_provider_ids=frozenset({"opendata"}),
        asset_types=frozenset({"index"}),
        data_kinds=frozenset({"bars"}),
        frequencies=frozenset({"1d"}),
        markets=frozenset({"CN-SSE"}),
        adjustments=frozenset({"not_applicable"}),
        price_bases=frozenset({"close"}),
        currencies=frozenset({None}),
        units=frozenset({"point"}),
        adapter=provider,
        family_id=OPENDATA_INDEX_BENCHMARK_FAMILY_ID,
        family_contract_version=OPENDATA_INDEX_BENCHMARK_FAMILY_VERSION,
        provider_endpoint=OPENDATA_INDEX_BENCHMARK_PROVIDER_ENDPOINT,
    )
    policy = MarketDataSourcePolicy(
        policy_id=OPENDATA_INDEX_DAILY_POLICY_ID,
        allowed_purposes=frozenset({"display", "research", "backtest"}),
        routes=(route,),
    )
    grant = await authorizer.authorize_policy(
        principal=principal,
        policy=policy,
        routes=(route,),
        asset_type="index",
        market="CN-SSE",
        purpose="display",
    )
    reader = OpenDataIndexBenchmarkReader(
        access=access,
        policy=policy,
        route=route,
        grant=grant,
    )
    return client, reader


def _assert_schema2_synthetic_coverage(payload: Any, publication_id: str) -> None:
    """Check the pinned synthetic record-set refs without elevating their claim."""
    if not isinstance(payload, dict):
        raise AssertionError("coverage response must be a JSON object")
    coverage = payload.get("coverage")
    if (
        payload.get("dataset_id") != _DATASET_ID
        or payload.get("publication_id") != publication_id
        or not isinstance(payload.get("contract_sha256"), str)
        or _SHA256_REF.fullmatch(payload["contract_sha256"]) is None
        or not isinstance(coverage, dict)
    ):
        raise AssertionError("coverage response metadata does not match the synthetic pin")
    if (
        coverage.get("status") != "complete"
        or coverage.get("scope") != "business_history"
        or coverage.get("requested") != {"start": _FIXTURE_START, "end": _FIXTURE_END_EXCLUSIVE}
        or coverage.get("missing_ranges") != []
        or coverage.get("limitation") is not None
    ):
        raise AssertionError("coverage response does not match the synthetic test window")
    evidence_refs = coverage.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not all(
        isinstance(value, str) for value in evidence_refs
    ):
        raise AssertionError("coverage evidence refs must be strings")
    record_set_refs = [
        value
        for value in evidence_refs
        if re.fullmatch(r"visible-record-set-v1:sha256:[0-9a-f]{64}", value)
    ]
    sequence_refs = [
        value for value in evidence_refs if re.fullmatch(r"publication-sequence:[1-9][0-9]*", value)
    ]
    count_refs = [value for value in evidence_refs if value == "visible-record-count:3"]
    contract_refs = [
        value for value in evidence_refs if re.fullmatch(r"contract-sha256:[0-9a-f]{64}", value)
    ]
    if not all(
        len(refs) == 1 for refs in (record_set_refs, sequence_refs, count_refs, contract_refs)
    ):
        raise AssertionError("schema 2 coverage evidence refs are incomplete or ambiguous")
    if contract_refs[0] != f"contract-sha256:{payload['contract_sha256']}":
        raise AssertionError("coverage contract evidence does not match its contract hash")


def test_real_opendata_v2_wire_drives_authorized_benchmark_reader(
    opendata_fixture: _FixtureEndpoint,
) -> None:
    """Exercise the cross-repository wire path without repository conftest hooks."""
    asyncio.run(_run_wire_test(opendata_fixture))


async def _run_wire_test(endpoint: _FixtureEndpoint) -> None:
    """Use only an owned in-memory AFI auth database for the wire assertions."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    required_tables = [User.__table__, user_roles, AssetDataSourceRegistry.__table__]
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: Base.metadata.create_all(
                    sync_connection,
                    tables=required_tables,
                )
            )
        await _exercise_wire_assertions(endpoint, session_factory)
    finally:
        await engine.dispose()


async def _exercise_wire_assertions(
    endpoint: _FixtureEndpoint,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Exercise real OD authentication, coverage, snapshot, records and AFI auth."""
    async with httpx.AsyncClient(
        base_url=endpoint.base_url,
        transport=_LoopbackOnlyTransport(endpoint.port),
        trust_env=False,
        follow_redirects=False,
        timeout=2.0,
    ) as fixture_client:
        health = await fixture_client.get("/_fixture/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ready"}

        direct_coverage = await fixture_client.get(
            f"/api/v2/datasets/{_DATASET_ID}/coverage",
            params={
                "publication_id": endpoint.publication_id,
                "start_date": _FIXTURE_START,
                "end_date": _FIXTURE_END_EXCLUSIVE,
            },
            headers={"X-API-Key": endpoint.api_key},
        )
        assert direct_coverage.status_code == 200
        _assert_schema2_synthetic_coverage(direct_coverage.json(), endpoint.publication_id)

    async with session_factory() as session:
        user = User(
            username="opendata-wire-synthetic",
            email="opendata-wire-synthetic@example.test",
            hashed_password="fixture-only-unused",
            is_active=True,
        )
        session.add(user)
        await session.flush()
        await session.execute(user_roles.insert().values(user_id=user.id, role=Role.USER.value))
        # This row only permits exercising AFI's current source-policy gate in
        # a synthetic test DB. It is not evidence of a real provider license.
        session.add(
            AssetDataSourceRegistry(
                source_id="opendata",
                asset_types=["index"],
                jurisdictions=["CN"],
                license_status="APPROVED",
                allowed_uses=["DISPLAY"],
                redistribution_policy="INTERNAL_ONLY",
                derived_data_policy="ALLOWED",
                retention_policy="market-data-v1",
                effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
                enabled=True,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

        authorizer = MarketDataAccessAuthorizer(session)
        principal = await authorizer.principal_for_user(user)
        access = MarketDataQueryAccess(principal=principal, authorizer=authorizer)

        # A deliberately invalid synthetic key must fail at OD auth before a
        # snapshot write or any record read.
        invalid_client, invalid_reader = await _new_reader(
            endpoint=endpoint,
            api_key="invalid-synthetic-fixture-key",
            access=access,
            authorizer=authorizer,
            principal=principal,
        )
        try:
            with pytest.raises(OpenDataIndexBenchmarkError) as error:
                await invalid_reader.fetch_prices(
                    "hs300", "000300.SH", _FIXTURE_START, _FIXTURE_END_INCLUSIVE
                )
            assert error.value.code == "opendata_credentials_rejected"
        finally:
            await invalid_client.aclose()

        valid_client, valid_reader = await _new_reader(
            endpoint=endpoint,
            api_key=endpoint.api_key,
            access=access,
            authorizer=authorizer,
            principal=principal,
        )
        try:

            async def fetch_benchmark_prices(
                symbol: str,
                start_date: str,
                end_date: str,
            ) -> list[dict[str, Any]]:
                return await valid_reader.fetch_prices("hs300", symbol, start_date, end_date)

            benchmark = await BenchmarkService().get_benchmark_returns(
                "hs300",
                _FIXTURE_START,
                _FIXTURE_END_INCLUSIVE,
                data_fetcher=fetch_benchmark_prices,
            )
        finally:
            await valid_client.aclose()

    assert benchmark.status == "ok"
    assert benchmark.symbol == "000300.SH"
    assert benchmark.dates == ["2024-01-02", "2024-01-03", "2024-01-04"]
    assert benchmark.observation_count == 3
    assert benchmark.returns == [0.01, -0.019802]

    async with httpx.AsyncClient(
        base_url=endpoint.base_url,
        transport=_LoopbackOnlyTransport(endpoint.port),
        trust_env=False,
        follow_redirects=False,
        timeout=2.0,
    ) as audit_client:
        audit_response = await audit_client.get("/_fixture/audit")
    assert audit_response.status_code == 200
    audit = audit_response.json()
    assert isinstance(audit, dict) and isinstance(audit.get("requests"), list)
    assert audit["requests"] == [
        {
            "method": "GET",
            "path": f"/api/v2/datasets/{_DATASET_ID}/coverage",
        },
        {
            "method": "GET",
            "path": f"/api/v2/datasets/{_DATASET_ID}/coverage",
        },
        {
            "method": "GET",
            "path": f"/api/v2/datasets/{_DATASET_ID}/coverage",
        },
        {"method": "POST", "path": "/api/v2/snapshots"},
        {"method": "GET", "path": f"/api/v2/datasets/{_DATASET_ID}/records"},
    ]
