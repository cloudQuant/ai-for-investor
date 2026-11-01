"""Opt-in AFI-to-OpenData replay of one previously captured stock-daily response.

Set ``AFI_OPENDATA_STOCK_DAILY_REPLAY_TEST=1``, ``OPENDATA_REPO`` and
``OPENDATA_PYTHON`` to run the unauthenticated replay test. Set
``AFI_OPENDATA_STOCK_DAILY_REPLAY_AUTH_TEST=1`` plus the same two repository
variables to run the authorization-enabled replay tests. The fixture locates a
privately archived capture metadata file whose declared raw-body SHA-256
matches the pinned digest, starts the real OpenData stock-daily v2 router in a
separate process over a disposable SQLite ledger/publication replayed from
those exact bytes, and is contacted only over IPv4 loopback.

The authorization-enabled test seeds synthetic current grants, audits, and an
``AssetDataSourceRegistry`` row into a private file-backed SQLite database and
calls the real ``OpendataStockDailySnapshotReader.read_authorized``. The user,
grants, grants registry configuration, and API key are synthetic test inputs;
this test establishes no issuer authentication, production grant registry,
source rights, deployment, scheduling, full history, or coverage completeness.

The body is a previously captured real provider response replayed offline. It
is not a live request.
"""

from __future__ import annotations

import asyncio
import hashlib
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_REPLAY_ENV = "AFI_OPENDATA_STOCK_DAILY_REPLAY_TEST"
_AUTHORIZED_REPLAY_ENV = "AFI_OPENDATA_STOCK_DAILY_REPLAY_AUTH_TEST"
_REPLAY_ENABLED = os.environ.get(_REPLAY_ENV) == "1"
_AUTHORIZED_REPLAY_ENABLED = os.environ.get(_AUTHORIZED_REPLAY_ENV) == "1"

if _REPLAY_ENABLED or _AUTHORIZED_REPLAY_ENABLED:
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
    from app.db.database import Base
    from app.models import (
        AssetDataSourceRegistry,
        StockSnapshotGrantAudit,
        StockSnapshotSourceResearchGrant,
        StockSnapshotUserReadGrant,
        User,
    )
    from app.models.permission import user_roles
    from app.services.market_data.opendata_credentials import OpendataCredentials
    from app.services.market_data.opendata_provider import OpendataProvider
    from app.services.market_data.opendata_stock_daily_snapshot import (
        OpendataStockDailySnapshotError,
        OpendataStockDailySnapshotReader,
    )
    from app.services.market_data.provider_models import MarketDataProviderRequest
    from app.services.stock_analysis.stock_daily_snapshot_authorization_adapter import (
        StockDailySnapshotAuthorizationAdapter,
        source_registry_revision,
    )

pytestmark = pytest.mark.skipif(
    not (_REPLAY_ENABLED or _AUTHORIZED_REPLAY_ENABLED),
    reason=(
        f"set {_REPLAY_ENV}=1 or {_AUTHORIZED_REPLAY_ENV}=1 to run the isolated "
        "stock-daily captured-response replay tests"
    ),
)

