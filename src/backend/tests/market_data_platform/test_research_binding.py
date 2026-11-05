"""Focused contracts for sealed local-first research data bindings."""

from __future__ import annotations

import importlib.util
from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects import mysql, postgresql, sqlite

from app.db.database import async_session_maker
from app.models.asset_research import AssetDataSourceRegistry
from app.models.data_governance import DgProvider
from app.models.market_data_platform import (
    SOURCE_AUTHORIZATION_STATE_VERIFIED,
    ImmutableMarketDataRecordError,
    MdPublication,
    MdResearchDataBinding,
    MdResearchDataBindingConsumer,
    MdResearchDataBindingRevocation,
    MdResearchDataBindingScope,
    MdSourceSnapshot,
)
from app.models.permission import Role, user_roles
from app.models.user import User
from app.models.workspace import StrategyUnit, Workspace
from app.schemas.ai_strategy_research import AIStrategyResearchRunRequest
from app.schemas.asset_research import InstrumentIdentity
from app.schemas.market_data_platform import MarketDataQueryRequest, ResolvedMarketDataQuery
from app.services.market_data.access import (
    MarketDataAccessAuthorizer,
    MarketDataAuthorizationError,
    MarketDataQueryAccess,
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
from app.services.market_data.publication import (
    PUBLICATION_SOURCE_SNAPSHOT,
    MarketDataVisibilityAnchor,
)
from app.services.market_data.query_resolution import ResolvedMarketDataQueryContext
from app.services.market_data.query_service import MarketDataQueryExecution
from app.services.market_data.research_binding import (
    MarketDataResearchBindingError,
    MarketDataResearchBindingService,
    _canonical_sha256,
    _strict_research_bars_family_id,
    build_market_data_research_binding_service,
    market_data_binding_content_sha256,
    market_data_binding_contract_sha256,
    market_data_binding_publication_pins,
)
from app.services.market_data.store import LocalObservationRevision

UTC = timezone.utc
NOW = datetime(2026, 2, 3, 12, tzinfo=UTC)
START = datetime(2026, 1, 5, tzinfo=UTC)
END = datetime(2026, 1, 7, tzinfo=UTC)
CANONICAL_ID = "instrument:stock:CN-SSE:600000"
SIGNING_KEY = "research-binding-test-key-material-at-least-thirty-two-bytes"
_SEALED_SOURCE_ID = "akshare"
_SEALED_PROVIDER_ID = "20000000-0000-0000-0000-000000000000"
_SEALED_SOURCE_SNAPSHOT_IDS = (
    "10000000-0000-0000-0000-000000000001",
    "10000000-0000-0000-0000-000000000002",
)
_SHA256_A = "a" * 64
_SHA256_B = "b" * 64
_SHA256_C = "c" * 64
# The shared in-memory database accumulates publication receipts across test
# modules, so the fixture reserves two clearly separated high sequences and the
# fake replay anchor sits above them.  The visibility instant must stay inside
# the binding's frozen anchor: a receipt sealed after the cutoff would leak a
# later publication into a point-in-time replay, which the binding refuses.
_SEALED_PUBLICATION_SEQUENCES = (9_999_990, 9_999_991)
_BINDING_ANCHOR_MAX_SEQUENCE = 10_000_000
_SEALED_PUBLICATION_VISIBLE_AT = datetime(2026, 1, 6, 6, tzinfo=UTC)


class _ContractResolver:
    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []

    async def resolve(
        self,
        *,
        asset_type: str,
        symbol: str,
        period: str,
        family_id: str | None = None,
    ) -> dict[str, Any] | None:
        self.calls.append(
            {
                "asset_type": asset_type,
                "symbol": symbol,
                "period": period,
                "family_id": family_id,
            }
        )
        return {
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
                "mode": "local_first",
                "family_id": "stock.realtime",
                "family_contract_version": "market-data-family-v1",
            },
        }


class _FamilyContractResolver:
    """Return one exact ready-bars family and reject a retargeted request."""

    def __init__(self, *, asset_type: str) -> None:
        self.asset_type = asset_type
        self.family_id = f"{asset_type}.realtime"
        self.calls: list[dict[str, str | None]] = []

    async def resolve(
        self,
        *,
        asset_type: str,
        symbol: str,
        period: str,
        family_id: str | None = None,
    ) -> dict[str, Any] | None:
        self.calls.append(
            {
                "asset_type": asset_type,
                "symbol": symbol,
                "period": period,
                "family_id": family_id,
            }
        )
        if (
            asset_type != self.asset_type
            or symbol != "600000"
            or period != "1d"
            or family_id != self.family_id
        ):
            return None
        return {
            "version": "market-data-v2",
            "request": {
                "identity": {"canonical_id": _canonical_id_for_asset_type(asset_type)},
                "dataset_code": "market.bars",
                "data_kind": "bars",
                "frequency": "1d",
                "required_fields": ["close"],
                "adjustment": "qfq",
                "price_basis": "close",
                "currency": "CNY",
                "unit": "share",
                "source_policy_id": "market-default-v1",
                "mode": "local_first",
                "family_id": family_id,
                "family_contract_version": "market-data-family-v1",
            },
        }


class _LocalOnlyQueryService:
    def __init__(
        self,
        *,
        missing_ohlc: bool = False,
        execution_error: Exception | None = None,
        close_adjustment: float = 0.0,
        on_execute: Callable[[MarketDataQueryRequest], Awaitable[None]] | None = None,
        asset_type: str = "stock",
    ) -> None:
        self.requests: list[MarketDataQueryRequest] = []
        self.accesses: list[MarketDataQueryAccess | None] = []
        self.missing_ohlc = missing_ohlc
        self.execution_error = execution_error
        self.close_adjustment = close_adjustment
        self.on_execute = on_execute
        self.asset_type = asset_type
        self.online_fetch_attempts = 0

    async def execute(
        self,
        request: MarketDataQueryRequest,
        *,
        access: MarketDataQueryAccess | None = None,
    ) -> MarketDataQueryExecution:
        self.requests.append(request)
        self.accesses.append(access)
        if self.on_execute is not None:
            await self.on_execute(request)
        if self.execution_error is not None:
            raise self.execution_error
        return _execution_for(
            request,
            missing_ohlc=self.missing_ohlc,
            close_adjustment=self.close_adjustment,
            asset_type=self.asset_type,
        )


async def _user(*, username: str) -> User:
    async with async_session_maker() as db:
        await _seed_sealed_source_evidence(db)
        user = User(
            username=username,
            email=f"{username}@example.test",
            hashed_password="unused",
            is_active=True,
        )
        db.add(user)
        await db.flush()
        await db.execute(user_roles.insert().values(user_id=user.id, role=Role.USER.value))
        await db.commit()
        return user


async def _seed_sealed_source_evidence(db: Any) -> None:
    """Persist the source-snapshot/publication/registry chain used by the local fake."""
    provider = await db.get(DgProvider, _SEALED_PROVIDER_ID)
    if provider is None:
        db.add(
            DgProvider(
                id=_SEALED_PROVIDER_ID,
                provider_id=_SEALED_SOURCE_ID,
                name="Sealed test source",
                category="market",
                is_active=True,
            )
        )
    registry = await db.get(AssetDataSourceRegistry, _SEALED_SOURCE_ID)
    if registry is None:
        db.add(
            AssetDataSourceRegistry(
                source_id=_SEALED_SOURCE_ID,
                asset_types=["stock"],
                jurisdictions=["CN"],
                license_status="APPROVED",
                allowed_uses=["BACKTEST"],
                redistribution_policy="NO_REDISTRIBUTION",
                derived_data_policy="ALLOWED",
                retention_policy="market-data-v1",
                effective_from=datetime(2020, 1, 1, tzinfo=UTC),
                effective_to=None,
                retention_expires_at=None,
                enabled=True,
                updated_at=NOW,
            )
        )
    await db.flush()
    existing_snapshot_ids = set(
        (
            await db.scalars(
                select(MdSourceSnapshot.id).where(
                    MdSourceSnapshot.id.in_(_SEALED_SOURCE_SNAPSHOT_IDS)
                )
            )
        ).all()
    )
    for source_snapshot_id in _SEALED_SOURCE_SNAPSHOT_IDS:
        if source_snapshot_id in existing_snapshot_ids:
            continue
        db.add(
            MdSourceSnapshot(
                id=source_snapshot_id,
                provider_id=_SEALED_PROVIDER_ID,
                platform="akshare",
                source_id=_SEALED_SOURCE_ID,
                adapter_id="akshare-test",
                endpoint_version="test-v1",
                request_fingerprint_sha256=_SHA256_A,
                payload_sha256=_SHA256_B,
                request_json={},
                payload_manifest_json={},
                provenance_json={},
                source_authorization_state=SOURCE_AUTHORIZATION_STATE_VERIFIED,
                source_authorization_descriptor_sha256=_SHA256_C,
                retrieved_at=NOW,
            )
        )
    await _seal_source_snapshot_publications(db)


