"""Explicit, bounded AFI client for OpenData's pinned temporal-identity API.

This module has no environment, settings, database, provider-selection, or cache
access. A caller must provide operator-trusted pin values and invoke one
resolution method explicitly. Every transport or contract failure is reduced
to a fixed error code; request credentials and upstream bodies are never added
to exception text.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, TypeGuard
from urllib.parse import urlsplit

import httpx

from app.services.market_data.opendata_credentials import OpendataCredentials

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,127}$", re.ASCII)
_SYMBOL = re.compile(r"^[0-9]{6}$", re.ASCII)
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", re.ASCII)
_API_KEY = re.compile(r"^[\x21-\x7e]{1,1024}$", re.ASCII)
_EXCHANGES = frozenset({"XSHG", "XSHE", "XBSE"})
_PATH = "/api/v2/identity/resolve"
_REQUEST_FIELDS = frozenset(
    {
        "dataset_id",
        "authority_id",
        "registry_id",
        "reference_version",
        "snapshot_sha256",
        "window_start",
        "window_end_exclusive",
        "exchange",
        "symbol",
        "instrument_id",
    }
)
_RESPONSE_FIELDS = frozenset(
    {
        "dataset_id",
        "authority_id",
        "registry_id",
        "reference_version",
        "snapshot_sha256",
        "subject",
        "pair",
        "instrument_id",
        "window",
        "segments",
        "completeness",
        "source_integrity",
    }
)
_WINDOW_FIELDS = frozenset({"start", "end_exclusive", "semantics"})
_SEGMENT_FIELDS = frozenset(
    {
        "start",
        "end_exclusive",
        "status",
        "assignment_id",
        "instrument_id",
        "pair",
        "source_id",
        "source_version",
    }
)
_MAX_REQUEST_BYTES = 8 * 1024
_MAX_RESPONSE_BYTES = 512 * 1024
_MAX_SEGMENTS = 256
_MAX_WINDOW_DAYS = 3_660
_COMPLETENESS = "not_established_by_identity_resolution"
_SOURCE_INTEGRITY = "snapshot_bytes_pinned_source_evidence_not_authenticated"
_CONFIG_INVALID = "OPENDATA_TEMPORAL_IDENTITY_CONFIG_INVALID"
_QUERY_INVALID = "OPENDATA_TEMPORAL_IDENTITY_QUERY_INVALID"
_UNAVAILABLE = "OPENDATA_TEMPORAL_IDENTITY_UNAVAILABLE"
_PROTOCOL_INVALID = "OPENDATA_TEMPORAL_IDENTITY_PROTOCOL_INVALID"
_LIMIT_EXCEEDED = "OPENDATA_TEMPORAL_IDENTITY_LIMIT_EXCEEDED"
_ERROR_CODES = frozenset(
    {_CONFIG_INVALID, _QUERY_INVALID, _UNAVAILABLE, _PROTOCOL_INVALID, _LIMIT_EXCEEDED}
)


class OpendataTemporalIdentityError(RuntimeError):
    """Fixed-code client failure that never contains upstream or credential text."""

    def __init__(self, code: str) -> None:
        self.code = code if isinstance(code, str) and code in _ERROR_CODES else _PROTOCOL_INVALID
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class OpendataTemporalIdentityPin:
    """Operator-trusted exact pin for one dataset and source."""

    dataset_id: str
    source_id: str
    authority_id: str
    registry_id: str
    reference_version: str
    snapshot_sha256: str

    def __post_init__(self) -> None:
        """Reject non-canonical identifiers and non-lowercase SHA-256 pins."""
        if any(not _valid_identifier(value) for value in self._identifiers()):
            raise OpendataTemporalIdentityError(_CONFIG_INVALID)
        if (
            not isinstance(self.snapshot_sha256, str)
            or _SHA256.fullmatch(self.snapshot_sha256) is None
        ):
            raise OpendataTemporalIdentityError(_CONFIG_INVALID)

    def _identifiers(self) -> tuple[str, ...]:
        return (
            self.dataset_id,
            self.source_id,
            self.authority_id,
            self.registry_id,
            self.reference_version,
        )


@dataclass(frozen=True, slots=True)
class OpendataTemporalIdentityConfig:
    """Explicit credentials and trusted identity pin for this client instance."""

    credentials: OpendataCredentials = field(repr=False)
    pin: OpendataTemporalIdentityPin
    _base_url: str = field(init=False, repr=False)
    _api_key: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate credentials, pin type, and an unambiguous service origin."""
        if type(self.credentials) is not OpendataCredentials:
            raise OpendataTemporalIdentityError(_CONFIG_INVALID)
        if type(self.pin) is not OpendataTemporalIdentityPin:
            raise OpendataTemporalIdentityError(_CONFIG_INVALID)
        key = self.credentials.api_key
        if not isinstance(key, str) or _API_KEY.fullmatch(key) is None:
            raise OpendataTemporalIdentityError(_CONFIG_INVALID)
        origin = _validate_origin(self.credentials.base_url)
        object.__setattr__(self, "_base_url", origin)
        object.__setattr__(self, "_api_key", key)