_DATASET_ID = "cn-equity-stock-daily"
_SOURCE_ID = "akshare.daily"
_MARKET = "CN-SSE"
_SYMBOL = "600519"
_START = "2026-10-12"
_END_EXCLUSIVE = "2026-10-24"
_EXPECTED_DATES = (
    "2026-10-12",
    "2026-10-13",
    "2026-10-14",
    "2026-10-15",
    "2026-10-16",
    "2026-10-19",
    "2026-10-20",
    "2026-10-21",
    "2026-10-22",
    "2026-10-23",
)
_EXPECTED_RECORD_COUNT = 10
_EXPECTED_RAW_SHA256 = "2d707ecd928e70a8d7695b621ee437aa90644036600b5c5e9ed19f302f32c509"
_EXPECTED_CAPTURE_METADATA_SHA256 = (
    "2bf19b13b6bcc8a3536d153a28aa17b4762dd9d3bc96396a8debab53d800ed23"
)
_MAX_SAMPLE_BYTES = 2 * 1024 * 1024
_MAX_CAPTURE_METADATA_BYTES = 64 * 1024
_PUBLICATION_ID = re.compile(r"[0-9a-f]{32}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_FIXTURE_READY_TIMEOUT_SECONDS = 20.0
_FIXTURE_SHUTDOWN_TIMEOUT_SECONDS = 8.0
_FIXTURE_REAP_TIMEOUT_SECONDS = 2.0
_FIXTURE_LIFETIME_PREFIX = "opendata-stock-daily-real-sample-replay-"


@dataclass(frozen=True, slots=True)
class _FixtureEndpoint:
    """Non-logging view of private readiness metadata."""

    base_url: str
    port: int
    api_key: str = field(repr=False)
    publication_id: str
    content_sha256: str
    record_count: int
    observed_at: str


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
            raise httpx.ConnectError("captured-response fixture transport is loopback-only")
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


def _read_private_regular_file(path: Path, maximum: int) -> bytes:
    """Read one bounded regular file privately without following a leaf symlink."""
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum or path.is_symlink():
        raise RuntimeError("private captured input has unsafe permissions or size")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        with os.fdopen(descriptor, "rb") as source:
            content = source.read(maximum + 1)
    except OSError:
        raise RuntimeError("private captured input is unreadable") from None
    if len(content) > maximum:
        raise RuntimeError("private captured input exceeds its byte limit")
    return content


def _read_capture_metadata(path: Path) -> dict[str, object]:
    """Decode one bounded capture metadata document without echoing its contents."""
    raw = _read_private_regular_file(path, _MAX_CAPTURE_METADATA_BYTES)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RuntimeError("private capture metadata is not valid JSON") from None
    if not isinstance(payload, dict):
        raise RuntimeError("private capture metadata is not an object")
    return payload


def _locate_capture_directory(repository: Path) -> Path:
    """Find exactly one archived capture whose body matches the pinned digest."""
    override = os.environ.get("OPENDATA_STOCK_DAILY_REPLAY_CAPTURE_DIR")
    if override:
        directory = Path(override)
        if not directory.is_absolute() or not directory.is_dir():
            pytest.fail("OPENDATA_STOCK_DAILY_REPLAY_CAPTURE_DIR is not an absolute directory")
        candidates = [directory / "capture.json"]
    else:
        reports = repository / "var" / "reports"
        candidates = sorted(reports.rglob("capture.json")) if reports.is_dir() else []

    matches: list[Path] = []
    for candidate in candidates:
        if candidate.parent.name != "capture" or not candidate.is_file():
            continue
        try:
            metadata = _read_capture_metadata(candidate)
            raw_file = metadata.get("raw_file")
            declared_sha256 = metadata.get("raw_sha256")
            if (
                not isinstance(raw_file, str)
                or not raw_file
                or raw_file in {".", ".."}
                or "/" in raw_file
                or "\\" in raw_file
                or declared_sha256 != _EXPECTED_RAW_SHA256
            ):
                continue
            body = _read_private_regular_file(candidate.parent / raw_file, _MAX_SAMPLE_BYTES)
        except (OSError, RuntimeError):
            continue
        if hashlib.sha256(body).hexdigest() == _EXPECTED_RAW_SHA256:
            matches.append(candidate.parent)
    if len(matches) != 1:
        pytest.fail(
            "expected exactly one archived capture matching the pinned raw-body "
            f"SHA-256, found {len(matches)}"
        )
    return matches[0]


def _fixture_command(
    repository: Path,
    capture_directory: Path,
    ready_file: Path,
) -> tuple[list[str], str]:
    """Build the explicit non-secret fixture invocation for the located capture."""
    metadata_path = capture_directory / "capture.json"
    metadata = _read_capture_metadata(metadata_path)
    if (
        hashlib.sha256(
            _read_private_regular_file(metadata_path, _MAX_CAPTURE_METADATA_BYTES)
        ).hexdigest()
        != _EXPECTED_CAPTURE_METADATA_SHA256
    ):
        pytest.fail("archived capture metadata does not match the pinned metadata digest")
    raw_file = metadata.get("raw_file")
    observed_at = metadata.get("retrieved_at_utc")
    if (
        not isinstance(raw_file, str)
        or not raw_file
        or raw_file in {".", ".."}
        or "/" in raw_file
        or "\\" in raw_file
        or not isinstance(observed_at, str)
        or not observed_at
        or metadata.get("raw_sha256") != _EXPECTED_RAW_SHA256
    ):
        pytest.fail("archived capture metadata does not describe the pinned replay sample")
    command = [
        str(repository / "tests" / "test_stock_daily_real_sample_replay_fixture_server.py"),
        "--raw-body",
        str(capture_directory / raw_file),
        "--raw-body-sha256",
        _EXPECTED_RAW_SHA256,
        "--observed-at",
        observed_at,
        "--capture-metadata",
        str(metadata_path),
        "--ready-file",
        str(ready_file),
    ]
    return command, observed_at


@pytest.fixture
def stock_daily_replay_fixture(tmp_path: Path) -> Iterator[_FixtureEndpoint]:
    """Start and always stop the isolated captured-response replay subprocess."""
    repository_value = os.environ.get("OPENDATA_REPO")
    python_value = os.environ.get("OPENDATA_PYTHON")
    if not repository_value or not python_value:
        pytest.fail("OPENDATA_REPO and OPENDATA_PYTHON are required for the replay test")

    repository = Path(repository_value).resolve()
    python = Path(python_value).resolve()
    if not python.is_file():
        pytest.fail("the configured OpenData Python executable is missing")
    capture_directory = _locate_capture_directory(repository)

    fixture_directory = tmp_path / "opendata-stock-daily-replay-client"
    fixture_directory.mkdir(mode=0o700)
    fixture_directory.chmod(0o700)
    working_directory = tmp_path / "opendata-stock-daily-replay-empty-cwd"
    working_directory.mkdir(mode=0o700)
    working_directory.chmod(0o700)
    ready_file = fixture_directory / "ready.json"
    log_path = fixture_directory / "fixture.log"
    log_descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    log_file = os.fdopen(log_descriptor, "wb")

    command, observed_at = _fixture_command(repository, capture_directory, ready_file)
    process = subprocess.Popen(
        [python.as_posix(), *command],
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
            observed_at=observed_at,
        ),
        directory=fixture_directory,
        log_file=log_file,
    )
    try:
        endpoint = _wait_for_fixture_ready(process, ready_file, observed_at)
        fixture.endpoint = endpoint
        yield endpoint
    finally:
        _stop_fixture(fixture, ready_file, log_path)


