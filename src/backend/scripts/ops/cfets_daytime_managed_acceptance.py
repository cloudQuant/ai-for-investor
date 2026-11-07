#!/usr/bin/env python3
"""Plan or supervise one read-only-preflighted CFETS daytime managed acceptance.

The apply mode makes one explicit CFETS POST through the registered producer and
the normal scheduler coordinator/write fence. The response body is fsynced before
the producer receives it. This is a narrow observation-batch check only: it does
not establish source completeness, a holiday calendar, or broader date coverage.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from datetime import time as day_time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

BACKEND = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

SCRIPT_ID = "fx_spot_quote"
SCRIPT_MODULE = "app.data_fetch.scripts.common.hourly.fx_spot_quote"
SCRIPT_FUNCTION = "fetch_data"
TABLE_NAME = "FX_SPOT_QUOTE_OBSERVATIONS"
LEGACY_TABLE_NAME = "FX_SPOT_QUOTE"
SOURCE = "cfets"
MAIN_SCOPE = "cfets_main_pairs_25"
DATE_BASIS = "cfets_main_pairs_session_2022_v1"
QUOTE_TIME_BASIS = "source_publication_time"
SOURCE_ROW_TIME_BASIS = "source_row_time"
UNKNOWN_BASIS = "unknown"
SHANGHAI = ZoneInfo("Asia/Shanghai")

# This claim belongs to the preserved natural 2026-10-20 10:10 Shanghai slot.
# The managed acceptance uses task_id=None and a different, unique period key.
PROTECTED_NATURAL_CLAIM_KEY = "b533a93fa88aed507429773146ae6af449f157ef8c2a09191a9d3d911f5f028c"

SOURCE_HTTP_TIMEOUT_SECONDS = 20  # AkShare fx_spot_quote's reviewed call contract.
MANAGED_TIMEOUT_SECONDS = 120
PARENT_SOFT_SECONDS = 140
PARENT_TERM_SECONDS = 150
PARENT_KILL_SECONDS = 155
PARENT_HARD_SECONDS = 160
POST_DISPATCH_READBACK_RESERVE_SECONDS = 30
MAX_SINGLE_ASYNC_READ_SECONDS = 5
MAX_WIRE_BYTES = 8 * 1024 * 1024
MAX_DAY_ROWS = 5000
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT
    / "var"
    / "reports"
    / "iteration203"
    / "fx-observation-managed-daytime-acceptance"
    / "runs"
)

_EMPTY_MARKERS = {"", "---", "--", "—", "–", "-", "n/a", "null", "none"}
_EXPECTED_COLUMNS = frozenset(
    {
        "quote_source",
        "symbol",
        "name",
        "quote_time",
        "observed_at",
        "data_date",
        "business_date_basis",
        "business_date_status",
        "quote_time_basis",
        "source_record_time",
        "source_record_time_basis",
        "source_scope",
        "bid_price",
        "ask_price",
        "mid_price",
        "price_basis",
        "fx_basis",
        "source_currency_pair",
        "source_bid_raw",
        "source_ask_raw",
    }
)
_NATIVE_COMPARE_FIELDS = (
    "quote_source",
    "symbol",
    "name",
    "quote_time",
    "data_date",
    "business_date_basis",
    "business_date_status",
    "quote_time_basis",
    "source_record_time",
    "source_record_time_basis",
    "source_scope",
    "bid_price",
    "ask_price",
    "mid_price",
    "price_basis",
    "fx_basis",
    "source_currency_pair",
    "source_bid_raw",
    "source_ask_raw",
)
_NUMERIC_FIELDS = frozenset({"bid_price", "ask_price", "mid_price"})


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_exclusive(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _write_json_exclusive(path: Path, payload: Any) -> None:
    _write_exclusive(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, default=str, allow_nan=False).encode(
            "utf-8"
        )
        + b"\n",
    )


def _safe_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, "" if not parsed.query else "[redacted]", "")
    )


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"CFETS JSON contains duplicate object key {key!r}")
        result[key] = value
    return result


def _as_shanghai_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(SHANGHAI).replace(tzinfo=None)


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("CFETS omitted a valid source publication timestamp")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("CFETS source publication timestamp is malformed") from exc
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(SHANGHAI).replace(tzinfo=None)


def _optional_decimal(value: Any, *, symbol: str, field: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"CFETS returned invalid {field} for {symbol}")
    text = value.strip() if isinstance(value, str) else str(value)
    if text.casefold() in _EMPTY_MARKERS:
        return None
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"CFETS returned invalid {field} for {symbol}") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f"CFETS returned non-positive or non-finite {field} for {symbol}")
    return number


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text.casefold() in _EMPTY_MARKERS else text


def _raw_quote_text(value: Any) -> str | None:
    """Preserve the exact decoded bid/ask value, including source sentinels."""
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def _business_date(quote_time: datetime) -> date | None:
    """Reviewed main-pair session rule; no weekday/holiday skipping is inferred."""
    clock = quote_time.time()
    if day_time(0, 0) <= clock <= day_time(3, 0):
        return quote_time.date() - timedelta(days=1)
    if clock >= day_time(9, 30):
        return quote_time.date()
    return None


def parse_native_response(
    body: bytes,
    *,
    received_at: datetime,
    require_daytime_current_date: bool = True,
) -> dict[str, Any]:
    """Independently validate the exact response bytes before producer parsing."""
    if not body or len(body) > MAX_WIRE_BYTES:
        raise ValueError("CFETS response body is empty or exceeds the acceptance bound")
    try:
        payload = json.loads(
            body.decode("utf-8-sig"),
            parse_float=str,
            parse_int=str,
            object_pairs_hook=_reject_duplicate_object_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("CFETS response is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise ValueError("CFETS response omitted its records list")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("CFETS response omitted its publication metadata")
    quote_time = _parse_timestamp(data.get("showDateCN"))
    received_local = _as_shanghai_naive(received_at)
    if quote_time > received_local:
        raise ValueError("CFETS publication time is after response observation time")
    if require_daytime_current_date and (
        quote_time.date() != received_local.date() or quote_time.time() < day_time(9, 30)
    ):
        raise ValueError("CFETS publication stamp is not a same-day daytime observation")
    if quote_time.microsecond:
        raise ValueError("CFETS publication timestamp exceeds the destination second precision")

    from app.data_fetch.scripts.common.hourly.fx_spot_quote import CFETS_MAIN_PAIRS

    raw_records = payload["records"]
    if len(raw_records) != len(CFETS_MAIN_PAIRS):
        raise ValueError("CFETS response does not contain exactly the reviewed 25-pair set")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_records:
        if not isinstance(raw, dict):
            raise ValueError("CFETS response contains a non-object quote row")
        pair_value = raw.get("ccyPair")
        if not isinstance(pair_value, str) or not pair_value.strip():
            raise ValueError("CFETS response contains an empty currency pair")
        pair = pair_value.strip()
        symbol = pair.upper().replace("/", "")
        if not re.fullmatch(r"(?:100)?[A-Z]{6}", symbol) or symbol not in CFETS_MAIN_PAIRS:
            raise ValueError(f"CFETS response contains an unreviewed pair {pair!r}")
        if symbol in seen:
            raise ValueError(f"CFETS response contains duplicate pair {symbol}")
        seen.add(symbol)

        bid = _optional_decimal(raw.get("bidPrc"), symbol=symbol, field="bid")
        ask = _optional_decimal(raw.get("askPrc"), symbol=symbol, field="ask")
        source_mid = _optional_decimal(raw.get("midprice"), symbol=symbol, field="mid")
        if bid is not None and ask is not None and bid > ask:
            raise ValueError(f"CFETS returned crossed spot quotes for {symbol}")
        if (
            source_mid is not None
            and (bid is None or source_mid >= bid)
            and (ask is None or source_mid <= ask)
        ):
            mid: Decimal | None = source_mid
            price_basis = "source_mid"
        elif bid is not None and ask is not None:
            # Preserve the producer's float arithmetic result for the SQL comparison.
            mid = Decimal(str((float(bid) + float(ask)) / 2))
            price_basis = "derived_bid_ask_mid"
        elif bid is not None or ask is not None:
            mid = None
            price_basis = "one_sided_quote"
        elif source_mid is not None:
            mid = source_mid
            price_basis = "source_mid"
        else:
            mid = None
            price_basis = "unavailable_quote"

        session_date = _business_date(quote_time)
        source_record_time = _optional_text(raw.get("time"))
        rows.append(
            {
                "quote_source": "CFETS",
                "symbol": symbol,
                "name": pair,
                "quote_time": quote_time,
                "data_date": session_date,
                "business_date_basis": DATE_BASIS if session_date is not None else UNKNOWN_BASIS,
                "business_date_status": "verified" if session_date is not None else "unknown",
                "quote_time_basis": QUOTE_TIME_BASIS,
                "source_record_time": source_record_time,
                "source_record_time_basis": (
                    SOURCE_ROW_TIME_BASIS if source_record_time is not None else UNKNOWN_BASIS
                ),
                "source_scope": MAIN_SCOPE,
                "bid_price": float(bid) if bid is not None else None,
                "ask_price": float(ask) if ask is not None else None,
                "mid_price": float(mid) if mid is not None else None,
                "price_basis": price_basis,
                "fx_basis": "interbank_spot",
                "source_currency_pair": pair,
                "source_bid_raw": _raw_quote_text(raw.get("bidPrc")),
                "source_ask_raw": _raw_quote_text(raw.get("askPrc")),
                "_native_bid_raw": _raw_quote_text(raw.get("bidPrc")),
                "_native_ask_raw": _raw_quote_text(raw.get("askPrc")),
                "_native_mid_raw": _optional_text(raw.get("midprice")),
            }
        )
    if seen != set(CFETS_MAIN_PAIRS):
        raise ValueError("CFETS response does not cover every exact main-pair symbol")
    unavailable_count = sum(row["price_basis"] == "unavailable_quote" for row in rows)
    valid_count = len(rows) - unavailable_count
    if valid_count <= 0:
        raise ValueError("CFETS response has no priced pair; fail before producer parsing")
    return {
        "quote_time": quote_time,
        "received_at": received_local,
        "main_pair_count": len(rows),
        "source_row_count": len(rows),
        "valid_row_count": valid_count,
        "unavailable_count": unavailable_count,
        "source_scope": MAIN_SCOPE,
        "business_date_basis": DATE_BASIS
        if all(row["data_date"] for row in rows)
        else UNKNOWN_BASIS,
        "quality_status": "partial" if unavailable_count else "passed",
        "source_complete": False,
        "source_rows": rows,
        "100jpy_pair": next((row for row in rows if row["symbol"] == "100JPYCNY"), None),
        "one_sided_symbols": [
            row["symbol"] for row in rows if row["price_basis"] == "one_sided_quote"
        ],
        "unavailable_symbols": [
            row["symbol"] for row in rows if row["price_basis"] == "unavailable_quote"
        ],
    }


class CfetsPostRecorder:
    """Capture one exact AKShare POST response before returning to its parser."""

    def __init__(
        self,
        requests_module: Any,
        *,
        expected_url: str,
        wire_directory: Path,
        require_daytime_current_date: bool = True,
    ) -> None:
        self.requests_module = requests_module
        self.expected_url = expected_url
        self.wire_directory = wire_directory
        self.require_daytime_current_date = require_daytime_current_date
        self.original_post: Any | None = None
        self.request_count = 0
        self.unexpected_post_attempts = 0
        self.metadata: dict[str, Any] = {}
        self.native_evidence: dict[str, Any] = {}

    def __enter__(self) -> CfetsPostRecorder:
        self.original_post = self.requests_module.post
        self.requests_module.post = self.post
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.original_post is not None:
            self.requests_module.post = self.original_post
            self.original_post = None

    def post(self, url: str, *args: Any, **kwargs: Any) -> Any:
        if url != self.expected_url:
            self.unexpected_post_attempts += 1
            raise RuntimeError("acceptance permits only the configured CFETS spot POST URL")
        if self.request_count:
            raise RuntimeError("acceptance permits exactly one CFETS source POST")
        timeout = kwargs.get("timeout")
        if (
            not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or timeout > SOURCE_HTTP_TIMEOUT_SECONDS
        ):
            raise RuntimeError("CFETS source call exceeded the reviewed 20 second timeout cap")
        self.request_count = 1
        request_start = datetime.now(timezone.utc)
        _write_json_exclusive(
            self.wire_directory / "request-may-start.json",
            {
                "request_started_at_utc": request_start.isoformat(timespec="microseconds"),
                "method": "POST",
                "url": _safe_url(url),
                "source_timeout_seconds": timeout,
                "response_not_yet_received": True,
            },
        )
        assert self.original_post is not None
        try:
            response = self.original_post(url, *args, **kwargs)
        except BaseException as exc:
            _write_json_exclusive(
                self.wire_directory / "transport-error.json",
                {
                    "error_type": type(exc).__name__,
                    "error": f"{type(exc).__name__}: {exc}"[:1000],
                    "request_started_at_utc": request_start.isoformat(timespec="microseconds"),
                    "request_count": 1,
                    "business_write_possible": False,
                },
            )
            raise
        received_utc = datetime.now(timezone.utc)
        received_local = received_utc.astimezone(SHANGHAI).replace(tzinfo=None)
        body = bytes(response.content)
        if len(body) > MAX_WIRE_BYTES:
            raise RuntimeError("CFETS response exceeds the acceptance body-size bound")
        body_path = self.wire_directory / "response-body.bin"
        _write_exclusive(body_path, body)
        headers = getattr(response, "headers", {}) or {}
        safe_headers = {
            key: str(headers[key])[:300]
            for key in ("Content-Type", "Content-Encoding", "Date", "Last-Modified", "ETag")
            if key in headers
        }
        self.metadata = {
            "method": "POST",
            "requested_url": _safe_url(url),
            "response_url": _safe_url(str(getattr(response, "url", url) or url)),
            "status_code": int(getattr(response, "status_code", 0) or 0),
            "response_bytes": len(body),
            "response_body_sha256": _sha256(body),
            "response_body_path": str(body_path.resolve()),
            "body_fsynced_before_producer_parse": True,
            "request_count": self.request_count,
            "request_started_at_utc": request_start.isoformat(timespec="microseconds"),
            "response_received_at_utc": received_utc.isoformat(timespec="microseconds"),
            "response_received_at_shanghai": received_local.isoformat(timespec="microseconds"),
            "timeout_seconds": timeout,
            "headers": safe_headers,
        }
        _write_json_exclusive(self.wire_directory / "response.json", self.metadata)
        print(
            "CFETS_WIRE_CAPTURE "
            + json.dumps(self.metadata, ensure_ascii=False, separators=(",", ":")),
            flush=True,
        )
        if self.metadata["status_code"] == 200:
            try:
                self.native_evidence = parse_native_response(
                    body,
                    received_at=received_local,
                    require_daytime_current_date=self.require_daytime_current_date,
                )
                _write_json_exclusive(
                    self.wire_directory / "native-source-evidence.json", self.native_evidence
                )
            except BaseException as exc:
                _write_json_exclusive(
                    self.wire_directory / "native-preparse-rejection.json",
                    {
                        "error_type": type(exc).__name__,
                        "error": f"{type(exc).__name__}: {exc}"[:1000],
                        "response_body_sha256": _sha256(body),
                        "producer_parser_was_not_called": True,
                    },
                )
                raise
        return response


def build_plan(*, output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    """Return a no-I/O plan; this function never imports the producer or DB."""
    return {
        "mode": "plan",
        "status": "not_started",
        "script_id": SCRIPT_ID,
        "source": SOURCE,
        "table": TABLE_NAME,
        "legacy_table_protection": LEGACY_TABLE_NAME,
        "parameters": {"_ingest_mode": "live", "_call_timeout": 30},
        "task_id": None,
        "operator_id": None,
        "unique_manual_period_each_attempt": True,
        "source_http_timeout_seconds": SOURCE_HTTP_TIMEOUT_SECONDS,
        "managed_timeout_seconds": MANAGED_TIMEOUT_SECONDS,
        "outer_hard_deadline_seconds": PARENT_HARD_SECONDS,
        "output_root": str(output_root),
        "source_calls": 0,
        "business_writes": 0,
        "wire_body_fsynced_before_producer_parse": True,
        "source_acceptance_scope": {
            "pairs": 25,
            "business_date_rule": DATE_BASIS,
            "publication_timestamp_is_not_observed_at": True,
            "source_complete": False,
            "calendar_and_lifecycle": "unknown",
            "100JPY": "retain 100JPYCNY identity/quotation unit; no scaling",
        },
        "comparison": {
            "native_json_to_fresh_sql": list(_NATIVE_COMPARE_FIELDS),
            "double_tolerance": "abs <= 1e-12; MySQL target uses DOUBLE",
            "protect_full_legacy_table_hash": LEGACY_TABLE_NAME,
            "protect_target_same_day_rows_outside_this_exact_quote_keyset": True,
            "protect_natural_claim_and_execution_hash": PROTECTED_NATURAL_CLAIM_KEY,
            "managed_receipt_positive_commit_required": True,
        },
        "expected_command": (
            f"{sys.executable} {Path(__file__).resolve()} --apply --output-root {output_root}"
        ),
    }


def _row_digest(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    encoded = sorted(_canonical(dict(row)).decode("utf-8") for row in rows)
    material = ("\n".join(encoded) + ("\n" if encoded else "")).encode("utf-8")
    return {"row_count": len(rows), "sha256": _sha256(material)}


def _safe_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ValueError("output root must not be a symlink")
    return expanded.resolve()


def _validate_target_schema() -> dict[str, Any]:
    """Perform read-only warehouse schema/key preflight before source dispatch."""
    import mysql.connector

    from app.data_fetch.configs.db_config import DB_CONFIG

    config = dict(DB_CONFIG)
    config["connection_timeout"] = min(int(config.get("connection_timeout", 10)), 5)
    config["read_timeout"] = 5
    config["write_timeout"] = 5
    connection = mysql.connector.connect(**config, autocommit=True)
    try:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(f"SHOW COLUMNS FROM `{TABLE_NAME}`")
            columns = {
                str(row.get("Field", "")).casefold(): str(row.get("Type", "")).casefold()
                for row in (cursor.fetchall() or [])
            }
            missing = sorted(name for name in _EXPECTED_COLUMNS if name.casefold() not in columns)
            if missing:
                raise RuntimeError(f"schema_mismatch: {TABLE_NAME} lacks {', '.join(missing)}")
            cursor.execute(f"SHOW INDEX FROM `{TABLE_NAME}`")
            groups: dict[str, list[dict[str, Any]]] = {}
            for row in cursor.fetchall() or []:
                groups.setdefault(str(row.get("Key_name", "")), []).append(row)
            exact_unique = False
            for rows in groups.values():
                ordered = sorted(rows, key=lambda row: int(row.get("Seq_in_index", 0)))
                names = [str(row.get("Column_name", "")).casefold() for row in ordered]
                if (
                    names == ["quote_source", "symbol", "quote_time"]
                    and all(int(row.get("Non_unique", 1)) == 0 for row in ordered)
                    and all(row.get("Sub_part") is None for row in ordered)
                ):
                    exact_unique = True
                    break
            if not exact_unique:
                raise RuntimeError(
                    f"schema_mismatch: {TABLE_NAME} requires unique "
                    "(quote_source, symbol, quote_time) without prefix lengths"
                )
            cursor.execute(
                "SELECT ENGINE FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
                (TABLE_NAME,),
            )
            engine_rows = cursor.fetchall() or []
            if (
                len(engine_rows) != 1
                or str(engine_rows[0].get("ENGINE", "")).casefold() != "innodb"
            ):
                raise RuntimeError(f"schema_mismatch: {TABLE_NAME} must be an exact InnoDB table")
            cursor.execute(f"SHOW COLUMNS FROM `{LEGACY_TABLE_NAME}`")
            legacy_columns = cursor.fetchall() or []
            if not legacy_columns:
                raise RuntimeError(f"legacy protection table {LEGACY_TABLE_NAME} is unavailable")
            return {
                "warehouse_schema": str(config.get("database", "unknown")),
                "target_table": TABLE_NAME,
                "target_column_count": len(columns),
                "target_unique_key_verified": True,
                "legacy_table": LEGACY_TABLE_NAME,
                "legacy_column_count": len(legacy_columns),
            }
        finally:
            cursor.close()
    finally:
        connection.close()


def _warehouse_connection() -> Any:
    import mysql.connector

    from app.data_fetch.configs.db_config import DB_CONFIG

    config = dict(DB_CONFIG)
    config["connection_timeout"] = min(int(config.get("connection_timeout", 10)), 5)
    config["read_timeout"] = 5
    config["write_timeout"] = 5
    return mysql.connector.connect(**config, autocommit=True)


def _run_async_bounded(awaitable: Any, *, deadline: float, phase: str) -> Any:
    """Run one async DB read within the invocation's monotonic deadline."""
    remaining = deadline - time.monotonic()
    timeout = min(MAX_SINGLE_ASYNC_READ_SECONDS, remaining)
    if timeout <= 0:
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise TimeoutError(f"outer acceptance deadline exhausted during {phase}")
    try:
        return asyncio.run(asyncio.wait_for(awaitable, timeout=timeout))
    except (TimeoutError, asyncio.TimeoutError) as exc:
        raise TimeoutError(f"bounded async read exceeded its deadline during {phase}") from exc


