from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app.api.data import queries
from app.schemas.market_data_platform import PublicMarketDataQueryRequest
from app.services.market_data.consumer_boundary import scan_repository
from app.services.market_data.opendata_provider import OpendataProvider, OpendataProviderError
from app.services.market_data.providers import MarketDataProviderRequest

UTC = timezone.utc


def _context(*, frequency: str = "1d") -> SimpleNamespace:
    return SimpleNamespace(
        identity=SimpleNamespace(asset_type="stock", venue="CN-SSE"),
        query=SimpleNamespace(
            data_kind="bars",
            frequency=frequency,
            adjustment="qfq",
            price_basis="close",
            currency="CNY",
            unit="share",
            family_id="stock.realtime",
            family_contract_version="market-data-family-v1",
        ),
    )


def _provider_request(*, frequency: str = "1d") -> MarketDataProviderRequest:
    return MarketDataProviderRequest(
        query_fingerprint="a" * 64,
        canonical_id="instrument:stock:CN-SSE:600519",
        asset_type="stock",
        provider_symbol="600519",
        market="CN-SSE",
        data_kind="bars",
        frequency=frequency,
        start_at=datetime(2026, 1, 2, tzinfo=UTC),
        end_at=datetime(2026, 1, 4, tzinfo=UTC),
        required_fields=frozenset({"close"}),
        provider="opendata",
        route_id="opendata-stock-daily-v1",
        family_id="stock.realtime",
        family_contract_version="market-data-family-v1",
        request_id="A" * 43,
        source_policy_id="market-default-v1",
    )


def test_ast_inventory_resolves_local_consumer_to_source_sdk(tmp_path: Path) -> None:
    backend = tmp_path / "src/backend"
    api = backend / "app/api"
    services = backend / "app/services"
    api.mkdir(parents=True)
    services.mkdir(parents=True)
    (api / "routes.py").write_text(
        "from app.services.fetcher import collect\n"
        "router = object()\n"
        "@router.get('/market')\n"
        "def market():\n"
        "    return collect()\n",
        encoding="utf-8",
    )
    (services / "fetcher.py").write_text(
        "import akshare as ak\n"
        "from app.data_fetch.core.mysql_base import MysqlBase\n"
        "def collect():\n"
        "    writer = MysqlBase()\n"
        "    return ak.stock_zh_a_hist(symbol='600519')\n",
        encoding="utf-8",
    )

    result = scan_repository(tmp_path)

    assert not result.parse_errors
    assert "app.api.routes::market" in result.source_reachable_entrypoints
    assert any(
        hit.category == "source_sdk_import" and hit.expression == "akshare" for hit in result.hits
    )
    assert any(
        hit.category == "warehouse_import" and "MysqlBase" in hit.expression for hit in result.hits
    )
    assert {hit.role for hit in result.hits} == {"business_service_consumer_candidate"}


def test_current_backend_ast_scan_is_reproducible_and_separates_legacy_scripts() -> None:
    repo_root = Path(__file__).resolve().parents[5]

    result = scan_repository(repo_root)

    assert result.python_files > 1000
    assert not result.parse_errors
    assert any(
        hit.path == "src/backend/app/api/data/queries.py"
        and hit.category == "source_adapter_import"
        and hit.expression.endswith("opendata_provider.OpendataProvider")
        for hit in result.hits
    )
    assert any(
        hit.role == "legacy_data_fetch_to_migrate" and hit.category == "warehouse_import"
        for hit in result.hits
    )
    assert any(hit.role == "operational_script_review" for hit in result.hits)


@pytest.mark.asyncio
async def test_opendata_mode_selects_only_opendata_and_missing_key_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    async def _handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    original_client = httpx.AsyncClient

    def _mock_client(**kwargs: object) -> httpx.AsyncClient:
        return original_client(transport=httpx.MockTransport(_handler), **kwargs)

    monkeypatch.setattr(
        "app.services.market_data.opendata_provider.httpx.AsyncClient", _mock_client
    )
    monkeypatch.delenv("OPENDATA_API_KEY", raising=False)
    monkeypatch.delenv("OPENDATA_BASE_URL", raising=False)
    queries._default_source_policy_registry.cache_clear()
    queries._shared_opendata_provider.cache_clear()

    def _legacy_provider_selected() -> None:
        raise AssertionError("OpenData-only selector constructed a legacy provider")

    monkeypatch.setattr(queries, "_shared_ths_provider", _legacy_provider_selected)
    monkeypatch.setattr(queries, "_shared_akshare_provider", _legacy_provider_selected)
    monkeypatch.setattr(queries, "_shared_openbb_provider", _legacy_provider_selected)
    try:
        registry = queries._default_source_policy_registry(
            "yfinance", (), ths_enabled=True, opendata_enabled=True
        )
        policy = registry.resolve("market-default-v1")
        routes = policy.routes_for(_context())

        assert [route.route_id for route in routes] == ["opendata-stock-daily-v1"]
        assert isinstance(routes[0].adapter, OpendataProvider)
        with pytest.raises(OpendataProviderError, match="OPENDATA_CREDENTIAL_MISSING"):
            await routes[0].adapter.fetch(_provider_request())
        assert requests == []
    finally:
        adapter = queries._shared_opendata_provider()
        await adapter._client.aclose()
        queries._shared_opendata_provider.cache_clear()
        queries._default_source_policy_registry.cache_clear()