def _wait_for_fixture_ready(
    process: subprocess.Popen[bytes],
    ready_file: Path,
    observed_at: str,
) -> _FixtureEndpoint:
    """Read an owner-only readiness file without exposing its synthetic API key."""
    deadline = time.monotonic() + _FIXTURE_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("OpenData stock-daily replay fixture exited before readiness")
        if ready_file.exists():
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("OpenData stock-daily replay fixture did not become ready in time")

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
        observed_at=observed_at,
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
                "OpenData stock-daily replay fixture left temporary database state after "
                f"shutdown; redacted log retained at {retained_log}"
            )
    if process.poll() is None:
        raise RuntimeError("OpenData stock-daily replay fixture child could not be reaped")
    if pending_interruption is not None:
        raise pending_interruption


def _retained_log_directory() -> Path:
    """Return the owner-only directory for redacted logs and replay evidence."""
    owner_id = os.getuid()
    retained_directory = (
        Path(tempfile.gettempdir()) / f"afi-opendata-stock-daily-replay-logs-{owner_id}"
    )
    retained_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if retained_directory.is_symlink() or not retained_directory.is_dir():
        raise RuntimeError("private OpenData stock-daily log directory is unsafe")
    directory_stat = retained_directory.stat()
    if directory_stat.st_uid != owner_id:
        raise RuntimeError("private OpenData stock-daily log directory has the wrong owner")
    retained_directory.chmod(0o700)
    return retained_directory