async def _seal_source_snapshot_publications(db: Any) -> None:
    """Seal one post-commit publication receipt per contributing source snapshot.

    A research binding refuses to describe a snapshot without a sealed
    publication, so the shared fixture must carry the same receipt the production
    publication manager appends after the snapshot's first commit.
    """
    await db.flush()
    sealed_ids = set(
        (
            await db.scalars(
                select(MdPublication.entity_id).where(
                    MdPublication.entity_type == PUBLICATION_SOURCE_SNAPSHOT,
                    MdPublication.entity_id.in_(_SEALED_SOURCE_SNAPSHOT_IDS),
                )
            )
        ).all()
    )
    missing = [
        source_snapshot_id
        for source_snapshot_id in _SEALED_SOURCE_SNAPSHOT_IDS
        if source_snapshot_id not in sealed_ids
    ]
    if not missing:
        return
    for entity_id in missing:
        offset = _SEALED_SOURCE_SNAPSHOT_IDS.index(entity_id)
        db.add(
            MdPublication(
                entity_type=PUBLICATION_SOURCE_SNAPSHOT,
                entity_id=entity_id,
                entity_sha256=_SHA256_B,
                published_at=_SEALED_PUBLICATION_VISIBLE_AT,
                visibility_sequence=_SEALED_PUBLICATION_SEQUENCES[offset],
                created_at=NOW,
            )
        )
    await db.flush()


async def _attach_research_unit(
    *,
    db: Any,
    service: MarketDataResearchBindingService,
    user: User,
    bound: AIStrategyResearchRunRequest,
    workspace_name: str = "binding research workspace",
) -> tuple[str, str]:
    """Create a trusted research unit and persist its binding consumer receipt."""
    workspace = Workspace(
        user_id=user.id,
        name=workspace_name,
        workspace_type="research",
    )
    db.add(workspace)
    await db.flush()
    unit = StrategyUnit(
        workspace_id=workspace.id,
        strategy_name="binding strategy",
        symbol="600000",
        timeframe="1d",
        timeframe_n=1,
        category="stock",
        data_config={
            **dict(bound.data_config),
            "range_type": "date",
            "start_date": "2026-01-05",
            "end_date": "2026-01-06",
            "use_end_date": True,
        },
    )
    db.add(unit)
    await db.commit()
    await service.attach_runtime_binding_consumer(
        user_id=user.id,
        binding_id=str(bound.data_config["market_data_binding_id"]),
        binding_hash=str(bound.data_config["market_data_binding_hash"]),
        signature=str(bound.data_config["market_data_binding_signature"]),
        intent_id=str(bound.data_config["market_data_binding_intent_id"]),
        workspace_id=workspace.id,
        unit_id=unit.id,
    )
    return workspace.id, unit.id


def _request(
    data_config: dict[str, object] | None = None,
    *,
    timeframe: str = "1d",
) -> AIStrategyResearchRunRequest:
    return AIStrategyResearchRunRequest(
        symbol="600000",
        timeframe=timeframe,
        timeframe_n=1,
        start_date="2026-01-05",
        end_date="2026-01-06",
        data_config=data_config or {"market_data_asset_type": "stock"},
        start_paper_trading=False,
    )


