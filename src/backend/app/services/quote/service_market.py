"""Authorized SDK service-market access for quote-page projections.

The deployment document is an operator-owned allowlist. JWT subjects select
only a previously configured public market key; request parameters never build
SDK identities, service scopes, endpoints, or provider-native instruments.
SDK imports and transports are deferred until an explicit deployment exists.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

__all__ = [
    "MarketQuoteResult",
    "ServiceMarketDeployment",
    "ServiceMarketDeploymentError",
    "project_market_event",
]

_ENVIRONMENT_VARIABLE = "SERVICE_MARKET_DEPLOYMENT_JSON"
_MAX_DEPLOYMENT_BYTES = 262_144
_MAX_SUBJECTS = 256
_MAX_MARKET_BINDINGS_PER_SUBJECT = 512
_MAX_QUEUE_SIZE = 64
_MAX_READ_KEYS = 64
_MAX_WAIT_MS = 1_000
_REQUEST_TIMEOUT_SECONDS = 30.0
_POLL_INTERVAL_SECONDS = 0.025
_MARKET_OPERATIONS = frozenset(
    {
        "market.subscribe",
        "market.unsubscribe",
        "market.snapshot",
        "market.head",
        "market.read_after",
    }
)
_Z85_ALPHABET = frozenset(
    "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-:+=^!/*?&<>()[]{}@%$#"
)
_PROJECTION_FIELDS = frozenset(
    {
        "exchange_name",
        "symbol",
        "instrument_id",
        "asset_type",
        "timestamp",
        "price",
        "last_price",
        "bid_price",
        "ask_price",
        "bid_volume",
        "ask_volume",
        "volume",
        "turnover",
        "high",
        "low",
        "open",
    }
)
_NUMERIC_FIELDS = frozenset(
    {
        "timestamp",
        "price",
        "last_price",
        "bid_price",
        "ask_price",
        "bid_volume",
        "ask_volume",
        "volume",
        "turnover",
        "high",
        "low",
        "open",
    }
)


class ServiceMarketDeploymentError(RuntimeError):
    """Finite configuration/access error with no deployment values attached."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class MarketQuoteResult:
    """One configured key's latest validated provider-neutral projection."""

    data: Mapping[str, Any] | None
    error_code: str | None
    healthy: bool


@dataclass(frozen=True, slots=True)
class _MarketProfile:
    subject: str
    identity: Any = field(repr=False, compare=False)
    client_config: Any = field(repr=False, compare=False)
    scope: Any = field(repr=False, compare=False)
    peer: Any = field(repr=False, compare=False)
    scope_ref: str
    service_id: str
    mount: str
    curve_keys: Mapping[str, tuple[bytes, bytes, bytes]] = field(repr=False, compare=False)
    routes: Mapping[tuple[str, str], Any] = field(repr=False, compare=False)


@dataclass(slots=True)
class _ReadRequest:
    keys: tuple[Any, ...]
    wait_ms: int
    done: threading.Event = field(default_factory=threading.Event)
    results: dict[str, MarketQuoteResult] = field(default_factory=dict)