@dataclass(frozen=True, slots=True)
class OpendataTemporalIdentityLimits:
    """Client budgets that can be lowered but never exceed the API contract."""

    max_request_bytes: int = _MAX_REQUEST_BYTES
    max_response_bytes: int = _MAX_RESPONSE_BYTES
    max_segments: int = _MAX_SEGMENTS
    deadline_seconds: float = 5.0
    request_timeout_seconds: float = 2.0

    def __post_init__(self) -> None:
        """Keep every caller-supplied budget within the fixed server ceiling."""
        for value, ceiling in (
            (self.max_request_bytes, _MAX_REQUEST_BYTES),
            (self.max_response_bytes, _MAX_RESPONSE_BYTES),
            (self.max_segments, _MAX_SEGMENTS),
        ):
            if type(value) is not int or not 1 <= value <= ceiling:
                raise OpendataTemporalIdentityError(_CONFIG_INVALID)
        for timeout_value, timeout_ceiling in (
            (self.deadline_seconds, 5.0),
            (self.request_timeout_seconds, 2.0),
        ):
            if (
                isinstance(timeout_value, bool)
                or not isinstance(timeout_value, (int, float))
                or not math.isfinite(timeout_value)
                or timeout_value <= 0
                or timeout_value > timeout_ceiling
            ):
                raise OpendataTemporalIdentityError(_CONFIG_INVALID)


@dataclass(frozen=True, slots=True)
class TemporalIdentityPair:
    """Exchange-qualified six-digit market symbol."""

    exchange: str
    symbol: str


@dataclass(frozen=True, slots=True)
class TemporalIdentitySegment:
    """One finite known assignment or explicit evidence-unknown interval."""

    start: date
    end_exclusive: date
    status: str
    assignment_id: str | None
    instrument_id: str | None
    pair: TemporalIdentityPair | None
    source_id: str | None
    source_version: str | None


@dataclass(frozen=True, slots=True)
class TemporalIdentityResolution:
    """Validated bounded partition returned by the OpenData resolve endpoint."""

    dataset_id: str
    authority_id: str
    registry_id: str
    reference_version: str
    snapshot_sha256: str
    subject: str
    pair: TemporalIdentityPair | None
    instrument_id: str | None
    window_start: date
    window_end_exclusive: date
    segments: tuple[TemporalIdentitySegment, ...]
    completeness: str
    source_integrity: str


class _BorrowedTransport(httpx.AsyncBaseTransport):
    """Let a per-call HTTPX client close without owning an injected transport."""

    def __init__(self, transport: httpx.AsyncBaseTransport) -> None:
        self._transport = transport

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._transport.handle_async_request(request)

    async def aclose(self) -> None:
        return None