def _current_day_rows(connection: Any, *, day: date, table_name: str) -> list[dict[str, Any]]:
    if table_name not in {TABLE_NAME, LEGACY_TABLE_NAME}:
        raise ValueError("unrecognized fixed warehouse table")
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            f"SELECT * FROM `{table_name}` WHERE `quote_time` >= %s AND `quote_time` < %s "
            "ORDER BY `quote_time`, `symbol` LIMIT %s",
            (
                datetime.combine(day, day_time.min),
                datetime.combine(day + timedelta(days=1), day_time.min),
                MAX_DAY_ROWS + 1,
            ),
        )
        rows = [dict(row) for row in cursor.fetchall() or []]
        if len(rows) > MAX_DAY_ROWS:
            raise RuntimeError(f"{table_name} current-day snapshot exceeds bounded row limit")
        return rows
    finally:
        cursor.close()


def _all_legacy_rows(connection: Any) -> list[dict[str, Any]]:
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(f"SELECT * FROM `{LEGACY_TABLE_NAME}` LIMIT 100001")
        rows = [dict(row) for row in cursor.fetchall() or []]
        if len(rows) > 100000:
            raise RuntimeError("legacy FX table exceeds bounded full-hash limit")
        return rows
    finally:
        cursor.close()


def _query_exact_observation_rows(
    connection: Any, source_rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    if not source_rows:
        return []
    quote_times = {row["quote_time"] for row in source_rows}
    if len(quote_times) != 1:
        raise ValueError("native source rows do not share one publication timestamp")
    quote_time = next(iter(quote_times))
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            f"SELECT * FROM `{TABLE_NAME}` WHERE `quote_source`=%s AND `quote_time`=%s ORDER BY `symbol`",
            ("CFETS", quote_time),
        )
        return [dict(row) for row in cursor.fetchall() or []]
    finally:
        cursor.close()


