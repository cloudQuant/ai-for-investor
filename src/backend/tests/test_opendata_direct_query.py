"""Contracts for the direct OpenData daily K-line compatibility slice."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
import pytest_asyncio
from httpx import AsyncClient

import app.api.data.base as data_base
from app.api.data.deps import get_authorized_market_data_access
from app.api.data.queries import (
    get_market_data_capability_evaluation,
    get_market_data_query_service,
)
from app.db.database import get_db
from app.main import app
from app.schemas.asset_research import InstrumentIdentity, StockIdentityDetails
from app.schemas.market_data_platform import MarketDataQueryRequest, ResolvedMarketDataQuery
from app.services.market_data.access import (
    MarketDataAccessAuthorizer,
    MarketDataAccessGrant,
    MarketDataPrincipal,
    MarketDataQueryAccess,
    MarketDataSourceAuthorization,
)
from app.services.market_data.catalog import DatasetStorageResolution
from app.services.market_data.coverage import QueryIdentity
from app.services.market_data.dataset_contracts import FAMILY_CONTRACT_VERSION
from app.services.market_data.identity import ResolvedMarketDataIdentity
from app.services.market_data.legacy_kline_projection import LegacyKlineRequest
from app.services.market_data.opendata_credentials import OpendataCredentials
from app.services.market_data.opendata_provider import OpendataProvider
from app.services.market_data.publication import MarketDataVisibilityAnchor
from app.services.market_data.query_resolution import ResolvedMarketDataQueryContext
from app.services.market_data.query_service import (
    MarketDataQueryService,
)
from app.services.market_data.source_policy import (
    MarketDataProviderRoute,
    MarketDataSourcePolicy,
    MarketDataSourcePolicyRegistry,
)

UTC = timezone.utc
CANONICAL_ID = "instrument:stock:CN-SSE:600000"
METADATA_VERSION = "stock-v1"
ROUTE_ID = "opendata-stock-daily-v1"
_BASE_CONTRACT = {
    "version": "market-data-v2",
    "request": {
        "identity": {"canonical_id": CANONICAL_ID},
        "dataset_code": "market.bars",
        "data_kind": "bars",
        "frequency": "1d",
        "required_fields": ["close"],
        "adjustment": "qfq",
        "price_basis": "close",
        "currency": "CNY",
        "unit": "share",
        "source_policy_id": "market-default-v1",
        "family_id": "stock.realtime",
        "family_contract_version": FAMILY_CONTRACT_VERSION,
    },
}


def _row(
    trade_date: str,
    *,
    include_change: bool = True,
) -> dict[str, object]:
    row: dict[str, object] = {
        "symbol": "600000",
        "trade_date": trade_date,
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "volume": 100,
        "amount": 1050.0,
    }
    if include_change:
        row["change_pct"] = 0.5
    return row


def _page(rows: list[dict[str, object]]) -> bytes:
    return json.dumps(
        {
            "success": True,
            "message": "success",
            "data": {
                "domain": "stock_daily",
                "asset_class": "equity",
                "layer": "dwd",
                "columns": [
                    "symbol",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                    "change_pct",
                ],
                "rows": rows,
                "page": 1,
                "page_size": 1000,
                "count": len(rows),
            },
        }
    ).encode("utf-8")


def _provider(
    rows: list[dict[str, object]],
    *,
    status_code: int = 200,
    requests: list[httpx.Request] | None = None,
) -> OpendataProvider:
    request_log = requests if requests is not None else []

    async def handler(request: httpx.Request) -> httpx.Response:
        request_log.append(request)
        if status_code >= 400:
            return httpx.Response(status_code, json={"detail": "unavailable"})
        start = request.url.params.get("start")
        end = request.url.params.get("end")
        if start is None or end is None:
            return httpx.Response(422, json={"detail": "missing date bounds"})
        selected_rows = [row for row in rows if start <= str(row["trade_date"]) <= end]
        return httpx.Response(200, content=_page(selected_rows))

    return OpendataProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        credentials=OpendataCredentials("test-api-key", base_url="http://opendata.test"),
    )


def _principal() -> MarketDataPrincipal:
    return MarketDataPrincipal(
        principal_id="user-test",
        principal_scope="principal-v1:test",
        tenant_scope="default",
        roles=("user",),
        permissions=("data:read",),
        entitlement_revision="e" * 64,
    )


def _source_authorization(principal: MarketDataPrincipal) -> MarketDataSourceAuthorization:
    return MarketDataSourceAuthorization(
        source_registry_id="opendata",
        registry_updated_at="2026-10-26T00:00:00+00:00",
        asset_type="stock",
        market="CN-SSE",
        purpose="display",
        license_status="APPROVED",
        allowed_uses=("DISPLAY",),
        jurisdictions=("CN",),
        effective_from="2020-01-01T00:00:00+00:00",
        effective_to=None,
        retention_policy="market-data-v1",
        retention_expires_at=None,
        redistribution_policy="INTERNAL_ONLY",
        principal_scope=principal.principal_scope,
        tenant_scope=principal.tenant_scope,
        entitlement_revision=principal.entitlement_revision,
        decision="ALLOW",
        descriptor_hash="d" * 64,
    )


class _Authorizer(MarketDataAccessAuthorizer):
    def __init__(self) -> None:
        super().__init__(object())  # type: ignore[arg-type]
        self.policy_calls = 0
        self.reauthorization_calls = 0
        self.read_entitlement_checks = 0
        self.authorization = _source_authorization(_principal())

    def require_read_data(self, *, principal: MarketDataPrincipal) -> None:
        self.read_entitlement_checks += 1
        super().require_read_data(principal=principal)

    async def authorize_policy(self, **kwargs: Any) -> MarketDataAccessGrant:
        self.policy_calls += 1
        routes = kwargs["routes"]
        assert tuple(route.route_id for route in routes) == (ROUTE_ID,)
        assert kwargs["local_sources"] == ()
        return MarketDataAccessGrant(
            principal=kwargs["principal"],
            policy_id="market-default-v1",
            purpose="display",
            route_authorizations=((ROUTE_ID, self.authorization),),
            policy_descriptor_hash="a" * 64,
        )

    async def reauthorize_route_for_write(self, **kwargs: Any) -> MarketDataSourceAuthorization:
        self.reauthorization_calls += 1
        assert kwargs["route"].route_id == ROUTE_ID
        return self.authorization


class _Store:
    def __init__(self) -> None:
        self.provider_active_checks = 0
        self.transaction_closes = 0
        self.fact_reads = 0
        self.fact_writes = 0

    async def resolve_visibility_anchor(self, **_kwargs: Any) -> MarketDataVisibilityAnchor:
        self.fact_reads += 1
        raise AssertionError("direct REST reads must not resolve AFI fact visibility")

    async def read_observation_revisions(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> tuple[Any, ...]:
        self.fact_reads += 1
        raise AssertionError("direct REST reads must not read AFI market facts")

    async def read_calendar_for_context(self, *_args: Any, **_kwargs: Any) -> Any:
        self.fact_reads += 1
        raise AssertionError("direct REST reads must not read AFI market calendars")

    async def ensure_provider_active(self, _provider_id: str) -> None:
        self.provider_active_checks += 1

    async def persist_provider_result(self, *_args: Any, **_kwargs: Any) -> Any:
        self.fact_writes += 1
        raise AssertionError("direct REST reads must not persist AFI market facts")

    async def close_transaction_before_provider_io(self) -> None:
        self.transaction_closes += 1


class _Resolver:
    async def resolve(
        self,
        request: MarketDataQueryRequest,
        *,
        identity_knowledge_cutoff: datetime | None = None,
        identity_visibility_anchor: MarketDataVisibilityAnchor | None = None,
    ) -> ResolvedMarketDataQueryContext:
        assert identity_knowledge_cutoff is not None
        assert identity_visibility_anchor is None
        query = ResolvedMarketDataQuery.from_request(
            request,
            canonical_id=CANONICAL_ID,
            dataset_code="market.bars",
            instrument_metadata_version=METADATA_VERSION,
        )
        identity = InstrumentIdentity(
            asset_type="stock",
            identity_level="ASSET",
            canonical_id=CANONICAL_ID,
            display_symbol="600000",
            name="测试股票",
            venue="CN-SSE",
            currency="CNY",
            timezone="Asia/Shanghai",
            identifier_type="EXCHANGE_SYMBOL",
            identifier_value="600000",
            product_type="EQUITY",
            metadata_version=METADATA_VERSION,
            details=StockIdentityDetails(exchange_symbol="600000.SH"),
        )
        return ResolvedMarketDataQueryContext(
            query=query,
            identity=ResolvedMarketDataIdentity(
                instrument_id="instrument-stock-v1",
                canonical_id=CANONICAL_ID,
                asset_type="stock",
                metadata_version=METADATA_VERSION,
                venue="CN-SSE",
                identity=identity,
                valid_from=datetime(2020, 1, 1, tzinfo=UTC),
                valid_to=None,
                known_at=datetime(2020, 1, 1, tzinfo=UTC),
            ),
            storage=DatasetStorageResolution(
                dataset_id="dataset-market-bars",
                dataset_code="market.bars",
                storage_id="canonical-market-data",
                engine="postgresql",
                database_name="market_data",
                physical_table="md_observation_revisions",
                write_mode="canonical_read_write",
            ),
            coverage_identity=QueryIdentity(
                dataset_code="market.bars",
                canonical_id=CANONICAL_ID,
                asset_type="stock",
                instrument_metadata_version=METADATA_VERSION,
                data_kind="bars",
                market="CN-SSE",
                frequency="1d",
                source_policy_id="market-default-v1",
                adjustment="qfq",
                price_basis="close",
                currency="CNY",
                unit="share",
                family_id="stock.realtime",
                family_contract_version=FAMILY_CONTRACT_VERSION,
            ),
        )


class _Db:
    def __init__(self) -> None:
        self.rollbacks = 0

    async def rollback(self) -> None:
        self.rollbacks += 1


class _ContractResolver:
    def __init__(self, *, contract: dict[str, Any] | None = None) -> None:
        self.contract = contract or _BASE_CONTRACT
        self.calls: list[tuple[str, str, str]] = []

    async def resolve(self, *, asset_type: str, symbol: str, period: str) -> dict[str, Any]:
        self.calls.append((asset_type, symbol, period))
        return self.contract


def _service(
    provider: OpendataProvider,
    store: _Store,
    *,
    effective_route_ids: frozenset[str] | None = None,
) -> MarketDataQueryService:
    route = MarketDataProviderRoute(
        route_id=ROUTE_ID,
        request_provider="opendata",
        expected_result_provider_ids=frozenset({"opendata"}),
        asset_types=frozenset({"stock"}),
        data_kinds=frozenset({"bars"}),
        frequencies=frozenset({"1d"}),
        markets=frozenset({"CN-SSE", "CN-SZSE"}),
        adjustments=frozenset({"unadjusted", "qfq", "hfq"}),
        price_bases=frozenset({None, "close"}),
        currencies=frozenset({None, "CNY"}),
        units=frozenset({None, "share"}),
        adapter=provider,
        family_id="stock.realtime",
        family_contract_version=FAMILY_CONTRACT_VERSION,
    )
    policies = MarketDataSourcePolicyRegistry(
        (
            MarketDataSourcePolicy(
                policy_id="market-default-v1",
                allowed_purposes=frozenset({"display"}),
                routes=(route,),
            ),
        )
    )
    return MarketDataQueryService(
        resolver=_Resolver(),  # type: ignore[arg-type]
        store=store,  # type: ignore[arg-type]
        source_policies=policies,
        allow_online_fetch=True,
        online_route_ids=(
            frozenset({ROUTE_ID}) if effective_route_ids is None else effective_route_ids
        ),
    )


@pytest_asyncio.fixture
async def direct_kline_dependencies(monkeypatch: pytest.MonkeyPatch) -> Any:
    provider_requests: list[httpx.Request] = []
    provider = _provider(
        [_row("2026-09-07")],
        requests=provider_requests,
    )
    store = _Store()
    service = _service(provider, store)
    db = _Db()
    resolver = _ContractResolver()
    authorizer = _Authorizer()
    access = MarketDataQueryAccess(principal=_principal(), authorizer=authorizer)
    evaluation = SimpleNamespace(
        response=SimpleNamespace(query_v2_enabled=True),
        route_is_effective=lambda route_id: route_id == ROUTE_ID,
    )

    monkeypatch.setattr(
        data_base,
        "get_settings",
        lambda: SimpleNamespace(MARKET_DATA_OPENDATA_ENABLED=True),
    )
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_authorized_market_data_access] = lambda: access
    app.dependency_overrides[get_market_data_capability_evaluation] = lambda: evaluation
    app.dependency_overrides[get_market_data_query_service] = lambda: service
    app.dependency_overrides[data_base.get_legacy_market_data_query_contract_resolver] = (
        lambda: resolver
    )
    try:
        yield db, store, service, resolver, authorizer, provider, provider_requests
    finally:
        for dependency in (
            get_db,
            get_authorized_market_data_access,
            get_market_data_capability_evaluation,
            get_market_data_query_service,
            data_base.get_legacy_market_data_query_contract_resolver,
        ):
            app.dependency_overrides.pop(dependency, None)
        await provider._client.aclose()


@pytest.mark.asyncio
async def test_kline_enabled_opendata_reads_rest_and_never_touches_local_facts(
    client: AsyncClient,
    direct_kline_dependencies: Any,
) -> None:
    (
        db,
        store,
        _service_value,
        resolver,
        authorizer,
        _provider_value,
        provider_requests,
    ) = direct_kline_dependencies
    response = await client.get(
        "/api/v1/data/kline",
        params={
            "symbol": "600000",
            "start_date": "2026-09-07",
            "end_date": "2026-09-07",
            "period": "daily",
        },
    )

    assert response.status_code == 200
    assert provider_requests[0].url.params["start"] == "2026-09-07"
    assert provider_requests[0].url.params["end"] == "2026-09-07"
    payload = response.json()
    assert payload["kline"] == {
        "dates": ["2026-09-07"],
        "ohlc": [[10.0, 10.5, 9.0, 11.0]],
        "volumes": [100],
    }
    assert payload["records"][0]["change"] == 0.5
    assert payload["provenance"]["provider_id"] == "opendata"
    assert payload["provenance"]["provider_adapter_revision"] == "opendata-rest-v1"
    assert payload["provenance"]["source_revision"] is None
    assert payload["provenance"]["durable_receipt"] == "not_created"
    assert payload["provenance"]["coverage_status"] == "unknown"
    assert payload["provenance"]["source_available_at"] == "unknown"
    assert payload["provenance"]["source_snapshot_id"] is None
    assert payload["provenance"]["observation_revision_ids"] is None
    assert payload["provenance"]["committed_at"] is None
    assert resolver.calls == [("stock", "600000", "daily")]
    assert authorizer.policy_calls == 1
    assert authorizer.reauthorization_calls == 1
    assert store.provider_active_checks == 1
    assert store.transaction_closes == 1
    assert store.fact_reads == 0
    assert store.fact_writes == 0
    assert db.rollbacks == 1


@pytest.mark.asyncio
async def test_multi_day_rest_query_includes_the_requested_last_business_date(
    client: AsyncClient,
    direct_kline_dependencies: Any,
) -> None:
    (
        _db,
        store,
        _service_value,
        _resolver,
        _authorizer,
        old_provider,
        _provider_requests,
    ) = direct_kline_dependencies
    await old_provider._client.aclose()
    provider_requests: list[httpx.Request] = []
    provider = _provider(
        [
            _row("2026-09-06"),
            _row("2026-09-07"),
            _row("2026-09-08"),
            _row("2026-09-09"),
        ],
        requests=provider_requests,
    )
    app.dependency_overrides[get_market_data_query_service] = lambda: _service(provider, store)
    try:
        response = await client.get(
            "/api/v1/data/kline",
            params={
                "symbol": "600000",
                "start_date": "2026-09-07",
                "end_date": "2026-09-08",
                "period": "daily",
            },
        )
    finally:
        await provider._client.aclose()

    assert response.status_code == 200
    assert provider_requests[0].url.params["start"] == "2026-09-07"
    assert provider_requests[0].url.params["end"] == "2026-09-08"
    assert response.json()["kline"]["dates"] == ["2026-09-07", "2026-09-08"]


@pytest.mark.asyncio
async def test_equivalent_utc_offsets_use_the_same_business_date_url(
    direct_kline_dependencies: Any,
) -> None:
    (
        db,
        _store_value,
        service,
        resolver,
        authorizer,
        _provider_value,
        provider_requests,
    ) = direct_kline_dependencies
    access = MarketDataQueryAccess(principal=_principal(), authorizer=authorizer)
    capabilities = SimpleNamespace(
        response=SimpleNamespace(query_v2_enabled=True),
        route_is_effective=lambda route_id: route_id == ROUTE_ID,
    )
    utc_window = LegacyKlineRequest(
        symbol="600000",
        period="daily",
        frequency="1d",
        start=datetime(2026, 9, 6, 16, tzinfo=timezone.utc),
        end=datetime(2026, 9, 7, 16, tzinfo=timezone.utc),
    )
    shanghai_window = LegacyKlineRequest(
        symbol="600000",
        period="daily",
        frequency="1d",
        start=datetime(2026, 9, 7, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        end=datetime(2026, 9, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    utc_result = await data_base.get_kline_data(
        request=utc_window,
        access=access,
        db=db,
        capabilities=capabilities,
        service=service,
        query_contracts=resolver,
    )
    shanghai_result = await data_base.get_kline_data(
        request=shanghai_window,
        access=access,
        db=db,
        capabilities=capabilities,
        service=service,
        query_contracts=resolver,
    )

    assert utc_result["kline"]["dates"] == ["2026-09-07"]
    assert shanghai_result["kline"]["dates"] == ["2026-09-07"]
    assert len(provider_requests) == 2
    for provider_request in provider_requests:
        assert provider_request.url.params["start"] == "2026-09-07"
        assert provider_request.url.params["end"] == "2026-09-07"


@pytest.mark.asyncio
async def test_empty_rest_result_is_returned_as_empty_with_unknown_coverage(
    client: AsyncClient,
    direct_kline_dependencies: Any,
) -> None:
    (
        _db,
        _store,
        _service_value,
        _resolver,
        _authorizer,
        old_provider,
        _provider_requests,
    ) = direct_kline_dependencies
    await old_provider._client.aclose()
    provider_requests: list[httpx.Request] = []
    provider = _provider([_row("2026-09-07")], requests=provider_requests)
    app.dependency_overrides[get_market_data_query_service] = lambda: _service(provider, _store)
    try:
        response = await client.get(
            "/api/v1/data/kline",
            params={
                "symbol": "600000",
                "start_date": "2026-09-08",
                "end_date": "2026-09-08",
                "period": "daily",
            },
        )
    finally:
        await provider._client.aclose()

    assert response.status_code == 200
    assert provider_requests[0].url.params["start"] == "2026-09-08"
    assert provider_requests[0].url.params["end"] == "2026-09-08"
    assert response.json()["count"] == 0
    assert response.json()["records"] == []
    assert response.json()["provenance"]["coverage_status"] == "unknown"


@pytest.mark.asyncio
async def test_direct_read_filters_out_of_window_rows_and_rejects_missing_fields(
    client: AsyncClient,
    direct_kline_dependencies: Any,
) -> None:
    (
        _db,
        store,
        _service_value,
        _resolver,
        _authorizer,
        old_provider,
        _provider_requests,
    ) = direct_kline_dependencies
    await old_provider._client.aclose()
    provider = _provider([_row("2026-09-06"), _row("2026-09-07")])
    app.dependency_overrides[get_market_data_query_service] = lambda: _service(provider, store)
    try:
        response = await client.get(
            "/api/v1/data/kline",
            params={
                "symbol": "600000",
                "start_date": "2026-09-07",
                "end_date": "2026-09-07",
                "period": "daily",
            },
        )
    finally:
        await provider._client.aclose()

    assert response.status_code == 200
    assert response.json()["kline"]["dates"] == ["2026-09-07"]

    invalid_provider = _provider([_row("2026-09-07", include_change=False)])
    app.dependency_overrides[get_market_data_query_service] = lambda: _service(
        invalid_provider,
        store,
    )
    try:
        invalid_response = await client.get(
            "/api/v1/data/kline",
            params={
                "symbol": "600000",
                "start_date": "2026-09-07",
                "end_date": "2026-09-07",
                "period": "daily",
            },
        )
    finally:
        await invalid_provider._client.aclose()

    assert invalid_response.status_code == 503
    assert invalid_response.json()["details"] == {"code": "KLINE_FIELD_QUALITY_INVALID"}


@pytest.mark.asyncio
async def test_opendata_provider_failure_does_not_fall_back_to_legacy_path(
    client: AsyncClient,
    direct_kline_dependencies: Any,
) -> None:
    (
        _db,
        store,
        _service_value,
        _resolver,
        _authorizer,
        old_provider,
        _provider_requests,
    ) = direct_kline_dependencies
    await old_provider._client.aclose()
    provider = _provider([], status_code=503)
    app.dependency_overrides[get_market_data_query_service] = lambda: _service(provider, store)
    try:
        response = await client.get(
            "/api/v1/data/kline",
            params={
                "symbol": "600000",
                "start_date": "2026-09-07",
                "end_date": "2026-09-07",
                "period": "daily",
            },
        )
    finally:
        await provider._client.aclose()

    assert response.status_code == 503
    assert response.json()["details"] == {"code": "OPENDATA_HTTP_ERROR"}
    assert store.fact_reads == 0
    assert store.fact_writes == 0


@pytest.mark.asyncio
async def test_opendata_rejects_unsupported_frequency_without_local_fallback(
    client: AsyncClient,
    direct_kline_dependencies: Any,
) -> None:
    (
        _db,
        store,
        _service_value,
        resolver,
        _authorizer,
        _provider_value,
        _provider_requests,
    ) = direct_kline_dependencies
    response = await client.get(
        "/api/v1/data/kline",
        params={
            "symbol": "600000",
            "start_date": "2026-09-07",
            "end_date": "2026-09-13",
            "period": "weekly",
        },
    )

    assert response.status_code == 422
    assert response.json()["details"] == {"code": "OPENDATA_FREQUENCY_UNSUPPORTED"}
    assert resolver.calls == []
    assert store.fact_reads == 0
    assert store.fact_writes == 0


@pytest.mark.asyncio
async def test_missing_route_attestation_fails_before_provider_or_fact_access(
    client: AsyncClient,
    direct_kline_dependencies: Any,
) -> None:
    (
        _db,
        store,
        _service_value,
        resolver,
        _authorizer,
        _provider_value,
        _provider_requests,
    ) = direct_kline_dependencies
    app.dependency_overrides[get_market_data_capability_evaluation] = lambda: SimpleNamespace(
        response=SimpleNamespace(query_v2_enabled=True),
        route_is_effective=lambda _route_id: False,
    )
    response = await client.get(
        "/api/v1/data/kline",
        params={
            "symbol": "600000",
            "start_date": "2026-09-07",
            "end_date": "2026-09-07",
            "period": "daily",
        },
    )

    assert response.status_code == 503
    assert response.json()["details"] == {"code": "OPENDATA_ROUTE_NOT_EFFECTIVE"}
    assert resolver.calls == []
    assert store.provider_active_checks == 0
    assert store.transaction_closes == 0
    assert store.fact_reads == 0
    assert store.fact_writes == 0


def test_public_direct_request_builder_refuses_the_private_kline_family() -> None:
    private_contract = {
        **_BASE_CONTRACT,
        "request": {
            **_BASE_CONTRACT["request"],
            "family_id": "stock.kline_legacy",
            "family_contract_version": "market-data-kline-v1",
            "required_fields": ["open", "high", "low", "close", "volume", "change_pct"],
        },
    }
    request = data_base.parse_legacy_kline_request(
        symbol="600000",
        start_date="2026-09-07",
        end_date="2026-09-07",
        period="daily",
    )

    with pytest.raises(data_base.LegacyKlineBridgeError) as exc:
        data_base._request_from_public_kline_contract(private_contract, request=request)

    assert exc.value.code == "KLINE_QUERY_CONTRACT_INVALID"