@pytest.mark.asyncio
async def test_opendata_mode_does_not_select_another_provider_for_unsupported_frequency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENDATA_API_KEY", "test-key")
    queries._default_source_policy_registry.cache_clear()
    queries._shared_opendata_provider.cache_clear()
    try:
        policy = queries._default_source_policy_registry(
            "yfinance", (), ths_enabled=True, opendata_enabled=True
        ).resolve("market-default-v1")

        assert [route.request_provider for route in policy.routes] == ["opendata"]
        assert policy.routes_for(_context(frequency="1w")) == ()
    finally:
        adapter = queries._shared_opendata_provider()
        await adapter._client.aclose()
        queries._shared_opendata_provider.cache_clear()
        queries._default_source_policy_registry.cache_clear()


@pytest.mark.asyncio
async def test_api_maps_missing_opendata_configuration_to_safe_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = PublicMarketDataQueryRequest(
        identity={"asset_type": "stock", "symbol": "600519", "market": "CN-SSE"},
        data_kind="bars",
        start=datetime(2026, 1, 2, tzinfo=UTC),
        end=datetime(2026, 1, 4, tzinfo=UTC),
        required_fields=("close",),
        family_id="stock.realtime",
        family_contract_version="market-data-family-v1",
        frequency="1d",
        source_policy_id="market-default-v1",
    )
    rolled_back = False

    class _Session:
        async def rollback(self) -> None:
            nonlocal rolled_back
            rolled_back = True

    async def _execution(**_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(warnings=(SimpleNamespace(code="OPENDATA_CREDENTIAL_MISSING"),))

    monkeypatch.setattr(queries, "execute_market_data_query_with_singleflight", _execution)
    access = SimpleNamespace(
        principal=SimpleNamespace(
            principal_scope="user:1",
            tenant_scope="default",
            entitlement_revision="test-rev",
        )
    )
    capabilities = SimpleNamespace(
        response=SimpleNamespace(
            query_v2_enabled=True,
            research_cache_fill_enabled=False,
        )
    )

    with pytest.raises(HTTPException) as failure:
        await queries.query_market_data(
            request,
            db=_Session(),
            access=access,
            capabilities=capabilities,
            service=object(),
        )

    assert failure.value.status_code == 503
    assert failure.value.detail == {"code": "OPENDATA_CREDENTIAL_MISSING"}
    assert rolled_back


@pytest.mark.asyncio
async def test_api_rejects_unsupported_frequency_before_query_or_source_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = PublicMarketDataQueryRequest(
        identity={"asset_type": "stock", "symbol": "600519", "market": "CN-SSE"},
        data_kind="bars",
        start=datetime(2026, 1, 2, tzinfo=UTC),
        end=datetime(2026, 1, 9, tzinfo=UTC),
        required_fields=("close",),
        family_id="stock.realtime",
        family_contract_version="market-data-family-v1",
        frequency="1w",
        source_policy_id="market-default-v1",
    )

    async def _unexpected_execution(**_kwargs: object) -> None:
        raise AssertionError("unsupported OpenData frequency reached query routing")

    monkeypatch.setattr(
        queries,
        "get_settings",
        lambda: SimpleNamespace(MARKET_DATA_OPENDATA_ENABLED=True),
    )
    monkeypatch.setattr(
        queries, "execute_market_data_query_with_singleflight", _unexpected_execution
    )
    access = SimpleNamespace(
        principal=SimpleNamespace(
            principal_scope="user:1",
            tenant_scope="default",
            entitlement_revision="test-rev",
        )
    )
    capabilities = SimpleNamespace(
        response=SimpleNamespace(
            query_v2_enabled=True,
            research_cache_fill_enabled=False,
        )
    )

    with pytest.raises(HTTPException) as failure:
        await queries.query_market_data(
            request,
            db=SimpleNamespace(),
            access=access,
            capabilities=capabilities,
            service=object(),
        )

    assert failure.value.status_code == 422
    assert failure.value.detail == {"code": "OPENDATA_FREQUENCY_UNSUPPORTED"}
