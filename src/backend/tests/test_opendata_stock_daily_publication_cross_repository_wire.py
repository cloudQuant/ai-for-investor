"""Opt-in AFI-to-OpenData stock-daily v2 wire test against a private fixture.

Set ``AFI_OPENDATA_STOCK_DAILY_WIRE_TEST=1``, ``OPENDATA_REPO`` and
``OPENDATA_PYTHON`` to run this test. The fixture starts the real OpenData
stock-daily v2 router in a separate process over a disposable SQLite
publication seeded with two synthetic raw daily bars. It contacts only that
process over IPv4 loopback. The publication, grants, contract, capacity
attestation, and API key are synthetic test inputs; this test establishes no
real-source rights, production authorization, data quality, or real history.
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

if os.environ.get("AFI_OPENDATA_STOCK_DAILY_WIRE_TEST") == "1":
    # ``--noconftest`` intentionally avoids app.main and repository-wide test
    # database overrides. Keep settings imports hermetic even though the app's
    # Settings can load a repository-level .env file.
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

    # Register model classes without loading app.main or the shared conftest.
    import app.models as _registered_models  # noqa: F401
    from app.services.market_data.opendata_credentials import OpendataCredentials
    from app.services.market_data.opendata_provider import OpendataProvider
    from app.services.market_data.opendata_stock_daily_snapshot import (
        OpendataStockDailySnapshotError,
        OpendataStockDailySnapshotReader,
    )
    from app.services.market_data.provider_models import MarketDataProviderRequest

pytestmark = pytest.mark.skipif(
    os.environ.get("AFI_OPENDATA_STOCK_DAILY_WIRE_TEST") != "1",
    reason=(
        "set AFI_OPENDATA_STOCK_DAILY_WIRE_TEST=1 to run the isolated "
        "stock-daily cross-repository wire test"
    ),
)

_DATASET_ID = "cn-equity-stock-daily"
_SOURCE_ID = "akshare.daily"
_MARKET = "CN-SSE"
_SYMBOL = "600519"
_START = "2026-10-26"
_END_EXCLUSIVE = "2026-10-29"
_EXPECTED_DATES = ("2026-10-26", "2026-10-27")
_EXPECTED_RECORD_COUNT = 2
_PUBLICATION_ID = re.compile(r"[0-9a-f]{32}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_FIXTURE_READY_TIMEOUT_SECONDS = 20.0
_FIXTURE_SHUTDOWN_TIMEOUT_SECONDS = 8.0
_FIXTURE_REAP_TIMEOUT_SECONDS = 2.0
_FIXTURE_LIFETIME_PREFIX = "opendata-stock-daily-cross-repository-"


@dataclass(frozen=True, slots=True)
class _FixtureEndpoint:
    """Non-logging view of private readiness metadata."""

    base_url: str
    port: int
    api_key: str = field(repr=False)
    publication_id: str
    content_sha256: str
    record_count: int


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
def stock_daily_fixture(tmp_path: Path) -> Iterator[_FixtureEndpoint]:
    """Start and always stop the isolated stock-daily fixture subprocess."""
    repository_value = os.environ.get("OPENDATA_REPO")
    python_value = os.environ.get("OPENDATA_PYTHON")
    if not repository_value or not python_value:
        pytest.fail("OPENDATA_REPO and OPENDATA_PYTHON are required for the wire test")

    repository = Path(repository_value).resolve()
    python = Path(python_value).resolve()
    fixture_script = repository / "tests" / "test_stock_daily_cross_repository_fixture_server.py"
    if not fixture_script.is_file() or not python.is_file():
        pytest.fail("the configured OpenData stock-daily fixture or Python executable is missing")

    fixture_directory = tmp_path / "opendata-stock-daily-client"
    fixture_directory.mkdir(mode=0o700)
    fixture_directory.chmod(0o700)
    working_directory = tmp_path / "opendata-stock-daily-empty-cwd"
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
        endpoint=_FixtureEndpoint(
            base_url="",
            port=0,
            api_key="",
            publication_id="",
            content_sha256="",
            record_count=0,
        ),
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
    """Read an owner-only readiness file without exposing its synthetic API key."""
    deadline = time.monotonic() + _FIXTURE_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("OpenData stock-daily fixture exited before readiness")
        if ready_file.exists():
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("OpenData stock-daily fixture did not become ready in time")

    metadata = ready_file.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size > 4096
    ):
        raise RuntimeError("OpenData stock-daily readiness file has unsafe permissions or size")
    descriptor = os.open(ready_file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        with os.fdopen(descriptor, "r", encoding="utf-8") as source:
            payload = json.load(source)
    except Exception:
        raise RuntimeError("OpenData stock-daily readiness metadata is invalid") from None
    finally:
        ready_file.unlink(missing_ok=True)

    if not isinstance(payload, dict):
        raise RuntimeError("OpenData stock-daily readiness metadata is invalid")
    base_url = payload.get("base_url")
    api_key = payload.get("api_key")
    publication_id = payload.get("publication_id")
    content_sha256 = payload.get("content_sha256")
    record_count = payload.get("record_count")
    parsed_url = urlsplit(base_url) if isinstance(base_url, str) else None
    if (
        not isinstance(api_key, str)
        or not api_key
        or payload.get("dataset_id") != _DATASET_ID
        or payload.get("start_date") != _START
        or payload.get("end_date") != _END_EXCLUSIVE
        or not isinstance(publication_id, str)
        or _PUBLICATION_ID.fullmatch(publication_id) is None
        or not isinstance(content_sha256, str)
        or _SHA256.fullmatch(content_sha256) is None
        or type(record_count) is not int
        or record_count != _EXPECTED_RECORD_COUNT
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
        raise RuntimeError("OpenData stock-daily readiness metadata failed the safe protocol")
    return _FixtureEndpoint(
        base_url=base_url,
        port=parsed_url.port,
        api_key=api_key,
        publication_id=publication_id,
        content_sha256=content_sha256,
        record_count=record_count,
    )


def _stop_fixture(fixture: _FixtureProcess, ready_file: Path, log_path: Path) -> None:
    """Stop and reap the child, retain redacted logs privately, and clean state."""
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
            leftovers = tuple(fixture.directory.glob(f"{_FIXTURE_LIFETIME_PREFIX}*"))
            for leftover in leftovers:
                if leftover.is_dir() and not leftover.is_symlink():
                    shutil.rmtree(leftover, ignore_errors=True)
                else:
                    leftover.unlink(missing_ok=True)
        finally:
            ready_file.unlink(missing_ok=True)
        if leftovers:
            raise AssertionError(
                "OpenData stock-daily fixture left temporary database state after shutdown; "
                f"redacted log retained at {retained_log}"
            )
    if process.poll() is None:
        raise RuntimeError("OpenData stock-daily fixture child could not be reaped")
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
    log_bytes = re.sub(rb"synthetic-afi204-[0-9a-f]{32}", b"synthetic-afi204-<redacted>", log_bytes)

    owner_id = os.getuid()
    retained_directory = (
        Path(tempfile.gettempdir()) / f"afi-opendata-stock-daily-wire-logs-{owner_id}"
    )
    retained_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if retained_directory.is_symlink() or not retained_directory.is_dir():
        raise RuntimeError("private OpenData stock-daily log directory is unsafe")
    directory_stat = retained_directory.stat()
    if directory_stat.st_uid != owner_id:
        raise RuntimeError("private OpenData stock-daily log directory has the wrong owner")
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


def _request() -> Any:
    """Build the exact raw stock-daily AFI request for the fixture window."""
    return MarketDataProviderRequest(
        query_fingerprint="c" * 64,
        canonical_id=f"instrument:stock:{_MARKET}:{_SYMBOL}",
        asset_type="stock",
        provider_symbol=_SYMBOL,
        market=_MARKET,
        data_kind="bars",
        frequency="1d",
        start_at=datetime(2026, 10, 26, tzinfo=timezone.utc),
        end_at=datetime(2026, 10, 29, tzinfo=timezone.utc),
        required_fields=frozenset({"open", "high", "low", "close", "volume", "turnover"}),
        provider="opendata",
        adjustment="unadjusted",
        price_basis="close",
        currency="CNY",
        unit="share",
        source_policy_id="market-default-v1",
        route_id="opendata-stock-daily-v1",
        family_id="stock.realtime",
        family_contract_version="market-data-family-v1",
    )


async def _audit(client: httpx.AsyncClient) -> list[dict[str, str]]:
    """Read the fixture's method/path-only audit trail."""
    response = await client.get("/_fixture/audit")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, dict)
    requests = payload.get("requests")
    assert isinstance(requests, list)
    return requests