class OpendataTemporalIdentityClient:
    """Resolve only explicitly requested pairs or instruments through OpenData."""

    def __init__(
        self,
        config: OpendataTemporalIdentityConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        limits: OpendataTemporalIdentityLimits | None = None,
    ) -> None:
        """Create an offline-testable client without reading shared settings."""
        if type(config) is not OpendataTemporalIdentityConfig:
            raise OpendataTemporalIdentityError(_CONFIG_INVALID)
        if transport is not None and not isinstance(transport, httpx.AsyncBaseTransport):
            raise OpendataTemporalIdentityError(_CONFIG_INVALID)
        if limits is not None and type(limits) is not OpendataTemporalIdentityLimits:
            raise OpendataTemporalIdentityError(_CONFIG_INVALID)
        self._config = config
        self._transport = transport
        self._limits = limits or OpendataTemporalIdentityLimits()
        self._origin = config._base_url

    async def resolve_pair(
        self,
        *,
        exchange: str,
        symbol: str,
        window_start: date,
        window_end_exclusive: date,
    ) -> TemporalIdentityResolution:
        """Resolve one exact exchange-symbol pair over a half-open date window."""
        query = _query(
            exchange=exchange,
            symbol=symbol,
            instrument_id=None,
            window_start=window_start,
            window_end_exclusive=window_end_exclusive,
        )
        return await self._resolve(query)

    async def resolve_instrument(
        self,
        *,
        instrument_id: str,
        window_start: date,
        window_end_exclusive: date,
    ) -> TemporalIdentityResolution:
        """Resolve one opaque instrument identifier over a half-open date window."""
        query = _query(
            exchange=None,
            symbol=None,
            instrument_id=instrument_id,
            window_start=window_start,
            window_end_exclusive=window_end_exclusive,
        )
        return await self._resolve(query)

    async def _resolve(self, query: _Query) -> TemporalIdentityResolution:
        request_body = self._request_body(query)
        if len(request_body) > self._limits.max_request_bytes:
            raise OpendataTemporalIdentityError(_LIMIT_EXCEEDED)
        try:
            payload = await asyncio.wait_for(
                self._fetch(request_body), timeout=self._limits.deadline_seconds
            )
        except OpendataTemporalIdentityError:
            raise
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            raise OpendataTemporalIdentityError(_LIMIT_EXCEEDED) from None
        except Exception:
            raise OpendataTemporalIdentityError(_UNAVAILABLE) from None
        return _validate_response(payload, self._config.pin, query, self._limits)

    def _request_body(self, query: _Query) -> bytes:
        """Serialize the exact API request with the trusted pin and no extras."""
        pin = self._config.pin
        body: dict[str, str | None] = {
            "dataset_id": pin.dataset_id,
            "authority_id": pin.authority_id,
            "registry_id": pin.registry_id,
            "reference_version": pin.reference_version,
            "snapshot_sha256": pin.snapshot_sha256,
            "window_start": query.window_start.isoformat(),
            "window_end_exclusive": query.window_end_exclusive.isoformat(),
            "exchange": query.exchange,
            "symbol": query.symbol,
            "instrument_id": query.instrument_id,
        }
        if frozenset(body) != _REQUEST_FIELDS:
            raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
        try:
            return json.dumps(
                body, ensure_ascii=True, separators=(",", ":"), allow_nan=False
            ).encode("ascii")
        except (TypeError, ValueError, UnicodeEncodeError):
            raise OpendataTemporalIdentityError(_PROTOCOL_INVALID) from None

    async def _fetch(self, request_body: bytes) -> dict[str, object]:
        """Send one bounded no-redirect request and parse a bounded JSON object."""
        options: dict[str, Any] = {
            "base_url": self._origin,
            "headers": {
                "X-API-Key": self._config._api_key,
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
            "timeout": httpx.Timeout(self._limits.request_timeout_seconds),
            "trust_env": False,
            "follow_redirects": False,
            "limits": httpx.Limits(max_connections=1, max_keepalive_connections=0),
        }
        if self._transport is not None:
            options["transport"] = _BorrowedTransport(self._transport)
        try:
            async with httpx.AsyncClient(**options) as client:
                async with client.stream(
                    "POST",
                    _PATH,
                    content=request_body,
                    headers={"Content-Type": "application/json"},
                ) as response:
                    if response.status_code != 200:
                        raise OpendataTemporalIdentityError(_UNAVAILABLE)
                    content_type = response.headers.get("content-type", "")
                    if content_type.split(";", maxsplit=1)[0].strip().lower() != "application/json":
                        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
                    if response.headers.get("content-encoding", "identity").strip().lower() != (
                        "identity"
                    ):
                        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
                    _validate_content_length(
                        response.headers.get_list("content-length"),
                        self._limits.max_response_bytes,
                    )
                    raw = bytearray()
                    async for chunk in response.aiter_raw():
                        if len(raw) + len(chunk) > self._limits.max_response_bytes:
                            raise OpendataTemporalIdentityError(_LIMIT_EXCEEDED)
                        raw.extend(chunk)
        except OpendataTemporalIdentityError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception:
            raise OpendataTemporalIdentityError(_UNAVAILABLE) from None
        return _decode_json_object(bytes(raw))


@dataclass(frozen=True, slots=True)
class _Query:
    window_start: date
    window_end_exclusive: date
    exchange: str | None
    symbol: str | None
    instrument_id: str | None

    @property
    def subject(self) -> str:
        return "instrument" if self.instrument_id is not None else "pair"

    @property
    def pair(self) -> TemporalIdentityPair | None:
        if self.exchange is None or self.symbol is None:
            return None
        return TemporalIdentityPair(exchange=self.exchange, symbol=self.symbol)


def _query(
    *,
    exchange: object,
    symbol: object,
    instrument_id: object,
    window_start: object,
    window_end_exclusive: object,
) -> _Query:
    """Validate an exact selector and finite calendar-date interval."""
    pair_selected = exchange is not None and symbol is not None
    instrument_selected = instrument_id is not None
    if pair_selected == instrument_selected or (exchange is None) != (symbol is None):
        raise OpendataTemporalIdentityError(_QUERY_INVALID)
    validated_exchange: str | None = None
    validated_symbol: str | None = None
    validated_instrument_id: str | None = None
    if pair_selected:
        if type(exchange) is not str or type(symbol) is not str:
            raise OpendataTemporalIdentityError(_QUERY_INVALID)
        if exchange not in _EXCHANGES or _SYMBOL.fullmatch(symbol) is None:
            raise OpendataTemporalIdentityError(_QUERY_INVALID)
        validated_exchange = exchange
        validated_symbol = symbol
    if instrument_selected:
        if not _valid_identifier(instrument_id):
            raise OpendataTemporalIdentityError(_QUERY_INVALID)
        validated_instrument_id = instrument_id
    if type(window_start) is not date or type(window_end_exclusive) is not date:
        raise OpendataTemporalIdentityError(_QUERY_INVALID)
    if window_start >= window_end_exclusive:
        raise OpendataTemporalIdentityError(_QUERY_INVALID)
    if (window_end_exclusive - window_start).days > _MAX_WINDOW_DAYS:
        raise OpendataTemporalIdentityError(_QUERY_INVALID)
    return _Query(
        window_start=window_start,
        window_end_exclusive=window_end_exclusive,
        exchange=validated_exchange,
        symbol=validated_symbol,
        instrument_id=validated_instrument_id,
    )


def _validate_response(
    payload: Mapping[str, object],
    pin: OpendataTemporalIdentityPin,
    query: _Query,
    limits: OpendataTemporalIdentityLimits,
) -> TemporalIdentityResolution:
    """Check the full pinned query, date partition, and known/unknown semantics."""
    if set(payload) != _RESPONSE_FIELDS:
        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
    for key in (
        "dataset_id",
        "authority_id",
        "registry_id",
        "reference_version",
        "snapshot_sha256",
    ):
        if payload.get(key) != getattr(pin, key):
            raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
    if payload.get("subject") != query.subject:
        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
    top_pair = _parse_pair(payload.get("pair"), nullable=True)
    if top_pair != query.pair or payload.get("instrument_id") != query.instrument_id:
        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
    window = payload.get("window")
    if not isinstance(window, dict) or set(window) != _WINDOW_FIELDS:
        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
    window_start = _parse_date(window.get("start"))
    window_end = _parse_date(window.get("end_exclusive"))
    if (
        window_start != query.window_start
        or window_end != query.window_end_exclusive
        or window.get("semantics") != "half_open_calendar_dates"
    ):
        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
    if payload.get("completeness") != _COMPLETENESS:
        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
    if payload.get("source_integrity") != _SOURCE_INTEGRITY:
        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
    segments_value = payload.get("segments")
    if not isinstance(segments_value, list) or not segments_value:
        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
    if len(segments_value) > limits.max_segments:
        raise OpendataTemporalIdentityError(_LIMIT_EXCEEDED)
    segments: list[TemporalIdentitySegment] = []
    cursor = query.window_start
    for item in segments_value:
        if not isinstance(item, dict) or set(item) != _SEGMENT_FIELDS:
            raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
        start = _parse_date(item.get("start"))
        end = _parse_date(item.get("end_exclusive"))
        if start != cursor or start >= end or end > query.window_end_exclusive:
            raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
        status = item.get("status")
        if status == "unknown":
            if any(
                item.get(key) is not None
                for key in (
                    "assignment_id",
                    "instrument_id",
                    "pair",
                    "source_id",
                    "source_version",
                )
            ):
                raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
            assignment_id = None
            instrument_id = None
            pair = None
            source_id = None
            source_version = None
        elif status == "known":
            assignment_id = _require_identifier(item.get("assignment_id"))
            instrument_id = _require_identifier(item.get("instrument_id"))
            pair = _parse_pair(item.get("pair"), nullable=False)
            source_id = _require_identifier(item.get("source_id"))
            source_version = _require_identifier(item.get("source_version"))
            if source_id != pin.source_id:
                raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
            if query.subject == "pair" and pair != query.pair:
                raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
            if query.subject == "instrument" and instrument_id != query.instrument_id:
                raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
        else:
            raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
        segments.append(
            TemporalIdentitySegment(
                start=start,
                end_exclusive=end,
                status=status,
                assignment_id=assignment_id,
                instrument_id=instrument_id,
                pair=pair,
                source_id=source_id,
                source_version=source_version,
            )
        )
        cursor = end
    if cursor != query.window_end_exclusive:
        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
    return TemporalIdentityResolution(
        dataset_id=pin.dataset_id,
        authority_id=pin.authority_id,
        registry_id=pin.registry_id,
        reference_version=pin.reference_version,
        snapshot_sha256=pin.snapshot_sha256,
        subject=query.subject,
        pair=query.pair,
        instrument_id=query.instrument_id,
        window_start=query.window_start,
        window_end_exclusive=query.window_end_exclusive,
        segments=tuple(segments),
        completeness=_COMPLETENESS,
        source_integrity=_SOURCE_INTEGRITY,
    )


def _validate_content_length(values: list[str], maximum: int) -> None:
    """Reject duplicate, malformed, and over-budget response lengths early."""
    if not values:
        return
    if len(values) != 1:
        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
    value = values[0]
    if not value.isascii() or not value.isdecimal():
        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
    normalized = value.lstrip("0") or "0"
    ceiling = str(maximum)
    if len(normalized) > len(ceiling) or (len(normalized) == len(ceiling) and normalized > ceiling):
        raise OpendataTemporalIdentityError(_LIMIT_EXCEEDED)


def _decode_json_object(body: bytes) -> dict[str, object]:
    """Decode strict UTF-8 JSON while rejecting duplicate keys and non-finite values."""
    if not body:
        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
    if len(body) > _MAX_RESPONSE_BYTES:
        raise OpendataTemporalIdentityError(_LIMIT_EXCEEDED)
    try:
        value = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID) from None
    if not isinstance(value, dict):
        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
    return value


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject repeated object keys at every JSON nesting level."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate object key")
        result[key] = value
    return result


