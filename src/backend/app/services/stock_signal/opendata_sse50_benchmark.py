"""Bounded OpenData reader for the SSE 50 stock-signal benchmark."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.services.market_data.opendata_credentials import (
    OpendataCredentials,
    OpendataCredentialsError,
)

_ROUTE = "/api/v1/data/index/index_daily"
_SYMBOL = "000016"
_SOURCE = "ths"
_LAYER = "dwd"
_ADJUST = "none"
_FIELDS = "trade_date,open,close"
_MAX_PAGE_SIZE = 1_000
_DEFAULT_PAGE_SIZE = 1_000
_MAX_ROWS = 20_000
_MAX_PAGES = 21  # One extra short/empty page proves the row limit was not truncated.
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_TOTAL_RESPONSE_BYTES = 32 * 1024 * 1024
_TIMEOUT_SECONDS = 10.0
_TOTAL_TIMEOUT_SECONDS = 30.0


class OpenDataSse50BenchmarkError(RuntimeError):
    """Stable, credential-free error for an invalid or unavailable response."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate keys instead of silently accepting ambiguous JSON."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_nonfinite_json_constant(value: str) -> None:
    """Reject non-standard NaN and infinity tokens accepted by Python's parser."""
    raise ValueError(f"non-finite JSON constant: {value}")