def _load_research_binding_migration() -> Any:
    """Load the owned revision without depending on Alembic's module cache."""
    backend_root = Path(__file__).resolve().parents[2]
    path = backend_root / "alembic" / "versions" / "20260909_market_data_research_bindings.py"
    spec = importlib.util.spec_from_file_location("research_binding_migration", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _identity() -> InstrumentIdentity:
    return InstrumentIdentity.model_validate(
        {
            "asset_type": "stock",
            "identity_level": "ASSET",
            "canonical_id": CANONICAL_ID,
            "display_symbol": "600000",
            "name": "测试股票",
            "venue": "CN-SSE",
            "currency": "CNY",
            "timezone": "Asia/Shanghai",
            "identifier_type": "EXCHANGE_SYMBOL",
            "identifier_value": "600000.SH",
            "product_type": "EQUITY",
            "metadata_version": "stock-v1",
            "details": {"kind": "STOCK", "exchange_symbol": "600000.SH"},
        }
    )


def _canonical_id_for_asset_type(asset_type: str) -> str:
    if asset_type == "stock":
        return CANONICAL_ID
    return f"instrument:{asset_type}:TEST:600000"


def _identity_for_asset_type(asset_type: str) -> InstrumentIdentity:
    """Build a valid typed identity for each ready strict-bars test family."""
    if asset_type == "stock":
        return _identity()

    common: dict[str, object] = {
        "asset_type": asset_type,
        "canonical_id": _canonical_id_for_asset_type(asset_type),
        "display_symbol": "600000",
        "timezone": "Asia/Shanghai",
        "identifier_type": "EXCHANGE_SYMBOL",
        "identifier_value": "600000",
        "metadata_version": f"{asset_type}-v1",
    }
    if asset_type == "futures":
        return InstrumentIdentity.model_validate(
            {
                **common,
                "identity_level": "PRODUCT",
                "name": "测试期货",
                "venue": "CFFEX",
                "currency": "CNY",
                "product_type": "FUTURES",
                "details": {
                    "kind": "FUTURES",
                    "product_code": "IF",
                    "trading_calendar_id": "CFFEX",
                },
            }
        )
    if asset_type == "bond":
        return InstrumentIdentity.model_validate(
            {
                **common,
                "identity_level": "PRODUCT",
                "name": "测试债券",
                "venue": "CN-SSE",
                "currency": "CNY",
                "product_type": "BOND",
                "details": {
                    "kind": "BOND",
                    "bond_identity_kind": "LISTING",
                    "issuer_id": "issuer-test",
                },
            }
        )
    if asset_type == "fund":
        return InstrumentIdentity.model_validate(
            {
                **common,
                "identity_level": "PRODUCT",
                "name": "测试基金",
                "venue": "CN-SSE",
                "currency": "CNY",
                "product_type": "ETF",
                "details": {
                    "kind": "FUND",
                    "fund_identity_kind": "LISTING",
                    "fund_id": "fund-test",
                    "share_class_id": "share-class-test",
                },
            }
        )
    if asset_type == "option":
        return InstrumentIdentity.model_validate(
            {
                **common,
                "identity_level": "CONTRACT",
                "name": "测试期权",
                "venue": "CFFEX",
                "currency": "CNY",
                "product_type": "OPTION",
                "details": {
                    "kind": "OPTION",
                    "option_contract_id": "600000",
                    "exchange": "CFFEX",
                    "underlying_instrument_id": CANONICAL_ID,
                    "underlying_contract_id": CANONICAL_ID,
                    "expiry_at": NOW + timedelta(days=30),
                    "last_trade_at": NOW + timedelta(days=29),
                    "strike": "100",
                    "option_right": "CALL",
                    "exercise_style": "EUROPEAN",
                    "contract_multiplier": "100",
                    "settlement_type": "CASH",
                    "deliverable": "cash",
                    "quote_unit": "CNY",
                    "tick_size": "0.01",
                    "trading_calendar_id": "CFFEX",
                    "automatic_exercise_rule": "test-rule",
                    "position_limit_rule": "test-rule",
                    "margin_rule_version": "test-v1",
                },
            }
        )
    if asset_type == "fx":
        return InstrumentIdentity.model_validate(
            {
                **common,
                "identity_level": "PRODUCT",
                "name": "测试外汇",
                "venue": "OTC",
                "currency": "USD",
                "product_type": "SPOT",
                "details": {
                    "kind": "FX",
                    "base_currency": "CNY",
                    "quote_currency": "USD",
                    "settlement_type": "SPOT",
                    "settlement_currency": "USD",
                    "calendar_id": "OTC",
                    "price_convention": "DIRECT",
                },
            }
        )
    raise AssertionError(f"test fixture does not define {asset_type}")


@pytest.mark.asyncio
async def test_production_binding_builder_rejects_settings_only_enablement_before_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh builder cannot turn an enabled environment flag into a grant."""
    import app.api.data.queries as data_queries

    artifact_root = tmp_path / "must-not-be-created"
    monkeypatch.setattr(
        data_queries,
        "get_settings",
        lambda: SimpleNamespace(
            MARKET_DATA_QUERY_V2_ENABLED=True,
            MARKET_DATA_ONLINE_FETCH_ENABLED=True,
            MARKET_DATA_RESEARCH_CACHE_FILL_ENABLED=True,
            MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_ENABLED=True,
            MARKET_DATA_OPENBB_ALLOWED_MARKETS="",
            MARKET_DATA_OPENBB_PROVIDER="yfinance",
            MARKET_DATA_RESEARCH_ARTIFACT_ROOT=str(artifact_root),
            MARKET_DATA_RESEARCH_ARTIFACT_SIGNING_KEY=SIGNING_KEY,
        ),
    )
    user = await _user(username="binding-builder-settings-only")

    async with async_session_maker() as db:
        with pytest.raises(MarketDataResearchBindingError) as failure:
            await build_market_data_research_binding_service(db, user_id=user.id)
        assert await db.scalar(select(func.count()).select_from(MdResearchDataBinding)) == 0

    assert failure.value.code == "MARKET_DATA_BRIDGE_DISABLED"
    assert not artifact_root.exists()


def _execution_for(
    request: MarketDataQueryRequest,
    *,
    missing_ohlc: bool,
    close_adjustment: float = 0.0,
    asset_type: str = "stock",
) -> MarketDataQueryExecution:
    canonical_id = _canonical_id_for_asset_type(asset_type)
    identity = _identity_for_asset_type(asset_type)
    assert request.identity.canonical_id == canonical_id
    resolved_query = ResolvedMarketDataQuery.from_request(
        request,
        canonical_id=canonical_id,
        dataset_code="market.bars",
        instrument_metadata_version=identity.metadata_version,
    )
    resolved_identity = ResolvedMarketDataIdentity(
        instrument_id="11111111-1111-1111-1111-111111111111",
        canonical_id=canonical_id,
        asset_type=asset_type,
        metadata_version=identity.metadata_version,
        venue=identity.venue,
        identity=identity,
        valid_from=START - timedelta(days=10),
        valid_to=None,
        known_at=START - timedelta(days=10),
        visibility_sequence=3,
    )
    coverage_identity = QueryIdentity(
        dataset_code="market.bars",
        canonical_id=canonical_id,
        asset_type=asset_type,
        instrument_metadata_version=identity.metadata_version,
        data_kind="bars",
        market=identity.venue or "OTC",
        frequency="1d",
        source_policy_id="market-default-v1",
        adjustment="qfq",
        price_basis="close",
        currency="CNY",
        unit="share",
    )
    context = ResolvedMarketDataQueryContext(
        query=resolved_query,
        identity=resolved_identity,
        storage=DatasetStorageResolution(
            dataset_id="dataset-market-bars",
            dataset_code="market.bars",
            storage_id="canonical-market-data",
            engine="sqlite",
            database_name="test",
            physical_table="md_observation_revisions",
            write_mode="canonical_read_write",
        ),
        coverage_identity=coverage_identity,
    )
    event_times = (request.start, request.start + timedelta(days=1))
    observations: list[LocalObservationRevision] = []
    for index, event_at in enumerate(event_times, start=1):
        fields: dict[str, object] = {
            "open": "10.00",
            "high": "11.00",
            "low": "9.50",
            "close": 10.5 + close_adjustment,
            "volume": "1000",
            "open_interest": "12",
        }
        if missing_ohlc:
            fields.pop("high")
        observations.append(
            LocalObservationRevision(
                revision_id=f"00000000-0000-0000-0000-{index:012d}",
                source_snapshot_id=f"10000000-0000-0000-0000-{index:012d}",
                event_at=event_at,
                available_at=event_at + timedelta(hours=1),
                committed_at=NOW,
                visible_at=NOW,
                visibility_sequence=index,
                revision_number=1,
                quality=ObservationQuality.PASS,
                fields=fields,
            )
        )
    expected_keys = tuple(EventKey(event_at) for event_at in event_times)
    anchor = MarketDataVisibilityAnchor(
        visible_at=request.knowledge_cutoff or NOW,
        max_visibility_sequence=_BINDING_ANCHOR_MAX_SEQUENCE,
    )
    return MarketDataQueryExecution(
        context=context,
        knowledge_cutoff=request.knowledge_cutoff or NOW,
        identity_knowledge_cutoff=request.knowledge_cutoff or NOW,
        visibility_anchor=anchor,
        identity_visibility_anchor=anchor,
        coverage=CoveragePlan(
            status=CoverageStatus.COMPLETE,
            expected_event_keys=expected_keys,
            accepted_event_keys=expected_keys,
            missing_event_keys=(),
            gaps=(),
            rejection_counts={},
        ),
        observations=tuple(observations),
        next_cursor=None,
        fetches=(),
        warnings=(),
    )


@pytest.mark.parametrize(
    ("asset_type", "expected_family_id"),
    (
        ("stock", "stock.realtime"),
        ("futures", "futures.realtime"),
        ("bond", "bond.realtime"),
        ("fund", "fund.realtime"),
        ("option", "option.realtime"),
        ("fx", "fx.realtime"),
        ("crypto", "crypto.range"),
    ),
)
def test_strict_research_bars_family_selection_is_explicit(
    asset_type: str,
    expected_family_id: str,
) -> None:
    """A snapshot family can never become the strict-backtest bars fallback."""
    assert _strict_research_bars_family_id(asset_type) == expected_family_id


@pytest.mark.asyncio
@pytest.mark.parametrize("asset_type", ("stock", "futures", "bond", "fund", "option", "fx"))
async def test_bind_request_uses_each_ready_strict_bars_family(
    tmp_path: Path,
    asset_type: str,
) -> None:
    """Every ready asset keeps its own server-selected local strict bars route."""
    user = await _user(username=f"binding-ready-bars-{asset_type}")
    expected_family_id = f"{asset_type}.realtime"
    contracts = _FamilyContractResolver(asset_type=asset_type)
    query_service = _LocalOnlyQueryService(asset_type=asset_type)
    async with async_session_maker() as db:
        service = MarketDataResearchBindingService(
            db,
            query_service,
            contracts,
            MarketDataAccessAuthorizer(db, clock=lambda: NOW),
            tmp_path,
            binding_signing_key=SIGNING_KEY,
            clock=lambda: NOW,
        )
        bound = await service.bind_request(
            user_id=user.id,
            request=_request({"market_data_asset_type": asset_type}),
            intent_id=f"ai-research-ready-bars-{asset_type}",
        )

    assert contracts.calls == [
        {
            "asset_type": asset_type,
            "symbol": "600000",
            "period": "1d",
            "family_id": expected_family_id,
        }
    ]
    assert len(query_service.requests) == 1
    query = query_service.requests[0]
    assert query.family_id == expected_family_id
    assert query.mode == "local_only"
    assert query.purpose == "backtest"
    assert query.consistency == "strict"
    assert query_service.online_fetch_attempts == 0
    assert bound.data_config["market_data_asset_type"] == asset_type


@pytest.mark.asyncio
@pytest.mark.parametrize("timeframe", ("1d", "1w", "1mo"))
async def test_bind_request_rejects_unconfigured_crypto_bars_before_contract_or_query(
    tmp_path: Path,
    timeframe: str,
) -> None:
    """Crypto range remains a fail-closed future bars route until explicitly enabled."""
    user = await _user(username=f"binding-crypto-{timeframe}")
    contracts = _ContractResolver()
    query_service = _LocalOnlyQueryService()
    artifact_root = tmp_path / "artifacts"
    async with async_session_maker() as db:
        service = MarketDataResearchBindingService(
            db,
            query_service,
            contracts,
            MarketDataAccessAuthorizer(db, clock=lambda: NOW),
            artifact_root,
            binding_signing_key=SIGNING_KEY,
            clock=lambda: NOW,
        )
        with pytest.raises(MarketDataResearchBindingError) as failure:
            await service.bind_request(
                user_id=user.id,
                request=_request(
                    {"market_data_asset_type": "crypto"},
                    timeframe=timeframe,
                ),
                intent_id=f"ai-research-crypto-{timeframe}",
            )
        binding_count = await db.scalar(select(func.count()).select_from(MdResearchDataBinding))

    assert failure.value.code == "MARKET_DATA_BINDING_STRICT_BARS_FAMILY_UNCONFIGURED"
    assert contracts.calls == []
    assert query_service.requests == []
    assert query_service.online_fetch_attempts == 0
    assert binding_count == 0
    assert not (artifact_root / "bindings").exists()


@pytest.mark.asyncio
async def test_bind_request_forces_strict_local_only_and_persists_deterministic_csv(
    tmp_path: Path,
) -> None:
    """A bound request carries only a signed opaque receipt, never a client path."""
    user = await _user(username="binding-owner")
    contracts = _ContractResolver()
    query_service = _LocalOnlyQueryService()
    async with async_session_maker() as db:
        service = MarketDataResearchBindingService(
            db,
            query_service,
            contracts,
            MarketDataAccessAuthorizer(db, clock=lambda: NOW),
            tmp_path,
            binding_signing_key=SIGNING_KEY,
            clock=lambda: NOW,
        )
        bound = await service.bind_request(
            user_id=user.id,
            request=_request(),
            intent_id="ai-research-task-001",
        )
        repeated = await service.bind_request(
            user_id=user.id,
            request=_request(),
            intent_id="ai-research-task-001",
        )
        count = await db.scalar(select(func.count()).select_from(MdResearchDataBinding))

    assert contracts.calls == [
        {
            "asset_type": "stock",
            "symbol": "600000",
            "period": "1d",
            "family_id": "stock.realtime",
        },
        {
            "asset_type": "stock",
            "symbol": "600000",
            "period": "1d",
            "family_id": "stock.realtime",
        },
    ]
    assert len(query_service.requests) == 2
    assert query_service.online_fetch_attempts == 0
    assert all(isinstance(access, MarketDataQueryAccess) for access in query_service.accesses)
    for query in query_service.requests:
        assert query.mode == "local_only"
        assert query.purpose == "backtest"
        assert query.consistency == "strict"
        assert query.knowledge_cutoff == END
        assert query.cursor is None
    assert count == 1
    assert bound.data_config == repeated.data_config
    assert set(bound.data_config) == {
        "market_data_asset_type",
        "market_data_binding_id",
        "market_data_binding_hash",
        "market_data_binding_signature",
        "market_data_binding_intent_id",
        "market_data_binding_required",
    }
    assert bound.data_config["market_data_asset_type"] == "stock"
    binding_hash = str(bound.data_config["market_data_binding_hash"])
    artifact = tmp_path / "bindings" / binding_hash / "data.csv"
    assert artifact.read_text(encoding="utf-8") == (
        "datetime,open,high,low,close,volume,openinterest\n"
        "2026-01-05T00:00:00.000000Z,10,11,9.5,10.5,1000,12\n"
        "2026-01-06T00:00:00.000000Z,10,11,9.5,10.5,1000,12\n"
    )


@pytest.mark.asyncio
async def test_bind_request_rejects_client_path_injection_and_missing_ohlc(tmp_path: Path) -> None:
    """A caller cannot provide artifact selectors and cannot synthesize OHLC bars."""
    user = await _user(username="binding-input-reject")
    async with async_session_maker() as db:
        service = MarketDataResearchBindingService(
            db,
            _LocalOnlyQueryService(),
            _ContractResolver(),
            MarketDataAccessAuthorizer(db, clock=lambda: NOW),
            tmp_path,
            binding_signing_key=SIGNING_KEY,
            clock=lambda: NOW,
        )
        with pytest.raises(MarketDataResearchBindingError) as injected:
            await service.bind_request(
                user_id=user.id,
                request=_request(
                    {
                        "market_data_asset_type": "stock",
                        "directory_path": "/tmp/attacker-controlled.csv",
                    }
                ),
                intent_id="ai-research-task-002",
            )
        assert injected.value.code == "MARKET_DATA_BINDING_CLIENT_DATA_CONFIG_FORBIDDEN"

        missing_ohlc_service = MarketDataResearchBindingService(
            db,
            _LocalOnlyQueryService(missing_ohlc=True),
            _ContractResolver(),
            MarketDataAccessAuthorizer(db, clock=lambda: NOW),
            tmp_path,
            binding_signing_key=SIGNING_KEY,
            clock=lambda: NOW,
        )
        with pytest.raises(MarketDataResearchBindingError) as missing_ohlc:
            await missing_ohlc_service.bind_request(
                user_id=user.id,
                request=_request(),
                intent_id="ai-research-task-003",
            )
    assert missing_ohlc.value.code == "MARKET_DATA_BINDING_OHLC_REQUIRED"


@pytest.mark.asyncio
async def test_runtime_binding_rechecks_owner_signature_subset_and_artifact_digest(
    tmp_path: Path,
) -> None:
    """Runtime can consume a sealed subset but cannot cross owners or tamper bytes."""
    owner = await _user(username="binding-runtime-owner")
    other = await _user(username="binding-runtime-other")
    async with async_session_maker() as db:
        service = MarketDataResearchBindingService(
            db,
            _LocalOnlyQueryService(),
            _ContractResolver(),
            MarketDataAccessAuthorizer(db, clock=lambda: NOW),
            tmp_path,
            binding_signing_key=SIGNING_KEY,
            clock=lambda: NOW,
        )
        bound = await service.bind_request(
            user_id=owner.id,
            request=_request(),
            intent_id="ai-research-task-004",
        )
        config = bound.data_config
        workspace_id, unit_id = await _attach_research_unit(
            db=db,
            service=service,
            user=owner,
            bound=bound,
        )
        runtime = await service.resolve_runtime_binding(
            user_id=owner.id,
            binding_id=str(config["market_data_binding_id"]),
            binding_hash=str(config["market_data_binding_hash"]),
            signature=str(config["market_data_binding_signature"]),
            workspace_id=workspace_id,
            unit_id=unit_id,
            intent_id=str(config["market_data_binding_intent_id"]),
            symbol="600000",
            timeframe="1d",
            timeframe_n=1,
            start="2026-01-06",
            end="2026-01-06",
        )
        assert runtime.artifact_path.is_file()
        assert runtime.query_semantics["full_window_start"] == "2026-01-05T00:00:00.000000Z"
        assert runtime.query_semantics["full_window_end"] == "2026-01-07T00:00:00.000000Z"

        with pytest.raises(MarketDataResearchBindingError) as incomplete_semantics:
            await service.resolve_runtime_binding(
                user_id=owner.id,
                binding_id=str(config["market_data_binding_id"]),
                binding_hash=str(config["market_data_binding_hash"]),
                signature=str(config["market_data_binding_signature"]),
                workspace_id=workspace_id,
                unit_id=unit_id,
                intent_id=str(config["market_data_binding_intent_id"]),
                symbol="600000",
                timeframe="1d",
                timeframe_n=1,
                start="2026-01-06",
            )
        assert incomplete_semantics.value.code == "MARKET_DATA_BINDING_RUNTIME_SEMANTICS_REQUIRED"

        with pytest.raises(MarketDataResearchBindingError) as cross_owner:
            await service.resolve_runtime_binding(
                user_id=other.id,
                binding_id=str(config["market_data_binding_id"]),
                binding_hash=str(config["market_data_binding_hash"]),
                signature=str(config["market_data_binding_signature"]),
                workspace_id=workspace_id,
                unit_id=unit_id,
                intent_id=str(config["market_data_binding_intent_id"]),
            )
        assert cross_owner.value.code == "MARKET_DATA_BINDING_OWNER_DENIED"

        with pytest.raises(MarketDataResearchBindingError) as expanded_window:
            await service.resolve_runtime_binding(
                user_id=owner.id,
                binding_id=str(config["market_data_binding_id"]),
                binding_hash=str(config["market_data_binding_hash"]),
                signature=str(config["market_data_binding_signature"]),
                workspace_id=workspace_id,
                unit_id=unit_id,
                intent_id=str(config["market_data_binding_intent_id"]),
                symbol="600000",
                timeframe="1d",
                timeframe_n=1,
                start="2026-01-04T00:00:00Z",
                end="2026-01-07T00:00:00Z",
            )
        assert expanded_window.value.code == "MARKET_DATA_BINDING_RUNTIME_WINDOW_INVALID"

        runtime.artifact_path.chmod(0o640)
        runtime.artifact_path.write_text("tampered", encoding="utf-8")
        with pytest.raises(MarketDataResearchBindingError) as tampered:
            await service.resolve_runtime_binding(
                user_id=owner.id,
                binding_id=str(config["market_data_binding_id"]),
                binding_hash=str(config["market_data_binding_hash"]),
                signature=str(config["market_data_binding_signature"]),
                workspace_id=workspace_id,
                unit_id=unit_id,
                intent_id=str(config["market_data_binding_intent_id"]),
            )
    assert tampered.value.code == "MARKET_DATA_BINDING_ARTIFACT_SIZE_MISMATCH"


@pytest.mark.asyncio
async def test_runtime_replay_rejects_injected_crypto_snapshot_family_before_query(
    tmp_path: Path,
) -> None:
    """A coherently re-sealed family injection cannot retarget a stock replay."""
    owner = await _user(username="binding-runtime-family-injection")
    contracts = _ContractResolver()
    query_service = _LocalOnlyQueryService()
    async with async_session_maker() as db:
        service = MarketDataResearchBindingService(
            db,
            query_service,
            contracts,
            MarketDataAccessAuthorizer(db, clock=lambda: NOW),
            tmp_path,
            binding_signing_key=SIGNING_KEY,
            clock=lambda: NOW,
        )
        bound = await service.bind_request(
            user_id=owner.id,
            request=_request(),
            intent_id="ai-research-runtime-family-injection",
        )
        workspace_id, unit_id = await _attach_research_unit(
            db=db,
            service=service,
            user=owner,
            bound=bound,
        )
        resolve_kwargs = {
            "user_id": owner.id,
            "binding_id": str(bound.data_config["market_data_binding_id"]),
            "binding_hash": str(bound.data_config["market_data_binding_hash"]),
            "signature": str(bound.data_config["market_data_binding_signature"]),
            "workspace_id": workspace_id,
            "unit_id": unit_id,
            "intent_id": str(bound.data_config["market_data_binding_intent_id"]),
        }

        runtime = await service.resolve_runtime_binding(**resolve_kwargs)
        assert runtime.query_semantics["family_id"] == "stock.realtime"
        resolver_calls_before_injection = len(contracts.calls)
        query_calls_before_injection = len(query_service.requests)

        binding = await db.get(MdResearchDataBinding, resolve_kwargs["binding_id"])
        unit = await db.get(StrategyUnit, unit_id)
        assert binding is not None
        assert unit is not None
        injected_manifest = deepcopy(binding.manifest_json)
        material = injected_manifest["material"]
        assert isinstance(material, dict)
        semantics = material["query_semantics"]
        assert isinstance(semantics, dict)
        # Keep the ready stock asset type so the runtime reaches the exact
        # family comparison. A literal crypto asset correctly stops earlier
        # at crypto.range's unconfigured lifecycle gate.
        semantics.update(
            {
                "asset_type": "stock",
                "family_id": "crypto.realtime",
                "data_kind": "bars",
                "query_fingerprint": _canonical_sha256({"test": "injected-crypto-realtime-family"}),
            }
        )
        # The pinned publication contract must stay internally consistent with the
        # tampered semantics; otherwise the sealed manifest itself is refused (see
        # the dedicated pinned-contract test) and the replay gate is never reached.
        dataset = material["publications"]["datasets"][0]
        assert isinstance(dataset, dict)
        dataset["family_id"] = "crypto.realtime"
        dataset["contract_sha256"] = market_data_binding_contract_sha256(dataset)
        injected_binding_hash = _canonical_sha256(material)
        injected_manifest["binding_hash"] = injected_binding_hash
        injected_manifest_sha256 = _canonical_sha256(injected_manifest)
        injected_config = dict(unit.data_config or {})
        injected_config["market_data_binding_hash"] = injected_binding_hash
        await db.execute(
            update(MdResearchDataBinding)
            .where(MdResearchDataBinding.id == binding.id)
            .values(
                binding_hash=injected_binding_hash,
                family_id="crypto.realtime",
                data_kind="bars",
                query_fingerprint=semantics["query_fingerprint"],
                manifest_json=injected_manifest,
                manifest_sha256=injected_manifest_sha256,
            )
        )
        await db.execute(
            update(StrategyUnit)
            .where(StrategyUnit.id == unit_id)
            .values(data_config=injected_config)
        )
        await db.commit()
        resolve_kwargs["binding_hash"] = injected_binding_hash

        with pytest.raises(MarketDataResearchBindingError) as injected:
            await service.resolve_runtime_binding(**resolve_kwargs)

    assert injected.value.code == "MARKET_DATA_BINDING_RUNTIME_CONTRACT_MISMATCH"
    assert len(contracts.calls) == resolver_calls_before_injection
    assert len(query_service.requests) == query_calls_before_injection


@pytest.mark.asyncio
async def test_runtime_binding_rejects_a_copied_token_without_a_server_consumer(
    tmp_path: Path,
) -> None:
    """An owner cannot reuse a sealed token in a second browser-created unit."""
    owner = await _user(username="binding-copy-owner")
    query_service = _LocalOnlyQueryService()
    async with async_session_maker() as db:
        service = MarketDataResearchBindingService(
            db,
            query_service,
            _ContractResolver(),
            MarketDataAccessAuthorizer(db, clock=lambda: NOW),
            tmp_path,
            binding_signing_key=SIGNING_KEY,
            clock=lambda: NOW,
        )
        bound = await service.bind_request(
            user_id=owner.id,
            request=_request(),
            intent_id="ai-research-task-copy-001",
        )
        workspace_id, trusted_unit_id = await _attach_research_unit(
            db=db,
            service=service,
            user=owner,
            bound=bound,
        )
        copied_unit = StrategyUnit(
            workspace_id=workspace_id,
            strategy_name="copied binding strategy",
            symbol="600000",
            timeframe="1d",
            timeframe_n=1,
            category="stock",
            data_config={
                **dict(bound.data_config),
                "range_type": "date",
                "start_date": "2026-01-05",
                "end_date": "2026-01-06",
                "use_end_date": True,
            },
        )
        db.add(copied_unit)
        await db.commit()
        binding_id = str(bound.data_config["market_data_binding_id"])
        scope = await db.get(MdResearchDataBindingScope, binding_id)
        consumers = list(
            (
                await db.scalars(
                    select(MdResearchDataBindingConsumer).where(
                        MdResearchDataBindingConsumer.binding_id == binding_id
                    )
                )
            ).all()
        )

        assert scope is not None
        assert scope.workspace_id == workspace_id
        assert [consumer.unit_id for consumer in consumers] == [trusted_unit_id]

        with pytest.raises(MarketDataResearchBindingError) as copied:
            await service.resolve_runtime_binding(
                user_id=owner.id,
                binding_id=binding_id,
                binding_hash=str(bound.data_config["market_data_binding_hash"]),
                signature=str(bound.data_config["market_data_binding_signature"]),
                workspace_id=workspace_id,
                unit_id=copied_unit.id,
                intent_id=str(bound.data_config["market_data_binding_intent_id"]),
            )

        workspace = await db.get(Workspace, workspace_id)
        assert workspace is not None
        workspace.workspace_type = "trading"
        await db.commit()
        with pytest.raises(MarketDataResearchBindingError) as moved_to_trading:
            await service.resolve_runtime_binding(
                user_id=owner.id,
                binding_id=binding_id,
                binding_hash=str(bound.data_config["market_data_binding_hash"]),
                signature=str(bound.data_config["market_data_binding_signature"]),
                workspace_id=workspace_id,
                unit_id=trusted_unit_id,
                intent_id=str(bound.data_config["market_data_binding_intent_id"]),
            )

    assert copied.value.code == "MARKET_DATA_BINDING_RUNTIME_INTENT_DENIED"
    assert moved_to_trading.value.code == "MARKET_DATA_BINDING_RUNTIME_INTENT_DENIED"
    # Binding + trusted attachment query only; a copied unit is rejected before
    # the potentially expensive current-policy local replay.
    assert len(query_service.requests) == 2


@pytest.mark.asyncio
async def test_runtime_binding_rechecks_current_read_permission_and_source_policy(
    tmp_path: Path,
) -> None:
    """Revoked data entitlements and source access fail before the artifact is reused."""
    owner = await _user(username="binding-current-access-owner")
    query_service = _LocalOnlyQueryService()
    async with async_session_maker() as db:
        service = MarketDataResearchBindingService(
            db,
            query_service,
            _ContractResolver(),
            MarketDataAccessAuthorizer(db, clock=lambda: NOW),
            tmp_path,
            binding_signing_key=SIGNING_KEY,
            clock=lambda: NOW,
        )
        bound = await service.bind_request(
            user_id=owner.id,
            request=_request(),
            intent_id="ai-research-task-current-access-001",
        )
        workspace_id, unit_id = await _attach_research_unit(
            db=db,
            service=service,
            user=owner,
            bound=bound,
        )
        resolve_kwargs = {
            "user_id": owner.id,
            "binding_id": str(bound.data_config["market_data_binding_id"]),
            "binding_hash": str(bound.data_config["market_data_binding_hash"]),
            "signature": str(bound.data_config["market_data_binding_signature"]),
            "workspace_id": workspace_id,
            "unit_id": unit_id,
            "intent_id": str(bound.data_config["market_data_binding_intent_id"]),
        }

        await db.execute(
            delete(user_roles).where(
                user_roles.c.user_id == owner.id,
                user_roles.c.role == Role.USER.value,
            )
        )
        await db.commit()
        with pytest.raises(MarketDataResearchBindingError) as no_read_access:
            await service.resolve_runtime_binding(**resolve_kwargs)
        assert no_read_access.value.code == "MARKET_DATA_BINDING_RUNTIME_READ_ACCESS_DENIED"

        await db.execute(user_roles.insert().values(user_id=owner.id, role=Role.USER.value))
        await db.commit()
        query_service.execution_error = MarketDataAuthorizationError("SOURCE_LICENSE_DENIED")
        with pytest.raises(MarketDataResearchBindingError) as no_source_access:
            await service.resolve_runtime_binding(**resolve_kwargs)

    assert no_source_access.value.code == "MARKET_DATA_BINDING_RUNTIME_SOURCE_POLICY_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_runtime_binding_rejects_changed_current_source_evidence_and_revocation(
    tmp_path: Path,
) -> None:
    """A permitted substitute datum and an append-only revocation both fail closed."""
    owner = await _user(username="binding-evidence-owner")
    query_service = _LocalOnlyQueryService()
    async with async_session_maker() as db:
        service = MarketDataResearchBindingService(
            db,
            query_service,
            _ContractResolver(),
            MarketDataAccessAuthorizer(db, clock=lambda: NOW),
            tmp_path,
            binding_signing_key=SIGNING_KEY,
            clock=lambda: NOW,
        )
        bound = await service.bind_request(
            user_id=owner.id,
            request=_request(),
            intent_id="ai-research-task-evidence-001",
        )
        workspace_id, unit_id = await _attach_research_unit(
            db=db,
            service=service,
            user=owner,
            bound=bound,
        )
        resolve_kwargs = {
            "user_id": owner.id,
            "binding_id": str(bound.data_config["market_data_binding_id"]),
            "binding_hash": str(bound.data_config["market_data_binding_hash"]),
            "signature": str(bound.data_config["market_data_binding_signature"]),
            "workspace_id": workspace_id,
            "unit_id": unit_id,
            "intent_id": str(bound.data_config["market_data_binding_intent_id"]),
        }

        query_service.close_adjustment = 0.5
        with pytest.raises(MarketDataResearchBindingError) as changed_evidence:
            await service.resolve_runtime_binding(**resolve_kwargs)
        assert changed_evidence.value.code == "MARKET_DATA_BINDING_RUNTIME_SOURCE_EVIDENCE_MISMATCH"

        query_service.close_adjustment = 0.0
        await service.revoke_runtime_binding(
            binding_id=resolve_kwargs["binding_id"],
            reason_code="OPERATOR_EMERGENCY_REVOKE",
            actor_user_id=owner.id,
        )
        revocation = await db.scalar(
            select(MdResearchDataBindingRevocation).where(
                MdResearchDataBindingRevocation.binding_id == resolve_kwargs["binding_id"]
            )
        )
        assert revocation is not None
        assert revocation.status == "REVOKED"
        revocation.status = "INVALID"
        with pytest.raises(ImmutableMarketDataRecordError):
            await db.commit()
        await db.rollback()

        with pytest.raises(MarketDataResearchBindingError) as revoked:
            await service.resolve_runtime_binding(**resolve_kwargs)

    assert revoked.value.code == "MARKET_DATA_BINDING_REVOKED"


@pytest.mark.asyncio
async def test_runtime_binding_reloads_after_revocation_commits_during_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A revocation committed at the replay fence cannot reuse an old snapshot.

    The shared in-memory SQLite test engine cannot hold an independent writer
    transaction while the resolver owns its read snapshot. The execute hook
    therefore records the revocation request during the long replay, and the
    snapshot-end wrapper commits it through a separate session immediately
    after the old snapshot is discarded. This models the MySQL interleaving
    where the operator transaction commits before the fresh current read.
    """
    owner = await _user(username="binding-replay-revocation-owner")
    query_service = _LocalOnlyQueryService()
    async with async_session_maker() as db:
        service = MarketDataResearchBindingService(
            db,
            query_service,
            _ContractResolver(),
            MarketDataAccessAuthorizer(db, clock=lambda: NOW),
            tmp_path,
            binding_signing_key=SIGNING_KEY,
            clock=lambda: NOW,
        )
        bound = await service.bind_request(
            user_id=owner.id,
            request=_request(),
            intent_id="ai-research-task-replay-revocation-001",
        )
        workspace_id, unit_id = await _attach_research_unit(
            db=db,
            service=service,
            user=owner,
            bound=bound,
        )
        resolve_kwargs = {
            "user_id": owner.id,
            "binding_id": str(bound.data_config["market_data_binding_id"]),
            "binding_hash": str(bound.data_config["market_data_binding_hash"]),
            "signature": str(bound.data_config["market_data_binding_signature"]),
            "workspace_id": workspace_id,
            "unit_id": unit_id,
            "intent_id": str(bound.data_config["market_data_binding_intent_id"]),
        }
        replay_requested_revocation = False
        revocation_committed = False

        async def request_revocation(_request: MarketDataQueryRequest) -> None:
            nonlocal replay_requested_revocation
            replay_requested_revocation = True

        query_service.on_execute = request_revocation
        request_count_before_resolve = len(query_service.requests)
        original_end_snapshot = service._end_runtime_read_snapshot

        async def end_snapshot_then_commit_revocation() -> None:
            nonlocal revocation_committed
            await original_end_snapshot()
            if not replay_requested_revocation or revocation_committed:
                return
            async with async_session_maker() as revoker_db:
                revoker = MarketDataResearchBindingService(
                    revoker_db,
                    _LocalOnlyQueryService(),
                    _ContractResolver(),
                    MarketDataAccessAuthorizer(revoker_db, clock=lambda: NOW),
                    tmp_path,
                    binding_signing_key=SIGNING_KEY,
                    clock=lambda: NOW,
                )
                await revoker.revoke_runtime_binding(
                    binding_id=resolve_kwargs["binding_id"],
                    reason_code="OPERATOR_REVOKED_DURING_REPLAY",
                    actor_user_id=owner.id,
                )
            revocation_committed = True

        monkeypatch.setattr(
            service,
            "_end_runtime_read_snapshot",
            end_snapshot_then_commit_revocation,
        )
        with pytest.raises(MarketDataResearchBindingError) as revoked:
            await service.resolve_runtime_binding(**resolve_kwargs)

    assert replay_requested_revocation
    assert revocation_committed
    assert revoked.value.code == "MARKET_DATA_BINDING_REVOKED"
    # The refreshed consumer check rejects before a second strict replay can
    # expose the artifact. The first new request is the long replay hook.
    assert len(query_service.requests) == request_count_before_resolve + 1


@pytest.mark.asyncio
async def test_runtime_binding_final_fence_rechecks_sealed_source_registries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A registry disabled after fresh replay cannot authorize its sealed bytes."""
    owner = await _user(username="binding-final-source-fence-owner")
    query_service = _LocalOnlyQueryService()
    async with async_session_maker() as db:
        service = MarketDataResearchBindingService(
            db,
            query_service,
            _ContractResolver(),
            MarketDataAccessAuthorizer(db, clock=lambda: NOW),
            tmp_path,
            binding_signing_key=SIGNING_KEY,
            clock=lambda: NOW,
        )
        bound = await service.bind_request(
            user_id=owner.id,
            request=_request(),
            intent_id="ai-research-task-final-source-fence-001",
        )
        workspace_id, unit_id = await _attach_research_unit(
            db=db,
            service=service,
            user=owner,
            bound=bound,
        )
        resolve_kwargs = {
            "user_id": owner.id,
            "binding_id": str(bound.data_config["market_data_binding_id"]),
            "binding_hash": str(bound.data_config["market_data_binding_hash"]),
            "signature": str(bound.data_config["market_data_binding_signature"]),
            "workspace_id": workspace_id,
            "unit_id": unit_id,
            "intent_id": str(bound.data_config["market_data_binding_intent_id"]),
        }
        request_count_before_resolve = len(query_service.requests)
        original_end_snapshot = service._end_runtime_read_snapshot
        snapshot_restarts = 0
        registry_disabled = False

        async def end_fresh_replay_then_disable_registry() -> None:
            nonlocal registry_disabled, snapshot_restarts
            await original_end_snapshot()
            snapshot_restarts += 1
            if snapshot_restarts != 2:
                return
            async with async_session_maker() as registry_db:
                registry = await registry_db.get(AssetDataSourceRegistry, _SEALED_SOURCE_ID)
                assert registry is not None
                registry.enabled = False
                await registry_db.commit()
            registry_disabled = True

        monkeypatch.setattr(
            service,
            "_end_runtime_read_snapshot",
            end_fresh_replay_then_disable_registry,
        )
        runtime = None
        with pytest.raises(MarketDataResearchBindingError) as denied:
            runtime = await service.resolve_runtime_binding(**resolve_kwargs)

    assert snapshot_restarts == 2
    assert registry_disabled
    assert runtime is None
    assert denied.value.code == "MARKET_DATA_BINDING_RUNTIME_SOURCE_POLICY_ACCESS_DENIED"
    # The fresh replay completed; the final locking registry fence, rather
    # than stale source-policy evidence, denied the artifact materialization.
    assert len(query_service.requests) == request_count_before_resolve + 2


@pytest.mark.asyncio
async def test_binding_without_a_signing_key_fails_before_any_local_query(tmp_path: Path) -> None:
    """A disabled/missing HMAC key cannot mint a runtime-usable artifact."""
    user = await _user(username="binding-no-key")
    query_service = _LocalOnlyQueryService()
    async with async_session_maker() as db:
        service = MarketDataResearchBindingService(
            db,
            query_service,
            _ContractResolver(),
            MarketDataAccessAuthorizer(db, clock=lambda: NOW),
            tmp_path,
            binding_signing_key=None,
            clock=lambda: NOW,
        )
        with pytest.raises(MarketDataResearchBindingError) as missing_key:
            await service.bind_request(
                user_id=user.id,
                request=_request(),
                intent_id="ai-research-task-005",
            )
    assert missing_key.value.code == "MARKET_DATA_BINDING_SIGNING_KEY_REQUIRED"
    assert query_service.requests == []


@pytest.mark.asyncio
async def test_binding_model_is_append_only_and_runtime_rejects_direct_model_tamper(
    tmp_path: Path,
) -> None:
    """ORM writes and bulk SQL cannot alter a sealed binding's runtime facts."""
    user = await _user(username="binding-immutable")
    async with async_session_maker() as db:
        service = MarketDataResearchBindingService(
            db,
            _LocalOnlyQueryService(),
            _ContractResolver(),
            MarketDataAccessAuthorizer(db, clock=lambda: NOW),
            tmp_path,
            binding_signing_key=SIGNING_KEY,
            clock=lambda: NOW,
        )
        bound = await service.bind_request(
            user_id=user.id,
            request=_request(),
            intent_id="ai-research-task-006",
        )
        binding_id = str(bound.data_config["market_data_binding_id"])
        binding_hash = str(bound.data_config["market_data_binding_hash"])
        signature = str(bound.data_config["market_data_binding_signature"])
        intent_id = str(bound.data_config["market_data_binding_intent_id"])
        workspace_id, unit_id = await _attach_research_unit(
            db=db,
            service=service,
            user=user,
            bound=bound,
        )
        binding = await db.get(MdResearchDataBinding, binding_id)
        assert binding is not None
        binding.status = "INVALID"
        with pytest.raises(ImmutableMarketDataRecordError):
            await db.commit()
        await db.rollback()

        await db.execute(
            update(MdResearchDataBinding)
            .where(MdResearchDataBinding.id == binding_id)
            .values(canonical_id=f"{CANONICAL_ID}:tampered")
        )
        await db.commit()

    async with async_session_maker() as db:
        service = MarketDataResearchBindingService(
            db,
            _LocalOnlyQueryService(),
            _ContractResolver(),
            MarketDataAccessAuthorizer(db, clock=lambda: NOW),
            tmp_path,
            binding_signing_key=SIGNING_KEY,
            clock=lambda: NOW,
        )
        with pytest.raises(MarketDataResearchBindingError) as tampered_record:
            await service.resolve_runtime_binding(
                user_id=user.id,
                binding_id=binding_id,
                binding_hash=binding_hash,
                signature=signature,
                workspace_id=workspace_id,
                unit_id=unit_id,
                intent_id=intent_id,
            )
    assert tampered_record.value.code == "MARKET_DATA_BINDING_MANIFEST_INVALID"


def test_research_binding_migration_preserves_exact_identifier_collation() -> None:
    """Fresh MySQL/PostgreSQL/SQLite binding DDL keeps canonical IDs bytewise."""
    migration = _load_research_binding_migration()
    assert migration.down_revision == "20260909_ai_research_market_data_merge"
    for dialect, expected_collation in (
        (mysql.dialect(), "COLLATE utf8mb4_bin"),
        (postgresql.dialect(), 'COLLATE "C"'),
        (sqlite.dialect(), 'COLLATE "BINARY"'),
    ):
        table = sa.Table(
            "research_binding_identity_probe",
            sa.MetaData(),
            sa.Column("canonical_id", migration._exact_identifier_type(512), nullable=False),
        )
        ddl = str(sa.schema.CreateTable(table).compile(dialect=dialect))
        assert expected_collation in ddl


async def _bind_research_request(
    db: Any,
    tmp_path: Path,
    *,
    user: User,
    intent_id: str,
) -> tuple[MarketDataResearchBindingService, AIStrategyResearchRunRequest]:
    """Bind one strict research request against the sealed shared fixture."""
    service = MarketDataResearchBindingService(
        db,
        _LocalOnlyQueryService(),
        _ContractResolver(),
        MarketDataAccessAuthorizer(db, clock=lambda: NOW),
        tmp_path,
        binding_signing_key=SIGNING_KEY,
        clock=lambda: NOW,
    )
    bound = await service.bind_request(
        user_id=user.id,
        request=_request(),
        intent_id=intent_id,
    )
    return service, bound


def _publication_dataset(material: dict[str, Any]) -> dict[str, Any]:
    datasets = material["publications"]["datasets"]
    assert isinstance(datasets, list) and len(datasets) == 1
    dataset = datasets[0]
    assert isinstance(dataset, dict)
    return dataset


async def _tamper_binding_manifest(
    db: Any,
    *,
    binding_id: str,
    unit_id: str,
    mutate,
) -> str:
    """Apply one raw-SQL manifest edit and re-point the unit token at the new hash."""
    binding = await db.get(MdResearchDataBinding, binding_id)
    assert binding is not None
    tampered = deepcopy(binding.manifest_json)
    mutate(tampered["material"])
    tampered_hash = _canonical_sha256(tampered["material"])
    tampered["binding_hash"] = tampered_hash
    unit = await db.get(StrategyUnit, unit_id)
    assert unit is not None
    await db.execute(
        update(MdResearchDataBinding)
        .where(MdResearchDataBinding.id == binding_id)
        .values(
            binding_hash=tampered_hash,
            manifest_json=tampered,
            manifest_sha256=_canonical_sha256(tampered),
        )
    )
    await db.execute(
        update(StrategyUnit)
        .where(StrategyUnit.id == unit_id)
        .values(
            data_config={
                **dict(unit.data_config or {}),
                "market_data_binding_hash": tampered_hash,
            }
        )
    )
    await db.commit()
    return tampered_hash


async def _reseal_publications(db: Any, *, values: dict[str, Any]) -> None:
    """Apply one raw SQL mutation to the fixture's sealed publication receipts."""
    await db.execute(
        update(MdPublication)
        .where(
            MdPublication.entity_type == PUBLICATION_SOURCE_SNAPSHOT,
            MdPublication.entity_id.in_(_SEALED_SOURCE_SNAPSHOT_IDS),
        )
        .values(**values)
    )
    await db.commit()


@pytest.mark.asyncio
async def test_bind_request_pins_publication_and_replay_identity(tmp_path: Path) -> None:
    """Each sealed snapshot is pinned to one publication, and a rebind replays identically."""
    user = await _user(username="binding-publication-pin")
    async with async_session_maker() as db:
        service, bound = await _bind_research_request(
            db, tmp_path, user=user, intent_id="ai-research-publication-pin"
        )
        repeated = await service.bind_request(
            user_id=user.id,
            request=_request(),
            intent_id="ai-research-publication-pin",
        )
        binding = await db.get(
            MdResearchDataBinding,
            str(bound.data_config["market_data_binding_id"]),
        )
    assert binding is not None
    assert repeated.data_config == bound.data_config
    manifest = dict(binding.manifest_json)
    material = dict(manifest["material"])
    section = material["publications"]
    assert section["schema_version"] == "market-data-research-publication-binding-v1"
    assert section["entity_type"] == PUBLICATION_SOURCE_SNAPSHOT
    dataset = _publication_dataset(material)
    receipts = dataset["publications"]
    assert [item["source_snapshot_id"] for item in receipts] == list(_SEALED_SOURCE_SNAPSHOT_IDS)
    assert [item["visibility_sequence"] for item in receipts] == list(_SEALED_PUBLICATION_SEQUENCES)
    assert all(item["entity_sha256"] == _SHA256_B for item in receipts)
    assert all(receipt["publication_id"] for receipt in receipts)
    assert dataset["window_start"] == "2026-01-05T00:00:00.000000Z"
    assert dataset["window_end"] == "2026-01-07T00:00:00.000000Z"
    assert dataset["knowledge_cutoff"] == "2026-01-07T00:00:00.000000Z"
    assert dataset["filters"] == {
        "asset_type": "stock",
        "symbol": "600000",
        "timeframe": "1d",
        "timeframe_n": 1,
    }
    assert dataset["mode"] == "local_only"
    assert dataset["consistency"] == "strict"
    assert dataset["purpose"] == "backtest"
    assert dataset["required_fields"] == ["close"]
    assert dataset["adjustment"] == "qfq"
    assert dataset["currency"] == "CNY"
    # Both pinned hashes are recomputable from the sealed vector, never invented.
    assert dataset["contract_sha256"] == market_data_binding_contract_sha256(dataset)
    artifact = tmp_path / "bindings" / str(bound.data_config["market_data_binding_hash"]) / "data.csv"
    assert dataset["content_sha256"] == market_data_binding_content_sha256(
        csv_content=artifact.read_bytes(),
        observation_evidence=material["observations"],
    )
    pins = market_data_binding_publication_pins(manifest)
    assert pins[0]["dataset_code"] == binding.dataset_code
    assert [dict(receipt) for receipt in pins[0]["publications"]] == receipts


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("missing", "MARKET_DATA_BINDING_PUBLICATION_INCOMPLETE"),
        ("unsealed", "MARKET_DATA_BINDING_PUBLICATION_UNSEALED"),
        ("future_visibility", "MARKET_DATA_BINDING_PUBLICATION_OUT_OF_ANCHOR"),
        ("content_drift", "MARKET_DATA_BINDING_PUBLICATION_CONTENT_MISMATCH"),
    ),
)
async def test_bind_request_refuses_incomplete_publication_reference(
    tmp_path: Path,
    mutation: str,
    expected_code: str,
) -> None:
    """A binding refuses rather than guessing when a publication reference is unusable."""
    user = await _user(username=f"binding-publication-{mutation}")
    async with async_session_maker() as db:
        if mutation == "missing":
            await db.execute(
                delete(MdPublication).where(
                    MdPublication.entity_type == PUBLICATION_SOURCE_SNAPSHOT,
                    MdPublication.entity_id.in_(_SEALED_SOURCE_SNAPSHOT_IDS),
                )
            )
            await db.commit()
        elif mutation == "unsealed":
            await _reseal_publications(
                db,
                values={"published_at": None, "visibility_sequence": None},
            )
        elif mutation == "future_visibility":
            await _reseal_publications(db, values={"published_at": NOW})
        else:
            await _reseal_publications(db, values={"entity_sha256": _SHA256_A})

        with pytest.raises(MarketDataResearchBindingError) as refused:
            await _bind_research_request(
                db, tmp_path, user=user, intent_id=f"ai-research-publication-{mutation}"
            )
    assert refused.value.code == expected_code