def _retain_fixture_log(log_path: Path, api_key: str) -> Path:
    """Persist redacted child diagnostics in an owner-only cache directory."""
    try:
        log_bytes = log_path.read_bytes()
    except FileNotFoundError:
        log_bytes = b""
    if api_key:
        log_bytes = log_bytes.replace(api_key.encode("utf-8"), b"<redacted>")
    log_bytes = re.sub(rb"synthetic-afi204-[0-9a-f]{32}", b"synthetic-afi204-<redacted>", log_bytes)

    retained_directory = _retained_log_directory()
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


def _write_replay_evidence(endpoint: _FixtureEndpoint) -> None:
    """Record non-secret replay identity in one owner-only private evidence file."""
    payload = {
        "dataset_id": _DATASET_ID,
        "publication_id": endpoint.publication_id,
        "content_sha256": endpoint.content_sha256,
        "record_count": endpoint.record_count,
        "start_date": _START,
        "end_date": _END_EXCLUSIVE,
        "raw_body_sha256": _EXPECTED_RAW_SHA256,
        "capture_metadata_sha256": _EXPECTED_CAPTURE_METADATA_SHA256,
        "observed_at": endpoint.observed_at,
    }
    retained_directory = _retained_log_directory()
    target = retained_directory / "last-replay-evidence.json"
    temporary = retained_directory / f".{target.name}.{os.getpid()}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as evidence_file:
            json.dump(payload, evidence_file, separators=(",", ":"), sort_keys=True)
            evidence_file.write("\n")
            evidence_file.flush()
            os.fsync(evidence_file.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _request() -> Any:
    """Build the exact raw stock-daily AFI request for the captured window."""
    return MarketDataProviderRequest(
        query_fingerprint="c" * 64,
        canonical_id=f"instrument:stock:{_MARKET}:{_SYMBOL}",
        asset_type="stock",
        provider_symbol=_SYMBOL,
        market=_MARKET,
        data_kind="bars",
        frequency="1d",
        start_at=datetime(2026, 10, 12, tzinfo=timezone.utc),
        end_at=datetime(2026, 10, 24, tzinfo=timezone.utc),
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


@pytest.mark.skipif(
    not _REPLAY_ENABLED,
    reason=f"set {_REPLAY_ENV}=1 to run the unauthenticated replay test",
)
def test_real_captured_stock_daily_replay_drives_pinned_publication_reader(
    stock_daily_replay_fixture: _FixtureEndpoint,
) -> None:
    """Exercise the replay path across both repositories without conftest hooks."""
    asyncio.run(_run_replay_test(stock_daily_replay_fixture))


async def _run_replay_test(endpoint: _FixtureEndpoint) -> None:
    """Use the real AFI reader against the loopback replay fixture."""
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
            assert snapshot["calendar_id"] == "SSE"
            assert snapshot["timezone"] == "Asia/Shanghai"
            assert snapshot["quality"]["status"] == "warning"

            assert result.coverage["status"] == "unknown"
            assert result.coverage["scope"] == "unknown"
            assert result.coverage["requested"] == {"start": _START, "end": _END_EXCLUSIVE}
            assert result.coverage["observed"] is None
            assert result.coverage["missing_ranges"] == []
            assert result.coverage["evidence_refs"] == []

            assert result.page_count == 1
            assert len(result.records) == _EXPECTED_RECORD_COUNT
            records = tuple(dict(record) for record in result.records)
            assert tuple(record["business_date"] for record in records) == _EXPECTED_DATES
            assert [record["business_key"] for record in records] == [
                f'["cn","{_SYMBOL}","{day}"]' for day in _EXPECTED_DATES
            ]
            assert all(record["publication_id"] == endpoint.publication_id for record in records)
            assert all(record["event_at"] is None for record in records)
            assert all(record["source_published_at"] is None for record in records)
            expected_observed_at = datetime.fromisoformat(
                endpoint.observed_at.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            assert all(
                datetime.fromisoformat(record["observed_at"]).astimezone(timezone.utc)
                == expected_observed_at
                for record in records
            )
            assert records[0]["payload"]["close"] == 1288.0
            assert records[-1]["payload"]["close"] == 1335.0
            assert records[0]["payload"]["volume"] == 3_155_600.0
            assert records[0]["payload"]["amount"] == 4_042_857_559.0

            expected_audit = [{"method": "GET", "path": "/api/v2/stock-daily/records"}]
            assert await _audit(fixture_client) == expected_audit

            _write_replay_evidence(endpoint)
        finally:
            await client.aclose()


_AUTH_USER_ID = "4a5a77a0-8db9-4e20-b8a3-070aef54e417"
_AUTH_USER_GRANT_ID = "88919c8f-6bd3-44ca-a96b-26c5b0551960"
_AUTH_SOURCE_GRANT_ID = "63fb60bb-23ef-4a96-9ea0-f814f78018d9"
_AUTH_POLICY_VERSION = "stock-analysis-opendata-access-v1"
_AUTHORIZATION_DATABASE_NAME = "stock-daily-authorization.sqlite3"
_EXPECTED_AUDIT = [{"method": "GET", "path": "/api/v2/stock-daily/records"}]


def _authorization_tables() -> tuple[Any, ...]:
    """Return the exact ORM tables the stock-daily adapter queries."""
    return (
        User.__table__,
        user_roles,
        AssetDataSourceRegistry.__table__,
        StockSnapshotUserReadGrant.__table__,
        StockSnapshotSourceResearchGrant.__table__,
        StockSnapshotGrantAudit.__table__,
    )


async def _authorization_engine(
    directory: Path,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create a private file-backed SQLite database with only the grant tables."""
    database = directory / _AUTHORIZATION_DATABASE_NAME
    descriptor = os.open(database, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    engine = create_async_engine(f"sqlite+aiosqlite:///{database.as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_controls(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                Base.metadata.create_all,
                tables=list(_authorization_tables()),
            )
    except BaseException:
        await engine.dispose()
        raise
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _authorization_user() -> Any:
    """Return one synthetic active human principal with the ``user`` role."""
    return User(
        id=_AUTH_USER_ID,
        username="stock-daily-auth-replay",
        email="stock-daily-auth-replay@example.test",
        hashed_password="test-only-hash",
        is_active=True,
    )


def _authorization_registry(now: datetime) -> Any:
    """Return a synthetic current registry decision allowing research reads."""
    return AssetDataSourceRegistry(
        source_id=_SOURCE_ID,
        asset_types=["stock"],
        jurisdictions=["CN", "CN-SSE"],
        license_status="APPROVED",
        allowed_uses=["RESEARCH", "DISPLAY"],
        redistribution_policy="INTERNAL_ONLY",
        retention_policy="research-v1",
        effective_from=now - timedelta(days=1),
        effective_to=now + timedelta(days=1),
        enabled=True,
        updated_at=now,
    )


def _authorization_user_grant(endpoint: _FixtureEndpoint, now: datetime) -> Any:
    """Return the exact user read grant for the fixture publication."""
    return StockSnapshotUserReadGrant(
        id=_AUTH_USER_GRANT_ID,
        user_id=_AUTH_USER_ID,
        permission="data:read",
        dataset_id=_DATASET_ID,
        instrument_id="600519.SH",
        market="SH",
        publication_id=endpoint.publication_id,
        capture_id=endpoint.content_sha256,
        purpose="RESEARCH",
        revision=1,
        valid_from=now - timedelta(minutes=5),
        expires_at=now + timedelta(hours=1),
    )


def _authorization_source_grant(
    endpoint: _FixtureEndpoint,
    now: datetime,
    *,
    registry_revision: str,
) -> Any:
    """Return the exact source research grant for the fixture publication."""
    return StockSnapshotSourceResearchGrant(
        id=_AUTH_SOURCE_GRANT_ID,
        user_id=_AUTH_USER_ID,
        source_id=_SOURCE_ID,
        dataset_id=_DATASET_ID,
        instrument_id="600519.SH",
        market="SH",
        publication_id=endpoint.publication_id,
        capture_id=endpoint.content_sha256,
        purpose="RESEARCH",
        source_registry_revision=registry_revision,
        revision=1,
        valid_from=now - timedelta(minutes=5),
        expires_at=now + timedelta(hours=1),
    )


def _authorization_audit(
    *,
    event_type: str,
    idempotency_hash: str,
    occurred_at: datetime,
    user_grant_id: str | None,
    source_grant_id: str | None,
) -> Any:
    """Return one synthetic issue or revoke audit bound to a grant revision."""
    return StockSnapshotGrantAudit(
        user_grant_id=user_grant_id,
        source_grant_id=source_grant_id,
        subject_user_id=_AUTH_USER_ID,
        actor_user_id=_AUTH_USER_ID,
        event_type=event_type,
        grant_revision=1,
        revocation_revision=1 if event_type == "ISSUED" else 2,
        policy_version=_AUTH_POLICY_VERSION,
        occurred_at=occurred_at,
        reason_code=f"test_{event_type.lower()}",
        idempotency_key_sha256=idempotency_hash,
    )


async def _seed_authorization_scope(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    endpoint: _FixtureEndpoint,
    now: datetime,
    user_grant: bool = True,
    source_grant: bool = True,
) -> None:
    """Seed one active user, registry row, exact grants, and ISSUED audits."""
    async with session_factory() as session:
        session.add(_authorization_user())
        await session.flush()
        await session.execute(user_roles.insert().values(user_id=_AUTH_USER_ID, role="user"))
        registry = _authorization_registry(now)
        session.add(registry)
        await session.flush()
        revision = source_registry_revision(registry)
        if user_grant:
            session.add(_authorization_user_grant(endpoint, now))
        if source_grant:
            session.add(
                _authorization_source_grant(
                    endpoint,
                    now,
                    registry_revision=revision,
                )
            )
        await session.flush()
        issued_at = now - timedelta(minutes=1)
        if user_grant:
            session.add(
                _authorization_audit(
                    event_type="ISSUED",
                    idempotency_hash="1" * 64,
                    occurred_at=issued_at,
                    user_grant_id=_AUTH_USER_GRANT_ID,
                    source_grant_id=None,
                )
            )
        if source_grant:
            session.add(
                _authorization_audit(
                    event_type="ISSUED",
                    idempotency_hash="2" * 64,
                    occurred_at=issued_at,
                    user_grant_id=None,
                    source_grant_id=_AUTH_SOURCE_GRANT_ID,
                )
            )
        await session.commit()


async def _revoke_authorization_user_grant(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    occurred_at: datetime,
) -> None:
    """Append the single synthetic REVOKED event for the seeded user grant."""
    async with session_factory() as session:
        session.add(
            _authorization_audit(
                event_type="REVOKED",
                idempotency_hash="9" * 64,
                occurred_at=occurred_at,
                user_grant_id=_AUTH_USER_GRANT_ID,
                source_grant_id=None,
            )
        )
        await session.commit()


class _RevokingOpendataProvider:
    """Delegate one real fetch, then revoke the grant before returning."""

    def __init__(
        self,
        provider: Any,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        revoked_at: datetime,
    ) -> None:
        self._provider = provider
        self._session_factory = session_factory
        self._revoked_at = revoked_at

    async def fetch_published_stock_daily_snapshot(
        self,
        request: Any,
        *,
        publication_id: str,
    ) -> Any:
        result = await self._provider.fetch_published_stock_daily_snapshot(
            request,
            publication_id=publication_id,
        )
        await _revoke_authorization_user_grant(
            self._session_factory,
            occurred_at=self._revoked_at,
        )
        return result


def _fixture_client(endpoint: _FixtureEndpoint) -> httpx.AsyncClient:
    """Return a loopback-only client for one fixture endpoint."""
    return httpx.AsyncClient(
        base_url=endpoint.base_url,
        transport=_LoopbackOnlyTransport(endpoint.port),
        trust_env=False,
        follow_redirects=False,
        timeout=2.0,
    )


def _fixture_provider(
    endpoint: _FixtureEndpoint,
    client: httpx.AsyncClient,
) -> Any:
    """Return the real OpenData provider limited to the fixture socket."""
    return OpendataProvider(
        client=client,
        credentials=OpendataCredentials(endpoint.api_key, base_url=endpoint.base_url),
        timeout_seconds=2.0,
        total_deadline_seconds=10.0,
        max_retries=0,
        retry_backoff_seconds=0.0,
    )


def _assert_authorized_replay_result(result: Any, endpoint: _FixtureEndpoint) -> None:
    """Assert the authorized read returned exactly the captured publication."""
    snapshot = result.snapshot
    assert snapshot["dataset_id"] == _DATASET_ID
    assert snapshot["publication_id"] == endpoint.publication_id
    assert snapshot["source"] == {"source_id": _SOURCE_ID, "source": "akshare"}
    assert snapshot["stock_selection"] == {"market": _MARKET, "symbol": _SYMBOL}
    assert snapshot["record_count"] == _EXPECTED_RECORD_COUNT
    assert snapshot["content_sha256"] == endpoint.content_sha256

    assert result.coverage["status"] == "unknown"
    assert result.coverage["scope"] == "unknown"
    assert result.coverage["observed"] is None
    assert result.coverage["missing_ranges"] == []
    assert result.coverage["evidence_refs"] == []

    assert result.page_count == 1
    assert len(result.records) == _EXPECTED_RECORD_COUNT
    records = tuple(dict(record) for record in result.records)
    assert tuple(record["business_date"] for record in records) == _EXPECTED_DATES
    assert all(record["publication_id"] == endpoint.publication_id for record in records)


async def _run_authorized_replay(endpoint: _FixtureEndpoint, directory: Path) -> None:
    """Read the captured publication through the real authorized reader path."""
    now = datetime.now(timezone.utc)
    engine, session_factory = await _authorization_engine(directory)
    fixture_client = _fixture_client(endpoint)
    client = _fixture_client(endpoint)
    try:
        health = await fixture_client.get("/_fixture/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ready"}

        await _seed_authorization_scope(session_factory, endpoint=endpoint, now=now)
        reader = OpendataStockDailySnapshotReader(
            _fixture_provider(endpoint, client),
            authorization_adapter=StockDailySnapshotAuthorizationAdapter(clock=lambda: now),
        )
        async with session_factory() as session:
            result = await reader.read_authorized(
                _request(),
                publication_id=endpoint.publication_id,
                content_sha256=endpoint.content_sha256,
                user_id=_AUTH_USER_ID,
                session=session,
            )

        _assert_authorized_replay_result(result, endpoint)
        assert await _audit(fixture_client) == _EXPECTED_AUDIT
        _write_replay_evidence(endpoint)
    finally:
        await client.aclose()
        await fixture_client.aclose()
        await engine.dispose()


async def _run_missing_user_grant_denial(endpoint: _FixtureEndpoint, directory: Path) -> None:
    """Deny a read with no user grant before the provider is ever contacted."""
    now = datetime.now(timezone.utc)
    engine, session_factory = await _authorization_engine(directory)
    fixture_client = _fixture_client(endpoint)
    client = _fixture_client(endpoint)
    try:
        await _seed_authorization_scope(
            session_factory,
            endpoint=endpoint,
            now=now,
            user_grant=False,
        )
        reader = OpendataStockDailySnapshotReader(
            _fixture_provider(endpoint, client),
            authorization_adapter=StockDailySnapshotAuthorizationAdapter(clock=lambda: now),
        )
        baseline_audit = await _audit(fixture_client)
        async with session_factory() as session:
            with pytest.raises(OpendataStockDailySnapshotError) as failure:
                await reader.read_authorized(
                    _request(),
                    publication_id=endpoint.publication_id,
                    content_sha256=endpoint.content_sha256,
                    user_id=_AUTH_USER_ID,
                    session=session,
                )
        assert failure.value.code == "stock_daily_user_grant_missing"
        assert await _audit(fixture_client) == baseline_audit == []
    finally:
        await client.aclose()
        await fixture_client.aclose()
        await engine.dispose()


async def _run_revocation_between_fetch_and_return(
    endpoint: _FixtureEndpoint,
    directory: Path,
) -> None:
    """Fail closed after the fetch if the current grant is revoked before return."""
    now = datetime.now(timezone.utc)
    engine, session_factory = await _authorization_engine(directory)
    fixture_client = _fixture_client(endpoint)
    client = _fixture_client(endpoint)
    try:
        await _seed_authorization_scope(session_factory, endpoint=endpoint, now=now)
        reader = OpendataStockDailySnapshotReader(
            _RevokingOpendataProvider(
                _fixture_provider(endpoint, client),
                session_factory,
                revoked_at=now,
            ),
            authorization_adapter=StockDailySnapshotAuthorizationAdapter(clock=lambda: now),
        )
        async with session_factory() as session:
            with pytest.raises(OpendataStockDailySnapshotError) as failure:
                await reader.read_authorized(
                    _request(),
                    publication_id=endpoint.publication_id,
                    content_sha256=endpoint.content_sha256,
                    user_id=_AUTH_USER_ID,
                    session=session,
                )
        assert failure.value.code == "user_grant_revoked"
        assert await _audit(fixture_client) == _EXPECTED_AUDIT
    finally:
        await client.aclose()
        await fixture_client.aclose()
        await engine.dispose()


@pytest.mark.skipif(
    not _AUTHORIZED_REPLAY_ENABLED,
    reason=f"set {_AUTHORIZED_REPLAY_ENV}=1 to run the authorized replay tests",
)
def test_authorized_real_captured_stock_daily_replay_reads_after_exact_grants(
    stock_daily_replay_fixture: _FixtureEndpoint,
    tmp_path: Path,
) -> None:
    """Exercise the real reader with current exact synthetic grants."""
    asyncio.run(_run_authorized_replay(stock_daily_replay_fixture, tmp_path))


@pytest.mark.skipif(
    not _AUTHORIZED_REPLAY_ENABLED,
    reason=f"set {_AUTHORIZED_REPLAY_ENV}=1 to run the authorized replay tests",
)
def test_authorized_replay_denies_missing_user_grant_before_records_request(
    stock_daily_replay_fixture: _FixtureEndpoint,
    tmp_path: Path,
) -> None:
    """A missing exact user grant denies without contacting the fixture."""
    asyncio.run(_run_missing_user_grant_denial(stock_daily_replay_fixture, tmp_path))


@pytest.mark.skipif(
    not _AUTHORIZED_REPLAY_ENABLED,
    reason=f"set {_AUTHORIZED_REPLAY_ENV}=1 to run the authorized replay tests",
)
def test_authorized_replay_denies_revocation_between_fetch_and_return(
    stock_daily_replay_fixture: _FixtureEndpoint,
    tmp_path: Path,
) -> None:
    """A revocation after fetch and before return still fails closed."""
    asyncio.run(_run_revocation_between_fetch_and_return(stock_daily_replay_fixture, tmp_path))
