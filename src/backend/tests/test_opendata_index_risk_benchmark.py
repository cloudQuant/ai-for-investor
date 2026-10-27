"""Safety tests for the immutable OpenData v2 risk-index benchmark route."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.api import risk_analytics
from app.api.data import queries
from app.db.database import async_session_maker
from app.models.asset_research import AssetDataSourceRegistry
from app.models.permission import Role, user_roles
from app.models.user import User
from app.services.market_data.access import (
    MarketDataAccessAuthorizer,
    MarketDataAccessGrant,
    MarketDataAuthorizationError,
    MarketDataPrincipal,
    MarketDataQueryAccess,
    MarketDataSourceAuthorization,
)
from app.services.market_data.opendata_contracts import (
    OPENDATA_INDEX_BENCHMARK_DATASETS,
    OPENDATA_INDEX_BENCHMARK_FAMILY_ID,
    OPENDATA_INDEX_BENCHMARK_FAMILY_VERSION,
    OPENDATA_INDEX_BENCHMARK_PROVIDER_ENDPOINT,
    OPENDATA_INDEX_BENCHMARK_ROUTE_ID,
    OPENDATA_MAX_PAGE_SIZE,
    OPENDATA_PROVIDER_CONTRACT_REGISTRY,
    prepare_opendata_historical_request,
)
from app.services.market_data.opendata_credentials import OpendataCredentials
from app.services.market_data.opendata_provider import (
    OpendataProvider,
    OpendataPublishedSnapshotResult,
)
from app.services.market_data.provider_contracts import ProviderContractError
from app.services.market_data.provider_models import MarketDataProviderRequest
from app.services.market_data.source_policy import (
    MarketDataProviderRoute,
    MarketDataSourcePolicy,
)
from app.services.risk_analytics.benchmark import BenchmarkService
from app.services.risk_analytics.opendata_index_benchmark import (
    OPENDATA_INDEX_DAILY_POLICY_ID,
    OPENDATA_INDEX_DAILY_ROUTE_ID,
    OpenDataIndexBenchmarkError,
    OpenDataIndexBenchmarkReader,
)
from fastapi import HTTPException

_START = "2024-01-01"
_END_EXCLUSIVE = "2024-01-04"
_SNAPSHOT_ID = "a" * 32
_PUBLICATION_ID = "b" * 32
_CONTRACT_HASH = "c" * 64
_RECORD_HASH = "d" * 64
_EXPECTED_IDENTITY_SEMANTICS = {
    "version": 1,
    "business_key_fields": ["symbol", "trade_date"],
    "identity_key_encoding": "canonical-json-array-v1",
    "revision": "latest non-deleted revision per business_key at the pinned publication sequence",
    "ordering_fields": ["trade_date", "symbol"],
    "storage_order": [
        {"field": "business_date", "direction": "asc", "nulls": "last", "comparison": "native"},
        {"field": "business_key", "direction": "asc", "comparison": "binary_lexicographic"},
    ],
    "temporal_semantics": "business_date",
    "time_field": "trade_date",
    "temporal_fields": {
        "business_date": (
            "business-date bucket; null ordering last (route rejects null time values)"
        ),
        "observed_at": "source observation time",
        "source_published_at": "source publication time",
        "available_at": "platform availability time",
        "event_at": "source event time",
    },
}


def _principal(permissions: tuple[str, ...] = ("data:read",)) -> MarketDataPrincipal:
    return MarketDataPrincipal(
        principal_id="risk-test-user",
        principal_scope="principal-v1:risk-test-user",
        tenant_scope="default",
        roles=("user",),
        permissions=permissions,
        entitlement_revision="e" * 64,
    )


class _TestAuthorizer(MarketDataAccessAuthorizer):
    def __init__(self, grant: MarketDataAccessGrant) -> None:
        super().__init__(object())  # type: ignore[arg-type]
        self.grant = grant

    async def revalidate_principal(self, *, principal: MarketDataPrincipal) -> MarketDataPrincipal:
        return principal

    async def authorize_policy(self, **_kwargs: Any) -> MarketDataAccessGrant:
        return self.grant


class _SnapshotAdapter:
    def __init__(self, result: OpendataPublishedSnapshotResult | Exception) -> None:
        self.result = result
        self.requests: list[tuple[MarketDataProviderRequest, str]] = []

    async def fetch(self, _request: MarketDataProviderRequest) -> None:
        raise AssertionError("risk route must use the pinned v2 snapshot method")

    async def fetch_published_index_snapshot(
        self, request: MarketDataProviderRequest, *, dataset_id: str
    ) -> OpendataPublishedSnapshotResult:
        self.requests.append((request, dataset_id))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _source_authorization(
    purpose: str,
    allowed_uses: tuple[str, ...] | None = None,
) -> MarketDataSourceAuthorization:
    uses = allowed_uses or (("DISPLAY",) if purpose == "display" else ("BACKTEST",))
    return MarketDataSourceAuthorization(
        source_registry_id="opendata",
        registry_updated_at="2026-10-26T00:00:00+00:00",
        asset_type="index",
        market="CN-SSE",
        purpose=purpose,
        license_status="APPROVED",
        allowed_uses=uses,
        jurisdictions=("CN",),
        effective_from="2020-01-01T00:00:00+00:00",
        effective_to=None,
        retention_policy="market-data-v1",
        retention_expires_at=None,
        redistribution_policy="INTERNAL_ONLY",
        principal_scope="principal-v1:risk-test-user",
        tenant_scope="default",
        entitlement_revision="e" * 64,
        decision="ALLOW",
        descriptor_hash="d" * 64,
    )


def _reader(
    adapter: object,
    *,
    purpose: str = "display",
    permissions: tuple[str, ...] = ("data:read",),
    allowed_uses: tuple[str, ...] | None = None,
    authorized_route: bool = True,
) -> OpenDataIndexBenchmarkReader:
    principal = _principal(permissions)
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
        adapter=adapter,  # type: ignore[arg-type]
        family_id=OPENDATA_INDEX_BENCHMARK_FAMILY_ID,
        family_contract_version=OPENDATA_INDEX_BENCHMARK_FAMILY_VERSION,
        provider_endpoint=OPENDATA_INDEX_BENCHMARK_PROVIDER_ENDPOINT,
    )
    source_authorization = _source_authorization(purpose, allowed_uses)
    grant = MarketDataAccessGrant(
        principal=principal,
        policy_id=OPENDATA_INDEX_DAILY_POLICY_ID,
        purpose=purpose,
        route_authorizations=(
            ((OPENDATA_INDEX_BENCHMARK_ROUTE_ID, source_authorization),) if authorized_route else ()
        ),
        policy_descriptor_hash="f" * 64,
    )
    policy = MarketDataSourcePolicy(
        policy_id=OPENDATA_INDEX_DAILY_POLICY_ID,
        allowed_purposes=frozenset({"display", "research", "backtest"}),
        routes=(route,),
    )
    authorizer = _TestAuthorizer(grant)
    return OpenDataIndexBenchmarkReader(
        access=MarketDataQueryAccess(principal=principal, authorizer=authorizer),
        policy=policy,
        route=route,
        grant=grant,
    )


def _snapshot(
    dataset_id: str = "cn.csi300.index.daily",
    *,
    record_count: int = 2,
    start: str = _START,
    end: str = _END_EXCLUSIVE,
) -> dict[str, Any]:
    fields = [
        ("symbol", "string"),
        ("trade_date", "date"),
        ("open", "number"),
        ("high", "number"),
        ("low", "number"),
        ("close", "number"),
        ("volume", "number"),
    ]
    return {
        "dataset_id": dataset_id,
        "publication_id": _PUBLICATION_ID,
        "sequence": 7,
        "schema_version": "index-ohlcv-v1",
        "semantic_version": "ths-index-points-and-shares-v1",
        "contract_sha256": _CONTRACT_HASH,
        "source": {"source_id": "ths.index_daily", "source": "ths"},
        "schema": [
            {"name": name, "data_type": data_type, "nullable": False} for name, data_type in fields
        ],
        "quality": {"status": "passed", "report_id": "quality-report-1", "issue_count": 0},
        "field_units": {
            "open": "index_points",
            "high": "index_points",
            "low": "index_points",
            "close": "index_points",
            "volume": "shares",
        },
        "field_currencies": {},
        "field_adjustments": {
            "open": "not_applicable",
            "high": "not_applicable",
            "low": "not_applicable",
            "close": "not_applicable",
            "volume": "not_applicable",
        },
        "currency": None,
        "adjustment_basis": "not_applicable",
        "asset_class": "index",
        "frequency": "1d",
        "record_kind": "time_series",
        "business_key_fields": ["symbol", "trade_date"],
        "ordering_fields": ["trade_date", "symbol"],
        "storage_order": _EXPECTED_IDENTITY_SEMANTICS["storage_order"],
        "identity_key_encoding": "canonical-json-array-v1",
        "filter_fields": [],
        "time_field": "trade_date",
        "temporal_semantics": "business_date",
        "source_available_at_field": None,
        "calendar_id": None,
        "timezone": "Asia/Shanghai",
        "pit_policy": "unsupported",
        "as_of": "2026-10-27T00:00:00+00:00",
        "identity_semantics": _EXPECTED_IDENTITY_SEMANTICS,
        "snapshot_id": _SNAPSHOT_ID,
        "window": {"start": start, "end": end, "end_exclusive": True},
        "page_size": OPENDATA_MAX_PAGE_SIZE,
        "created_at": "2026-10-27T00:00:00+00:00",
        "expires_at": "2026-10-28T00:00:00+00:00",
        "record_count": record_count,
        "selection_sha256": "1" * 64,
        "content_sha256": "2" * 64,
    }


def _coverage(
    snapshot: dict[str, Any],
    *,
    status: str = "complete",
    observed: tuple[str, str] | None = None,
    missing_ranges: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    window = snapshot["window"]
    requested = {"start": window["start"], "end": window["end"]}
    return {
        "dataset_id": snapshot["dataset_id"],
        "publication_id": snapshot["publication_id"],
        "contract_sha256": snapshot["contract_sha256"],
        "coverage": {
            "status": status,
            "scope": "business_history",
            "requested": requested,
            "observed": ({"start": observed[0], "end": observed[1]} if observed else requested),
            "missing_ranges": missing_ranges if missing_ranges is not None else [],
            "evidence_refs": ["coverage-evidence:verified-index-history"],
            "limitation": None,
        },
    }


def _row(
    day: str,
    *,
    symbol: str = "000300.SH",
    dataset_id: str = "cn.csi300.index.daily",
    close: float = 3510.0,
) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "business_key": json.dumps([symbol, day], separators=(",", ":")),
        "revision": 1,
        "publication_id": _PUBLICATION_ID,
        "publication_sequence": 7,
        "business_date": day,
        "event_at": None,
        "observed_at": "2024-01-02T08:00:00+08:00",
        "source_published_at": "2024-01-02T08:00:00+08:00",
        "available_at": "2024-01-02T08:00:01+08:00",
        "payload": {
            "symbol": symbol,
            "trade_date": day,
            "open": 3500.0,
            "high": 3550.0,
            "low": 3490.0,
            "close": close,
            "volume": 100.0,
        },
        "record_hash": _RECORD_HASH,
    }


def _result(
    *,
    dataset_id: str = "cn.csi300.index.daily",
    coverage_status: str = "complete",
    start: str = _START,
    end: str = _END_EXCLUSIVE,
    observed: tuple[str, str] | None = None,
    missing_ranges: list[dict[str, str]] | None = None,
    records: tuple[dict[str, Any], ...] | None = None,
    page_count: int = 2,
) -> OpendataPublishedSnapshotResult:
    snapshot = _snapshot(
        dataset_id,
        record_count=2 if records is None else len(records),
        start=start,
        end=end,
    )
    return OpendataPublishedSnapshotResult(
        snapshot=snapshot,
        coverage=_coverage(
            snapshot,
            status=coverage_status,
            observed=observed,
            missing_ranges=missing_ranges,
        ),
        records=records or (_row("2024-01-02"), _row("2024-01-03", close=3520.0)),
        page_count=page_count,
    )


def _provider(handler: Any) -> tuple[OpendataProvider, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
    return (
        OpendataProvider(
            client=client,
            credentials=OpendataCredentials("test-key", base_url="http://opendata.test"),
            max_retries=0,
        ),
        client,
    )


def test_index_route_uses_new_published_snapshot_identity_and_stock_contract_is_unchanged() -> None:
    assert OPENDATA_INDEX_BENCHMARK_ROUTE_ID == "opendata-index-benchmark-published-v2"
    assert OPENDATA_INDEX_BENCHMARK_FAMILY_VERSION == "risk-index-benchmark-published-v2"
    assert (
        "GET /api/v2/datasets/{dataset_id}/coverage" in OPENDATA_INDEX_BENCHMARK_PROVIDER_ENDPOINT
    )
    assert OPENDATA_INDEX_BENCHMARK_DATASETS == {
        "hs300": ("000300.SH", "cn.csi300.index.daily"),
        "csi500": ("000905.SH", "cn.csi500.index.daily"),
        "csi800": ("000906.SH", "cn.csi800.index.daily"),
    }
    assert {contract.route_id for contract in OPENDATA_PROVIDER_CONTRACT_REGISTRY.contracts} == {
        "opendata-stock-daily-v1"
    }
    stock_contract = OPENDATA_PROVIDER_CONTRACT_REGISTRY.contract_for(
        provider="opendata", route_id="opendata-stock-daily-v1"
    )
    stock_request = MarketDataProviderRequest(
        query_fingerprint="a" * 64,
        canonical_id="stock:600000.SH",
        asset_type="stock",
        provider_symbol="600000.SH",
        market="CN-SSE",
        data_kind="bars",
        frequency="1d",
        start_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_at=datetime(2024, 1, 4, tzinfo=timezone.utc),
        required_fields=frozenset({"close"}),
        provider="opendata",
        adjustment="qfq",
        price_basis="close",
        currency="CNY",
        unit="share",
        source_policy_id="market-default-v1",
        route_id="opendata-stock-daily-v1",
        family_id="stock.realtime",
        family_contract_version="market-data-family-v1",
    )
    params = prepare_opendata_historical_request(stock_contract, stock_request)
    assert params["source"] == "auto"
    assert params["adjust"] == "qfq"
    with pytest.raises(ProviderContractError):
        OPENDATA_PROVIDER_CONTRACT_REGISTRY.contract_for(
            provider="opendata", route_id=OPENDATA_INDEX_BENCHMARK_ROUTE_ID
        )


def test_default_policy_registers_index_route_only_when_both_opendata_switches_are_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubProvider:
        async def fetch(self, _request: MarketDataProviderRequest) -> Any:
            raise AssertionError("policy assembly must not fetch data")

    provider = StubProvider()
    monkeypatch.setattr(queries, "_shared_akshare_provider", lambda: provider)
    monkeypatch.setattr(queries, "_shared_opendata_provider", lambda: provider)
    queries._default_source_policy_registry.cache_clear()
    try:
        for opendata_enabled, risk_enabled, expected in (
            (False, False, False),
            (False, True, False),
            (True, False, False),
            (True, True, True),
        ):
            registry = queries._default_source_policy_registry(
                "yfinance",
                (),
                opendata_enabled=opendata_enabled,
                risk_benchmark_opendata_enabled=risk_enabled,
            )
            route_ids = {route.route_id for route in registry.resolve("market-default-v1").routes}
            assert (OPENDATA_INDEX_BENCHMARK_ROUTE_ID in route_ids) is expected
    finally:
        queries._default_source_policy_registry.cache_clear()


@pytest.mark.parametrize("benchmark_id", ["hs300", "csi500", "csi800"])
@pytest.mark.asyncio
async def test_reader_preserves_exact_dataset_and_exchange_symbol(benchmark_id: str) -> None:
    symbol, dataset_id = OPENDATA_INDEX_BENCHMARK_DATASETS[benchmark_id]
    record_rows = (
        _row("2024-01-02", symbol=symbol, dataset_id=dataset_id),
        _row("2024-01-03", symbol=symbol, dataset_id=dataset_id, close=3520.0),
    )
    snapshot = _snapshot(dataset_id, record_count=2)
    result = OpendataPublishedSnapshotResult(
        snapshot=snapshot,
        coverage=_coverage(snapshot),
        records=record_rows,
        page_count=2,
    )
    adapter = _SnapshotAdapter(result)
    reader = _reader(adapter)

    rows = await reader.fetch_prices(benchmark_id, symbol, _START, "2024-01-03")

    assert rows == [
        {"date": "2024-01-02", "close": 3510.0},
        {"date": "2024-01-03", "close": 3520.0},
    ]
    request, requested_dataset = adapter.requests[0]
    assert requested_dataset == dataset_id
    assert request.provider_symbol == symbol
    assert request.canonical_id == f"index:{benchmark_id}"
    assert request.route_id == OPENDATA_INDEX_BENCHMARK_ROUTE_ID
    assert request.family_contract_version == OPENDATA_INDEX_BENCHMARK_FAMILY_VERSION
    assert request.start_at.date().isoformat() == _START
    assert request.end_at.date().isoformat() == _END_EXCLUSIVE


@pytest.mark.parametrize(
    "invalid_coverage",
    [
        "observed-before-request",
        "observed-after-request",
        "reversed-observed",
        "empty-observed",
        "null-observed",
        "missing-range",
    ],
)
@pytest.mark.asyncio
async def test_reader_rejects_complete_coverage_with_out_of_bounds_or_missing_observations(
    invalid_coverage: str,
) -> None:
    result = _result()
    coverage = dict(result.coverage)
    coverage_details = dict(coverage["coverage"])
    if invalid_coverage == "observed-before-request":
        coverage_details["observed"] = {"start": "2023-12-31", "end": "2024-01-03"}
    elif invalid_coverage == "observed-after-request":
        coverage_details["observed"] = {"start": "2024-01-02", "end": "2024-01-05"}
    elif invalid_coverage == "reversed-observed":
        coverage_details["observed"] = {"start": "2024-01-03", "end": "2024-01-02"}
    elif invalid_coverage == "empty-observed":
        coverage_details["observed"] = {"start": "2024-01-02", "end": "2024-01-02"}
    elif invalid_coverage == "null-observed":
        coverage_details["observed"] = None
    else:
        coverage_details["missing_ranges"] = [{"start": "2024-01-03", "end": "2024-01-04"}]
    coverage["coverage"] = coverage_details
    invalid_result = OpendataPublishedSnapshotResult(
        snapshot=result.snapshot,
        coverage=coverage,
        records=result.records,
        page_count=result.page_count,
    )
    reader = _reader(_SnapshotAdapter(invalid_result))

    with pytest.raises(OpenDataIndexBenchmarkError) as exc_info:
        await reader.fetch_prices("hs300", "000300.SH", _START, "2024-01-03")

    assert exc_info.value.code == "opendata_coverage_unavailable"


@pytest.mark.parametrize(
    ("permissions", "purpose", "uses", "authorized_route"),
    [
        ((), "display", ("DISPLAY",), True),
        (("data:read",), "display", ("RESEARCH",), True),
        (("data:read",), "backtest", ("DISPLAY",), True),
        (("data:read",), "display", ("DISPLAY",), False),
    ],
)
def test_reader_rejects_missing_read_route_or_matching_source_use(
    permissions: tuple[str, ...],
    purpose: str,
    uses: tuple[str, ...],
    authorized_route: bool,
) -> None:
    adapter = _SnapshotAdapter(_result())
    with pytest.raises(MarketDataAuthorizationError):
        _reader(
            adapter,
            purpose=purpose,
            permissions=permissions,
            allowed_uses=uses,
            authorized_route=authorized_route,
        )
    assert adapter.requests == []


@pytest.mark.parametrize(
    ("purpose", "allowed_uses", "expected_allow", "expected_error"),
    [
        ("display", ["DISPLAY"], True, None),
        ("backtest", ["BACKTEST"], True, None),
        ("display", ["RESEARCH"], False, "SOURCE_USE_DENIED"),
        ("backtest", ["DISPLAY"], False, "SOURCE_USE_DENIED"),
        ("display", None, False, "SOURCE_REGISTRY_UNREGISTERED"),
    ],
)
@pytest.mark.asyncio
async def test_real_source_registry_authorization_separates_display_and_backtest_uses(
    purpose: str,
    allowed_uses: list[str] | None,
    expected_allow: bool,
    expected_error: str | None,
) -> None:
    suffix = uuid4().hex
    user = User(
        username=f"risk-source-{suffix}",
        email=f"risk-source-{suffix}@example.test",
        hashed_password="not-used",
        is_active=True,
    )
    async with async_session_maker() as session:
        session.add(user)
        await session.flush()
        await session.execute(user_roles.insert().values(user_id=user.id, role=Role.USER.value))
        if allowed_uses is not None:
            session.add(
                AssetDataSourceRegistry(
                    source_id="opendata",
                    asset_types=["index"],
                    jurisdictions=["CN"],
                    license_status="APPROVED",
                    allowed_uses=allowed_uses,
                    redistribution_policy="INTERNAL_ONLY",
                    derived_data_policy="ALLOWED",
                    retention_policy="market-data-v1",
                    effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
                    effective_to=None,
                    enabled=True,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        await session.commit()

        authorizer = MarketDataAccessAuthorizer(session)
        principal = await authorizer.principal_for_user(user)
        seed_adapter = _SnapshotAdapter(_result())
        seed_reader = _reader(seed_adapter, purpose=purpose)
        route = seed_reader._route
        policy = seed_reader._policy
        if expected_allow:
            grant = await authorizer.authorize_policy(
                principal=principal,
                policy=policy,
                routes=(route,),
                asset_type="index",
                market="CN-SSE",
                purpose=purpose,
            )
            reader = OpenDataIndexBenchmarkReader(
                access=MarketDataQueryAccess(principal=principal, authorizer=authorizer),
                policy=policy,
                route=route,
                grant=grant,
            )
            rows = await reader.fetch_prices("hs300", "000300.SH", _START, "2024-01-03")
            assert grant.authorized_route_ids == {OPENDATA_INDEX_BENCHMARK_ROUTE_ID}
            assert grant.authorization_for_route(
                OPENDATA_INDEX_BENCHMARK_ROUTE_ID
            ).allowed_uses == tuple(allowed_uses or ())
            assert len(seed_adapter.requests) == 1
            assert rows[0] == {"date": "2024-01-02", "close": 3510.0}
        else:
            with pytest.raises(MarketDataAuthorizationError) as exc_info:
                await authorizer.authorize_policy(
                    principal=principal,
                    policy=policy,
                    routes=(route,),
                    asset_type="index",
                    market="CN-SSE",
                    purpose=purpose,
                )
            assert exc_info.value.code == expected_error
            assert seed_adapter.requests == []


@pytest.mark.asyncio
async def test_provider_pins_each_page_and_rejects_unverified_coverage_before_records() -> None:
    snapshot = _snapshot(record_count=2)
    coverage = _coverage(snapshot)
    rows = [_row("2024-01-02"), _row("2024-01-03", close=3520.0)]
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["X-API-Key"] == "test-key"
        if request.url.path.endswith("/coverage"):
            assert request.url.params["start_date"] == _START
            assert request.url.params["end_date"] == _END_EXCLUSIVE
            return httpx.Response(200, json=coverage)
        if request.method == "POST":
            assert request.url.path == "/api/v2/snapshots"
            assert json.loads(request.content) == {
                "dataset_id": "cn.csi300.index.daily",
                "publication_id": _PUBLICATION_ID,
                "start_date": _START,
                "end_date": _END_EXCLUSIVE,
                "page_size": OPENDATA_MAX_PAGE_SIZE,
            }
            return httpx.Response(201, json=snapshot)
        assert request.url.path == "/api/v2/datasets/cn.csi300.index.daily/records"
        assert request.url.params["snapshot_id"] == _SNAPSHOT_ID
        if "cursor" not in request.url.params:
            page_rows = rows[:1]
            next_cursor = "cursor-page-two"
        else:
            assert request.url.params["cursor"] == "cursor-page-two"
            page_rows = rows[1:]
            next_cursor = None
        page = {
            **snapshot,
            "rows": page_rows,
            "count": len(page_rows),
            "next_cursor": next_cursor,
            "has_more": next_cursor is not None,
            "meta": {
                "snapshot": snapshot,
                "ordering_fields": snapshot["ordering_fields"],
                "storage_order": snapshot["storage_order"],
                "identity_key_encoding": snapshot["identity_key_encoding"],
            },
        }
        return httpx.Response(200, json=page)

    provider, client = _provider(handler)
    try:
        reader = _reader(provider)

        async def fetch_reader_prices(symbol: str, start: str, end: str) -> list[dict[str, Any]]:
            return await reader.fetch_prices("hs300", symbol, start, end)

        result = await BenchmarkService().get_benchmark_returns(
            "hs300",
            _START,
            "2024-01-03",
            data_fetcher=fetch_reader_prices,
        )
    finally:
        await client.aclose()

    assert result.status == "ok"
    assert result.symbol == "000300.SH"
    assert result.dates == ["2024-01-02", "2024-01-03"]
    assert result.returns == [round((3520.0 - 3510.0) / 3510.0, 6)]
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/api/v2/datasets/cn.csi300.index.daily/coverage"),
        ("POST", "/api/v2/snapshots"),
        ("GET", "/api/v2/datasets/cn.csi300.index.daily/records"),
        ("GET", "/api/v2/datasets/cn.csi300.index.daily/records"),
    ]


@pytest.mark.asyncio
async def test_provider_and_reader_accept_weekend_holiday_edges_without_rewriting_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = "2024-02-10"  # Lunar New Year holiday and Saturday.
    end_exclusive = "2024-02-25"  # Sunday after the final covered session.
    end_inclusive = "2024-02-24"
    observed = ("2024-02-19", "2024-02-24")
    snapshot = _snapshot(
        record_count=5,
        start=start,
        end=end_exclusive,
    )
    coverage = _coverage(snapshot, observed=observed)
    trading_dates = (
        "2024-02-19",
        "2024-02-20",
        "2024-02-21",
        "2024-02-22",
        "2024-02-23",
    )
    rows = [_row(day, close=3510.0 + index * 10.0) for index, day in enumerate(trading_dates)]
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/coverage"):
            assert request.url.params["start_date"] == start
            assert request.url.params["end_date"] == end_exclusive
            return httpx.Response(200, json=coverage)
        if request.method == "POST":
            assert json.loads(request.content) == {
                "dataset_id": "cn.csi300.index.daily",
                "publication_id": _PUBLICATION_ID,
                "start_date": start,
                "end_date": end_exclusive,
                "page_size": OPENDATA_MAX_PAGE_SIZE,
            }
            return httpx.Response(201, json=snapshot)
        assert request.url.params["snapshot_id"] == _SNAPSHOT_ID
        if "cursor" not in request.url.params:
            page_rows = rows[:2]
            next_cursor = "weekend-window-page-two"
        else:
            assert request.url.params["cursor"] == "weekend-window-page-two"
            page_rows = rows[2:]
            next_cursor = None
        return httpx.Response(
            200,
            json={
                **snapshot,
                "rows": page_rows,
                "count": len(page_rows),
                "next_cursor": next_cursor,
                "has_more": next_cursor is not None,
                "meta": {
                    "snapshot": snapshot,
                    "ordering_fields": snapshot["ordering_fields"],
                    "storage_order": snapshot["storage_order"],
                    "identity_key_encoding": snapshot["identity_key_encoding"],
                },
            },
        )

    provider, client = _provider(handler)
    published_results: list[OpendataPublishedSnapshotResult] = []
    original_fetch = provider.fetch_published_index_snapshot

    async def capture_snapshot(
        request: MarketDataProviderRequest,
        *,
        dataset_id: str,
    ) -> OpendataPublishedSnapshotResult:
        result = await original_fetch(request, dataset_id=dataset_id)
        published_results.append(result)
        return result

    monkeypatch.setattr(provider, "fetch_published_index_snapshot", capture_snapshot)
    try:
        reader = _reader(provider)

        async def fetch_reader_prices(
            symbol: str, fetch_start: str, fetch_end: str
        ) -> list[dict[str, Any]]:
            return await reader.fetch_prices("hs300", symbol, fetch_start, fetch_end)

        result = await BenchmarkService().get_benchmark_returns(
            "hs300",
            start,
            end_inclusive,
            data_fetcher=fetch_reader_prices,
        )
    finally:
        await client.aclose()

    assert result.status == "ok"
    assert result.dates == list(trading_dates)
    assert len(published_results) == 1
    assert published_results[0].coverage == coverage
    assert published_results[0].coverage["coverage"]["requested"] == {
        "start": start,
        "end": end_exclusive,
    }
    assert published_results[0].coverage["coverage"]["observed"] == {
        "start": observed[0],
        "end": observed[1],
    }
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/api/v2/datasets/cn.csi300.index.daily/coverage"),
        ("POST", "/api/v2/snapshots"),
        ("GET", "/api/v2/datasets/cn.csi300.index.daily/records"),
        ("GET", "/api/v2/datasets/cn.csi300.index.daily/records"),
    ]


@pytest.mark.parametrize(
    "invalid_coverage",
    [
        "observed-before-request",
        "observed-after-request",
        "reversed-observed",
        "empty-observed",
        "null-observed",
        "missing-range",
    ],
)
@pytest.mark.asyncio
async def test_provider_rejects_false_complete_coverage_before_creating_snapshot(
    invalid_coverage: str,
) -> None:
    snapshot = _snapshot(record_count=0)
    coverage = _coverage(snapshot)
    coverage_details = coverage["coverage"]
    if invalid_coverage == "observed-before-request":
        coverage_details["observed"] = {"start": "2023-12-31", "end": "2024-01-03"}
    elif invalid_coverage == "observed-after-request":
        coverage_details["observed"] = {"start": "2024-01-02", "end": "2024-01-05"}
    elif invalid_coverage == "reversed-observed":
        coverage_details["observed"] = {"start": "2024-01-03", "end": "2024-01-02"}
    elif invalid_coverage == "empty-observed":
        coverage_details["observed"] = {"start": "2024-01-02", "end": "2024-01-02"}
    elif invalid_coverage == "null-observed":
        coverage_details["observed"] = None
    else:
        coverage_details["missing_ranges"] = [{"start": "2024-01-03", "end": "2024-01-04"}]
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/api/v2/datasets/cn.csi300.index.daily/coverage"
        return httpx.Response(200, json=coverage)

    provider, client = _provider(handler)
    try:
        reader = _reader(provider)
        with pytest.raises(OpenDataIndexBenchmarkError) as exc_info:
            await reader.fetch_prices("hs300", "000300.SH", _START, "2024-01-03")
    finally:
        await client.aclose()

    assert exc_info.value.code == "opendata_coverage_unavailable"
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/api/v2/datasets/cn.csi300.index.daily/coverage")
    ]


@pytest.mark.asyncio
async def test_unknown_coverage_stops_before_any_records_request() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        return httpx.Response(
            200,
            json=_coverage(_snapshot(record_count=0), status="unknown"),
        )

    provider, client = _provider(handler)
    try:
        reader = _reader(provider)
        with pytest.raises(OpenDataIndexBenchmarkError) as exc_info:
            await reader.fetch_prices("hs300", "000300.SH", _START, "2024-01-03")
    finally:
        await client.aclose()

    assert exc_info.value.code == "opendata_coverage_unavailable"
    assert [request.url.path for request in requests] == [
        "/api/v2/datasets/cn.csi300.index.daily/coverage"
    ]


@pytest.mark.asyncio
async def test_snapshot_must_match_coverage_publication_before_records() -> None:
    coverage_snapshot = _snapshot(record_count=0)
    changed_snapshot = dict(coverage_snapshot)
    changed_snapshot["publication_id"] = "e" * 32
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/coverage"):
            return httpx.Response(200, json=_coverage(coverage_snapshot))
        if request.method == "POST":
            payload = json.loads(request.content)
            assert payload["publication_id"] == _PUBLICATION_ID
            return httpx.Response(201, json=changed_snapshot)
        raise AssertionError("publication mismatch must stop before records retrieval")

    provider, client = _provider(handler)
    try:
        reader = _reader(provider)
        with pytest.raises(OpenDataIndexBenchmarkError) as exc_info:
            await reader.fetch_prices("hs300", "000300.SH", _START, "2024-01-03")
    finally:
        await client.aclose()

    assert exc_info.value.code == "opendata_snapshot_metadata_invalid"
    assert [request.url.path for request in requests] == [
        "/api/v2/datasets/cn.csi300.index.daily/coverage",
        "/api/v2/snapshots",
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda snapshot: snapshot.update(dataset_id="cn.csi500.index.daily"),
        lambda snapshot: snapshot.update(semantic_version="changed"),
        lambda snapshot: snapshot.update(pit_policy="supported"),
        lambda snapshot: snapshot.update(quality={"status": "warning", "issue_count": 1}),
    ],
)
@pytest.mark.asyncio
async def test_reader_rejects_snapshot_contract_drift(mutation: Any) -> None:
    result = _result()
    snapshot = dict(result.snapshot)
    mutation(snapshot)
    adapter = _SnapshotAdapter(
        OpendataPublishedSnapshotResult(
            snapshot=snapshot,
            coverage=result.coverage,
            records=result.records,
            page_count=result.page_count,
        )
    )
    reader = _reader(adapter)

    with pytest.raises(OpenDataIndexBenchmarkError) as exc_info:
        await reader.fetch_prices("hs300", "000300.SH", _START, "2024-01-03")

    assert exc_info.value.code == "opendata_snapshot_contract_mismatch"


@pytest.mark.asyncio
async def test_display_endpoint_uses_display_grant_and_never_falls_back_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {"purpose": None, "legacy": 0}

    class FailingReader:
        async def fetch_prices(self, *_args: Any) -> list[dict[str, Any]]:
            raise OpenDataIndexBenchmarkError("opendata_coverage_unavailable")

    class FallbackDetectingService:
        async def get_benchmark_returns(
            self, benchmark_id: str, start: str, end: str, *, data_fetcher: Any = None
        ) -> Any:
            if data_fetcher is None:
                calls["legacy"] += 1
                raise AssertionError("feature-on failure must not call the legacy fetcher")
            await data_fetcher("000300.SH", start, end)
            raise AssertionError("expected fail-closed OpenData error")

    async def authorized_reader(**kwargs: Any) -> FailingReader:
        calls["purpose"] = kwargs["purpose"]
        return FailingReader()

    async def rollback() -> None:
        return None

    monkeypatch.setattr(
        risk_analytics,
        "get_settings",
        lambda: SimpleNamespace(MARKET_DATA_RISK_BENCHMARK_OPENDATA_ENABLED=True),
    )
    monkeypatch.setattr(
        risk_analytics,
        "_authorized_opendata_index_benchmark_reader",
        authorized_reader,
    )

    result = await risk_analytics.get_benchmark_returns(
        "hs300",
        _START,
        "2024-01-03",
        current_user=SimpleNamespace(sub="risk-test-user"),
        benchmark_service=FallbackDetectingService(),  # type: ignore[arg-type]
        db=SimpleNamespace(rollback=rollback),  # type: ignore[arg-type]
    )

    assert result.status == "degraded"
    assert result.reason == "opendata_coverage_unavailable"
    assert calls == {"purpose": "display", "legacy": 0}


@pytest.mark.asyncio
async def test_metrics_route_uses_backtest_source_grant_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {"purpose": None, "legacy": 0}

    class FailingReader:
        async def fetch_prices(self, *_args: Any) -> list[dict[str, Any]]:
            raise OpenDataIndexBenchmarkError("opendata_coverage_unavailable")

    class BacktestStub:
        async def get_result(self, _backtest_id: str, *, user_id: str) -> Any:
            return SimpleNamespace(equity_curve=[100.0, 110.0], equity_dates=[_START, "2024-01-02"])

    class BenchmarkServiceStub:
        async def get_benchmark_returns(
            self, _benchmark_id: str, start: str, end: str, *, data_fetcher: Any = None
        ) -> Any:
            if data_fetcher is None:
                calls["legacy"] += 1
                raise AssertionError("feature-on failure must not call the legacy fetcher")
            await data_fetcher("000300.SH", start, end)
            raise AssertionError("expected fail-closed OpenData error")

    class MetricsStub:
        @staticmethod
        def return_observations_from_equity_curve(*_args: Any) -> list[Any]:
            return [SimpleNamespace(start_date=_START, end_date="2024-01-02")]

    async def authorized_reader(**kwargs: Any) -> FailingReader:
        calls["purpose"] = kwargs["purpose"]
        return FailingReader()

    async def rollback() -> None:
        return None

    monkeypatch.setattr(
        risk_analytics,
        "get_settings",
        lambda: SimpleNamespace(MARKET_DATA_RISK_BENCHMARK_OPENDATA_ENABLED=True),
    )
    monkeypatch.setattr(
        risk_analytics,
        "_authorized_opendata_index_benchmark_reader",
        authorized_reader,
    )

    result = await risk_analytics.get_benchmark_metrics(
        "backtest-1",
        benchmark_id="hs300",
        risk_free_rate=0.0,
        current_user=SimpleNamespace(sub="risk-test-user"),
        backtest_service=BacktestStub(),  # type: ignore[arg-type]
        benchmark_service=BenchmarkServiceStub(),  # type: ignore[arg-type]
        benchmark_metrics_service=MetricsStub(),  # type: ignore[arg-type]
        db=SimpleNamespace(rollback=rollback),  # type: ignore[arg-type]
    )

    assert result.status == "degraded"
    assert result.reason == "opendata_coverage_unavailable"
    assert calls == {"purpose": "backtest", "legacy": 0}


@pytest.mark.parametrize("permissions", [(), ("market_data:read",)])
@pytest.mark.asyncio
async def test_api_read_data_gate_denies_before_route_capability_or_reader(
    permissions: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability_checks = 0

    class PrincipalAuthorizer(MarketDataAccessAuthorizer):
        def __init__(self, _db: object) -> None:
            pass

        async def principal_for_user(self, _user: object) -> MarketDataPrincipal:
            return _principal(permissions)

    async def capabilities_must_not_be_checked(**_kwargs: Any) -> None:
        nonlocal capability_checks
        capability_checks += 1
        raise AssertionError("READ_DATA must be checked before route capabilities")

    monkeypatch.setattr(risk_analytics, "MarketDataAccessAuthorizer", PrincipalAuthorizer)
    monkeypatch.setattr(
        risk_analytics,
        "evaluate_market_data_capabilities",
        capabilities_must_not_be_checked,
    )

    with pytest.raises(HTTPException) as exc_info:
        await risk_analytics._authorized_opendata_index_benchmark_reader(
            db=object(),
            current_user=SimpleNamespace(sub="risk-test-user"),
            purpose="display",
            settings=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "MARKET_DATA_READ_ENTITLEMENT_DENIED"
    assert capability_checks == 0


@pytest.mark.asyncio
async def test_missing_durable_route_attestation_stops_before_source_grant_or_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize_calls = 0
    reader_constructions = 0

    class PrincipalAuthorizer(MarketDataAccessAuthorizer):
        def __init__(self, _db: object) -> None:
            pass

        async def principal_for_user(self, _user: object) -> MarketDataPrincipal:
            return _principal(("data:read",))

        async def authorize_policy(self, **_kwargs: Any) -> MarketDataAccessGrant:
            nonlocal authorize_calls
            authorize_calls += 1
            raise AssertionError("missing durable attestation must stop before source grant")

    class ReaderMustNotBeBuilt:
        def __init__(self, **_kwargs: Any) -> None:
            nonlocal reader_constructions
            reader_constructions += 1
            raise AssertionError("missing durable attestation must stop before reader creation")

    async def missing_attestation(_db: object, *, settings: object | None = None) -> Any:
        return SimpleNamespace(
            response=SimpleNamespace(online_fetch_enabled=True),
            route_is_effective=lambda route_id: route_id != OPENDATA_INDEX_DAILY_ROUTE_ID,
        )

    monkeypatch.setattr(risk_analytics, "MarketDataAccessAuthorizer", PrincipalAuthorizer)
    monkeypatch.setattr(risk_analytics, "evaluate_market_data_capabilities", missing_attestation)
    monkeypatch.setattr(risk_analytics, "OpenDataIndexBenchmarkReader", ReaderMustNotBeBuilt)

    with pytest.raises(HTTPException) as exc_info:
        await risk_analytics._authorized_opendata_index_benchmark_reader(
            db=object(),
            current_user=SimpleNamespace(sub="risk-test-user"),
            purpose="display",
            settings=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "OPENDATA_RISK_BENCHMARK_ROUTE_UNAVAILABLE"
    assert authorize_calls == 0
    assert reader_constructions == 0


@pytest.mark.asyncio
async def test_disabled_switch_retains_legacy_path_selector() -> None:
    assert not risk_analytics._uses_opendata_risk_benchmark(
        SimpleNamespace(MARKET_DATA_RISK_BENCHMARK_OPENDATA_ENABLED=False), "hs300"
    )
    enabled = SimpleNamespace(MARKET_DATA_RISK_BENCHMARK_OPENDATA_ENABLED=True)
    assert all(
        risk_analytics._uses_opendata_risk_benchmark(enabled, benchmark_id)
        for benchmark_id in ("hs300", "csi500", "csi800")
    )
    assert not risk_analytics._uses_opendata_risk_benchmark(enabled, "spx")


@pytest.mark.parametrize("benchmark_id", ["hs300", "csi500", "csi800"])
@pytest.mark.asyncio
async def test_default_benchmark_service_fails_closed_for_unmigrated_opendata_indices(
    benchmark_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def legacy_fetcher(symbol: str, _start: str, _end: str) -> list[dict[str, Any]]:
        calls.append(symbol)
        return [
            {"date": "2024-01-01", "close": 100.0},
            {"date": "2024-01-02", "close": 101.0},
        ]

    monkeypatch.setattr(
        "app.services.risk_analytics.benchmark.get_settings",
        lambda: SimpleNamespace(MARKET_DATA_RISK_BENCHMARK_OPENDATA_ENABLED=True),
    )
    monkeypatch.setattr(BenchmarkService, "_default_fetcher", staticmethod(legacy_fetcher))

    result = await BenchmarkService().get_benchmark_returns(benchmark_id, _START, "2024-01-03")

    assert result.status == "degraded"
    assert result.reason == "opendata_benchmark_consumer_not_migrated"
    assert calls == []


@pytest.mark.asyncio
async def test_default_benchmark_guard_preserves_other_assets_and_explicit_fetchers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fetcher(symbol: str, _start: str, _end: str) -> list[dict[str, Any]]:
        calls.append(symbol)
        return [
            {"date": "2024-01-01", "close": 100.0},
            {"date": "2024-01-02", "close": 101.0},
        ]

    monkeypatch.setattr(
        "app.services.risk_analytics.benchmark.get_settings",
        lambda: SimpleNamespace(MARKET_DATA_RISK_BENCHMARK_OPENDATA_ENABLED=True),
    )
    monkeypatch.setattr(BenchmarkService, "_default_fetcher", staticmethod(fetcher))

    default_service = BenchmarkService()
    other_asset = await default_service.get_benchmark_returns("spx", _START, "2024-01-03")
    per_call_fetcher = await default_service.get_benchmark_returns(
        "hs300", _START, "2024-01-03", data_fetcher=fetcher
    )
    configured_fetcher = await BenchmarkService(data_fetcher=fetcher).get_benchmark_returns(
        "csi500", _START, "2024-01-03"
    )

    assert other_asset.status == "ok"
    assert per_call_fetcher.status == "ok"
    assert configured_fetcher.status == "ok"
    assert calls == ["SPX", "000300.SH", "000905.SH"]


@pytest.mark.parametrize(
    ("denied_scope", "expected_methods"),
    [
        ("coverage.read", ["GET"]),
        ("snapshot.create", ["GET", "POST"]),
        ("data.read", ["GET", "POST", "GET"]),
    ],
)
@pytest.mark.asyncio
async def test_dataset_scope_denial_fails_closed_without_retry_or_fallback(
    denied_scope: str,
    expected_methods: list[str],
) -> None:
    snapshot = _snapshot(record_count=0)
    coverage = _coverage(snapshot)
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/coverage"):
            if denied_scope == "coverage.read":
                return httpx.Response(403, json={"error": {"code": "permission_denied"}})
            return httpx.Response(200, json=coverage)
        if request.method == "POST":
            if denied_scope == "snapshot.create":
                return httpx.Response(403, json={"error": {"code": "permission_denied"}})
            return httpx.Response(201, json=snapshot)
        assert request.url.path.endswith("/records")
        if denied_scope == "data.read":
            return httpx.Response(403, json={"error": {"code": "permission_denied"}})
        page = {
            **snapshot,
            "rows": [],
            "count": 0,
            "next_cursor": None,
            "has_more": False,
            "meta": {
                "snapshot": snapshot,
                "ordering_fields": snapshot["ordering_fields"],
                "storage_order": snapshot["storage_order"],
                "identity_key_encoding": snapshot["identity_key_encoding"],
            },
        }
        return httpx.Response(200, json=page)

    provider, client = _provider(handler)
    try:
        reader = _reader(provider)
        with pytest.raises(OpenDataIndexBenchmarkError) as exc_info:
            await reader.fetch_prices("hs300", "000300.SH", _START, "2024-01-03")
    finally:
        await client.aclose()

    assert exc_info.value.code == "opendata_dataset_grant_denied"
    assert [request.method for request in requests] == expected_methods
    assert [request.url.path for request in requests] == {
        "coverage.read": ["/api/v2/datasets/cn.csi300.index.daily/coverage"],
        "snapshot.create": [
            "/api/v2/datasets/cn.csi300.index.daily/coverage",
            "/api/v2/snapshots",
        ],
        "data.read": [
            "/api/v2/datasets/cn.csi300.index.daily/coverage",
            "/api/v2/snapshots",
            "/api/v2/datasets/cn.csi300.index.daily/records",
        ],
    }[denied_scope]