@pytest.mark.asyncio
async def test_runtime_replay_refuses_stale_publication_reference(tmp_path: Path) -> None:
    """A resealed publication cannot silently substitute a different vector."""
    user = await _user(username="binding-publication-stale")
    async with async_session_maker() as db:
        service, bound = await _bind_research_request(
            db, tmp_path, user=user, intent_id="ai-research-publication-stale"
        )
        workspace_id, unit_id = await _attach_research_unit(
            db=db,
            service=service,
            user=user,
            bound=bound,
        )
        resolve_kwargs = {
            "user_id": user.id,
            "binding_id": str(bound.data_config["market_data_binding_id"]),
            "binding_hash": str(bound.data_config["market_data_binding_hash"]),
            "signature": str(bound.data_config["market_data_binding_signature"]),
            "workspace_id": workspace_id,
            "unit_id": unit_id,
            "intent_id": str(bound.data_config["market_data_binding_intent_id"]),
        }
        runtime = await service.resolve_runtime_binding(**resolve_kwargs)
        assert runtime.publication_pins
        await db.execute(
            update(MdPublication)
            .where(MdPublication.entity_id == _SEALED_SOURCE_SNAPSHOT_IDS[0])
            .values(visibility_sequence=7_777_777)
        )
        await db.commit()

        with pytest.raises(MarketDataResearchBindingError) as stale:
            await service.resolve_runtime_binding(**resolve_kwargs)
    assert stale.value.code == "MARKET_DATA_BINDING_PUBLICATION_STALE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    (
        (
            "family_id",
            "crypto.realtime",
            "MARKET_DATA_BINDING_PUBLICATION_CONTRACT_MISMATCH",
        ),
        ("content_sha256", _SHA256_A, "MARKET_DATA_BINDING_REPLAY_CONTENT_MISMATCH"),
    ),
)
async def test_runtime_replay_refuses_pinned_publication_drift(
    tmp_path: Path,
    field: str,
    value: str,
    expected_code: str,
) -> None:
    """Rehashing a manifest cannot move a pinned contract axis or content identity."""
    user = await _user(username=f"binding-publication-drift-{field}")
    intent_id = f"ai-research-publication-drift-{field}"
    async with async_session_maker() as db:
        service, bound = await _bind_research_request(
            db, tmp_path, user=user, intent_id=intent_id
        )
        workspace_id, unit_id = await _attach_research_unit(
            db=db,
            service=service,
            user=user,
            bound=bound,
        )

        def mutate(material: dict[str, Any]) -> None:
            _publication_dataset(material)[field] = value

        tampered_hash = await _tamper_binding_manifest(
            db,
            binding_id=str(bound.data_config["market_data_binding_id"]),
            unit_id=unit_id,
            mutate=mutate,
        )

        with pytest.raises(MarketDataResearchBindingError) as drift:
            await service.resolve_runtime_binding(
                user_id=user.id,
                binding_id=str(bound.data_config["market_data_binding_id"]),
                binding_hash=tampered_hash,
                signature=str(bound.data_config["market_data_binding_signature"]),
                workspace_id=workspace_id,
                unit_id=unit_id,
                intent_id=str(bound.data_config["market_data_binding_intent_id"]),
            )
    assert drift.value.code == expected_code