class ServiceMarketDeployment:
    """Exact-subject directory and lazy owner-thread SDK market clients."""

    def __init__(self, profiles: Mapping[str, _MarketProfile]) -> None:
        copied = dict(profiles)
        if not copied:
            raise ServiceMarketDeploymentError("EMPTY_DEPLOYMENT")
        self._profiles = MappingProxyType(copied)
        self._workers: dict[str, _ServiceMarketOwner] = {}
        self._lock = threading.Lock()
        self._closed = False

    @classmethod
    def from_environment(cls) -> ServiceMarketDeployment | None:
        """Load the optional bounded deployment value without logging it."""

        value = os.environ.get(_ENVIRONMENT_VARIABLE)
        if value is None or value == "":
            return None
        return cls.from_value(value)

    @classmethod
    def from_value(cls, value: object) -> ServiceMarketDeployment | None:
        """Parse a deployment-owned JSON document; empty input disables this path."""

        if value is None or value == "":
            return None
        if type(value) is not str:
            raise ServiceMarketDeploymentError("INVALID_DEPLOYMENT")
        try:
            encoded = value.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            raise ServiceMarketDeploymentError("INVALID_DEPLOYMENT") from None
        if len(encoded) > _MAX_DEPLOYMENT_BYTES:
            raise ServiceMarketDeploymentError("DEPLOYMENT_TOO_LARGE")
        try:
            document = json.loads(
                value,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
        except (ValueError, TypeError, RecursionError):
            raise ServiceMarketDeploymentError("INVALID_DEPLOYMENT") from None
        if (
            type(document) is not dict
            or set(document) != {"schema_version", "subjects"}
            or type(document["schema_version"]) is not int
            or document["schema_version"] != 1
            or type(document["subjects"]) is not list
            or not document["subjects"]
            or len(document["subjects"]) > _MAX_SUBJECTS
        ):
            raise ServiceMarketDeploymentError("INVALID_DEPLOYMENT")

        sdk = _load_sdk_types()
        profiles: dict[str, _MarketProfile] = {}
        identities: set[tuple[str, str, str | None]] = set()
        try:
            for raw_profile in document["subjects"]:
                profile = _parse_profile(raw_profile, sdk)
                if profile.subject in profiles:
                    raise ServiceMarketDeploymentError("DUPLICATE_SUBJECT")
                identity_key = (
                    profile.identity.principal_ref,
                    profile.identity.actor_ref,
                    profile.identity.delegate_ref,
                )
                if identity_key in identities:
                    raise ServiceMarketDeploymentError("IDENTITY_SHARED")
                identities.add(identity_key)
                profiles[profile.subject] = profile
        except ServiceMarketDeploymentError:
            raise
        except Exception:
            raise ServiceMarketDeploymentError("INVALID_DEPLOYMENT") from None
        return cls(profiles)

    def configured_routes(
        self, subject: str, source: str, symbols: list[str]
    ) -> dict[str, Any]:
        """Return only exact subject/source/symbol bindings known to deployment."""

        if type(subject) is not str or not subject or type(source) is not str:
            return {}
        profile = self._profiles.get(subject)
        if profile is None:
            return {}
        normalized_source = source.strip().upper()
        result: dict[str, Any] = {}
        for symbol in symbols:
            if type(symbol) is not str:
                continue
            key = profile.routes.get((normalized_source, symbol))
            if key is not None:
                result[symbol] = key
        return result

    def read_quotes(
        self,
        subject: str,
        routes: Mapping[str, Any],
        *,
        wait_ms: int = 250,
    ) -> dict[str, MarketQuoteResult]:
        """Read configured keys through their subject's serialized SDK owner."""

        if type(wait_ms) is not int or not 0 <= wait_ms <= _MAX_WAIT_MS:
            raise ServiceMarketDeploymentError("INVALID_WAIT")
        if not isinstance(routes, Mapping):
            raise ServiceMarketDeploymentError("INVALID_MARKET_BINDINGS")
        if len(routes) > _MAX_READ_KEYS:
            raise ServiceMarketDeploymentError("TOO_MANY_MARKET_KEYS")
        with self._lock:
            if self._closed:
                raise ServiceMarketDeploymentError("DEPLOYMENT_CLOSED")
            profile = self._profiles.get(subject)
            if profile is None:
                raise ServiceMarketDeploymentError("SUBJECT_NOT_CONFIGURED")
            keys: list[Any] = []
            seen_streams: set[str] = set()
            for symbol, key in routes.items():
                if (
                    type(symbol) is not str
                    or profile.routes.get(("OKX", symbol)) != key
                ):
                    raise ServiceMarketDeploymentError("MARKET_BINDING_NOT_CONFIGURED")
                if key.stream_id in seen_streams:
                    raise ServiceMarketDeploymentError("DUPLICATE_MARKET_KEY")
                seen_streams.add(key.stream_id)
                keys.append(key)
            if not keys:
                return {}
            worker = self._workers.get(subject)
            if worker is None:
                worker = _ServiceMarketOwner(profile)
                self._workers[subject] = worker
        return worker.read(tuple(keys), wait_ms=wait_ms)

    def close(self) -> None:
        """Close each started owner and retain any finite cleanup failure."""

        with self._lock:
            self._closed = True
            workers = tuple(self._workers.values())
        failures: list[str] = []
        for worker in reversed(workers):
            try:
                worker.close()
            except ServiceMarketDeploymentError as error:
                failures.append(error.code)
        if failures:
            raise ServiceMarketDeploymentError("CLOSE_FAILED")


class _ServiceMarketOwner:
    """One fixed thread owns an application runtime and all its market clients."""

    def __init__(self, profile: _MarketProfile) -> None:
        self._profile = profile
        self._requests: queue.Queue[_ReadRequest] = queue.Queue(maxsize=_MAX_QUEUE_SIZE)
        self._state_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._closed = False
        self._close_error: str | None = None
        self._startup_error: str | None = None
        self._runtime: Any = None
        self._clients: dict[str, tuple[Any, Any]] = {}
        self._latest: dict[str, Mapping[str, Any]] = {}
        self._client_errors: dict[str, str] = {}

    def read(self, keys: tuple[Any, ...], *, wait_ms: int) -> dict[str, MarketQuoteResult]:
        request = _ReadRequest(keys, wait_ms)
        with self._state_lock:
            if self._closed:
                return _failed_results(keys, "SERVICE_MARKET_CLOSED")
            if self._thread is None:
                stable = hashlib.sha256(self._profile.subject.encode("utf-8")).hexdigest()[:12]
                thread = threading.Thread(
                    target=self._run,
                    name=f"afi-service-market-{stable}",
                    daemon=False,
                )
                try:
                    thread.start()
                except Exception:
                    return _failed_results(keys, "OWNER_START_FAILED")
                self._thread = thread
            try:
                self._requests.put_nowait(request)
            except queue.Full:
                return _failed_results(keys, "SERVICE_MARKET_BUSY")
        if not request.done.wait(_REQUEST_TIMEOUT_SECONDS):
            return _failed_results(keys, "SERVICE_MARKET_TIMEOUT")
        return request.results

    def close(self) -> None:
        with self._state_lock:
            if self._closed and self._thread is None:
                return
            self._closed = True
            self._stop.set()
            thread = self._thread
            if thread is None:
                return
        thread.join(timeout=_REQUEST_TIMEOUT_SECONDS)
        if thread.is_alive():
            raise ServiceMarketDeploymentError("OWNER_CLOSE_UNCERTAIN")
        if self._close_error is not None:
            raise ServiceMarketDeploymentError("OWNER_CLOSE_FAILED")

    def _run(self) -> None:
        try:
            while True:
                try:
                    request = self._requests.get(timeout=_POLL_INTERVAL_SECONDS)
                except queue.Empty:
                    request = None
                if self._stop.is_set():
                    if isinstance(request, _ReadRequest):
                        request.results = _failed_results(
                            request.keys, "SERVICE_MARKET_CLOSED"
                        )
                        request.done.set()
                    return
                if isinstance(request, _ReadRequest):
                    self._handle_request(request)
                self._poll_clients()
        except BaseException as error:
            if isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                self._startup_error = "OWNER_STOPPED"
            else:
                self._startup_error = _safe_error_code(error)
        finally:
            self._close_owned_runtime()
            while True:
                try:
                    pending = self._requests.get_nowait()
                except queue.Empty:
                    break
                pending.results = _failed_results(
                    pending.keys, self._startup_error or "SERVICE_MARKET_CLOSED"
                )
                pending.done.set()

    def _handle_request(self, request: _ReadRequest) -> None:
        if self._startup_error is not None:
            request.results = _failed_results(request.keys, self._startup_error)
            request.done.set()
            return
        try:
            self._ensure_runtime()
            for key in request.keys:
                self._ensure_client(key)
        except BaseException as error:
            code = _safe_error_code(error)
            self._startup_error = code
            request.results = _failed_results(request.keys, code)
            request.done.set()
            return

        deadline = time.monotonic() + request.wait_ms / 1000.0
        while True:
            self._poll_clients()
            if all(
                key.stream_id in self._latest or key.stream_id in self._client_errors
                for key in request.keys
            ) or time.monotonic() >= deadline:
                break
            time.sleep(min(_POLL_INTERVAL_SECONDS, max(0.0, deadline - time.monotonic())))
        request.results = {
            key.stream_id: MarketQuoteResult(
                data=self._latest.get(key.stream_id),
                error_code=self._client_errors.get(key.stream_id),
                healthy=self._client_is_healthy(key.stream_id),
            )
            for key in request.keys
        }
        request.done.set()

    def _ensure_runtime(self) -> None:
        if self._runtime is not None:
            return
        try:
            from bt_api_py.service_runtime import (
                ClientCurveKeys,
                ServiceClientRuntime,
                ZmqTransportFactory,
            )
        except ImportError:
            raise ServiceMarketDeploymentError("SDK_NOT_INSTALLED") from None
        transport_keys = {
            reference: ClientCurveKeys(*keys)
            for reference, keys in self._profile.curve_keys.items()
        }
        runtime = ServiceClientRuntime(
            self._profile.client_config,
            identity=self._profile.identity,
            scope_resolver=lambda scope_ref: (
                self._profile.scope
                if scope_ref == self._profile.scope_ref
                else _raise_unknown_scope()
            ),
            peer_resolver=lambda service_id: (
                self._profile.peer
                if service_id == self._profile.service_id
                else _raise_unknown_peer()
            ),
            transport_factory=ZmqTransportFactory(transport_keys),
            requested_operations={"application.market": _MARKET_OPERATIONS},
        )
        self._runtime = runtime
        runtime.start()

    def _ensure_client(self, key: Any) -> None:
        if key.stream_id in self._clients or key.stream_id in self._client_errors:
            return
        try:
            from bt_api_py.service_market import ServiceMarketClient, ZmqMarketTransportFactory
            from bt_api_py.service_runtime import ClientCurveKeys
        except ImportError:
            raise ServiceMarketDeploymentError("SDK_MARKET_CLIENT_UNAVAILABLE") from None
        security = {
            reference: ClientCurveKeys(*keys)
            for reference, keys in self._profile.curve_keys.items()
        }
        client = ServiceMarketClient(
            self._runtime,
            self._profile.mount,
            key,
            subscriber_factory=ZmqMarketTransportFactory(security),
            stream_scope=self._profile.scope,
        )
        self._clients[key.stream_id] = (key, client)
        bootstrap = client.start()
        if bootstrap.snapshot is not None:
            self._cache_event(key, bootstrap.snapshot)

    def _poll_clients(self) -> None:
        for key_id, (key, client) in tuple(self._clients.items()):
            try:
                event = client.poll(timeout_ms=0)
            except BaseException as error:
                if isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                    raise
                self._client_errors[key_id] = _safe_error_code(error)
                continue
            if event is not None:
                try:
                    self._cache_event(key, event)
                except ServiceMarketDeploymentError as error:
                    self._client_errors[key_id] = error.code

    def _cache_event(self, key: Any, event: Any) -> None:
        try:
            projected = project_market_event(event, expected_key=key)
        except ServiceMarketDeploymentError as error:
            self._client_errors[key.stream_id] = error.code
            return
        self._latest[key.stream_id] = MappingProxyType(projected)
        self._client_errors.pop(key.stream_id, None)

    def _client_is_healthy(self, key_id: str) -> bool:
        client_entry = self._clients.get(key_id)
        return bool(client_entry and client_entry[1].healthy and key_id not in self._client_errors)

    def _close_owned_runtime(self) -> None:
        failures = False
        for _key, client in reversed(tuple(self._clients.values())):
            try:
                client.close()
            except BaseException:
                failures = True
        self._clients.clear()
        if self._runtime is not None:
            try:
                self._runtime.close()
                if self._runtime.cleanup_failures or self._runtime.unregister_uncertainties:
                    failures = True
            except BaseException:
                failures = True
            self._runtime = None
        if failures:
            self._close_error = "OWNER_CLOSE_FAILED"


def project_market_event(event: Any, *, expected_key: Any) -> dict[str, Any]:
    """Validate the established market event key/data contract and map to QuoteTick input."""

    try:
        from bt_api_base.market_protocol import (
            MARKET_EVENT_OPERATION,
            MARKET_EVENT_SCHEMA,
            MarketSubscriptionKey,
        )
        from bt_api_base.service_protocol import WireEnvelope
    except ImportError:
        raise ServiceMarketDeploymentError("SDK_NOT_INSTALLED") from None
    if type(event) is not WireEnvelope or type(expected_key) is not MarketSubscriptionKey:
        raise ServiceMarketDeploymentError("INVALID_MARKET_EVENT")
    header = event.header
    if (
        header.schema_id != MARKET_EVENT_SCHEMA
        or header.schema_version != 1
        or header.operation != MARKET_EVENT_OPERATION
        or not isinstance(event.payload, Mapping)
        or set(event.payload) != {"key", "data"}
        or header.stream_id != expected_key.stream_id
        or type(header.sequence) is not int
        or header.sequence <= 0
    ):
        raise ServiceMarketDeploymentError("INVALID_MARKET_EVENT")
    try:
        published_key = MarketSubscriptionKey.from_dict(event.payload["key"])
    except Exception:
        raise ServiceMarketDeploymentError("INVALID_MARKET_KEY") from None
    if published_key != expected_key:
        raise ServiceMarketDeploymentError("MARKET_KEY_MISMATCH")
    data = event.payload["data"]
    if not isinstance(data, Mapping) or set(data) != _PROJECTION_FIELDS:
        raise ServiceMarketDeploymentError("INVALID_MARKET_PROJECTION")
    for field_name in ("exchange_name", "symbol", "instrument_id", "asset_type"):
        if type(data[field_name]) is not str or not data[field_name]:
            raise ServiceMarketDeploymentError("INVALID_MARKET_PROJECTION")
    if (
        data["exchange_name"] != expected_key.instrument.venue
        or data["asset_type"] != expected_key.instrument.product_type
        or data["symbol"] != expected_key.instrument.native_symbol
        or data["instrument_id"] != expected_key.instrument.instrument_id
    ):
        raise ServiceMarketDeploymentError("MARKET_INSTRUMENT_MISMATCH")
    normalized: dict[str, Any] = {}
    for field_name in _NUMERIC_FIELDS:
        value = data[field_name]
        if value is None:
            normalized[field_name] = None
            continue
        if type(value) not in (int, float) or isinstance(value, bool):
            raise ServiceMarketDeploymentError("INVALID_MARKET_PROJECTION")
        try:
            number = float(value)
        except (OverflowError, ValueError):
            raise ServiceMarketDeploymentError("INVALID_MARKET_PROJECTION") from None
        if not math.isfinite(number):
            raise ServiceMarketDeploymentError("INVALID_MARKET_PROJECTION")
        normalized[field_name] = number
    if normalized["timestamp"] is None or normalized["timestamp"] <= 0:
        raise ServiceMarketDeploymentError("INVALID_MARKET_PROJECTION")
    return {
        "symbol": data["symbol"],
        "instrument_id": data["instrument_id"],
        "exchange": data["exchange_name"],
        "asset_type": data["asset_type"],
        "timestamp": normalized["timestamp"],
        "price": normalized["price"],
        "last_price": normalized["last_price"],
        "bid_price": normalized["bid_price"],
        "ask_price": normalized["ask_price"],
        "bid_volume": normalized["bid_volume"],
        "ask_volume": normalized["ask_volume"],
        "volume": normalized["volume"],
        "turnover": normalized["turnover"],
        "high_price": normalized["high"],
        "low_price": normalized["low"],
        "open_price": normalized["open"],
    }


def _parse_profile(raw: object, sdk: Mapping[str, Any]) -> _MarketProfile:
    required_fields = {
        "subject",
        "identity",
        "client_config",
        "scope_claims",
        "peer_identities",
        "curve_keys",
        "market_bindings",
    }
    if type(raw) is not dict or set(raw) != required_fields:
        raise ServiceMarketDeploymentError("INVALID_PROFILE")
    subject = _identifier(raw["subject"])
    identity_raw = _exact_mapping(
        raw["identity"], {"principal_ref", "actor_ref", "delegate_ref"}
    )
    delegate_ref = identity_raw["delegate_ref"]
    identity = sdk["WireIdentity"](
        sdk["WireRole"].APPLICATION_CLIENT,
        _identifier(identity_raw["principal_ref"]),
        _identifier(identity_raw["actor_ref"]),
        None if delegate_ref is None else _identifier(delegate_ref),
    )
    client_raw = raw["client_config"]
    if type(client_raw) is not dict:
        raise ServiceMarketDeploymentError("INVALID_CLIENT_CONFIG")
    try:
        client_config = sdk["parse_client_config"](client_raw)
        public_config = client_config.to_public_dict()
    except Exception:
        raise ServiceMarketDeploymentError("INVALID_CLIENT_CONFIG") from None
    if (
        client_config.process_role != "application_client"
        or client_config.registration.get("application_ref") != identity.actor_ref
    ):
        raise ServiceMarketDeploymentError("CLIENT_IDENTITY_MISMATCH")

    clients = public_config.get("clients")
    if type(clients) is not dict or set(clients) != {"gateway"}:
        raise ServiceMarketDeploymentError("INVALID_CLIENT_BINDINGS")
    settings = clients["gateway"].get("settings")
    bindings = settings.get("bindings") if type(settings) is dict else None
    if type(bindings) is not list or len(bindings) != 1 or type(bindings[0]) is not dict:
        raise ServiceMarketDeploymentError("INVALID_CLIENT_BINDINGS")
    binding = bindings[0]
    if binding.get("mount") != "application.market" or (
        "account_ref" in binding or "portfolio_ref" in binding
    ):
        raise ServiceMarketDeploymentError("INVALID_CLIENT_BINDINGS")
    scope_ref = _identifier(binding.get("scope_ref"))
    service_id = _identifier(binding.get("service_id"))
    transport_ref = _identifier(binding.get("transport_ref"))
    if binding.get("required") is not True:
        raise ServiceMarketDeploymentError("INVALID_CLIENT_BINDINGS")

    scope_claims = raw["scope_claims"]
    if type(scope_claims) is not dict or set(scope_claims) != {scope_ref}:
        raise ServiceMarketDeploymentError("INVALID_SCOPES")
    scope_raw = _exact_mapping(scope_claims[scope_ref], {"execution_domain_ref"})
    scope = sdk["WireScope"](execution_domain_ref=_identifier(scope_raw["execution_domain_ref"]))

    peers_raw = raw["peer_identities"]
    if type(peers_raw) is not dict or set(peers_raw) != {service_id}:
        raise ServiceMarketDeploymentError("INVALID_PEERS")
    peer_raw = _exact_mapping(peers_raw[service_id], {"principal_ref", "actor_ref"})
    if peer_raw["actor_ref"] != service_id:
        raise ServiceMarketDeploymentError("INVALID_PEERS")
    peer = sdk["WireIdentity"](
        sdk["WireRole"].SERVICE,
        _identifier(peer_raw["principal_ref"]),
        service_id,
    )

    communication = public_config.get("communication")
    profiles = communication.get("profiles") if type(communication) is dict else None
    if type(profiles) is not dict or set(profiles) != {transport_ref}:
        raise ServiceMarketDeploymentError("INVALID_TRANSPORT")
    transport = profiles[transport_ref]
    if type(transport) is not dict or transport.get("backend") != "zmq":
        raise ServiceMarketDeploymentError("INVALID_TRANSPORT")
    security_ref = transport.get("security_profile_ref")
    if type(security_ref) is not str or not security_ref:
        raise ServiceMarketDeploymentError("INVALID_TRANSPORT")
    endpoints = transport.get("endpoints")
    if type(endpoints) is not dict or not {"rpc_connect", "market_connect"} <= set(endpoints):
        raise ServiceMarketDeploymentError("INVALID_TRANSPORT")
    options = transport.get("options")
    if type(options) is not dict:
        raise ServiceMarketDeploymentError("INVALID_TRANSPORT")
    if type(options.get("request_timeout_ms")) is not int or options["request_timeout_ms"] > 10_000:
        raise ServiceMarketDeploymentError("INVALID_TRANSPORT")
    if type(options.get("max_message_bytes")) is not int or options["max_message_bytes"] > 1_048_576:
        raise ServiceMarketDeploymentError("INVALID_TRANSPORT")

    curve_raw = raw["curve_keys"]
    if type(curve_raw) is not dict or set(curve_raw) != {security_ref}:
        raise ServiceMarketDeploymentError("INVALID_TRANSPORT_KEYS")
    curve_profile = _exact_mapping(
        curve_raw[security_ref], {"server_key", "public_key", "secret_key"}
    )
    curve_keys = MappingProxyType(
        {
            security_ref: tuple(
                _curve_key(curve_profile[name])
                for name in ("server_key", "public_key", "secret_key")
            )
        }
    )

    market_raw = raw["market_bindings"]
    if (
        type(market_raw) is not list
        or not market_raw
        or len(market_raw) > _MAX_MARKET_BINDINGS_PER_SUBJECT
    ):
        raise ServiceMarketDeploymentError("INVALID_MARKET_BINDINGS")
    routes: dict[tuple[str, str], Any] = {}
    for item in market_raw:
        binding_raw = _exact_mapping(item, {"source", "symbol", "key"})
        source = _identifier(binding_raw["source"]).upper()
        symbol = _identifier(binding_raw["symbol"])
        try:
            key = sdk["MarketSubscriptionKey"].from_dict(binding_raw["key"])
        except Exception:
            raise ServiceMarketDeploymentError("INVALID_MARKET_KEY") from None
        instrument = key.instrument
        if (
            source != "OKX"
            or instrument.provider != "okx"
            or instrument.venue != "OKX"
            or instrument.product_type not in {"SPOT", "SWAP"}
            or instrument.instrument_id != symbol
            or instrument.native_symbol != symbol
            or key.channel != "tickers"
            or key.depth is not None
            or key.timeframe is not None
        ):
            raise ServiceMarketDeploymentError("UNSUPPORTED_MARKET_BINDING")
        route = (source, symbol)
        if route in routes:
            raise ServiceMarketDeploymentError("DUPLICATE_MARKET_BINDING")
        routes[route] = key
    return _MarketProfile(
        subject,
        identity,
        client_config,
        scope,
        peer,
        scope_ref,
        service_id,
        "application.market",
        curve_keys,
        MappingProxyType(routes),
    )


def _load_sdk_types() -> Mapping[str, Any]:
    try:
        from bt_api_base.market_protocol import MarketSubscriptionKey
        from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
        from bt_api_py.service_config import parse_client_config
    except ImportError:
        raise ServiceMarketDeploymentError("SDK_NOT_INSTALLED") from None
    return {
        "MarketSubscriptionKey": MarketSubscriptionKey,
        "WireIdentity": WireIdentity,
        "WireRole": WireRole,
        "WireScope": WireScope,
        "parse_client_config": parse_client_config,
    }


def _curve_key(value: object) -> bytes:
    if (
        type(value) is not str
        or len(value) != 40
        or any(character not in _Z85_ALPHABET for character in value)
    ):
        raise ServiceMarketDeploymentError("INVALID_TRANSPORT_KEYS")
    return value.encode("ascii")


def _identifier(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or value == "*"
        or len(value) > 256
        or not value.isprintable()
    ):
        raise ServiceMarketDeploymentError("INVALID_IDENTIFIER")
    return value


def _exact_mapping(value: object, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ServiceMarketDeploymentError("INVALID_DEPLOYMENT")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _raise_unknown_scope() -> Any:
    raise KeyError("unconfigured service market scope")


def _raise_unknown_peer() -> Any:
    raise KeyError("unconfigured service market peer")


def _safe_error_code(error: BaseException) -> str:
    code = getattr(error, "code", None)
    if type(code) is str and code and len(code) <= 64 and code.replace("_", "").isalnum():
        return code.upper()
    return "SERVICE_MARKET_UNAVAILABLE"


def _failed_results(keys: tuple[Any, ...], code: str) -> dict[str, MarketQuoteResult]:
    return {
        key.stream_id: MarketQuoteResult(None, code, False)
        for key in keys
    }