def test_real_opendata_stock_daily_wire_drives_pinned_publication_reader(
    stock_daily_fixture: _FixtureEndpoint,
) -> None:
    """Exercise the cross-repository pinned-publication path without conftest hooks."""
    asyncio.run(_run_wire_test(stock_daily_fixture))


async def _run_wire_test(endpoint: _FixtureEndpoint) -> None:
    """Use the real AFI reader against the private OpenData stock-daily fixture."""
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

        client = httpx.AsyncClient(
            base_url=endpoint.base_url,
            transport=_LoopbackOnlyTransport(endpoint.port),
            trust_env=False,
            follow_redirects=False,
            timeout=2.0,
        )
        try:
            provider = OpendataProvider(
                client=client,
                credentials=OpendataCredentials(endpoint.api_key, base_url=endpoint.base_url),
                timeout_seconds=2.0,
                total_deadline_seconds=10.0,
                max_retries=0,
                retry_backoff_seconds=0.0,
            )
            reader = OpendataStockDailySnapshotReader(provider)
            result = await reader.read(_request(), publication_id=endpoint.publication_id)

            snapshot = result.snapshot
            assert snapshot["dataset_id"] == _DATASET_ID
            assert snapshot["publication_id"] == endpoint.publication_id
            assert snapshot["schema_version"] == "1.0.0"
            assert snapshot["semantic_version"] == "stock-daily-raw-v1"
            assert snapshot["source"] == {"source_id": _SOURCE_ID, "source": "akshare"}
            assert snapshot["stock_selection"] == {"market": _MARKET, "symbol": _SYMBOL}
            assert snapshot["window"] == {
                "start": _START,
                "end": _END_EXCLUSIVE,
                "end_exclusive": True,
            }
            assert snapshot["page_size"] == 1000
            assert snapshot["record_count"] == _EXPECTED_RECORD_COUNT
            assert snapshot["content_sha256"] == endpoint.content_sha256
            assert _SHA256.fullmatch(snapshot["contract_sha256"]) is not None
            assert snapshot["adjustment_basis"] == "raw"
            assert snapshot["currency"] == "CNY"
            assert snapshot["field_units"] == {
                "open": "CNY/share",
                "high": "CNY/share",
                "low": "CNY/share",
                "close": "CNY/share",
                "volume": "share",
                "amount": "CNY",
            }
            assert snapshot["field_adjustments"] == {
                "open": "raw",
                "high": "raw",
                "low": "raw",
                "close": "raw",
                "volume": "not_applicable",
                "amount": "not_applicable",
            }
            assert snapshot["calendar_id"] == "SSE"
            assert snapshot["timezone"] == "Asia/Shanghai"
            assert snapshot["quality"]["status"] == "warning"

            assert result.coverage["status"] == "unknown"
            assert result.coverage["scope"] == "unknown"
            assert result.coverage["requested"] == {"start": _START, "end": _END_EXCLUSIVE}
            assert result.coverage["observed"] is None
            assert result.coverage["missing_ranges"] == []
            assert result.coverage["evidence_refs"] == []

            assert result.page_count >= 1
            assert len(result.records) == _EXPECTED_RECORD_COUNT
            records = tuple(dict(record) for record in result.records)
            assert tuple(record["business_date"] for record in records) == _EXPECTED_DATES
            assert [record["payload"]["close"] for record in records] == [100.0, 101.0]
            assert [record["business_key"] for record in records] == [
                '["cn","600519","2026-10-26"]',
                '["cn","600519","2026-10-27"]',
            ]
            assert all(record["publication_id"] == endpoint.publication_id for record in records)
            assert all(record["event_at"] is None for record in records)
            assert all(record["source_published_at"] is None for record in records)

            expected_audit = [{"method": "GET", "path": "/api/v2/stock-daily/records"}]
            assert await _audit(fixture_client) == expected_audit

            mismatched_publication_id = (
                "0" * 32 if endpoint.publication_id != "0" * 32 else "f" * 32
            )
            with pytest.raises(OpendataStockDailySnapshotError) as error:
                await reader.read(_request(), publication_id=mismatched_publication_id)
            assert error.value.code == "opendata_fetch_failed"

            assert await _audit(fixture_client) == [
                *expected_audit,
                {"method": "GET", "path": "/api/v2/stock-daily/records"},
            ]
        finally:
            await client.aclose()