def test_publication_content_digest_refives_drift() -> None:
    """The record-set digest is deterministic and refuses shape/provenance drift."""
    csv_content = (
        b"datetime,open,high,low,close,volume,openinterest\n"
        b"2026-01-05T00:00:00.000000Z,10,11,9.5,10.5,1000,12\n"
    )
    observation = {
        "revision_id": "00000000-0000-0000-0000-000000000001",
        "source_snapshot_id": _SEALED_SOURCE_SNAPSHOT_IDS[0],
        "event_at": "2026-01-05T00:00:00.000000Z",
        "available_at": "2026-01-05T01:00:00.000000Z",
        "visibility_sequence": 1,
        "revision_number": 1,
    }
    digest = market_data_binding_content_sha256(
        csv_content=csv_content,
        observation_evidence=[observation],
    )
    assert digest == market_data_binding_content_sha256(
        csv_content=csv_content,
        observation_evidence=[dict(observation)],
    )
    with pytest.raises(MarketDataResearchBindingError) as rows:
        market_data_binding_content_sha256(csv_content=csv_content, observation_evidence=[])
    assert rows.value.code == "MARKET_DATA_BINDING_CONTENT_ROWS_MISMATCH"
    with pytest.raises(MarketDataResearchBindingError) as columns:
        market_data_binding_content_sha256(
            csv_content=csv_content.replace(b"datetime", b"time", 1),
            observation_evidence=[observation],
        )
    assert columns.value.code == "MARKET_DATA_BINDING_CONTENT_COLUMNS_INVALID"
    with pytest.raises(MarketDataResearchBindingError) as provenance:
        market_data_binding_content_sha256(
            csv_content=csv_content,
            observation_evidence=[{**observation, "extra": "tampered"}],
        )
    assert provenance.value.code == "MARKET_DATA_BINDING_CONTENT_PROVENANCE_INVALID"


def test_publication_pins_refuse_a_missing_reference() -> None:
    """Consumers cannot read pins out of a binding that carries no publication."""
    with pytest.raises(MarketDataResearchBindingError) as refused:
        market_data_binding_publication_pins({"material": {"schema_version": "v"}})
    assert refused.value.code == "MARKET_DATA_BINDING_PUBLICATION_INVALID"
