"""Synthetic wire contract for unadjusted generic queries through OpenData."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

import app.api.data.queries as queries
from app.schemas.asset_research import InstrumentIdentity, StockIdentityDetails
from app.schemas.market_data_platform import (
    MarketDataCapabilitiesResponse,
    PublicMarketDataQueryRequest,
    ResolvedMarketDataQuery,
)
from app.services.market_data.access import (
    MarketDataAccessAuthorizer,
    MarketDataAccessGrant,
    MarketDataPrincipal,
    MarketDataQueryAccess,
    MarketDataSourceAuthorization,
)
from app.services.market_data.capability_ledger import MarketDataCapabilityEvaluation
from app.services.market_data.catalog import DatasetStorageResolution
from app.services.market_data.coverage import (
    CalendarSnapshot,
    CalendarStatus,
    EventKey,
    ObservationQuality,
    QueryIdentity,
    TimeWindow,
)
from app.services.market_data.dataset_contracts import FAMILY_CONTRACT_VERSION
from app.services.market_data.fetch_lease import MarketDataFetchLeaseHandle
from app.services.market_data.identity import ResolvedMarketDataIdentity
from app.services.market_data.opendata_contracts import OPENDATA_STOCK_DAILY_ENDPOINT
from app.services.market_data.opendata_credentials import OpendataCredentials
from app.services.market_data.opendata_provider import OpendataProvider
from app.services.market_data.publication import MarketDataVisibilityAnchor
from app.services.market_data.query_resolution import ResolvedMarketDataQueryContext
from app.services.market_data.query_service import MarketDataQueryService
from app.services.market_data.store import LocalObservationRevision, PersistedProviderFetch

UTC = timezone.utc
_CANONICAL_ID = "instrument:stock:CN-SSE:600519"
_ROUTE_ID = "opendata-stock-daily-v1"


def _request() -> PublicMarketDataQueryRequest:
    """Return one fully specified, synthetic public daily-bars query."""
    return PublicMarketDataQueryRequest.model_validate(
        {
            "identity": {"asset_type": "stock", "symbol": "600519", "market": "CN-SSE"},
            "dataset_code": "market.stock_daily",
            "data_kind": "bars",
            "frequency": "1d",
            "start": "2026-10-20T00:00:00+00:00",
            "end": "2026-10-23T00:00:00+00:00",
            "required_fields": ["close"],
            "adjustment": "unadjusted",
            "price_basis": "close",
            "currency": "CNY",
            "unit": "share",
            "source_policy_id": "market-default-v1",
            "family_id": "stock.realtime",
            "family_contract_version": FAMILY_CONTRACT_VERSION,
        }
    )


def _response_body() -> dict[str, Any]:
    """Return synthetic source-native bars with values that must pass through."""
    return {
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
            ],
            "rows": [
                {
                    "symbol": "600519",
                    "trade_date": "2026-10-20",
                    "open": 1490.0,
                    "high": 1505.0,
                    "low": 1485.0,
                    "close": 1500.0,
                    "volume": 12345,
                    "amount": 18500000.0,
                },
                {
                    "symbol": "600519",
                    "trade_date": "2026-10-22",
                    "open": 1500.0,
                    "high": 1510.0,
                    "low": 1490.0,
                    "close": 1502.5,
                    "volume": 23456,
                    "amount": 35100000.0,
                },
            ],
            "page": 1,
            "page_size": 1000,
            "count": 2,
        },
    }


class _Resolver:
    """Resolve the public synthetic selector to one fixed synthetic identity."""

    async def resolve(
        self,
        request: PublicMarketDataQueryRequest,
        *,
        identity_knowledge_cutoff: datetime | None = None,
        identity_visibility_anchor: MarketDataVisibilityAnchor | None = None,
    ) -> ResolvedMarketDataQueryContext:
        del identity_knowledge_cutoff, identity_visibility_anchor
        query = ResolvedMarketDataQuery.from_request(
            request,
            canonical_id=_CANONICAL_ID,
            dataset_code=request.dataset_code or "market.stock_daily",
            instrument_metadata_version="synthetic-instrument-v1",
        )
        identity_dto = InstrumentIdentity(
            asset_type="stock",
            identity_level="ASSET",
            canonical_id=_CANONICAL_ID,
            display_symbol="600519",
            name="Synthetic Equity",
            venue="CN-SSE",
            currency="CNY",
            timezone="Asia/Shanghai",
            identifier_type="EXCHANGE_SYMBOL",
            identifier_value="600519",
            product_type="EQUITY",
            metadata_version="synthetic-instrument-v1",
            details=StockIdentityDetails(exchange_symbol="600519.SH"),
        )
        identity = ResolvedMarketDataIdentity(
            instrument_id="synthetic-instrument-600519",
            canonical_id=_CANONICAL_ID,
            asset_type="stock",
            metadata_version="synthetic-instrument-v1",
            venue="CN-SSE",
            identity=identity_dto,
            valid_from=datetime(2020, 1, 1, tzinfo=UTC),
            valid_to=None,
            known_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        storage = DatasetStorageResolution(
            dataset_id="synthetic-stock-daily",
            dataset_code=query.dataset_code,
            storage_id="synthetic-local-store",
            engine="synthetic",
            database_name="synthetic",
            physical_table="synthetic_observations",
            write_mode="canonical_read_write",
        )
        coverage_identity = QueryIdentity(
            dataset_code=query.dataset_code,
            canonical_id=_CANONICAL_ID,
            asset_type="stock",
            instrument_metadata_version="synthetic-instrument-v1",
            data_kind=query.data_kind,
            market="CN-SSE",
            frequency=query.frequency or "snapshot",
            source_policy_id=query.source_policy_id or "market-default-v1",
            adjustment=query.adjustment,
            price_basis=query.price_basis,
            currency=query.currency,
            unit=query.unit,
            family_id=query.family_id,
            family_contract_version=query.family_contract_version,
        )
        return ResolvedMarketDataQueryContext(
            query=query,
            identity=identity,
            storage=storage,
            coverage_identity=coverage_identity,
        )


class _Store:
    """In-memory synthetic fact store; it does not open a database connection."""

    def __init__(self, *, calendar: CalendarSnapshot) -> None:
        self.calendar = calendar
        self.rows: list[LocalObservationRevision] = []
        self.provider_activation_checks: list[str] = []
        self.persisted_routes: list[str] = []
        self.persisted_adjustments: list[str | None] = []

    async def resolve_visibility_anchor(
        self,
        *,
        knowledge_cutoff: datetime,
    ) -> MarketDataVisibilityAnchor:
        visible = [
            row.visibility_sequence for row in self.rows if row.visible_at <= knowledge_cutoff
        ]
        return MarketDataVisibilityAnchor(
            visible_at=knowledge_cutoff,
            max_visibility_sequence=max(visible, default=0),
        )

    async def read_observation_revisions(
        self,
        context: ResolvedMarketDataQueryContext,
        *,
        knowledge_cutoff: datetime,
        visibility_anchor: MarketDataVisibilityAnchor | None = None,
        include_unusable_for_coverage: bool = False,
        allowed_source_registry_ids: frozenset[str] | None = None,
    ) -> tuple[LocalObservationRevision, ...]:
        del include_unusable_for_coverage, allowed_source_registry_ids
        anchor = visibility_anchor or await self.resolve_visibility_anchor(
            knowledge_cutoff=knowledge_cutoff
        )
        return tuple(
            row
            for row in self.rows
            if context.query.start <= row.event_at < context.query.end
            and row.available_at <= knowledge_cutoff
            and anchor.permits(
                visible_at=row.visible_at,
                visibility_sequence=row.visibility_sequence,
            )
        )

    async def read_calendar_for_context(
        self,
        _context: ResolvedMarketDataQueryContext,
        *,
        knowledge_cutoff: datetime,
        visibility_anchor: MarketDataVisibilityAnchor | None = None,
        allowed_source_registry_ids: frozenset[str] | None = None,
    ) -> CalendarSnapshot:
        del knowledge_cutoff, visibility_anchor, allowed_source_registry_ids
        return self.calendar

    async def ensure_provider_active(self, provider_id: str) -> None:
        self.provider_activation_checks.append(provider_id)
        assert provider_id == "opendata"

    async def close_transaction_before_provider_io(self) -> None:
        return None

    async def persist_provider_result(
        self,
        context: ResolvedMarketDataQueryContext,
        result: Any,
        *,
        received_at: datetime,
        source_authorization: MarketDataSourceAuthorization | None = None,
        fetch_lease: MarketDataFetchLeaseHandle | None = None,
    ) -> PersistedProviderFetch:
        del source_authorization, fetch_lease
        self.persisted_routes.append(result.request.route_id)
        self.persisted_adjustments.append(result.request.adjustment)
        revisions: list[str] = []
        for index, item in enumerate(result.observations, start=len(self.rows) + 1):
            revision_id = f"synthetic-revision-{index}"
            revisions.append(revision_id)
            self.rows.append(
                LocalObservationRevision(
                    revision_id=revision_id,
                    source_snapshot_id="synthetic-opendata-snapshot",
                    event_at=item.event_at,
                    available_at=received_at,
                    committed_at=received_at,
                    visible_at=received_at,
                    visibility_sequence=index,
                    revision_number=1,
                    quality=ObservationQuality.PASS,
                    fields=dict(item.fields),
                )
            )
        return PersistedProviderFetch(
            series_id="synthetic-stock-daily-series",
            source_snapshot_id="synthetic-opendata-snapshot",
            observation_revision_ids=tuple(revisions),
            passing_observation_count=len(revisions),
            failed_observation_count=0,
            received_at=received_at,
        )


class _Authorizer(MarketDataAccessAuthorizer):
    """Grant the one synthetic OpenData route without database access."""

    def __init__(self, authorization: MarketDataSourceAuthorization) -> None:
        super().__init__(object())  # type: ignore[arg-type]
        self.authorization = authorization

    async def authorize_policy(self, **kwargs: Any) -> MarketDataAccessGrant:
        routes = tuple(kwargs["routes"])
        assert tuple(route.route_id for route in routes) == (_ROUTE_ID,)
        return MarketDataAccessGrant(
            principal=kwargs["principal"],
            policy_id=kwargs["policy"].policy_id,
            purpose=kwargs["purpose"],
            route_authorizations=((_ROUTE_ID, self.authorization),),
            policy_descriptor_hash="a" * 64,
        )

    async def revalidate_principal(
        self,
        *,
        principal: MarketDataPrincipal,
    ) -> MarketDataPrincipal:
        return principal

    async def reauthorize_route_for_write(self, **kwargs: Any) -> MarketDataSourceAuthorization:
        assert kwargs["route"].route_id == _ROUTE_ID
        return self.authorization


class _Leases:
    """One deterministic in-memory lease used only by this synthetic test."""

    async def acquire(self, lease_key_sha256: str) -> MarketDataFetchLeaseHandle:
        return MarketDataFetchLeaseHandle(
            lease_key_sha256=lease_key_sha256,
            owner_token="synthetic-query-owner",
            fence_token=1,
            expires_at=datetime(2026, 10, 29, 12, tzinfo=UTC) + timedelta(minutes=5),
        )

    async def release(self, _handle: MarketDataFetchLeaseHandle) -> bool:
        return True


class _FakeDb:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        raise AssertionError("synthetic successful query must not touch a database")


@pytest.mark.asyncio
async def test_generic_query_keeps_unadjusted_semantics_on_the_opendata_wire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The generic query policy sends ``unadjusted`` as OpenData ``adjust=none``."""
    outbound_requests: list[httpx.Request] = []

    async def transport(request: httpx.Request) -> httpx.Response:
        outbound_requests.append(request)
        return httpx.Response(200, json=_response_body())

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(transport),
        trust_env=False,
    )
    provider = OpendataProvider(
        client=client,
        credentials=OpendataCredentials(
            "synthetic-test-key",
            base_url="http://opendata.example.test",
        ),
        max_retries=0,
    )
    principal = MarketDataPrincipal(
        principal_id="synthetic-user",
        principal_scope="principal-v1:synthetic-user",
        tenant_scope="default",
        roles=("user",),
        permissions=("data:read",),
        entitlement_revision="e" * 64,
    )
    authorization = MarketDataSourceAuthorization(
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
        retention_policy="market-data-synthetic-v1",
        retention_expires_at=None,
        redistribution_policy="INTERNAL_ONLY",
        principal_scope=principal.principal_scope,
        tenant_scope=principal.tenant_scope,
        entitlement_revision=principal.entitlement_revision,
        decision="ALLOW",
        descriptor_hash="d" * 64,
    )
    access = MarketDataQueryAccess(
        principal=principal,
        authorizer=_Authorizer(authorization),
    )
    settings = SimpleNamespace(
        MARKET_DATA_OPENDATA_ENABLED=True,
        MARKET_DATA_RISK_BENCHMARK_OPENDATA_ENABLED=False,
        MARKET_DATA_THS_ENABLED=True,
        MARKET_DATA_OPENBB_PROVIDER="yfinance",
        MARKET_DATA_OPENBB_ALLOWED_MARKETS="CN-SSE",
    )

    def unexpected_legacy_provider() -> None:
        raise AssertionError("OpenData-only policy constructed a legacy provider")

    queries._default_source_policy_registry.cache_clear()
    monkeypatch.setattr(queries, "get_settings", lambda: settings)
    monkeypatch.setattr(queries, "_shared_opendata_provider", lambda: provider)
    monkeypatch.setattr(queries, "_shared_ths_provider", unexpected_legacy_provider)
    monkeypatch.setattr(queries, "_shared_akshare_provider", unexpected_legacy_provider)
    monkeypatch.setattr(queries, "_shared_openbb_provider", unexpected_legacy_provider)
    try:
        registry = queries._source_policies_from_settings(settings)
        policy = registry.resolve("market-default-v1")
        effective_route_ids = frozenset(route.route_id for route in policy.routes)
        assert effective_route_ids == {_ROUTE_ID}
        request = _request()
        calendar = CalendarSnapshot(
            calendar_id="CN-SSE",
            calendar_version="synthetic-calendar-v1",
            timezone_name="Asia/Shanghai",
            coverage_window=TimeWindow(start_at=request.start, end_at=request.end),
            event_keys=(
                EventKey(datetime(2026, 10, 20, tzinfo=UTC)),
                EventKey(datetime(2026, 10, 22, tzinfo=UTC)),
            ),
            status=CalendarStatus.KNOWN,
        )
        store = _Store(calendar=calendar)
        db = _FakeDb()
        capabilities = MarketDataCapabilityEvaluation(
            response=MarketDataCapabilitiesResponse(
                query_v2_enabled=True,
                online_fetch_enabled=True,
                research_cache_fill_enabled=False,
                research_backtest_bridge_enabled=False,
            ),
            effective_source_policies=registry,
            effective_route_ids=effective_route_ids,
        )
        service = MarketDataQueryService(
            resolver=_Resolver(),  # type: ignore[arg-type]
            store=store,
            source_policies=registry,
            allow_online_fetch=True,
            clock=lambda: datetime(2026, 10, 29, 12, tzinfo=UTC),
            fetch_leases=_Leases(),
        )
        response = await queries.query_market_data(
            request,
            db=db,  # type: ignore[arg-type]
            access=access,
            capabilities=capabilities,
            service=service,
        )
    finally:
        await client.aclose()
        queries._default_source_policy_registry.cache_clear()

    assert store.provider_activation_checks
    assert set(store.provider_activation_checks) == {"opendata"}
    assert store.persisted_routes == [_ROUTE_ID]
    assert store.persisted_adjustments == ["unadjusted"]
    assert db.commits == 1
    assert len(outbound_requests) == 1
    wire_request = outbound_requests[0]
    assert wire_request.method == "GET"
    assert wire_request.url.host == "opendata.example.test"
    assert wire_request.url.path == OPENDATA_STOCK_DAILY_ENDPOINT
    assert wire_request.headers["X-API-Key"] == "synthetic-test-key"
    assert wire_request.url.params["symbols"] == "600519"
    assert wire_request.url.params["start"] == "2026-10-20"
    assert wire_request.url.params["end"] == "2026-10-22"
    assert wire_request.url.params["adjust"] == "none"
    assert "qfq" not in wire_request.url.params.values()

    payload = response.model_dump(mode="json")
    expected_query = ResolvedMarketDataQuery.from_request(
        request,
        canonical_id=_CANONICAL_ID,
        dataset_code="market.stock_daily",
        instrument_metadata_version="synthetic-instrument-v1",
    )
    assert payload["query_id"] == expected_query.query_fingerprint
    assert payload["canonical_id"] == _CANONICAL_ID
    assert payload["fetches"][0]["route_id"] == _ROUTE_ID
    assert [row["event_at"] for row in payload["observations"]] == [
        "2026-10-20T00:00:00Z",
        "2026-10-22T00:00:00Z",
    ]
    assert [row["fields"]["close"] for row in payload["observations"]] == [1500.0, 1502.5]
    assert [row["fields"]["turnover"] for row in payload["observations"]] == [
        18500000.0,
        35100000.0,
    ]
