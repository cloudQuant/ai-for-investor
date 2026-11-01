"""Bounded, fixed-domain proxy for OpenData ``stock_daily`` freshness."""

from __future__ import annotations

import asyncio
import json
import math
from datetime import date, datetime, timezone
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr, ValidationError

from app.schemas.market_data_trust import OpenDataStockDailyFreshnessResponse
from app.services.market_data.opendata_credentials import (
    OpendataCredentials,
    OpendataCredentialsError,
)

_FRESHNESS_PATH = "/api/v1/data/domains/stock_daily/freshness"
_MAX_RESPONSE_BYTES = 16 * 1024
_TIMEOUT_SECONDS = 5.0


class OpenDataStockDailyFreshnessError(RuntimeError):
    """Safe public error for the OpenData freshness proxy."""

    def __init__(self, code: str, *, status_code: int = 503) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


class _FreshnessData(BaseModel):
    """Strict upstream DTO; do not forward unvalidated upstream fields."""

    model_config = ConfigDict(extra="forbid", strict=True)

    domain: Literal["stock_daily"]
    source: None
    status: Literal["fresh", "stale", "missing"]
    latest: StrictStr | None = None
    expected_data_date: StrictStr
    field: StrictStr | None = None
    lag_days: StrictInt | None = None


class _FreshnessEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    success: StrictBool
    message: StrictStr | None = None
    data: _FreshnessData


def _parse_iso_date(value: str) -> date:
    if len(value) != 10:
        raise ValueError("date format")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("date format")
    return parsed


def _validated_response(payload: Any) -> OpenDataStockDailyFreshnessResponse:
    try:
        envelope = _FreshnessEnvelope.model_validate(payload)
        if envelope.success is not True:
            raise ValueError("unsuccessful envelope")
        data = envelope.data
        expected = _parse_iso_date(data.expected_data_date)
        latest = _parse_iso_date(data.latest) if data.latest is not None else None

        if data.status == "missing":
            if latest is not None or data.lag_days is not None or data.field is not None:
                raise ValueError("inconsistent missing status")
        else:
            if latest is None or data.lag_days is None or not data.field:
                raise ValueError("incomplete freshness data")
            if data.lag_days != (expected - latest).days:
                raise ValueError("inconsistent freshness lag")
            if (data.status == "fresh") != (data.lag_days <= 0):
                raise ValueError("inconsistent freshness status")

        return OpenDataStockDailyFreshnessResponse(
            provider="opendata",
            domain="stock_daily",
            source=None,
            field=data.field,
            latest=latest,
            lag_days=data.lag_days,
            status=data.status,
            expected_data_date=expected,
            checked_at=datetime.now(timezone.utc),
        )
    except (ValidationError, TypeError, ValueError, OverflowError):
        raise OpenDataStockDailyFreshnessError(
            "OPENDATA_FRESHNESS_RESPONSE_INVALID", status_code=502
        ) from None


class OpenDataStockDailyFreshnessService:
    """Read the fixed DWD freshness route without touching AFI market-data stores."""

    def __init__(
        self,
        *,
        credentials: OpendataCredentials,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = _TIMEOUT_SECONDS,
        max_response_bytes: int = _MAX_RESPONSE_BYTES,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        self._credentials = credentials
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes

    async def read(self) -> OpenDataStockDailyFreshnessResponse:
        """Fetch and validate one bounded, source-independent DWD status."""
        base = urlsplit(self._credentials.base_url)
        if (
            base.scheme not in {"http", "https"}
            or not base.hostname
            or base.username is not None
            or base.password is not None
            or base.query
            or base.fragment
        ):
            raise OpenDataStockDailyFreshnessError("OPENDATA_FRESHNESS_CONFIG_INVALID")

        try:
            body = await asyncio.wait_for(
                self._fetch_body(f"{self._credentials.base_url}{_FRESHNESS_PATH}"),
                timeout=self._timeout_seconds,
            )
        except OpenDataStockDailyFreshnessError:
            raise
        except (asyncio.TimeoutError, httpx.TimeoutException, httpx.TransportError):
            raise OpenDataStockDailyFreshnessError("OPENDATA_FRESHNESS_UNAVAILABLE") from None
        except Exception:
            # Stream protocol and custom-transport failures must remain bounded
            # public errors; never forward their implementation details.
            raise OpenDataStockDailyFreshnessError("OPENDATA_FRESHNESS_UNAVAILABLE") from None

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise OpenDataStockDailyFreshnessError(
                "OPENDATA_FRESHNESS_RESPONSE_INVALID", status_code=502
            ) from None
        return _validated_response(payload)

    async def _fetch_body(self, endpoint: str) -> bytes:
        """Read a bounded raw wire body; the caller applies the total deadline."""
        async with httpx.AsyncClient(
            transport=self._transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(self._timeout_seconds),
        ) as client:
            async with client.stream(
                "GET",
                endpoint,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "X-API-Key": self._credentials.api_key,
                },
            ) as response:
                if response.status_code == 429:
                    raise OpenDataStockDailyFreshnessError(
                        "OPENDATA_FRESHNESS_RATE_LIMITED", status_code=429
                    )
                if response.status_code < 200 or response.status_code >= 300:
                    raise OpenDataStockDailyFreshnessError("OPENDATA_FRESHNESS_UNAVAILABLE")
                content_type = response.headers.get("content-type", "")
                if content_type.split(";", maxsplit=1)[0].strip().lower() != "application/json":
                    raise OpenDataStockDailyFreshnessError(
                        "OPENDATA_FRESHNESS_RESPONSE_INVALID", status_code=502
                    )
                content_encoding = response.headers.get("content-encoding", "identity")
                if content_encoding.strip().lower() not in {"", "identity"}:
                    raise OpenDataStockDailyFreshnessError(
                        "OPENDATA_FRESHNESS_RESPONSE_INVALID", status_code=502
                    )
                declared_length = response.headers.get("content-length")
                if declared_length is not None:
                    try:
                        parsed_length = int(declared_length)
                        if parsed_length < 0 or parsed_length > self._max_response_bytes:
                            raise OpenDataStockDailyFreshnessError(
                                "OPENDATA_FRESHNESS_RESPONSE_INVALID", status_code=502
                            )
                    except ValueError:
                        raise OpenDataStockDailyFreshnessError(
                            "OPENDATA_FRESHNESS_RESPONSE_INVALID", status_code=502
                        ) from None

                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_raw():
                    total += len(chunk)
                    if total > self._max_response_bytes:
                        raise OpenDataStockDailyFreshnessError(
                            "OPENDATA_FRESHNESS_RESPONSE_INVALID", status_code=502
                        )
                    chunks.append(chunk)
                return b"".join(chunks)


def get_opendata_stock_daily_freshness_service() -> OpenDataStockDailyFreshnessService:
    """Build the proxy with server-owned credentials; missing config fails closed."""
    try:
        credentials = OpendataCredentials.from_environment()
    except OpendataCredentialsError:
        raise OpenDataStockDailyFreshnessError("OPENDATA_FRESHNESS_CONFIG_INVALID") from None
    if credentials is None:
        raise OpenDataStockDailyFreshnessError("OPENDATA_FRESHNESS_CONFIG_INVALID")
    return OpenDataStockDailyFreshnessService(credentials=credentials)


__all__ = [
    "OpenDataStockDailyFreshnessError",
    "OpenDataStockDailyFreshnessService",
    "get_opendata_stock_daily_freshness_service",
]