def _model_record(model: Any) -> dict[str, Any] | None:
    if model is None:
        return None
    return {column.key: getattr(model, column.key) for column in model.__table__.columns}


async def _load_registration_and_natural_claim() -> tuple[dict[str, Any], dict[str, Any]]:
    from sqlalchemy import select

    from app.db.database import async_session_maker
    from app.models.akshare_mgmt import AkshareTaskRunClaim, DataScript, TaskExecution

    async with async_session_maker() as session:
        script = await session.scalar(select(DataScript).where(DataScript.script_id == SCRIPT_ID))
        if script is None or not script.is_active:
            raise RuntimeError("fx_spot_quote registration is missing or inactive")
        registration = {
            "script_id": str(script.script_id),
            "source": str(script.source or ""),
            "module_path": str(script.module_path or ""),
            "function_name": str(script.function_name or ""),
            "registered_target_table": str(script.target_table or ""),
        }
        if (
            registration["source"].casefold() != SOURCE
            or registration["module_path"] != SCRIPT_MODULE
            or registration["function_name"] != SCRIPT_FUNCTION
        ):
            raise RuntimeError("active CFETS registration differs from reviewed source contract")
        claim = await session.get(AkshareTaskRunClaim, PROTECTED_NATURAL_CLAIM_KEY)
        if claim is None:
            raise RuntimeError("protected natural 10:10 claim is missing")
        execution = (
            await session.scalar(
                select(TaskExecution).where(TaskExecution.execution_id == claim.execution_id)
            )
            if claim.execution_id
            else None
        )
        if (
            claim.task_id != 101
            or claim.script_id != SCRIPT_ID
            or not str(claim.period_key).startswith("cron:")
            or execution is None
            or execution.task_id != 101
        ):
            raise RuntimeError("protected natural claim does not identify task 101 scheduler run")
        natural = {
            "claim_key": claim.claim_key,
            "claim_sha256": _sha256(_canonical(_model_record(claim))),
            "execution_id": execution.execution_id,
            "execution_sha256": _sha256(_canonical(_model_record(execution))),
            "period_key": claim.period_key,
            "claim_status": claim.status,
            "execution_status": getattr(getattr(execution, "status", None), "value", None),
        }
        return registration, natural