def _reject_json_constant(_: str) -> None:
    """Reject JavaScript-only NaN and infinity tokens."""
    raise ValueError("non-standard JSON number")


def _parse_date(value: object) -> date:
    """Accept only canonical ISO calendar dates, never timestamp coercions."""
    if not isinstance(value, str) or _DATE.fullmatch(value) is None:
        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID) from None
    if parsed.isoformat() != value:
        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
    return parsed


def _parse_pair(value: object, *, nullable: bool) -> TemporalIdentityPair | None:
    """Parse the exact exchange and symbol pair shape from the REST contract."""
    if value is None:
        if nullable:
            return None
        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
    if not isinstance(value, dict) or set(value) != {"exchange", "symbol"}:
        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
    exchange = value.get("exchange")
    symbol = value.get("symbol")
    if (
        type(exchange) is not str
        or exchange not in _EXCHANGES
        or type(symbol) is not str
        or _SYMBOL.fullmatch(symbol) is None
    ):
        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
    return TemporalIdentityPair(exchange=exchange, symbol=symbol)


def _require_identifier(value: object) -> str:
    """Validate a fixed-format opaque identifier without reflecting its value."""
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise OpendataTemporalIdentityError(_PROTOCOL_INVALID)
    return value


def _valid_identifier(value: object) -> TypeGuard[str]:
    return type(value) is str and _IDENTIFIER.fullmatch(value) is not None


