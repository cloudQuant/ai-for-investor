"""Read bounded, source-native financial observations from OpenData."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import re
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.services.market_data.opendata_credentials import (
    OpendataCredentials,
    OpendataCredentialsError,
)

_ROUTE = "/api/v2/data/financial-statements/archive"
_SOURCE_ID = "ths_fuyao"
_STATEMENT_TYPES = ("income", "balance", "cashflow")
_PERIODICITIES = ("annual", "quarterly")
_MAX_PAGE_SIZE = 199
_MAX_RESPONSE_BYTES = 256 * 1024
_MAX_ARCHIVE_RESPONSE_BYTES = 1024 * 1024
_STREAM_CHUNK_BYTES = 64 * 1024
_REQUEST_TIMEOUT_SECONDS = 8.0
_TOTAL_TIMEOUT_SECONDS = 30.0
_RECORD_FIELDS = (
    "source_id",
    "instrument_id",
    "statement_type",
    "periodicity",
    "report_period",
    "source_disclosure_date",
    "observed_at_utc",
    "item_code",
    "value_decimal_text",
    "native_unit",
)
_INSTRUMENT_ID_PATTERN = re.compile(r"[0-9]{6}\.(?:SH|SZ|BJ)", re.ASCII)
_DECIMAL_TEXT_PATTERN = re.compile(
    r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?",
    re.ASCII,
)
_RESPONSE_FIELDS = frozenset(
    {
        "scope",
        "records",
        "completeness",
        "point_in_time_reconstruction",
        "period_amount_semantics",
    }
)


class OpenDataFinancialArchiveError(RuntimeError):
    """Stable error code that never includes a URL, credential, or response body."""

    def __init__(self, code: str, *, response_bytes: int = 0) -> None:
        self.code = code
        self.response_bytes = response_bytes
        super().__init__(code)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON keys instead of accepting ambiguous responses."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


class OpenDataFinancialArchiveReader:
    """Read bounded ``ths_fuyao`` archive pages while preserving native evidence.

    The reader has no provider fallback. It validates the fixed request scope and
    every response row, keeps decimal text and source timestamps verbatim, and
    returns only stable failure codes. Successful rows remain raw evidence: this
    class does not map item codes, units, or period semantics into analysis metrics.
    """

    def __init__(
        self,
        credentials: OpendataCredentials | None,
        *,
        client: httpx.AsyncClient | None = None,
        configuration_error: str | None = None,
        request_timeout_seconds: float = _REQUEST_TIMEOUT_SECONDS,
        total_timeout_seconds: float = _TOTAL_TIMEOUT_SECONDS,
        max_response_bytes: int = _MAX_RESPONSE_BYTES,
        max_archive_response_bytes: int = _MAX_ARCHIVE_RESPONSE_BYTES,
        allowed_hosts: str | set[str] | frozenset[str] | None = None,
    ) -> None:
        if (
            not math.isfinite(request_timeout_seconds)
            or request_timeout_seconds <= 0
            or request_timeout_seconds > _REQUEST_TIMEOUT_SECONDS
        ):
            raise ValueError("request timeout must be finite and positive")
        if (
            not math.isfinite(total_timeout_seconds)
            or total_timeout_seconds <= 0
            or total_timeout_seconds > _TOTAL_TIMEOUT_SECONDS
        ):
            raise ValueError("total timeout must be finite and positive")
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or max_response_bytes < 1
            or max_response_bytes > _MAX_RESPONSE_BYTES
        ):
            raise ValueError("response byte limit must be positive")
        if (
            isinstance(max_archive_response_bytes, bool)
            or not isinstance(max_archive_response_bytes, int)
            or max_archive_response_bytes < 1
            or max_archive_response_bytes > _MAX_ARCHIVE_RESPONSE_BYTES
        ):
            raise ValueError("archive response byte limit must be positive")
        self._credentials = credentials
        self._client = client
        self._configuration_error = configuration_error
        self._request_timeout_seconds = request_timeout_seconds
        self._total_timeout_seconds = total_timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._max_archive_response_bytes = max_archive_response_bytes
        if allowed_hosts is None:
            self._allowed_origins = frozenset()
        elif isinstance(allowed_hosts, str):
            self._allowed_origins, allowlist_error = _parse_allowed_origins(
                host for host in allowed_hosts.split(",") if host.strip()
            )
            self._configuration_error = configuration_error or allowlist_error
        elif isinstance(allowed_hosts, (set, frozenset)):
            if any(not isinstance(host, str) for host in allowed_hosts):
                raise ValueError("allowed hosts must contain only strings")
            self._allowed_origins, allowlist_error = _parse_allowed_origins(
                host for host in allowed_hosts if host.strip()
            )
            self._configuration_error = configuration_error or allowlist_error
        else:
            raise ValueError("allowed hosts must be a comma-separated string or a set")

    @classmethod
    def from_environment(
        cls,
        *,
        allowed_hosts: str | set[str] | frozenset[str] | None = None,
    ) -> OpenDataFinancialArchiveReader:
        """Resolve the shared OpenData credential reference without exposing it."""
        if allowed_hosts is None:
            import os

            allowed_hosts = os.environ.get(
                "STOCK_ANALYSIS_OPENDATA_FINANCIAL_ARCHIVE_ALLOWED_HOSTS", ""
            )
        try:
            credentials = OpendataCredentials.from_environment()
        except OpendataCredentialsError as exc:
            return cls(None, configuration_error=exc.code, allowed_hosts=allowed_hosts)
        return cls(credentials, allowed_hosts=allowed_hosts)

    async def fetch_analysis_evidence(
        self,
        *,
        instrument_id: str,
        analysis_date: date,
    ) -> dict[str, Any]:
        """Fetch the existing stock-analysis lookback window as raw archive evidence."""
        if not isinstance(analysis_date, date) or isinstance(analysis_date, datetime):
            raise OpenDataFinancialArchiveError("analysis_date_invalid")
        if (
            not isinstance(instrument_id, str)
            or _INSTRUMENT_ID_PATTERN.fullmatch(instrument_id) is None
        ):
            raise OpenDataFinancialArchiveError("instrument_id_invalid")

        start_report_period = date(max(1, analysis_date.year - 2), 1, 1)
        scopes = [
            {
                "source_id": _SOURCE_ID,
                "instrument_id": instrument_id,
                "statement_type": statement_type,
                "periodicity": periodicity,
                "start_report_period": start_report_period.isoformat(),
                "end_report_period": analysis_date.isoformat(),
            }
            for statement_type in _STATEMENT_TYPES
            for periodicity in _PERIODICITIES
        ]

        started_at = asyncio.get_running_loop().time()
        if self._client is not None:
            queries = await self._fetch_scopes(self._client, scopes, started_at=started_at)
        else:
            async with httpx.AsyncClient(
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(self._request_timeout_seconds),
            ) as client:
                queries = await self._fetch_scopes(client, scopes, started_at=started_at)

        records = [record for query in queries for record in query.get("records", [])]
        future_disclosure_count = sum(
            record["source_disclosure_date"] > analysis_date.isoformat() for record in records
        )
        for record in records:
            record["disclosure_date_relation_to_analysis_date"] = (
                "after_analysis_date"
                if record["source_disclosure_date"] > analysis_date.isoformat()
                else "on_or_before_analysis_date"
            )
        successful_queries = sum(query["status"] == "ok" for query in queries)
        failed_queries = [query for query in queries if query["status"] != "ok"]
        if failed_queries and successful_queries:
            result_status = "partial"
        elif failed_queries:
            result_status = "unavailable"
        elif records:
            result_status = "observed"
        else:
            result_status = "empty"

        return {
            "source": "opendata",
            "source_id": _SOURCE_ID,
            "instrument_id": instrument_id,
            "status": result_status,
            "requested_window": {
                "start_report_period": start_report_period.isoformat(),
                "end_report_period": analysis_date.isoformat(),
            },
            "queries": [
                {
                    "statement_type": query["statement_type"],
                    "periodicity": query["periodicity"],
                    "status": query["status"],
                    "record_count": len(query.get("records", [])),
                    **({"reason_code": query["reason_code"]} if "reason_code" in query else {}),
                }
                for query in queries
            ],
            "records": records,
            "single_page_limit": _MAX_PAGE_SIZE,
            "pagination_supported": False,
            "future_disclosure_record_count": future_disclosure_count,
            "historical_as_of_status": "unavailable",
            "analysis_date_filtering": "report_period_only",
            "completeness": "unknown",
            "point_in_time_reconstruction": "unavailable",
            "period_amount_semantics": "unknown",
            "provenance_status": "incomplete",
            "observation_time_semantics": "deduplicated_observation_timestamp_not_capture_time",
            "normalization_status": "unreviewed",
            "eligible_for_decision_or_backtest": False,
        }

    async def _fetch_scopes(
        self,
        client: httpx.AsyncClient,
        scopes: list[dict[str, str]],
        *,
        started_at: float,
    ) -> list[dict[str, Any]]:
        queries: list[dict[str, Any]] = []
        authorization_failed = False
        aggregate_limit_reached = False
        total_retained_response_bytes = 0
        for scope in scopes:
            if authorization_failed:
                queries.append(
                    {
                        "statement_type": scope["statement_type"],
                        "periodicity": scope["periodicity"],
                        "status": "not_attempted",
                        "reason_code": "authorization_failed",
                        "records": [],
                    }
                )
                continue
            if aggregate_limit_reached:
                queries.append(
                    {
                        "statement_type": scope["statement_type"],
                        "periodicity": scope["periodicity"],
                        "status": "not_attempted",
                        "reason_code": "archive_response_too_large",
                        "records": [],
                    }
                )
                continue

            try:
                remaining = self._total_timeout_seconds - (
                    asyncio.get_running_loop().time() - started_at
                )
                if remaining <= 0:
                    raise OpenDataFinancialArchiveError("timeout")
                remaining_archive_bytes = (
                    self._max_archive_response_bytes - total_retained_response_bytes
                )
                if remaining_archive_bytes <= 0:
                    raise OpenDataFinancialArchiveError("archive_response_too_large")
                scope_response_limit = min(self._max_response_bytes, remaining_archive_bytes)
                overflow_code = (
                    "archive_response_too_large"
                    if remaining_archive_bytes <= self._max_response_bytes
                    else "response_too_large"
                )
                records, response_bytes = await asyncio.wait_for(
                    self._read_scope(
                        client,
                        scope,
                        timeout_seconds=min(self._request_timeout_seconds, remaining),
                        max_response_bytes=scope_response_limit,
                        overflow_code=overflow_code,
                    ),
                    timeout=remaining,
                )
            except OpenDataFinancialArchiveError as exc:
                records = []
                error_code = exc.code
                total_retained_response_bytes += exc.response_bytes
            except (asyncio.TimeoutError, httpx.TimeoutException):
                records = []
                error_code = "timeout"
            except httpx.TransportError:
                records = []
                error_code = "transport_error"
            else:
                error_code = None
                total_retained_response_bytes += response_bytes

            query_result: dict[str, Any] = {
                "statement_type": scope["statement_type"],
                "periodicity": scope["periodicity"],
                "status": "ok" if error_code is None else "failed",
                "records": records,
            }
            if error_code is not None:
                query_result["reason_code"] = error_code
                authorization_failed = error_code in {
                    "http_401_unauthorized",
                    "http_403_forbidden",
                }
                aggregate_limit_reached = error_code == "archive_response_too_large"
            queries.append(query_result)
        return queries

    async def _read_scope(
        self,
        client: httpx.AsyncClient,
        scope: dict[str, str],
        *,
        timeout_seconds: float,
        max_response_bytes: int,
        overflow_code: str,
    ) -> tuple[list[dict[str, Any]], int]:
        if self._configuration_error is not None:
            raise OpenDataFinancialArchiveError(self._configuration_error)
        if self._credentials is None:
            raise OpenDataFinancialArchiveError("credential_missing")
        url = self._endpoint_url()
        body = bytearray()
        try:
            async with client.stream(
                "GET",
                url,
                params={**scope, "page_size": _MAX_PAGE_SIZE},
                headers={"X-API-Key": self._credentials.api_key, "Accept": "application/json"},
                timeout=httpx.Timeout(timeout_seconds),
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    reason_code = {
                        401: "http_401_unauthorized",
                        403: "http_403_forbidden",
                        413: "archive_scope_page_limit_exceeded",
                        422: "http_422_invalid_request",
                        429: "http_429_rate_limited",
                    }.get(response.status_code)
                    if reason_code is None:
                        reason_code = (
                            f"http_{response.status_code}_server_error"
                            if response.status_code >= 500
                            else "http_error"
                        )
                    raise OpenDataFinancialArchiveError(reason_code)
                if "application/json" not in response.headers.get("content-type", "").lower():
                    raise OpenDataFinancialArchiveError("content_type_invalid")
                async for chunk in response.aiter_bytes(chunk_size=_STREAM_CHUNK_BYTES):
                    if len(body) + len(chunk) > max_response_bytes:
                        raise OpenDataFinancialArchiveError(
                            overflow_code,
                            # The decoded chunk that crossed the limit is discarded.
                            # Aggregate accounting covers bytes retained in the body;
                            # the bounded stream chunk is transient and never appended.
                            response_bytes=len(body),
                        )
                    body.extend(chunk)
        except (httpx.TimeoutException, asyncio.TimeoutError):
            raise OpenDataFinancialArchiveError("timeout", response_bytes=len(body)) from None
        except httpx.TransportError:
            raise OpenDataFinancialArchiveError(
                "transport_error", response_bytes=len(body)
            ) from None

        try:
            payload = json.loads(
                body.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
            records = self._validate_payload(payload, expected_scope=scope)
        except OpenDataFinancialArchiveError as exc:
            exc.response_bytes = len(body)
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            raise OpenDataFinancialArchiveError(
                "response_json_invalid", response_bytes=len(body)
            ) from None
        return records, len(body)

    def _endpoint_url(self) -> str:
        assert self._credentials is not None
        try:
            parsed = urlsplit(self._credentials.base_url)
            hostname = parsed.hostname
            configured_port = parsed.port
        except ValueError:
            raise OpenDataFinancialArchiveError("base_url_invalid") from None
        if (
            parsed.scheme not in {"http", "https"}
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or configured_port == 0
        ):
            raise OpenDataFinancialArchiveError("base_url_invalid")
        normalized_hostname = hostname.lower().rstrip(".")
        port = configured_port if configured_port is not None else (
            443 if parsed.scheme == "https" else 80
        )
        is_loopback = _is_loopback_host(normalized_hostname)
        if parsed.scheme == "http" and not is_loopback:
            raise OpenDataFinancialArchiveError("base_url_insecure_transport")
        if not is_loopback and (normalized_hostname, port) not in self._allowed_origins:
            raise OpenDataFinancialArchiveError("base_url_host_not_allowed")
        return f"{self._credentials.base_url.rstrip('/')}{_ROUTE}"

    @classmethod
    def _validate_payload(
        cls,
        payload: Any,
        *,
        expected_scope: dict[str, str],
    ) -> list[dict[str, Any]]:
        if not isinstance(payload, dict) or set(payload) != _RESPONSE_FIELDS:
            raise OpenDataFinancialArchiveError("response_shape_invalid")
        if payload.get("scope") != expected_scope:
            raise OpenDataFinancialArchiveError("response_scope_mismatch")
        if (
            payload.get("completeness") != "unknown"
            or payload.get("point_in_time_reconstruction") != "unavailable"
            or payload.get("period_amount_semantics") != "unknown"
        ):
            raise OpenDataFinancialArchiveError("response_semantics_invalid")
        rows = payload.get("records")
        if not isinstance(rows, list):
            raise OpenDataFinancialArchiveError("response_records_invalid")
        if len(rows) > _MAX_PAGE_SIZE:
            raise OpenDataFinancialArchiveError("response_row_limit_exceeded")
        return [cls._validate_record(row, expected_scope=expected_scope) for row in rows]

    @staticmethod
    def _validate_record(row: Any, *, expected_scope: dict[str, str]) -> dict[str, Any]:
        if not isinstance(row, dict) or set(row) != set(_RECORD_FIELDS):
            raise OpenDataFinancialArchiveError("response_record_shape_invalid")
        for field in ("source_id", "instrument_id", "statement_type", "periodicity"):
            expected = expected_scope[field]
            if row.get(field) != expected:
                raise OpenDataFinancialArchiveError("response_record_scope_mismatch")

        report_period = row.get("report_period")
        disclosure_date = row.get("source_disclosure_date")
        observed_at = row.get("observed_at_utc")
        item_code = row.get("item_code")
        native_unit = row.get("native_unit")
        decimal_text = row.get("value_decimal_text")
        if not _is_iso_date(report_period) or not _is_iso_date(disclosure_date):
            raise OpenDataFinancialArchiveError("response_date_invalid")
        if not expected_scope["start_report_period"] <= report_period <= expected_scope[
            "end_report_period"
        ]:
            raise OpenDataFinancialArchiveError("response_record_period_out_of_scope")
        if (
            not isinstance(observed_at, str)
            or len(observed_at) > 40
            or not observed_at.endswith("Z")
        ):
            raise OpenDataFinancialArchiveError("response_observed_at_invalid")
        try:
            parsed_observed_at = datetime.fromisoformat(observed_at[:-1] + "+00:00")
        except ValueError:
            raise OpenDataFinancialArchiveError("response_observed_at_invalid") from None
        if parsed_observed_at.utcoffset() != timedelta(0):
            raise OpenDataFinancialArchiveError("response_observed_at_invalid")
        if parsed_observed_at.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ) != observed_at:
            raise OpenDataFinancialArchiveError("response_observed_at_invalid")
        if not isinstance(item_code, str) or not item_code.strip() or len(item_code) > 256:
            raise OpenDataFinancialArchiveError("response_item_code_invalid")
        if not isinstance(native_unit, str) or not native_unit.strip() or len(native_unit) > 128:
            raise OpenDataFinancialArchiveError("response_native_unit_invalid")
        if decimal_text is not None:
            if (
                not isinstance(decimal_text, str)
                or not decimal_text
                or len(decimal_text) > 128
                or _DECIMAL_TEXT_PATTERN.fullmatch(decimal_text) is None
            ):
                raise OpenDataFinancialArchiveError("response_decimal_invalid")
            try:
                value = Decimal(decimal_text)
            except InvalidOperation:
                raise OpenDataFinancialArchiveError("response_decimal_invalid") from None
            if not value.is_finite():
                raise OpenDataFinancialArchiveError("response_decimal_invalid")

        # Return only allowlisted fields, retaining the exact ISO and decimal text.
        return {field: row[field] for field in _RECORD_FIELDS}


def _is_iso_date(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _parse_allowed_origins(
    host_entries: Iterable[str],
) -> tuple[frozenset[tuple[str, int]], str | None]:
    """Parse exact HTTPS hosts; a bare hostname pins the standard port 443."""
    origins: set[tuple[str, int]] = set()
    for raw_entry in host_entries:
        entry = raw_entry.strip()
        if not entry:
            continue
        try:
            parsed = urlsplit(f"//{entry}")
            hostname = parsed.hostname
            configured_port = parsed.port
        except ValueError:
            return frozenset(), "allowed_hosts_invalid"
        if (
            not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or entry.endswith(":")
            or any(character.isspace() for character in entry)
            or "\\" in entry
            or (configured_port is not None and configured_port == 0)
        ):
            return frozenset(), "allowed_hosts_invalid"
        origins.add((hostname.lower().rstrip("."), configured_port or 443))
    return frozenset(origins), None


def _is_loopback_host(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


__all__ = ["OpenDataFinancialArchiveError", "OpenDataFinancialArchiveReader"]
