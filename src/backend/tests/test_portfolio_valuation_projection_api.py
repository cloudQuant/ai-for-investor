"""Focused HTTP coverage for server-owned portfolio market inputs."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, insert
from bt_api_base.account_protocol import AccountKey

import app.main as main_module
import app.services.portfolio_valuation_bindings as valuation_bindings_module
from app.api.data import queries as market_queries
from app.api.service_read import configure_service_read
from app.db.database import async_session_maker
from app.models.asset_research import AssetDataSourceRegistry
from app.models.market_data_platform import MdCapabilityLedgerEntry
from app.models.permission import Role, user_roles
from app.models.portfolio_composition import PortfolioCompositionVersion
from app.schemas.asset_research import FxIdentityDetails, FuturesIdentityDetails, InstrumentIdentity
from app.schemas.market_data_platform import MarketDataQueryRequest, ResolvedMarketDataQuery
from app.services.market_data.access import MarketDataQueryAccess
from app.services.market_data.capability_ledger import (
    MARKET_DATA_QUERY_V2_CAPABILITY,
    rollout_capability_descriptor_sha256,
)
from app.services.market_data.catalog import DatasetStorageResolution
from app.services.market_data.coverage import (
    CoveragePlan,
    CoverageStatus,
    EventKey,
    ObservationQuality,
    QueryIdentity,
)
from app.services.market_data.identity import ResolvedMarketDataIdentity
from app.services.market_data.publication import MarketDataVisibilityAnchor
from app.services.market_data.query_resolution import ResolvedMarketDataQueryContext
from app.services.market_data.query_service import MarketDataQueryExecution, MarketDataQueryService
from app.services.market_data.source_policy import (
    MarketDataLocalReadSource,
    MarketDataSourcePolicy,
)
from app.services.market_data.store import LocalObservationRevision
from app.services.portfolio_valuation_bindings import PortfolioValuationBindingRegistry
from app.services.service_read.access import ReadAccess, ServiceReadAccessDirectory
from app.services.service_read.contracts import AccountReadView, ReadQuality
from app.utils.security import decode_access_token

app = main_module.app

UTC_NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
ACCOUNT_OBSERVED_AT = "2026-10-16T11:59:00Z"
ACCOUNT_REF = "afi-valuation-http-account"
PORTFOLIO_REF = "afi-valuation-http-view"
PRIVATE_ACCOUNT_ID = "synthetic-private-account-id-do-not-project"
EXECUTION_SCOPE_KEY = "private-internal-execution-scope-do-not-project"
_BASE_KEY = {
    "provider": "PAPER",
    "venue": "synthetic-venue",
    "environment": "simulation",
    "product_type": "futures",
}
_QUERY_CANONICALS = {
    suffix: f"instrument:futures:SYN-EX:{suffix.upper()}"
    for suffix in (
        "eur", "zero", "missing", "error", "stale", "coverage",
        "multiplier-stale", "multiplier-unit-error", "multiplier-missing", "binding-stale",
        "market-binding-stale",
    )
}
_FX_CANONICAL = "instrument:fx:SYNTHETIC:EURUSD"
_MARKET_SOURCE_ID = "afi-synthetic-local-market-read"


def _market_data_binding(
    *,
    canonical_id: str,
    asset_type: str,
    venue: str,
    product_type: str,
    metadata_version: str,
    currency: str,
    unit: str,
    binding_ref: str,
    fx_pair: tuple[str, str] | None = None,
    valid_to_utc: str | None = None,
) -> dict[str, Any]:
    return {
        "canonical_id": canonical_id,
        "asset_type": asset_type,
        "venue": venue,
        "product_type": product_type,
        "metadata_version": metadata_version,
        "family_id": "fx.realtime" if fx_pair else "futures.realtime",
        "family_contract_version": "market-data-family-v1",
        "dataset_code": "market.bars",
        "data_kind": "bars",
        "frequency": "1d",
        "required_fields": ["close"],
        "value_field": "close",
        "adjustment": None,
        "price_basis": "close",
        "currency": currency,
        "unit": unit,
        "source_policy_id": "market-default-v1",
        "query_window_seconds": 172800,
        "page_size": 25,
        "freshness_max_age_seconds": 60,
        "binding_ref": binding_ref,
        "binding_version": "v1",
        "valid_from_utc": "2020-01-01T00:00:00Z",
        "valid_to_utc": valid_to_utc,
        "provenance_ref": f"reviewed-source:{binding_ref}",
        "fx_base_currency": fx_pair[0] if fx_pair else None,
        "fx_quote_currency": fx_pair[1] if fx_pair else None,
    }


def _binding_config_json() -> str:
    instruments: list[dict[str, Any]] = []
    for suffix in _QUERY_CANONICALS:
        quantity_unit = "lots" if suffix == "multiplier-unit-error" else "contracts"
        multiplier_end = "2026-10-16T11:58:00Z" if suffix == "multiplier-stale" else None
        binding_end = "2026-10-16T11:58:00Z" if suffix == "binding-stale" else None
        market_binding_end = (
            "2026-10-16T11:58:00Z" if suffix == "market-binding-stale" else None
        )
        multiplier = None if suffix == "multiplier-missing" else "10"
        instruments.append(
            {
                "market_key": {
                    **_BASE_KEY,
                    "instrument_id": f"contract:{suffix}",
                    "native_symbol": f"SYN-{suffix.upper()}-202612",
                },
                "binding_ref": f"account-market:{suffix}",
                "binding_version": "v1",
                "valid_from_utc": "2020-01-01T00:00:00Z",
                "valid_to_utc": binding_end,
                "market_data": _market_data_binding(
                    canonical_id=_QUERY_CANONICALS[suffix],
                    asset_type="futures",
                    venue="SYN-EX",
                    product_type="FUTURES",
                    metadata_version="futures-market-v1",
                    currency="EUR" if suffix == "eur" else "USD",
                    unit="contract",
                    binding_ref=f"mark:{suffix}",
                    valid_to_utc=market_binding_end,
                ),
                "multiplier": multiplier,
                "quantity_unit": quantity_unit,
                "multiplier_provenance_ref": f"contract-spec:{suffix}:2026-v1",
                "multiplier_metadata_version": "contract-spec-2026-v1",
                "multiplier_valid_from_utc": "2020-01-01T00:00:00Z",
                "multiplier_valid_to_utc": multiplier_end,
            }
        )
    return json.dumps(
        {
            "version": "portfolio-valuation-bindings-v1",
            "instruments": instruments,
            "fx_pairs": [
                {
                    "from_currency": "EUR",
                    "to_currency": "USD",
                    "rate_convention": "to_per_from",
                    "binding_ref": "fx:EUR-USD",
                    "binding_version": "v1",
                    "valid_from_utc": "2020-01-01T00:00:00Z",
                    "valid_to_utc": None,
                    "market_data": _market_data_binding(
                        canonical_id=_FX_CANONICAL,
                        asset_type="fx",
                        venue="SYNTHETIC-FX",
                        product_type="FX_SPOT",
                        metadata_version="fx-market-v1",
                        currency="USD",
                        unit="EUR",
                        binding_ref="mark:EUR-USD",
                        fx_pair=("EUR", "USD"),
                    ),
                }
            ],
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _account_key() -> dict[str, Any]:
    return {
        **{key: _BASE_KEY[key] for key in ("provider", "venue", "environment")},
        "account_id": PRIVATE_ACCOUNT_ID,
        "subaccount_id": None,
    }


PRIVATE_ACCOUNT_KEY_ID = AccountKey.from_dict(_account_key()).account_key_id


def _account_view(account_ref: str = ACCOUNT_REF) -> AccountReadView:
    resource = {"product_type": "futures", "margin_pool": "cross"}
    positions: list[dict[str, Any]] = []
    for suffix in (*_QUERY_CANONICALS, "unmapped"):
        positions.append(
            {
                "resource": resource,
                "instrument": {
                    **_BASE_KEY,
                    "instrument_id": f"contract:{suffix}",
                    "native_symbol": f"SYN-{suffix.upper()}-202612",
                },
                "side": "long",
                "quantity": "2",
                "qty_unit": "contracts",
                "average_price": "40.00",
                "price_currency": "EUR" if suffix == "eur" else "USD",
                "observed_at_utc": ACCOUNT_OBSERVED_AT,
            }
        )
    observation = {
        "observation_id": "synthetic-observation-valuation-http",
        "coverage": [resource],
        "balances": [
            {
                "resource": resource,
                "currency": "EUR",
                "total": "12.50",
                "available": "12.50",
                "locked": "0",
                "observed_at_utc": ACCOUNT_OBSERVED_AT,
            },
            {
                "resource": resource,
                "currency": "USD",
                "total": "0",
                "available": "0",
                "locked": "0",
                "observed_at_utc": ACCOUNT_OBSERVED_AT,
            },
        ],
        "positions": positions,
        "valuation": None,
        "started_at_utc": "2026-10-16T11:58:59Z",
        "completed_at_utc": ACCOUNT_OBSERVED_AT,
        "consistency": "multi_query",
        "balances_complete": True,
        "positions_complete": True,
    }
    return AccountReadView(
        account_ref=account_ref,
        execution_domain_ref="paper:synthetic-execution-domain",
        source_service_id="synthetic-service-id",
        session_generation="synthetic-generation-v1",
        cursor=7,
        currency="USD",
        quality=ReadQuality.FRESH,
        cash=Decimal("120.00"),
        value=Decimal("500.00"),
        observed_at_utc=ACCOUNT_OBSERVED_AT,
        received_age_seconds=1,
        fresh_for_seconds=7200,
        positions_count=len(positions),
        account_key=_account_key(),
        account_key_id=PRIVATE_ACCOUNT_KEY_ID,
        provider_observation=observation,
    )


class _AuthorizedSyntheticWorker:
    def __init__(self, view: AccountReadView) -> None:
        self.view = view

    async def read_account(self, account_ref: str, *, currency: str | None = None) -> AccountReadView:
        assert account_ref == self.view.account_ref
        assert currency == "USD"
        return self.view

    async def read_order(self, _scope_ref: str, _intent_id: str) -> None:
        raise AssertionError("portfolio projection must not read orders")

    async def read_strategy_health(self, _scope_ref: str) -> None:
        raise AssertionError("portfolio projection must not read strategy health")


def _execution(
    request: MarketDataQueryRequest,
    *,
    fx_value: str | None = "1.08",
    fx_price_convention: str = "USD_PER_EUR",
) -> MarketDataQueryExecution:
    assert request.identity.canonical_id is not None
    canonical_id = request.identity.canonical_id
    if canonical_id == _FX_CANONICAL:
        asset_type = "fx"
        venue = "SYNTHETIC-FX"
        product_type = "FX_SPOT"
        currency = "USD"
        metadata_version = "fx-market-v1"
        event_at = UTC_NOW - timedelta(seconds=20)
        value = fx_value
        coverage_status = CoverageStatus.COMPLETE
        details = FxIdentityDetails(
            base_currency="EUR",
            quote_currency="USD",
            settlement_type="SPOT",
            settlement_currency="USD",
            calendar_id="synthetic-fx-24x5",
            price_convention=fx_price_convention,
        )
    else:
        suffix = next(key for key, item in _QUERY_CANONICALS.items() if item == canonical_id)
        asset_type = "futures"
        venue = "SYN-EX"
        product_type = "FUTURES"
        currency = "EUR" if suffix == "eur" else "USD"
        metadata_version = "futures-market-v1"
        event_at = UTC_NOW - timedelta(seconds=30)
        value = "42.5"
        coverage_status = CoverageStatus.COMPLETE
        if suffix == "zero":
            value = "0"
        elif suffix == "missing":
            value = None
            event_at = None
        elif suffix == "error":
            value = "NaN"
        elif suffix == "stale":
            value = "19.75"
            event_at = UTC_NOW - timedelta(hours=2)
        elif suffix == "coverage":
            value = "17.25"
            coverage_status = CoverageStatus.INCOMPLETE
        elif suffix == "multiplier-stale":
            value = "28.5"
        elif suffix == "multiplier-unit-error":
            value = "31.5"
        details = FuturesIdentityDetails(
            product_code="SYN",
            contract_month="202612",
            expiry_at=UTC_NOW + timedelta(days=60),
            contract_multiplier=Decimal("10"),
            trading_calendar_id="synthetic-futures-calendar",
            mapped_contract_id=canonical_id,
        )

    request_binding = ResolvedMarketDataQuery.from_request(
        request,
        canonical_id=canonical_id,
        dataset_code="market.bars",
        instrument_metadata_version=metadata_version,
    )
    identity = InstrumentIdentity(
        asset_type=asset_type,
        identity_level="PRODUCT" if asset_type == "fx" else "CONTRACT",
        canonical_id=canonical_id,
        display_symbol="EUR/USD" if asset_type == "fx" else canonical_id.rsplit(":", 1)[-1],
        name="Synthetic authorized market identity",
        venue=venue,
        currency=currency,
        timezone="UTC",
        identifier_type="FX_PAIR" if asset_type == "fx" else "EXCHANGE_SYMBOL",
        identifier_value="EUR/USD" if asset_type == "fx" else canonical_id.rsplit(":", 1)[-1],
        product_type=product_type,
        metadata_version=metadata_version,
        details=details,
    )
    resolved_identity = ResolvedMarketDataIdentity(
        instrument_id=f"md:{canonical_id}",
        canonical_id=canonical_id,
        asset_type=asset_type,
        metadata_version=metadata_version,
        venue=venue,
        identity=identity,
        valid_from=UTC_NOW - timedelta(days=365),
        valid_to=None,
        known_at=UTC_NOW - timedelta(days=365),
        visibility_sequence=1,
    )
    query_identity = QueryIdentity(
        dataset_code="market.bars",
        canonical_id=canonical_id,
        asset_type=asset_type,
        instrument_metadata_version=metadata_version,
        data_kind="bars",
        market=venue,
        frequency="1d",
        source_policy_id="market-default-v1",
        adjustment=None,
        price_basis="close",
        currency=currency,
        unit="EUR" if asset_type == "fx" else "contract",
        family_id="fx.realtime" if asset_type == "fx" else "futures.realtime",
        family_contract_version="market-data-family-v1",
    )
    context = ResolvedMarketDataQueryContext(
        query=request_binding,
        identity=resolved_identity,
        storage=DatasetStorageResolution(
            dataset_id="synthetic-market-bars",
            dataset_code="market.bars",
            storage_id="synthetic-storage",
            engine="sqlite",
            database_name="synthetic",
            physical_table="md_observation_revisions",
            write_mode="canonical_read_write",
        ),
        coverage_identity=query_identity,
    )
    expected: tuple[EventKey, ...] = () if event_at is None else (EventKey(event_at),)
    accepted = expected
    missing: tuple[EventKey, ...] = ()
    if coverage_status is CoverageStatus.INCOMPLETE and event_at is not None:
        missing = (EventKey(event_at - timedelta(days=1)),)
        expected = (*missing, *expected)
    coverage = CoveragePlan(
        status=coverage_status,
        expected_event_keys=expected,
        accepted_event_keys=accepted,
        missing_event_keys=missing,
        gaps=(),
        rejection_counts={},
    )
    observations: tuple[LocalObservationRevision, ...] = ()
    if event_at is not None:
        source_at = UTC_NOW - timedelta(seconds=5)
        observations = (
            LocalObservationRevision(
                revision_id=f"revision:{canonical_id}",
                source_snapshot_id=f"snapshot:{canonical_id}",
                event_at=event_at,
                available_at=source_at,
                committed_at=source_at,
                visible_at=source_at,
                visibility_sequence=1,
                revision_number=1,
                quality=ObservationQuality.PASS,
                fields=MappingProxyType({"close": value}),
            ),
        )
    anchor = MarketDataVisibilityAnchor(visible_at=UTC_NOW, max_visibility_sequence=1)
    return MarketDataQueryExecution(
        context=context,
        knowledge_cutoff=UTC_NOW,
        identity_knowledge_cutoff=UTC_NOW,
        visibility_anchor=anchor,
        identity_visibility_anchor=anchor,
        coverage=coverage,
        observations=observations,
        next_cursor=None,
        fetches=(),
        warnings=(),
    )


async def _authorize_synthetic_local_market_read(
    request: MarketDataQueryRequest,
    access: MarketDataQueryAccess,
    execution: MarketDataQueryExecution,
) -> None:
    """Run the production source-registry decision for synthetic local facts."""
    context = execution.context
    identity = context.identity
    assert identity.venue is not None
    local_source = MarketDataLocalReadSource(
        local_source_id="afi-synthetic-market-observation-v1",
        source_registry_id=_MARKET_SOURCE_ID,
        asset_types=frozenset({identity.asset_type}),
        data_kinds=frozenset({request.data_kind}),
        frequencies=frozenset({request.frequency or "snapshot"}),
        markets=frozenset({identity.venue}),
        adjustments=frozenset({request.adjustment}),
        price_bases=frozenset({request.price_basis}),
        currencies=frozenset({request.currency}),
        units=frozenset({request.unit}),
        family_id=request.family_id,
        family_contract_version=request.family_contract_version,
        product_types=frozenset({identity.identity.product_type or ""}),
    )
    policy = MarketDataSourcePolicy(
        policy_id=request.source_policy_id or "synthetic-market-v1",
        allowed_purposes=frozenset({request.purpose}),
        routes=(),
        local_sources=(local_source,),
    )
    sources = policy.local_sources_for(context)
    assert sources == (local_source,)
    grant = await access.authorizer.authorize_policy(
        principal=access.principal,
        policy=policy,
        routes=(),
        local_sources=sources,
        asset_type=identity.asset_type,
        market=identity.venue,
        purpose=request.purpose,
    )
    assert grant.authorized_source_registry_ids == frozenset({_MARKET_SOURCE_ID})


async def _seed_membership(subject: str, portfolio_ref: str) -> None:
    async with async_session_maker() as session:
        session.add(
            PortfolioCompositionVersion(
                owner_subject=subject,
                portfolio_ref=portfolio_ref,
                membership_version=1,
                source_type="live",
                base_currency="USD",
                members=[{"kind": "account", "ref": ACCOUNT_REF}],
                membership_sha256="a" * 64,
            )
        )
        await session.commit()


async def _grant_market_data_read_role(subject: str) -> None:
    """Grant the explicit data-read entitlement required by MarketData v2."""
    async with async_session_maker() as session:
        await session.execute(
            insert(user_roles).values(user_id=subject, role=Role.USER.value)
        )
        await session.commit()


async def _seed_query_capability() -> None:
    now = datetime.now(UTC)
    async with async_session_maker() as session:
        session.add(
            MdCapabilityLedgerEntry(
                capability_id=MARKET_DATA_QUERY_V2_CAPABILITY,
                revision=1,
                descriptor_sha256=rollout_capability_descriptor_sha256(
                    MARKET_DATA_QUERY_V2_CAPABILITY
                ),
                evidence_sha256=hashlib.sha256(b"synthetic-local-query-v2-evidence").hexdigest(),
                declared_capability=True,
                installed_capability=True,
                verified_capability=True,
                verified_at=now - timedelta(minutes=1),
                verified_until=now + timedelta(hours=1),
                authorized_capability=True,
                authorized_at=now - timedelta(minutes=1),
                authorized_until=now + timedelta(hours=1),
                effective_from=now - timedelta(minutes=1),
                effective_until=None,
            )
        )
        session.add(
            AssetDataSourceRegistry(
                source_id=_MARKET_SOURCE_ID,
                asset_types=["FUTURES", "FX"],
                jurisdictions=["GLOBAL"],
                license_status="APPROVED",
                allowed_uses=["DISPLAY"],
                redistribution_policy="INTERNAL_ONLY",
                derived_data_policy="ALLOWED",
                retention_policy="market-data-v1",
                effective_from=now - timedelta(days=1),
                effective_to=None,
                freshness_sla={"max_stale_seconds": 3600},
                enabled=True,
                updated_at=now,
            )
        )
        await session.commit()


def _subject(headers: dict[str, str]) -> str:
    token = headers["Authorization"].split(" ", 1)[1]
    payload = decode_access_token(token)
    assert payload is not None and isinstance(payload.get("sub"), str)
    return payload["sub"]


@pytest.mark.asyncio
async def test_lifespan_bound_market_inputs_use_authorized_v2_and_keep_totals_separate(
    client: Any,
    auth_user: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(valuation_bindings_module, "_utc_now", lambda: UTC_NOW)
    _, headers = auth_user
    subject = _subject(headers)
    binding_json = _binding_config_json()
    # The shared test fixture creates the in-memory SQLite tables but does not
    # create an Alembic revision row. Exercise the application's documented
    # dev/test schema-creation startup path during the real lifespan instead.
    monkeypatch.setattr(main_module.settings, "DB_AUTO_CREATE_SCHEMA", True)
    configured_settings = main_module.settings.model_copy(
        update={
            "PORTFOLIO_VALUATION_BINDINGS_JSON": SecretStr(binding_json),
            "MARKET_DATA_QUERY_V2_ENABLED": True,
            "MARKET_DATA_CURSOR_SIGNING_KEY": "synthetic-market-data-cursor-signing-key-0123456789",
        }
    )
    monkeypatch.setattr(main_module, "settings", configured_settings)
    monkeypatch.setattr(market_queries, "get_settings", lambda: configured_settings)

    await _seed_membership(subject, PORTFOLIO_REF)
    await _grant_market_data_read_role(subject)
    await _seed_query_capability()
    query_calls: list[tuple[str, str, MarketDataQueryAccess]] = []
    fx_result_value = ["1.08"]
    fx_price_convention = ["USD_PER_EUR"]

    async def synthetic_market_execution(
        service: MarketDataQueryService,
        request: MarketDataQueryRequest,
        *,
        cursor_binding: Any = None,
        access: MarketDataQueryAccess | None = None,
    ) -> MarketDataQueryExecution:
        assert type(service) is MarketDataQueryService
        assert access is not None and type(access) is MarketDataQueryAccess
        assert access.principal.principal_id == subject
        access.authorizer.require_read_data(principal=access.principal)
        canonical_id = request.identity.canonical_id
        assert canonical_id is not None
        is_fx = canonical_id == _FX_CANONICAL
        suffix = next(
            (key for key, value in _QUERY_CANONICALS.items() if value == canonical_id),
            None,
        )
        assert is_fx or suffix is not None
        assert request.family_id == ("fx.realtime" if is_fx else "futures.realtime")
        assert request.family_contract_version == "market-data-family-v1"
        assert request.dataset_code == "market.bars"
        assert request.data_kind == "bars"
        assert request.frequency == "1d"
        assert request.required_fields == ("close",)
        assert request.adjustment is None
        assert request.price_basis == "close"
        assert request.currency == (
            "USD" if is_fx or suffix != "eur" else "EUR"
        )
        assert request.unit == ("EUR" if is_fx else "contract")
        assert request.source_policy_id == "market-default-v1"
        assert request.consistency == "display"
        assert request.purpose == "display"
        assert request.mode == "local_first"
        assert request.page_size == 25
        assert request.start == UTC_NOW - timedelta(days=2)
        assert request.end == UTC_NOW
        execution = _execution(
            request,
            fx_value=fx_result_value[0],
            fx_price_convention=fx_price_convention[0],
        )
        await _authorize_synthetic_local_market_read(request, access, execution)
        query_calls.append((canonical_id, request.query_fingerprint, access))
        return execution

    monkeypatch.setattr(MarketDataQueryService, "execute", synthetic_market_execution)
    worker = _AuthorizedSyntheticWorker(_account_view())

    async with main_module.lifespan(app):
        registry = app.state.portfolio_valuation_bindings
        assert type(registry) is PortfolioValuationBindingRegistry
        assert registry.instrument(
            {
                **_BASE_KEY,
                "instrument_id": "contract:eur",
                "native_symbol": "SYN-EUR-202612",
            }
        ) is not None
        assert registry.instrument(
            {
                **_BASE_KEY,
                "instrument_id": "contract:EUR",
                "native_symbol": "SYN-EUR-202612",
            }
        ) is None
        configure_service_read(
            ServiceReadAccessDirectory(
                {
                    subject: ReadAccess(worker, allow_account_refs=frozenset({ACCOUNT_REF})),
                }
            )
        )
        try:
            response = await client.get(
                f"/api/v1/portfolio/compositions/{PORTFOLIO_REF}/versions/1/projection",
                headers=headers,
            )
            assert response.status_code == 200, response.text
            projection = response.json()
            assert projection["account_total"] == {
                "status": "current",
                "currency": "USD",
                "value": "500.00",
            }
            account = projection["accounts"][0]
            assert account["included_in_total"] is True
            assert account["detail_code"] is None
            assert account["cash"] == "120.00"
            assert account["provider_observation"]["balances"][0]["currency"] == "EUR"
            assert account["provider_observation"]["balances"][0]["total"] == "12.50"
            positions = {
                row["instrument"]["instrument_id"].split(":", 1)[1]: row
                for row in account["provider_observation"]["positions"]
            }

            euro = positions["eur"]["valuation_inputs"]
            assert euro["mark_price"]["status"] == "available", {
                "status": euro["mark_price"].get("status"),
                "code": euro["mark_price"].get("code"),
                "query_id": euro["mark_price"].get("source", {}).get("query_id"),
                "authorized_query_count": len(query_calls),
            }
            assert positions["eur"]["valuation_binding"] == {
                "status": "configured",
                "binding_ref": "account-market:eur",
                "binding_version": "v1",
                "valid_from_utc": "2020-01-01T00:00:00Z",
                "valid_to_utc": None,
            }
            assert euro["mark_price"]["status"] == "available"
            assert euro["mark_price"]["value"] == "42.5"
            assert euro["mark_price"]["currency"] == "EUR"
            assert euro["mark_price"]["observed_at_utc"] == "2026-10-16T11:59:30Z"
            assert euro["mark_price"]["source"]["provenance_ref"] == "reviewed-source:mark:eur"
            assert euro["contract_multiplier"]["value"] == "10"
            assert euro["contract_multiplier"]["quantity_unit"] == "contracts"
            assert euro["contract_multiplier"]["provenance_ref"] == "contract-spec:eur:2026-v1"
            assert euro["fx_rate"]["status"] == "available"
            assert euro["fx_rate"]["value"] == "1.08"
            assert euro["fx_rate"]["currency"] == "USD"
            assert euro["fx_rate"]["unit"] == "EUR"
            assert euro["fx_rate"]["from_currency"] == "EUR"
            assert euro["fx_rate"]["to_currency"] == "USD"
            assert euro["fx_rate"]["rate_convention"] == "to_per_from"
            assert euro["market_cut"]["atomic"] is False
            assert euro["market_cut"]["account_to_market_skew_ns"] == "30000000000"
            assert euro["market_cut"]["coverage"]["status"] == "complete"
            assert euro["fx_market_cut"]["market_event_at_utc"] == "2026-10-16T11:59:40Z"
            assert euro["fx_market_cut"]["account_to_market_skew_ns"] == "40000000000"
            assert euro["market_value"] == {
                "status": "not_calculated",
                "code": "AFI04_VALUATION_NOT_CALCULATED",
                "value": None,
            }

            assert positions["zero"]["valuation_inputs"]["mark_price"]["status"] == "available"
            assert positions["zero"]["valuation_inputs"]["mark_price"]["value"] == "0"
            assert positions["missing"]["valuation_inputs"]["mark_price"]["status"] == "missing"
            assert positions["missing"]["valuation_inputs"]["mark_price"]["value"] is None
            assert positions["error"]["valuation_inputs"]["mark_price"]["status"] == "error"
            assert positions["error"]["valuation_inputs"]["mark_price"]["code"] == (
                "MARKET_DATA_VALUE_INVALID"
            )
            assert positions["stale"]["valuation_inputs"]["mark_price"]["status"] == "stale"
            assert positions["stale"]["valuation_inputs"]["mark_price"]["value"] == "19.75"
            assert positions["stale"]["valuation_inputs"]["mark_price"]["observed_at_utc"] == (
                "2026-10-16T10:00:00Z"
            )
            assert positions["coverage"]["valuation_inputs"]["mark_price"]["status"] == (
                "coverage_incomplete"
            )
            assert positions["coverage"]["valuation_inputs"]["mark_price"]["value"] == "17.25"
            assert positions["coverage"]["valuation_inputs"]["mark_price"]["coverage"][
                "missing_event_count"
            ] == 1
            assert positions["multiplier-stale"]["valuation_inputs"]["contract_multiplier"][
                "status"
            ] == "stale"
            assert positions["multiplier-stale"]["valuation_inputs"][
                "contract_multiplier"
            ]["value"] == "10"
            assert positions["multiplier-stale"]["valuation_inputs"][
                "contract_multiplier"
            ]["valid_to_utc"] == "2026-10-16T11:58:00Z"
            assert positions["multiplier-unit-error"]["valuation_inputs"][
                "contract_multiplier"
            ]["status"] == "error"
            assert positions["multiplier-unit-error"]["valuation_inputs"][
                "contract_multiplier"
            ]["value"] == "10"
            assert positions["multiplier-unit-error"]["valuation_inputs"][
                "contract_multiplier"
            ]["position_quantity_unit"] == "contracts"
            assert positions["multiplier-missing"]["valuation_inputs"][
                "contract_multiplier"
            ]["status"] == "unsupported"
            assert positions["multiplier-missing"]["valuation_inputs"][
                "contract_multiplier"
            ]["value"] is None
            assert positions["unmapped"]["valuation_inputs"]["mark_price"]["status"] == (
                "unsupported"
            )
            assert positions["binding-stale"]["valuation_inputs"]["mark_price"]["status"] == (
                "stale"
            )
            assert positions["binding-stale"]["valuation_inputs"]["mark_price"]["code"] == (
                "VALUATION_BINDING_OUTSIDE_VALIDITY"
            )
            assert positions["binding-stale"]["valuation_inputs"]["mark_price"]["source"][
                "canonical_id"
            ] == _QUERY_CANONICALS["binding-stale"]
            assert positions["binding-stale"]["valuation_inputs"]["market_cut"][
                "market_event_at_utc"
            ] is None
            assert positions["binding-stale"]["valuation_inputs"]["market_cut"][
                "account_position_observed_at_utc"
            ] == ACCOUNT_OBSERVED_AT
            assert positions["market-binding-stale"]["valuation_inputs"][
                "mark_price"
            ]["status"] == "stale"
            assert positions["market-binding-stale"]["valuation_inputs"][
                "mark_price"
            ]["code"] == "MARKET_DATA_BINDING_OUTSIDE_VALIDITY"
            assert positions["market-binding-stale"]["valuation_inputs"][
                "market_cut"
            ]["market_event_at_utc"] is None
            assert positions["market-binding-stale"]["valuation_inputs"][
                "market_cut"
            ]["account_position_observed_at_utc"] == ACCOUNT_OBSERVED_AT

            assert projection["market_valuation"]["account_total_included"] is False
            assert projection["market_valuation"]["creditable"] is False
            assert projection["market_valuation"]["reconciliation_status"] == "not_established"
            expected_market_queries = set(_QUERY_CANONICALS.values()) - {
                _QUERY_CANONICALS["binding-stale"],
                _QUERY_CANONICALS["market-binding-stale"],
            }
            assert len(query_calls) == len(expected_market_queries) + 1
            assert {call[0] for call in query_calls} == expected_market_queries | {_FX_CANONICAL}
            assert all(call[2].principal.can_read_data for call in query_calls)
            for private_value in (PRIVATE_ACCOUNT_ID, PRIVATE_ACCOUNT_KEY_ID, EXECUTION_SCOPE_KEY):
                assert private_value not in response.text
            assert "account_key" not in account["provider_observation"]
            assert "account_key_id" not in account["provider_observation"]

            fx_result_value[0] = "0"
            zero_fx_response = await client.get(
                f"/api/v1/portfolio/compositions/{PORTFOLIO_REF}/versions/1/projection",
                headers=headers,
            )
            assert zero_fx_response.status_code == 200, zero_fx_response.text
            zero_fx = zero_fx_response.json()["accounts"][0]["provider_observation"]["positions"][0][
                "valuation_inputs"
            ]["fx_rate"]
            assert zero_fx["status"] == "error"
            assert zero_fx["code"] == "FX_RATE_NON_POSITIVE"
            assert zero_fx["value"] == "0"

            fx_price_convention[0] = "EUR_PER_USD"
            reversed_fx_response = await client.get(
                f"/api/v1/portfolio/compositions/{PORTFOLIO_REF}/versions/1/projection",
                headers=headers,
            )
            assert reversed_fx_response.status_code == 200, reversed_fx_response.text
            reversed_positions = {
                row["instrument"]["instrument_id"].split(":", 1)[1]: row
                for row in reversed_fx_response.json()["accounts"][0][
                    "provider_observation"
                ]["positions"]
            }
            reversed_fx = reversed_positions["eur"]["valuation_inputs"]["fx_rate"]
            assert reversed_fx["status"] == "error"
            assert reversed_fx["code"] == "MARKET_DATA_IDENTITY_BINDING_MISMATCH"
            assert reversed_fx["value"] is None
            assert reversed_fx_response.json()["account_total"]["value"] == "500.00"
        finally:
            configure_service_read(None)


@pytest.mark.asyncio
async def test_market_data_denial_is_unavailable_and_does_not_change_account_total(
    client: Any,
    auth_user: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(valuation_bindings_module, "_utc_now", lambda: UTC_NOW)
    _, headers = auth_user
    subject = _subject(headers)
    denied_registration = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "afi_market_data_denied",
            "email": "afi_market_data_denied@test.com",
            "password": "Test12345678",
        },
    )
    assert denied_registration.status_code == 200, denied_registration.text
    denied_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "afi_market_data_denied", "password": "Test12345678"},
    )
    assert denied_login.status_code == 200, denied_login.text
    denied_headers = {"Authorization": f"Bearer {denied_login.json()['access_token']}"}
    denied_subject = _subject(denied_headers)
    binding_json = _binding_config_json()
    # Keep the authorization-denial case on the same real startup path as the
    # successful projection case, using only the isolated test database.
    monkeypatch.setattr(main_module.settings, "DB_AUTO_CREATE_SCHEMA", True)
    configured_settings = main_module.settings.model_copy(
        update={
            "PORTFOLIO_VALUATION_BINDINGS_JSON": SecretStr(binding_json),
            "MARKET_DATA_QUERY_V2_ENABLED": True,
            "MARKET_DATA_CURSOR_SIGNING_KEY": "synthetic-market-data-cursor-signing-key-0123456789",
        }
    )
    monkeypatch.setattr(main_module, "settings", configured_settings)
    monkeypatch.setattr(market_queries, "get_settings", lambda: configured_settings)
    await _seed_membership(denied_subject, "afi-market-denied-view")
    async with async_session_maker() as session:
        await session.execute(delete(user_roles).where(user_roles.c.user_id == denied_subject))
        await session.execute(
            insert(user_roles).values(user_id=denied_subject, role=Role.GUEST.value)
        )
        await session.commit()
    await _seed_membership(subject, "afi-market-authorized-view")
    await _grant_market_data_read_role(subject)
    await _seed_query_capability()
    executions: list[str] = []

    async def synthetic_market_execution(
        service: MarketDataQueryService,
        request: MarketDataQueryRequest,
        *,
        cursor_binding: Any = None,
        access: MarketDataQueryAccess | None = None,
    ) -> MarketDataQueryExecution:
        assert access is not None
        executions.append(access.principal.principal_id)
        execution = _execution(request)
        await _authorize_synthetic_local_market_read(request, access, execution)
        return execution

    monkeypatch.setattr(MarketDataQueryService, "execute", synthetic_market_execution)
    worker_denied = _AuthorizedSyntheticWorker(_account_view())
    worker_authorized = _AuthorizedSyntheticWorker(_account_view())
    directory = ServiceReadAccessDirectory(
        {
            denied_subject: ReadAccess(
                worker_denied, allow_account_refs=frozenset({ACCOUNT_REF})
            ),
            subject: ReadAccess(worker_authorized, allow_account_refs=frozenset({ACCOUNT_REF})),
        }
    )

    async with main_module.lifespan(app):
        configure_service_read(directory)
        try:
            denied = await client.get(
                "/api/v1/portfolio/compositions/afi-market-denied-view/versions/1/projection",
                headers=denied_headers,
            )
            assert denied.status_code == 200, denied.text
            denied_projection = denied.json()
            assert denied_projection["account_total"]["value"] == "500.00"
            denied_positions = {
                row["instrument"]["instrument_id"].split(":", 1)[1]: row
                for row in denied_projection["accounts"][0]["provider_observation"]["positions"]
            }
            denied_position = denied_positions["eur"]
            assert denied_position["valuation_inputs"]["mark_price"]["status"] == "unavailable"
            assert denied_position["valuation_inputs"]["mark_price"]["code"] == (
                "MARKET_DATA_ACCESS_DENIED"
            )
            assert denied_position["valuation_inputs"]["fx_rate"]["status"] == "unavailable"
            assert denied_position["valuation_inputs"]["market_cut"][
                "account_position_observed_at_utc"
            ] == ACCOUNT_OBSERVED_AT
            assert denied_position["valuation_inputs"]["market_cut"][
                "market_event_at_utc"
            ] is None
            assert denied_position["valuation_inputs"]["fx_market_cut"][
                "account_position_observed_at_utc"
            ] == ACCOUNT_OBSERVED_AT
            assert denied_position["valuation_inputs"]["fx_market_cut"][
                "market_event_at_utc"
            ] is None
            assert denied_positions["zero"]["valuation_inputs"]["fx_rate"][
                "status"
            ] == "not_required"
            assert denied_positions["market-binding-stale"]["valuation_inputs"][
                "mark_price"
            ]["status"] == "stale"
            assert denied_subject not in executions

            authorized = await client.get(
                "/api/v1/portfolio/compositions/afi-market-authorized-view/versions/1/projection",
                headers=headers,
            )
            assert authorized.status_code == 200, authorized.text
            authorized_projection = authorized.json()
            assert authorized_projection["account_total"]["value"] == "500.00"
            authorized_position = next(
                row
                for row in authorized_projection["accounts"][0][
                    "provider_observation"
                ]["positions"]
                if row["instrument"]["instrument_id"] == "contract:eur"
            )
            authorized_mark = authorized_position["valuation_inputs"]["mark_price"]
            assert authorized_mark["status"] == "available", {
                "status": authorized_mark.get("status"),
                "code": authorized_mark.get("code"),
                "query_id": authorized_mark.get("source", {}).get("query_id"),
                "authorized_query_count": len(executions),
            }
            assert executions and set(executions) == {subject}
        finally:
            configure_service_read(None)