async def _read_natural_claim_hashes() -> dict[str, Any]:
    from sqlalchemy import select

    from app.db.database import async_session_maker
    from app.models.akshare_mgmt import AkshareTaskRunClaim, TaskExecution

    async with async_session_maker() as session:
        claim = await session.get(AkshareTaskRunClaim, PROTECTED_NATURAL_CLAIM_KEY)
        record = _model_record(claim)
        if not isinstance(record, dict):
            return {"claim_found": False, "claim_sha256": None, "execution_found": False}
        execution_id = record.get("execution_id")
        execution = (
            await session.scalar(
                select(TaskExecution).where(TaskExecution.execution_id == execution_id)
            )
            if execution_id
            else None
        )
        execution_record = _model_record(execution)
        return {
            "claim_found": True,
            "claim_sha256": _sha256(_canonical(record)),
            "execution_found": isinstance(execution_record, dict),
            "execution_id": execution_id,
            "execution_sha256": _sha256(_canonical(execution_record)) if execution_record else None,
        }


def _run_async(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def _claim_identity(source: str, period_key: str, parameters: dict[str, Any]) -> tuple[str, str]:
    from app.services.akshare.scheduler import _identity_key, _parameter_hash

    parameter_hash = _parameter_hash(parameters)
    return _identity_key(SCRIPT_ID, source, period_key, parameter_hash), parameter_hash


def _install_directory(output_root: Path, run_id: str) -> Path:
    root = _safe_path(output_root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    directory = root / run_id
    directory.mkdir(mode=0o700, exist_ok=False)
    return directory


async def _managed_worker(directory: Path, parent_pid: int) -> int:
    if os.getppid() != parent_pid:
        raise RuntimeError("managed worker must be started by its supervising parent")
    invocation = json.loads((directory / "invocation.json").read_text(encoding="utf-8"))
    if not isinstance(invocation, dict) or invocation.get("task_id") is not None:
        raise ValueError("worker invocation must use the isolated manual task_id=None scope")
    from app.data_fetch.scripts.common.hourly import fx_spot_quote as producer
    from app.models.akshare_mgmt import TriggeredBy
    from app.services.akshare.scheduler import get_akshare_scheduler

    if not getattr(producer, "PREFER_LOCAL_SCRIPT", False):
        raise RuntimeError("managed CFETS producer is not marked PREFER_LOCAL_SCRIPT")
    producer_instance = producer.FxSpotQuote()
    if producer_instance.table_name != TABLE_NAME:
        raise RuntimeError("managed CFETS producer does not target the reviewed observation table")
    ak_fx = importlib.import_module("akshare.fx.fx_quote")
    wire_directory = directory / "wire"
    wire_directory.mkdir(mode=0o700, exist_ok=False)
    recorder = CfetsPostRecorder(
        ak_fx.requests,
        expected_url=str(ak_fx.FX_SPOT_URL),
        wire_directory=wire_directory,
    )
    execution_summary: dict[str, Any] | None = None
    error: str | None = None
    timed_out = False
    managed_timeout = int(invocation.get("managed_timeout_seconds", MANAGED_TIMEOUT_SECONDS))
    if not 1 <= managed_timeout <= MANAGED_TIMEOUT_SECONDS:
        raise ValueError("managed timeout must be within the reviewed 120 second ceiling")
    scheduler = get_akshare_scheduler()
    try:
        with recorder:
            try:
                execution = await asyncio.wait_for(
                    scheduler.run_script_now(
                        SCRIPT_ID,
                        parameters=invocation["parameters"],
                        operator_id=None,
                        task_id=None,
                        triggered_by=TriggeredBy.MANUAL,
                        timeout_seconds=managed_timeout,
                        _claim_key=invocation["claim_key"],
                        _period_key=invocation["period_key"],
                    ),
                    timeout=managed_timeout,
                )
                result = execution.result if isinstance(execution.result, dict) else {}
                execution_summary = {
                    "execution_id": execution.execution_id,
                    "status": str(getattr(execution.status, "value", execution.status)),
                    "task_id": execution.task_id,
                    "operator_id": execution.operator_id,
                    "start_time": execution.start_time,
                    "end_time": execution.end_time,
                    "error_message": (execution.error_message or "")[:1000],
                    "result": result,
                }
            except (TimeoutError, asyncio.TimeoutError) as exc:
                timed_out = True
                error = f"{type(exc).__name__}: managed call exceeded {managed_timeout}s"
            except BaseException as exc:
                error = f"{type(exc).__name__}: {exc}"[:1500]
    finally:
        await scheduler.shutdown()
        from app.db.database import engine

        await engine.dispose()
    worker_result = {
        "run_id": invocation["run_id"],
        "period_key": invocation["period_key"],
        "claim_key": invocation["claim_key"],
        "parameters": invocation["parameters"],
        "managed_status": (execution_summary or {}).get("status", "unknown"),
        "managed_call_error": error,
        "timed_out": timed_out,
        "execution": execution_summary,
        "wire_request_count": recorder.request_count,
        "unexpected_post_attempts": recorder.unexpected_post_attempts,
        "wire_metadata": recorder.metadata,
        "native_evidence": recorder.native_evidence,
        "source_complete": False,
    }
    _write_json_exclusive(directory / "worker-result.json", worker_result)
    return (
        0
        if execution_summary and execution_summary.get("status", "").casefold() == "completed"
        else 1
    )


def _table_rows_by_key(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[Any, ...], dict[str, Any]]:
    result: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = (row.get("quote_source"), row.get("symbol"), row.get("quote_time"))
        if key in result:
            raise ValueError("warehouse query returned a duplicate natural observation key")
        result[key] = dict(row)
    return result


def _number_equal(actual: Any, expected: Any) -> bool:
    if actual is None or expected is None:
        return actual is None and expected is None
    try:
        actual_number = Decimal(str(actual))
        expected_number = Decimal(str(expected))
    except (InvalidOperation, ValueError):
        return False
    return actual_number.is_finite() and abs(actual_number - expected_number) <= Decimal("1e-12")


def compare_native_rows(
    source_rows: Sequence[Mapping[str, Any]],
    sql_rows: Sequence[Mapping[str, Any]],
    *,
    before_target_rows: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Compare exact native source keys and all source-derived destination fields."""
    expected = {str(row["symbol"]): dict(row) for row in source_rows}
    actual: dict[str, dict[str, Any]] = {}
    for row in sql_rows:
        symbol = str(row.get("symbol", ""))
        if symbol in actual:
            raise ValueError("fresh SQL contains duplicate symbol/publication-time key")
        actual[symbol] = dict(row)
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    before_by_key = _table_rows_by_key(before_target_rows)
    checks: list[dict[str, Any]] = []
    for symbol in sorted(set(expected) & set(actual)):
        source = expected[symbol]
        stored = actual[symbol]
        mismatches: list[str] = []
        for field in _NATIVE_COMPARE_FIELDS:
            if field in _NUMERIC_FIELDS:
                equal = _number_equal(stored.get(field), source.get(field))
            else:
                left, right = stored.get(field), source.get(field)
                if isinstance(left, datetime) and isinstance(right, datetime):
                    equal = _as_shanghai_naive(left) == _as_shanghai_naive(right)
                elif (
                    isinstance(left, date)
                    and not isinstance(left, datetime)
                    and isinstance(right, date)
                ):
                    equal = left == right
                else:
                    equal = left == right
            if not equal:
                mismatches.append(field)
        created_at = stored.get("created_at")
        if created_at is None:
            mismatches.append("created_at_nonnull")
        before_key = ("CFETS", symbol, source["quote_time"])
        prior = before_by_key.get(before_key)
        if prior is not None and prior.get("created_at") != created_at:
            mismatches.append("preexisting_created_at_unchanged")
        raw_bid_exact = source.get("_native_bid_raw") == stored.get("source_bid_raw")
        raw_ask_exact = source.get("_native_ask_raw") == stored.get("source_ask_raw")
        checks.append(
            {
                "symbol": symbol,
                "matched": not mismatches,
                "mismatches": mismatches,
                "source_bid_raw_lexically_preserved": raw_bid_exact,
                "source_ask_raw_lexically_preserved": raw_ask_exact,
                "single_sided_mid_is_null": (
                    source.get("price_basis") != "one_sided_quote"
                    or stored.get("mid_price") is None
                ),
                "100jpy_identity_preserved": (
                    symbol != "100JPYCNY"
                    or (
                        stored.get("symbol") == "100JPYCNY"
                        and stored.get("source_currency_pair") == source.get("source_currency_pair")
                        and _number_equal(stored.get("bid_price"), source.get("bid_price"))
                        and _number_equal(stored.get("ask_price"), source.get("ask_price"))
                    )
                ),
            }
        )
    raw_lexical_mismatch_count = sum(
        not row["source_bid_raw_lexically_preserved"]
        or not row["source_ask_raw_lexically_preserved"]
        for row in checks
    )
    all_matches = (
        bool(source_rows)
        and not missing
        and not extra
        and all(
            row["matched"] and row["single_sided_mid_is_null"] and row["100jpy_identity_preserved"]
            for row in checks
        )
    )
    return {
        "matched": all_matches,
        "source_key_count": len(source_rows),
        "sql_key_count": len(sql_rows),
        "missing_symbols": missing,
        "extra_symbols": extra,
        "field_comparison_count": len(checks) * len(_NATIVE_COMPARE_FIELDS),
        "field_mismatch_count": sum(len(row["mismatches"]) for row in checks),
        "source_bid_ask_lexical_mismatch_count": raw_lexical_mismatch_count,
        "raw_bid_ask_original_lexical_text_saved_as_an_exact_value": raw_lexical_mismatch_count
        == 0,
        "symbol_checks": checks,
        "compared_fields": list(_NATIVE_COMPARE_FIELDS),
        "double_absolute_tolerance": "1e-12",
    }


def _execution_receipt_checks(
    execution: Mapping[str, Any] | None, native: Mapping[str, Any]
) -> dict[str, bool]:
    result = execution.get("result") if isinstance(execution, Mapping) else None
    result = result if isinstance(result, Mapping) else {}
    committed = result.get("committed_write_count")
    row_counts = result.get("committed_write_row_counts")
    valid_row_counts = (
        isinstance(row_counts, list)
        and bool(row_counts)
        and all(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
            for value in row_counts
        )
        and any(value > 0 for value in row_counts)
    )
    return {
        "execution_completed": isinstance(execution, Mapping)
        and str(execution.get("status", "")).casefold() == "completed",
        "task_id_none": isinstance(execution, Mapping) and execution.get("task_id") is None,
        "operator_id_none": isinstance(execution, Mapping) and execution.get("operator_id") is None,
        "result_table_matches": result.get("table_name") == TABLE_NAME,
        "run_mode_live": result.get("run_mode") == "live",
        "source_scope_main25": result.get("source_scope") == MAIN_SCOPE,
        "source_complete_false": result.get("source_complete") is False,
        "source_row_count_matches": result.get("source_row_count")
        == native.get("source_row_count"),
        "valid_row_count_matches": result.get("valid_row_count") == native.get("valid_row_count"),
        "unavailable_count_matches": result.get("unavailable_count")
        == native.get("unavailable_count"),
        "committed_write_count_positive": isinstance(committed, int)
        and not isinstance(committed, bool)
        and committed > 0,
        "committed_write_row_counts_present": isinstance(
            result.get("committed_write_row_counts"), list
        )
        and len(result.get("committed_write_row_counts")) > 0,
        "committed_write_row_counts_positive_and_valid": valid_row_counts,
    }


def _load_claim_readback(claim_key: str, period_key: str, *, deadline: float) -> dict[str, Any]:
    from sqlalchemy import select

    from app.db.database import async_session_maker, engine
    from app.models.akshare_mgmt import AkshareTaskRunClaim, TaskExecution

    async def read() -> dict[str, Any]:
        try:
            async with async_session_maker() as session:
                claim = await session.scalar(
                    select(AkshareTaskRunClaim).where(
                        AkshareTaskRunClaim.claim_key == claim_key,
                        AkshareTaskRunClaim.period_key == period_key,
                    )
                )
                if claim is None:
                    return {"claim_found": False}
                execution = (
                    await session.scalar(
                        select(TaskExecution).where(
                            TaskExecution.execution_id == claim.execution_id
                        )
                    )
                    if claim.execution_id
                    else None
                )
                return {
                    "claim_found": True,
                    "claim_key": claim.claim_key,
                    "script_id": claim.script_id,
                    "source": claim.source,
                    "period_key": claim.period_key,
                    "parameter_hash": claim.parameter_hash,
                    "task_id": claim.task_id,
                    "claim_status": claim.status,
                    "execution_id": claim.execution_id,
                    "execution_status": getattr(getattr(execution, "status", None), "value", None),
                    "execution_task_id": getattr(execution, "task_id", None),
                    "execution_operator_id": getattr(execution, "operator_id", None),
                }
        finally:
            await engine.dispose()

    return _run_async_bounded(read(), deadline=deadline, phase="managed claim readback")


def _summary_after_run(
    *,
    run_directory: Path,
    worker: Mapping[str, Any],
    dispatch: Mapping[str, Any],
    before: Mapping[str, Any],
    legacy_after: Sequence[Mapping[str, Any]],
    day_rows_after: Sequence[Mapping[str, Any]],
    exact_sql_rows: Sequence[Mapping[str, Any]],
    natural_after: Mapping[str, Any],
    claim_readback: Mapping[str, Any],
    parent_state: Mapping[str, Any],
) -> dict[str, Any]:
    wire = worker.get("wire_metadata") if isinstance(worker.get("wire_metadata"), Mapping) else {}
    native = (
        worker.get("native_evidence") if isinstance(worker.get("native_evidence"), Mapping) else {}
    )
    source_rows = native.get("source_rows") if isinstance(native.get("source_rows"), list) else []
    native_comparison = (
        compare_native_rows(
            source_rows,
            exact_sql_rows,
            before_target_rows=before.get("target_same_day_rows", []),
        )
        if source_rows
        else {"matched": False, "source_key_count": 0, "sql_key_count": len(exact_sql_rows)}
    )
    execution = worker.get("execution") if isinstance(worker.get("execution"), Mapping) else None
    receipt_checks = _execution_receipt_checks(execution, native)
    execution_result = execution.get("result") if isinstance(execution, Mapping) else None
    committed_count = (
        execution_result.get("committed_write_count")
        if isinstance(execution_result, Mapping)
        else None
    )
    committed_status = (
        committed_count > 0
        if isinstance(committed_count, int) and not isinstance(committed_count, bool)
        else None
    )
    observed_values = {
        row.get("observed_at") for row in exact_sql_rows if row.get("observed_at") is not None
    }
    observed_at = next(iter(observed_values)) if len(observed_values) == 1 else None
    received_at = native.get("received_at")
    observation_time_consistent = (
        len(observed_values) == 1
        and isinstance(observed_at, datetime)
        and isinstance(received_at, datetime)
        and _as_shanghai_naive(observed_at) >= _as_shanghai_naive(received_at)
        and all(
            isinstance(row.get("quote_time"), datetime)
            and _as_shanghai_naive(row["quote_time"]) <= _as_shanghai_naive(observed_at)
            for row in exact_sql_rows
        )
    )
    claim_matches = (
        claim_readback.get("claim_found") is True
        and claim_readback.get("claim_key") == dispatch.get("claim_key")
        and claim_readback.get("period_key") == dispatch.get("period_key")
        and claim_readback.get("source") == dispatch.get("source")
        and claim_readback.get("script_id") == SCRIPT_ID
        and claim_readback.get("task_id") is None
        and claim_readback.get("execution_task_id") is None
        and claim_readback.get("execution_operator_id") is None
        and claim_readback.get("claim_status") == "completed"
        and claim_readback.get("execution_status") == "completed"
    )
    legacy_before = before.get("legacy_full_hash", {})
    legacy_after_hash = _row_digest(legacy_after)
    legacy_unchanged = legacy_before == legacy_after_hash
    before_target = before.get("target_same_day_rows", [])
    expected_keys = {
        (row.get("quote_source"), row.get("symbol"), row.get("quote_time")) for row in source_rows
    }
    before_by_key = _table_rows_by_key(before_target)
    after_by_key = _table_rows_by_key(day_rows_after)
    before_outside = [row for key, row in before_by_key.items() if key not in expected_keys]
    after_outside = [row for key, row in after_by_key.items() if key not in expected_keys]
    target_outside_unchanged = _row_digest(before_outside) == _row_digest(after_outside)
    natural_unchanged = (
        natural_after.get("claim_sha256") == before.get("natural_claim", {}).get("claim_sha256")
        and natural_after.get("execution_sha256")
        == before.get("natural_claim", {}).get("execution_sha256")
        and natural_after.get("claim_found") is True
        and natural_after.get("execution_found") is True
    )
    request_count = wire.get("request_count", worker.get("wire_request_count", "unknown"))
    checks = {
        "wire_one_post_200": request_count == 1 and wire.get("status_code") == 200,
        "body_saved_before_parser": wire.get("body_fsynced_before_producer_parse") is True,
        "source_exact_main25": native.get("main_pair_count") == 25 and len(source_rows) == 25,
        "source_current_day_publication": (
            isinstance(native.get("quote_time"), datetime)
            and isinstance(native.get("received_at"), datetime)
            and native["quote_time"].date() == native["received_at"].date()
            and native["quote_time"] <= native["received_at"]
            and native["quote_time"].time() >= day_time(9, 30)
        ),
        "native_source_to_sql_exact_keys_and_fields": native_comparison.get("matched") is True,
        "publication_precedes_observation": observation_time_consistent,
        "natural_claim_and_execution_unchanged": natural_unchanged,
        "legacy_fx_spot_full_hash_unchanged": legacy_unchanged,
        "target_same_day_rows_outside_exact_keys_unchanged": target_outside_unchanged,
        "managed_claim_execution_matches": claim_matches,
        **receipt_checks,
    }
    return {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "run_id": dispatch.get("run_id"),
        "status": "verified_daytime_observation_batch"
        if all(checks.values())
        else "acceptance_failed_or_unknown",
        "checks": checks,
        "source_calls": request_count,
        "business_write_possible": bool(parent_state.get("child_started")),
        "business_write_committed": committed_status,
        "managed_dispatch": dict(dispatch),
        "managed_readback": dict(claim_readback),
        "managed_execution": execution,
        "wire": {key: value for key, value in wire.items() if key not in {"headers"}},
        "native_evidence": {
            key: value for key, value in native.items() if key not in {"source_rows"}
        },
        "native_to_sql_comparison": native_comparison,
        "legacy_fx_spot_hash_before": legacy_before,
        "legacy_fx_spot_hash_after": legacy_after_hash,
        "natural_claim_hash_before": before.get("natural_claim"),
        "natural_claim_hash_after": natural_after,
        "target_same_day_outside_hash_before": _row_digest(before_outside),
        "target_same_day_outside_hash_after": _row_digest(after_outside),
        "source_complete": False,
        "calendar_and_lifecycle": "unknown",
        "source_bid_ask_native_lexical_storage_preserved": native_comparison.get(
            "raw_bid_ask_original_lexical_text_saved_as_an_exact_value"
        ),
        "limitations": [
            "The acceptance requires AKShare's include_timestamp frame to retain the decoded pre-coercion bid/ask values; numeric JSON tokens are represented using the JSON decoder's value string form.",
            "The current source completeness denominator is only the reviewed 25-pair response set.",
            "No holiday or full market calendar completeness is claimed.",
        ],
    }


def _supervise(child: subprocess.Popen[Any], *, hard_seconds: float) -> dict[str, Any]:
    state: dict[str, Any] = {"timed_out": False, "term_sent": False, "kill_sent": False}
    hard = max(1.0, hard_seconds)
    term_at = max(1.0, hard - 10.0)
    kill_at = max(term_at + 0.1, hard - 5.0)
    try:
        child.wait(timeout=term_at)
    except subprocess.TimeoutExpired:
        state["timed_out"] = True
        state["term_sent"] = True
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=kill_at - term_at)
        except subprocess.TimeoutExpired:
            state["kill_sent"] = True
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=max(1, hard - kill_at))
    return state


def _terminate_child_after_parent_error(child: subprocess.Popen[Any]) -> dict[str, Any]:
    """Stop a dispatched child immediately if parent bookkeeping fails."""
    state = {"term_sent": False, "kill_sent": False, "exit_code": child.poll()}
    if state["exit_code"] is not None:
        return state
    state["term_sent"] = True
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        state["exit_code"] = child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        state["kill_sent"] = True
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        state["exit_code"] = child.wait(timeout=2)
    return state


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _apply(*, output_root: Path) -> dict[str, Any]:
    invocation_started = time.monotonic()
    deadline = invocation_started + PARENT_HARD_SECONDS
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    directory = _install_directory(output_root, run_id)
    params = {"_ingest_mode": "live", "_call_timeout": 30}
    parent_state: dict[str, Any] = {"child_started": False, "source_calls": 0}
    dispatch: dict[str, Any] = {}
    before: dict[str, Any] = {}
    child: subprocess.Popen[Any] | None = None
    try:
        registration, natural_claim = _run_async_bounded(
            _load_registration_and_natural_claim(),
            deadline=deadline - POST_DISPATCH_READBACK_RESERVE_SECONDS,
            phase="registration and protected natural claim preflight",
        )
        producer = importlib.import_module(SCRIPT_MODULE)
        if not getattr(producer, "PREFER_LOCAL_SCRIPT", False):
            raise RuntimeError("local CFETS producer preference is not enabled")
        if producer.FxSpotQuote().table_name != TABLE_NAME:
            raise RuntimeError("producer table does not match the reviewed observation table")
        schema = _validate_target_schema()
        local_day = datetime.now(SHANGHAI).date()
        connection = _warehouse_connection()
        try:
            target_day_before = _current_day_rows(connection, day=local_day, table_name=TABLE_NAME)
            legacy_rows_before = _all_legacy_rows(connection)
        finally:
            connection.close()
        natural_before = _run_async_bounded(
            _read_natural_claim_hashes(),
            deadline=deadline - POST_DISPATCH_READBACK_RESERVE_SECONDS,
            phase="protected natural claim preflight hash",
        )
        if (
            natural_before.get("claim_sha256") != natural_claim["claim_sha256"]
            or natural_before.get("execution_sha256") != natural_claim["execution_sha256"]
        ):
            raise RuntimeError("protected natural task 101 claim changed during preflight")
        before = {
            "warehouse_schema": schema.get("warehouse_schema"),
            "target_same_day_rows": target_day_before,
            "target_same_day_hash": _row_digest(target_day_before),
            "legacy_full_hash": _row_digest(legacy_rows_before),
            "natural_claim": natural_claim,
        }
        _write_json_exclusive(directory / "before.json", before)
        period_key = f"cfets-daytime-managed-acceptance:{run_id}"
        remaining_total = deadline - time.monotonic()
        child_budget = remaining_total - POST_DISPATCH_READBACK_RESERVE_SECONDS
        if child_budget < 20:
            raise TimeoutError("outer budget has no safe managed-call and readback reserve")
        managed_timeout = min(MANAGED_TIMEOUT_SECONDS, max(1, int(child_budget - 15)))
        claim_key, parameter_hash = _claim_identity(registration["source"], period_key, params)
        dispatch = {
            "run_id": run_id,
            "script_id": SCRIPT_ID,
            "source": registration["source"],
            "registration": registration,
            "parameters": params,
            "task_id": None,
            "operator_id": None,
            "triggered_by": "manual",
            "managed_timeout_seconds": managed_timeout,
            "period_key": period_key,
            "parameter_hash": parameter_hash,
            "claim_key": claim_key,
            "persisted_before_child_spawn": True,
            "source_http_timeout_seconds": SOURCE_HTTP_TIMEOUT_SECONDS,
        }
        _write_json_exclusive(directory / "dispatch.json", dispatch)
        _write_json_exclusive(
            directory / "invocation.json",
            {**dispatch, "output_directory": str(directory.resolve())},
        )
        stdout_path = directory / "stdout.log"
        stderr_path = directory / "stderr.log"
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            os.chmod(stdout_path, 0o600)
            os.chmod(stderr_path, 0o600)
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                str(directory),
                "--parent-pid",
                str(os.getpid()),
            ]
            _write_json_exclusive(
                directory / "dispatch-may-start.json",
                {
                    "created_at_utc": datetime.now(timezone.utc).isoformat(),
                    "source_or_write_possible_after_marker": True,
                },
            )
            child = subprocess.Popen(
                command,
                cwd=BACKEND,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            parent_state["child_started"] = True
            _write_json_exclusive(directory / "child.json", {"pid": child.pid, "argv": command})
            remaining_outer = deadline - time.monotonic()
            child_hard_budget = remaining_outer - POST_DISPATCH_READBACK_RESERVE_SECONDS
            if child_hard_budget <= 0:
                raise TimeoutError("outer deadline left no budget for child cleanup and readback")
            supervisor = _supervise(child, hard_seconds=child_hard_budget)
            parent_state["supervisor"] = supervisor

        worker = _load_json(directory / "worker-result.json")
        parent_state["source_calls"] = worker.get("wire_request_count", "unknown")
        wire_metadata = (
            worker.get("wire_metadata") if isinstance(worker.get("wire_metadata"), dict) else {}
        )
        native_body_path = wire_metadata.get("response_body_path")
        if native_body_path and Path(str(native_body_path)).is_file():
            native_body = Path(str(native_body_path)).read_bytes()
            if _sha256(native_body) != wire_metadata.get("response_body_sha256"):
                raise RuntimeError(
                    "persisted CFETS body SHA-256 changed before native verification"
                )
            received_at = _parse_timestamp(wire_metadata.get("response_received_at_shanghai"))
            native_independent = parse_native_response(native_body, received_at=received_at)
            worker["native_evidence"] = native_independent
        connection = _warehouse_connection()
        try:
            target_day_after = _current_day_rows(connection, day=local_day, table_name=TABLE_NAME)
            legacy_rows_after = _all_legacy_rows(connection)
            native = (
                worker.get("native_evidence")
                if isinstance(worker.get("native_evidence"), dict)
                else {}
            )
            exact_sql_rows = _query_exact_observation_rows(
                connection, native.get("source_rows", [])
            )
        finally:
            connection.close()
        natural_after = _run_async_bounded(
            _read_natural_claim_hashes(),
            deadline=deadline,
            phase="protected natural claim postflight hash",
        )
        claim_readback = _load_claim_readback(claim_key, period_key, deadline=deadline)
        if not worker:
            result = {
                "checked_at_utc": datetime.now(timezone.utc).isoformat(),
                "run_id": run_id,
                "status": "managed_outcome_unknown_write_possible",
                "source_calls": "unknown",
                "business_write_possible": True,
                "business_write_committed": None,
                "dispatch": dispatch,
                "dispatch_marker": True,
                "managed_readback": claim_readback,
                "supervisor": parent_state.get("supervisor"),
                "source_complete": False,
            }
        else:
            result = _summary_after_run(
                run_directory=directory,
                worker=worker,
                dispatch=dispatch,
                before=before,
                legacy_after=legacy_rows_after,
                day_rows_after=target_day_after,
                exact_sql_rows=exact_sql_rows,
                natural_after=natural_after,
                claim_readback=claim_readback,
                parent_state=parent_state,
            )
            result["supervisor"] = parent_state.get("supervisor")
            result["legacy_full_hash_before"] = before["legacy_full_hash"]
            result["legacy_full_hash_after"] = _row_digest(legacy_rows_after)
            result["target_same_day_hash_before"] = before["target_same_day_hash"]
            result["target_same_day_hash_after"] = _row_digest(target_day_after)
        try:
            _write_json_exclusive(directory / "acceptance-summary.json", result)
        except Exception as persist_exc:
            # The stdout receipt still carries a conservative result if local
            # storage fails after the child may have reached the managed writer.
            return {
                **result,
                "status": "acceptance_result_artifact_write_failed",
                "business_write_possible": True,
                "business_write_committed": result.get("business_write_committed"),
                "artifact_write_error": f"{type(persist_exc).__name__}: {persist_exc}"[:1000],
            }
        return result
    except BaseException as exc:
        dispatch_marker = (directory / "dispatch-may-start.json").exists()
        if child is not None and child.poll() is None:
            try:
                parent_state["exception_child_cleanup"] = _terminate_child_after_parent_error(child)
            except BaseException as cleanup_exc:
                parent_state["exception_child_cleanup"] = {
                    "status": "unknown",
                    "error_type": type(cleanup_exc).__name__,
                }
        failure = {
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "status": "failed_closed_write_possible"
            if dispatch_marker
            else "failed_closed_before_dispatch",
            "error_type": type(exc).__name__,
            "error": f"{type(exc).__name__}: {exc}"[:1500],
            "source_calls": "unknown" if dispatch_marker else 0,
            "business_write_possible": dispatch_marker,
            "business_write_committed": None if dispatch_marker else False,
            "dispatch": dispatch,
            "source_complete": False,
            "child_cleanup": parent_state.get("exception_child_cleanup"),
        }
        if not (directory / "acceptance-summary.json").exists():
            try:
                _write_json_exclusive(directory / "acceptance-summary.json", failure)
            except Exception as persist_exc:
                failure["artifact_write_error"] = f"{type(persist_exc).__name__}: {persist_exc}"[
                    :1000
                ]
        return failure


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply", action="store_true", help="run one managed daytime observation check"
    )
    mode.add_argument("--plan", action="store_true", help="print the no-I/O acceptance plan")
    mode.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--parent-pid", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(argv)
    try:
        if args.worker is not None:
            if args.parent_pid is None:
                raise ValueError("internal worker mode requires --parent-pid")
            return asyncio.run(_managed_worker(args.worker.resolve(), args.parent_pid))
        if args.plan or not args.apply:
            print(
                json.dumps(build_plan(output_root=args.output_root), ensure_ascii=False, indent=2)
            )
            return 0
        result = _apply(output_root=args.output_root)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("status") == "verified_daytime_observation_batch" else 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "mode": "error",
                    "status": "failed_closed_before_dispatch",
                    "error_type": type(exc).__name__,
                    "error": f"{type(exc).__name__}: {exc}"[:1500],
                    "source_calls": 0,
                    "business_write_possible": False,
                    "source_complete": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