def _positive_finite_number(value: object) -> float | None:
    """Return a finite positive JSON number, excluding booleans and numeric strings."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


class OpenDataSse50BenchmarkReader:
    """Read only unadjusted SSE 50 index bars from the fixed OpenData route.

    This reader intentionally has no provider fallback. Its caller decides whether
    the disabled-by-default integration is selected; any failure is surfaced as a
    stable code so the stock-signal batch can preserve its existing empty-benchmark
    behavior without accidentally switching sources. A successful response, even
    with rows, does not establish full historical coverage or production readiness;
    keep the integration disabled until 000016 coverage and daily source differences
    are checked against Eastmoney and operational monitoring is in place.
    """

    def __init__(
        self,
        credentials: OpendataCredentials | None,
        *,
        client: httpx.AsyncClient | None = None,
        page_size: int = _DEFAULT_PAGE_SIZE,
        max_rows: int = _MAX_ROWS,
        max_pages: int = _MAX_PAGES,
        timeout_seconds: float = _TIMEOUT_SECONDS,
        total_timeout_seconds: float = _TOTAL_TIMEOUT_SECONDS,
        max_response_bytes: int = _MAX_RESPONSE_BYTES,
        max_total_response_bytes: int = _MAX_TOTAL_RESPONSE_BYTES,
    ) -> None:
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or not 1 <= page_size <= _MAX_PAGE_SIZE
        ):
            raise ValueError("page_size must be between 1 and the OpenData page limit")
        if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
            raise ValueError("max_rows must be positive")
        if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1:
            raise ValueError("max_pages must be positive")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        if not math.isfinite(total_timeout_seconds) or total_timeout_seconds <= 0:
            raise ValueError("total_timeout_seconds must be finite and positive")
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or isinstance(max_total_response_bytes, bool)
            or not isinstance(max_total_response_bytes, int)
            or max_response_bytes < 1
            or max_total_response_bytes < max_response_bytes
        ):
            raise ValueError("response byte limits are invalid")
        self._credentials = credentials
        self._client = client
        self._page_size = page_size
        self._max_rows = max_rows
        self._max_pages = max_pages
        self._timeout_seconds = timeout_seconds
        self._total_timeout_seconds = total_timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._max_total_response_bytes = max_total_response_bytes

    @classmethod
    def from_environment(cls) -> OpenDataSse50BenchmarkReader:
        """Resolve OpenData credentials from environment without exposing secrets."""
        try:
            credentials = OpendataCredentials.from_environment()
        except OpendataCredentialsError as exc:
            raise OpenDataSse50BenchmarkError(exc.code) from None
        return cls(credentials)

    async def fetch_rows(self, *, start_date: date, end_date: date) -> list[dict[str, Any]]:
        """Fetch the complete inclusive business-date window or fail closed.

        Returned ``open``/``close`` values remain native index points. The reader
        does not apply stock currency, share-price, or corporate-action transforms.
        """
        if (
            not isinstance(start_date, date)
            or isinstance(start_date, datetime)
            or not isinstance(end_date, date)
            or isinstance(end_date, datetime)
            or start_date > end_date
        ):
            raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_DATE_RANGE_INVALID")
        if self._credentials is None:
            raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_CREDENTIAL_MISSING")

        url = self._endpoint_url()
        if self._client is not None:
            return await self._fetch_with_deadline(
                self._client, url, start_date=start_date, end_date=end_date
            )

        async with httpx.AsyncClient(
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(self._timeout_seconds),
        ) as client:
            return await self._fetch_with_deadline(
                client, url, start_date=start_date, end_date=end_date
            )

    def _endpoint_url(self) -> str:
        """Validate the configured origin before joining a fixed route."""
        assert self._credentials is not None
        try:
            base_url = self._credentials.base_url
            parsed = urlsplit(base_url)
            hostname = parsed.hostname
            _ = parsed.port
        except ValueError:
            raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_BASE_URL_INVALID") from None
        if (
            parsed.scheme not in {"http", "https"}
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_BASE_URL_INVALID")
        return f"{base_url.rstrip('/')}{_ROUTE}"

    async def _fetch_with_deadline(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """Read every page under a hard total deadline and canonicalize rows."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._total_timeout_seconds
        total_bytes = 0
        rows: list[dict[str, Any]] = []
        previous_date: date | None = None

        for page in range(1, self._max_pages + 1):
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_TIMEOUT")
            params = {
                "symbols": _SYMBOL,
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "source": _SOURCE,
                "layer": _LAYER,
                "adjust": _ADJUST,
                "fields": _FIELDS,
                "page": page,
                "page_size": self._page_size,
            }
            try:
                page_data, page_bytes = await asyncio.wait_for(
                    self._read_page(client, url, params, remaining=remaining),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_TIMEOUT") from None
            except httpx.TimeoutException:
                raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_TIMEOUT") from None
            except httpx.TransportError:
                raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_TRANSPORT_ERROR") from None

            total_bytes += page_bytes
            if total_bytes > self._max_total_response_bytes:
                raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_RESPONSE_TOO_LARGE")

            page_rows = self._validate_page(
                page_data,
                expected_page=page,
                start_date=start_date,
                end_date=end_date,
            )
            for row in page_rows:
                business_date = date.fromisoformat(row["date"])
                if previous_date is not None and business_date <= previous_date:
                    raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_DATE_ORDER_INVALID")
                previous_date = business_date
                rows.append(row)
                if len(rows) > self._max_rows:
                    raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_ROW_LIMIT_EXCEEDED")

            if len(page_rows) < self._page_size:
                return rows
            if page == self._max_pages:
                raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_PAGE_LIMIT_EXCEEDED")

        raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_PAGE_LIMIT_EXCEEDED")

    async def _read_page(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: Mapping[str, Any],
        *,
        remaining: float,
    ) -> tuple[Mapping[str, Any], int]:
        """Stream and validate one response without forwarding credentials."""
        assert self._credentials is not None
        body = bytearray()
        try:
            async with client.stream(
                "GET",
                url,
                params=dict(params),
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "X-API-Key": self._credentials.api_key,
                },
                timeout=min(self._timeout_seconds, remaining),
                follow_redirects=False,
            ) as response:
                if not 200 <= response.status_code < 300:
                    if response.status_code == 401:
                        code = "OPENDATA_SSE50_UNAUTHORIZED"
                    elif response.status_code == 403:
                        code = "OPENDATA_SSE50_FORBIDDEN"
                    elif response.status_code == 429:
                        code = "OPENDATA_SSE50_RATE_LIMITED"
                    else:
                        code = "OPENDATA_SSE50_HTTP_ERROR"
                    raise OpenDataSse50BenchmarkError(code)

                content_type = response.headers.get("content-type", "")
                if content_type.split(";", maxsplit=1)[0].strip().lower() != "application/json":
                    raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_CONTENT_TYPE_INVALID")
                encoding = response.headers.get("content-encoding", "identity").strip().lower()
                if encoding not in {"", "identity"}:
                    raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_CONTENT_ENCODING_INVALID")
                declared_length = response.headers.get("content-length")
                if declared_length is not None:
                    try:
                        parsed_length = int(declared_length)
                    except ValueError:
                        raise OpenDataSse50BenchmarkError(
                            "OPENDATA_SSE50_CONTENT_LENGTH_INVALID"
                        ) from None
                    if parsed_length < 0 or parsed_length > self._max_response_bytes:
                        raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_RESPONSE_TOO_LARGE")
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > self._max_response_bytes:
                        raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_RESPONSE_TOO_LARGE")
                    body.extend(chunk)
        except OpenDataSse50BenchmarkError:
            raise
        except httpx.TimeoutException:
            raise
        except httpx.TransportError:
            raise
        except Exception:
            raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_RESPONSE_INVALID") from None

        try:
            payload = json.loads(
                body.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_nonfinite_json_constant,
            )
        except (UnicodeDecodeError, ValueError):
            raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_RESPONSE_INVALID_JSON") from None
        if not isinstance(payload, Mapping):
            raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_ENVELOPE_INVALID")
        if payload.get("success") is not True:
            raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_ENVELOPE_FAILURE")
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_DATA_INVALID")
        return data, len(body)

    def _validate_page(
        self,
        data: Mapping[str, Any],
        *,
        expected_page: int,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """Validate response identity, pagination metadata, and every business row."""
        expected_metadata = {
            "domain": "index_daily",
            "asset_class": "index",
            "layer": _LAYER,
            "source": _SOURCE,
            "adjust": _ADJUST,
        }
        if any(data.get(key) != value for key, value in expected_metadata.items()):
            raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_IDENTITY_MISMATCH")

        columns = data.get("columns")
        if (
            not isinstance(columns, list)
            or any(not isinstance(column, str) for column in columns)
            or len(set(columns)) != len(columns)
            or not {"symbol", "trade_date", "open", "close"}.issubset(columns)
        ):
            raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_COLUMNS_INVALID")

        page = data.get("page")
        page_size = data.get("page_size")
        count = data.get("count")
        if isinstance(page, bool) or not isinstance(page, int) or page != expected_page:
            raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_PAGE_MISMATCH")
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or page_size != self._page_size
        ):
            raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_PAGE_SIZE_MISMATCH")
        rows = data.get("rows")
        if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
            raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_ROWS_INVALID")
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or count != len(rows)
            or count < 0
            or count > self._page_size
        ):
            raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_COUNT_INVALID")

        canonical: list[dict[str, Any]] = []
        seen_dates: set[date] = set()
        for row in rows:
            if row.get("symbol") != _SYMBOL:
                raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_SYMBOL_MISMATCH")
            raw_date = row.get("trade_date")
            if not isinstance(raw_date, str):
                raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_DATE_INVALID")
            try:
                business_date = date.fromisoformat(raw_date)
            except ValueError:
                raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_DATE_INVALID") from None
            if business_date.isoformat() != raw_date:
                raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_DATE_INVALID")
            if not start_date <= business_date <= end_date:
                raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_DATE_OUT_OF_RANGE")
            if business_date in seen_dates:
                raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_DUPLICATE_DATE")
            seen_dates.add(business_date)

            open_price = _positive_finite_number(row.get("open"))
            close_price = _positive_finite_number(row.get("close"))
            if open_price is None or close_price is None:
                raise OpenDataSse50BenchmarkError("OPENDATA_SSE50_PRICE_INVALID")
            canonical.append(
                {
                    "date": business_date.isoformat(),
                    "open": open_price,
                    "close": close_price,
                }
            )
        return canonical


__all__ = ["OpenDataSse50BenchmarkError", "OpenDataSse50BenchmarkReader"]