def _validate_origin(base_url: object) -> str:
    """Allow HTTPS origins or numeric loopback HTTP origins only."""
    if not isinstance(base_url, str) or not base_url or base_url != base_url.strip():
        raise OpendataTemporalIdentityError(_CONFIG_INVALID)
    try:
        parts = urlsplit(base_url)
        hostname = parts.hostname
        port = parts.port
    except ValueError:
        raise OpendataTemporalIdentityError(_CONFIG_INVALID) from None
    if (
        parts.scheme.lower() not in {"http", "https"}
        or hostname is None
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or "?" in base_url
        or "#" in base_url
        or parts.path not in {"", "/"}
    ):
        raise OpendataTemporalIdentityError(_CONFIG_INVALID)
    if parts.scheme.lower() == "http":
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            raise OpendataTemporalIdentityError(_CONFIG_INVALID) from None
        if not address.is_loopback:
            raise OpendataTemporalIdentityError(_CONFIG_INVALID)
    if port is not None and not 1 <= port <= 65535:
        raise OpendataTemporalIdentityError(_CONFIG_INVALID)
    return f"{parts.scheme.lower()}://{parts.netloc}"


__all__ = [
    "OpendataTemporalIdentityClient",
    "OpendataTemporalIdentityConfig",
    "OpendataTemporalIdentityError",
    "OpendataTemporalIdentityLimits",
    "OpendataTemporalIdentityPin",
    "TemporalIdentityPair",
    "TemporalIdentityResolution",
    "TemporalIdentitySegment",
]
