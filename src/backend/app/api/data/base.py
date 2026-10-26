"""
Market data API routes.
"""

import logging
import typing
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from math import isfinite
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.data.deps import (
    get_authorized_market_data_access,
    get_market_data_access_authorizer,
)
from app.api.data.queries import (
    evaluate_market_data_capabilities,
    execute_market_data_query_with_singleflight,
    get_market_data_capability_evaluation,
    get_market_data_query_service,
)
from app.api.deps import get_current_user
from app.config import get_settings
from app.db.database import get_db
from app.schemas.market_data_platform import MarketDataQueryRequest
from app.services.market_data.access import (
    MarketDataAccessAuthorizer,
    MarketDataAuthorizationError,
    MarketDataQueryAccess,
)
from app.services.market_data.capability_ledger import MarketDataCapabilityEvaluation
from app.services.market_data.dataset_contracts import (
    FAMILY_CONTRACT_VERSION,
    KLINE_LEGACY_FAMILY_ID,
    DatasetContractRegistryError,
)
from app.services.market_data.field_quality import (
    FieldQualityValueError,
    is_usable_field_value,
    normalize_numeric_field_value,
)
from app.services.market_data.identity import MarketDataIdentityResolutionError
from app.services.market_data.legacy_contract import LegacyMarketDataQueryContractResolver
from app.services.market_data.legacy_kline_bridge import execute_legacy_kline_local_first
from app.services.market_data.legacy_kline_identity import matches_legacy_kline_display_token
from app.services.market_data.legacy_kline_projection import (
    LegacyKlineBridgeError,
    LegacyKlineInputError,
    LegacyKlineRequest,
    parse_legacy_kline_request,
)
from app.services.market_data.query_resolution import MarketDataQueryResolutionError
from app.services.market_data.query_service import (
    MarketDataCursorBinding,
    MarketDataQueryService,
    MarketDataQueryServiceError,
    OpendataDirectRead,
)
from app.services.market_data.source_policy import MarketDataSourcePolicyError
from app.services.market_data.store import MarketDataStoreError
from app.services.market_instrument import (
    LegacyMarketDataOnlineRefreshDisabledError,
    MarketAssetType,
    MarketInstrumentService,
)

router = APIRouter()
logger = logging.getLogger(__name__)
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MAX_SAFE_JSON_INTEGER = 9_007_199_254_740_991
_TWO_DECIMAL_PLACES = Decimal("0.01")

# The K-line facade reserves HTTP 403 for the caller's current data-read
# entitlement. Source-route, license, and provider-policy decisions are
# server-side availability/governance failures for this compatibility path and
# must remain fail-closed 503 responses rather than being misreported as a
# missing user grant.
_KLINE_DATA_READ_DENIAL_CODES = frozenset(
    {
        "MARKET_DATA_ACCESS_CHANGED_DURING_FETCH",
        "MARKET_DATA_ACCESS_REQUIRED",
        "MARKET_DATA_PRINCIPAL_INVALID",
        "MARKET_DATA_PRINCIPAL_REVOKED",
        "MARKET_DATA_READ_ENTITLEMENT_DENIED",
    }
)


def get_market_instrument_service() -> MarketInstrumentService:
    return MarketInstrumentService()


def build_legacy_market_data_query_contract_resolver(
    db: AsyncSession,
    *,
    settings: object | None = None,
) -> LegacyMarketDataQueryContractResolver:
    """Build the read-only v2 compatibility bridge from concrete inputs.

    This is deliberately a plain composition helper so non-HTTP consumers do
    not need to invoke a FastAPI dependency function directly.
    """
    effective_settings = get_settings() if settings is None else settings
    allowed_markets = frozenset(
        item.strip()
        for item in str(
            getattr(effective_settings, "MARKET_DATA_OPENBB_ALLOWED_MARKETS", "")
        ).split(",")
        if item.strip()
    )
    return LegacyMarketDataQueryContractResolver(
        db,
        openbb_provider=str(getattr(effective_settings, "MARKET_DATA_OPENBB_PROVIDER", "yfinance")),
        openbb_allowed_markets=allowed_markets,
    )


def get_legacy_market_data_query_contract_resolver(
    db: AsyncSession = Depends(get_db),
) -> LegacyMarketDataQueryContractResolver:
    """Build the read-only v2 compatibility bridge for a request database session."""
    return build_legacy_market_data_query_contract_resolver(db)


@router.get(
    "/market-instruments/query-contract",
    summary="Resolve a local-first market-data query contract",
    response_model=None,
)
async def get_market_data_query_contract(
    symbol: str = Query(
        ..., min_length=1, description="Exact instrument code from approved master data"
    ),
    asset_type: MarketAssetType = Query("stock", description="Instrument type"),
    period: str = Query(
        "daily",
        description="Legacy period label or an exact server-issued v2 cadence",
    ),
    family_id: str | None = Query(
        default=None,
        max_length=128,
        description="Optional exact market-page family selected from the server bundle",
    ),
    capabilities: MarketDataCapabilityEvaluation = Depends(get_market_data_capability_evaluation),
    query_contracts: LegacyMarketDataQueryContractResolver = Depends(
        get_legacy_market_data_query_contract_resolver
    ),
) -> typing.Any:
    """Return a strict v2 template without touching legacy data providers.

    A page uses this probe before the legacy lookup so a catalog-backed,
    uniquely registered identity can take the normalized local-first path on
    its first request. The resolver does not derive an identity from a nearby
    symbol and the endpoint intentionally returns 404 if bootstrap or
    approved master data is incomplete; clients then retain the legacy path.
    """
    if not capabilities.response.query_v2_enabled:
        raise HTTPException(
            status_code=503,
            detail={"code": "MARKET_DATA_QUERY_V2_DISABLED"},
        )
    # The K-line family is private to the server-owned compatibility facade.
    # Reject it at the public control-plane boundary rather than delegating to
    # the resolver, which keeps its private-product rejection from looking
    # like an ordinary invalid public family selector.
    if family_id == KLINE_LEGACY_FAMILY_ID:
        raise HTTPException(
            status_code=503,
            detail={"code": "MARKET_DATA_PRIVATE_FAMILY"},
        )
    try:
        resolve_args: dict[str, str] = {
            "asset_type": asset_type,
            "symbol": symbol,
            "period": period,
        }
        if family_id is not None:
            resolve_args["family_id"] = family_id
        contract = await query_contracts.resolve(**resolve_args)
    except DatasetContractRegistryError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code},
        ) from exc
    except SQLAlchemyError as exc:
        # A partially migrated metadata store is an unavailable compatibility
        # probe, not a server trace exposed to a market-page client.
        logger.warning("market-data v2 query contract unavailable")
        raise HTTPException(
            status_code=503,
            detail={"code": "MARKET_DATA_QUERY_CONTRACT_UNAVAILABLE"},
        ) from exc
    if contract is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "MARKET_DATA_QUERY_CONTRACT_UNAVAILABLE"},
        )
    return contract


def get_legacy_kline_request(
    http_request: Request,
    _access: MarketDataQueryAccess = Depends(get_authorized_market_data_access),
    symbol: str = Query(..., description="Stock code, e.g., 000001.SZ"),
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    period: str = Query("daily", description="Period: daily/weekly/monthly"),
) -> LegacyKlineRequest:
    """Validate the selector only after the current data-read authorization."""
    allowed_keys = {"symbol", "start_date", "end_date", "period"}
    query_keys = set(http_request.query_params.keys())
    if query_keys - allowed_keys or any(
        len(http_request.query_params.getlist(key)) != 1 for key in query_keys
    ):
        raise HTTPException(status_code=422, detail={"code": "KLINE_REQUEST_INVALID"})
    try:
        return parse_legacy_kline_request(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
        )
    except LegacyKlineInputError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code}) from exc


@router.get("/kline", summary="Query K-line data", response_model=None)
async def get_kline_data(
    request: LegacyKlineRequest = Depends(get_legacy_kline_request),
    access: MarketDataQueryAccess = Depends(get_authorized_market_data_access),
    db: AsyncSession = Depends(get_db),
    capabilities: MarketDataCapabilityEvaluation = Depends(get_market_data_capability_evaluation),
    service: MarketDataQueryService = Depends(get_market_data_query_service),
    query_contracts: LegacyMarketDataQueryContractResolver = Depends(
        get_legacy_market_data_query_contract_resolver
    ),
) -> typing.Any:
    """Return either a governed local K-line read or a direct OpenData daily read.

    The transitional local-first path still requires a local-only reread. When
    the explicit OpenData switch is enabled, ordinary stock daily requests use
    the independently authorized public ``stock.realtime`` contract and
    project the REST observations directly with honest, non-durable provenance.
    """
    if not capabilities.response.query_v2_enabled:
        raise HTTPException(
            status_code=503,
            detail={"code": "MARKET_DATA_QUERY_V2_DISABLED"},
        )

    binding = MarketDataCursorBinding(
        principal_scope=access.principal.principal_scope,
        tenant_scope=access.principal.tenant_scope,
        entitlement_revision=access.principal.entitlement_revision,
    )

    async def execute_local_first(query: typing.Any) -> typing.Any:
        return await execute_market_data_query_with_singleflight(
            service=service,
            db=db,
            request=query,
            cursor_binding=binding,
            access=access,
        )

    async def execute_local_only(query: typing.Any) -> typing.Any:
        return await service.execute(
            query,
            cursor_binding=binding,
            access=access,
        )

    try:
        if bool(getattr(get_settings(), "MARKET_DATA_OPENDATA_ENABLED", False)):
            if request.frequency != "1d":
                raise HTTPException(
                    status_code=422,
                    detail={"code": "OPENDATA_FREQUENCY_UNSUPPORTED"},
                )
            route_is_effective = getattr(capabilities, "route_is_effective", None)
            if not callable(route_is_effective) or not route_is_effective(
                "opendata-stock-daily-v1"
            ):
                raise HTTPException(
                    status_code=503,
                    detail={"code": "OPENDATA_ROUTE_NOT_EFFECTIVE"},
                )
            contract = await query_contracts.resolve(
                asset_type="stock",
                symbol=request.symbol,
                period=request.period,
            )
            direct_request = _request_from_public_kline_contract(
                contract,
                request=request,
            )
            result = await service.read_opendata_direct(direct_request, access=access)
            response = _project_opendata_legacy_kline(result, request=request)
            # The resolver, provider lifecycle gate and post-fetch source
            # reauthorization may have opened a read transaction. No write is
            # performed on this route, so release it explicitly.
            await db.rollback()
            return response
        return await execute_legacy_kline_local_first(
            request=request,
            contract_resolver=query_contracts,
            execute_local_first=execute_local_first,
            execute_local_only=execute_local_only,
        )
    except MarketDataAuthorizationError as exc:
        await db.rollback()
        response_status = 403 if exc.code in _KLINE_DATA_READ_DENIAL_CODES else 503
        raise HTTPException(status_code=response_status, detail={"code": exc.code}) from exc
    except (
        LegacyKlineBridgeError,
        DatasetContractRegistryError,
        MarketDataIdentityResolutionError,
        MarketDataQueryResolutionError,
        MarketDataSourcePolicyError,
        MarketDataQueryServiceError,
        MarketDataStoreError,
    ) as exc:
        await db.rollback()
        code = getattr(exc, "code", "KLINE_QUERY_FAILED")
        raise HTTPException(status_code=503, detail={"code": code}) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=503, detail={"code": "MARKET_DATA_WRITE_FAILED"}) from exc


def _request_from_public_kline_contract(
    contract: object,
    *,
    request: LegacyKlineRequest,
) -> MarketDataQueryRequest:
    """Bind the legacy date window to the reviewed public stock-bars contract."""
    if (
        not isinstance(contract, dict)
        or set(contract) != {"version", "request"}
        or contract.get("version") != "market-data-v2"
        or not isinstance(contract.get("request"), dict)
    ):
        raise LegacyKlineBridgeError("KLINE_CONTRACT_UNAVAILABLE")
    payload = dict(contract["request"])
    payload.update(
        {
            "start": request.start,
            "end": request.end,
            "mode": "local_first",
            "cursor": None,
            "page_size": 2000,
        }
    )
    try:
        query = MarketDataQueryRequest.model_validate(payload)
    except ValidationError as exc:
        raise LegacyKlineBridgeError("KLINE_QUERY_CONTRACT_INVALID") from exc
    if (
        query.identity.canonical_id is None
        or query.dataset_code != "market.bars"
        or query.data_kind != "bars"
        or query.frequency != "1d"
        or query.required_fields != ("close",)
        or query.adjustment != "qfq"
        or query.price_basis != "close"
        or query.currency != "CNY"
        or query.unit != "share"
        or query.source_policy_id != "market-default-v1"
        or query.family_id != "stock.realtime"
        or query.family_contract_version != FAMILY_CONTRACT_VERSION
        or query.consistency != "display"
        or query.purpose != "display"
        or query.knowledge_cutoff is not None
        or query.mode != "local_first"
        or query.cursor is not None
        or query.page_size != 2000
        or query.start != request.start
        or query.end != request.end
    ):
        raise LegacyKlineBridgeError("KLINE_QUERY_CONTRACT_INVALID")
    return query


def _project_opendata_legacy_kline(
    result: OpendataDirectRead,
    *,
    request: LegacyKlineRequest,
) -> dict[str, object]:
    """Project a direct REST response without claiming AFI calendar coverage."""
    if not isinstance(result, OpendataDirectRead):
        raise LegacyKlineBridgeError("KLINE_DIRECT_RESULT_INVALID")
    context = result.context
    query = context.query
    fetch_result = result.fetch_result
    if (
        query.dataset_code != "market.bars"
        or query.data_kind != "bars"
        or query.frequency != request.frequency
        or query.adjustment != "qfq"
        or query.price_basis != "close"
        or query.currency != "CNY"
        or query.unit != "share"
        or query.source_policy_id != "market-default-v1"
        or query.family_id != "stock.realtime"
        or query.family_contract_version != FAMILY_CONTRACT_VERSION
        or query.consistency != "display"
        or query.purpose != "display"
        or query.knowledge_cutoff is not None
        or query.mode != "local_first"
        or query.cursor is not None
        or query.page_size != 2000
        or query.start != request.start
        or query.end != request.end
        or context.identity.canonical_id != query.canonical_id
        or context.identity.asset_type != "stock"
        or context.identity.venue not in {"CN-SSE", "CN-SZSE"}
        or not matches_legacy_kline_display_token(
            context.identity.identity,
            token=request.symbol,
        )
        or fetch_result.provider_id != "opendata"
        or fetch_result.request.canonical_id != query.canonical_id
        or fetch_result.request.frequency != "1d"
    ):
        raise LegacyKlineBridgeError("KLINE_DIRECT_RESULT_INVALID")
    if len(fetch_result.observations) > 366:
        raise LegacyKlineBridgeError("OPENDATA_RESULT_TOO_LARGE")

    observations = sorted(fetch_result.observations, key=lambda item: item.event_at)
    dates: list[str] = []
    ohlc: list[list[float]] = []
    volumes: list[int] = []
    records: list[dict[str, object]] = []
    for observation in observations:
        if observation.event_at.tzinfo is None or observation.event_at.utcoffset() is None:
            raise LegacyKlineBridgeError("KLINE_EVENT_TIME_INVALID")
        local_date = observation.event_at.astimezone(_SHANGHAI).date()
        rendered_date = local_date.isoformat()
        if dates and rendered_date <= dates[-1]:
            raise LegacyKlineBridgeError("KLINE_DATE_INTEGRITY")
        rendered_open = _direct_two_decimal_number(observation.fields.get("open"), "open")
        rendered_high = _direct_two_decimal_number(observation.fields.get("high"), "high")
        rendered_low = _direct_two_decimal_number(observation.fields.get("low"), "low")
        rendered_close = _direct_two_decimal_number(observation.fields.get("close"), "close")
        rendered_volume = _direct_safe_integer(observation.fields.get("volume"), "volume")
        rendered_change = _direct_two_decimal_number(
            observation.fields.get("change_pct"),
            "change_pct",
        )
        dates.append(rendered_date)
        ohlc.append([rendered_open, rendered_close, rendered_low, rendered_high])
        volumes.append(rendered_volume)
        records.append(
            {
                "date": rendered_date,
                "open": rendered_open,
                "high": rendered_high,
                "low": rendered_low,
                "close": rendered_close,
                "volume": rendered_volume,
                "change": rendered_change,
            }
        )

    return {
        "symbol": request.symbol,
        "count": len(records),
        "kline": {"dates": dates, "ohlc": ohlc, "volumes": volumes},
        "records": records,
        "provenance": {
            "provider_id": fetch_result.provider_id,
            "provider_adapter_revision": fetch_result.source_revision,
            "source_revision": None,
            "request_id": fetch_result.request.request_id,
            "retrieved_at": fetch_result.retrieved_at.isoformat(),
            "raw_payload_sha256": fetch_result.raw_payload_hash,
            "source_registry_id": result.source_authorization.source_registry_id,
            "coverage_status": "unknown",
            "source_available_at": "unknown",
            "source_snapshot_id": None,
            "observation_revision_ids": None,
            "committed_at": None,
            "durable_receipt": "not_created",
        },
    }


def _direct_two_decimal_number(value: object, field_name: str) -> float:
    """Render one finite field using the legacy K-line numeric convention."""
    decimal_value = _direct_finite_decimal(value, field_name)
    try:
        rounded = decimal_value.quantize(_TWO_DECIMAL_PLACES, rounding=ROUND_HALF_UP)
        rendered = float(rounded)
    except (InvalidOperation, OverflowError, ValueError) as exc:
        raise LegacyKlineBridgeError("KLINE_FIELD_QUALITY_INVALID") from exc
    if not isfinite(rendered) or Decimal(str(rendered)) != rounded:
        raise LegacyKlineBridgeError("KLINE_FIELD_QUALITY_INVALID")
    return 0.0 if rendered == 0 else rendered


def _direct_safe_integer(value: object, field_name: str) -> int:
    """Render a non-negative JSON-safe integer quantity."""
    decimal_value = _direct_finite_decimal(value, field_name)
    if decimal_value != decimal_value.to_integral_value():
        raise LegacyKlineBridgeError("KLINE_VOLUME_INVALID")
    rendered = int(decimal_value)
    if rendered < 0 or rendered > _MAX_SAFE_JSON_INTEGER:
        raise LegacyKlineBridgeError("KLINE_VOLUME_INVALID")
    return rendered


def _direct_finite_decimal(value: object, field_name: str) -> Decimal:
    if not is_usable_field_value(field_name, value):
        raise LegacyKlineBridgeError("KLINE_FIELD_QUALITY_INVALID")
    try:
        normalized = normalize_numeric_field_value(value, field_name=field_name)
        if normalized is None:
            raise LegacyKlineBridgeError("KLINE_FIELD_QUALITY_INVALID")
        decimal_value = Decimal(str(normalized))
    except (FieldQualityValueError, InvalidOperation, ValueError) as exc:
        raise LegacyKlineBridgeError("KLINE_FIELD_QUALITY_INVALID") from exc
    if not decimal_value.is_finite():
        raise LegacyKlineBridgeError("KLINE_FIELD_QUALITY_INVALID")
    return decimal_value


@router.get(
    "/market-instruments/lookup",
    summary="Lookup aggregated market instrument data",
    response_model=None,
)
async def lookup_market_instrument(
    symbol: str = Query(..., min_length=1, description="Instrument code, e.g. 000001 or RB2510"),
    asset_type: MarketAssetType = Query("stock", description="Instrument type"),
    start_date: date | None = Query(None, description="Start date YYYY-MM-DD"),
    end_date: date | None = Query(None, description="End date YYYY-MM-DD"),
    period: str = Query("daily", description="Period: daily/weekly/monthly"),
    market: str | None = Query(None, description="Futures market, default CF"),
    refresh_online: bool = Query(
        False,
        description="Deprecated legacy online refresh; use the v2 local-first query endpoint",
    ),
    current_user: typing.Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: MarketInstrumentService = Depends(get_market_instrument_service),
    access_authorizer: MarketDataAccessAuthorizer = Depends(get_market_data_access_authorizer),
    query_contracts: LegacyMarketDataQueryContractResolver = Depends(
        get_legacy_market_data_query_contract_resolver
    ),
) -> typing.Any:
    """Return a normalized snapshot, historical rows, and derived indicators."""
    try:
        payload = await service.lookup(
            asset_type=asset_type,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
            market=market,
            refresh_online=refresh_online,
        )
        # The legacy shape remains authoritative until the v2 rollout is
        # explicitly enabled and its catalog/master-data prerequisites are
        # satisfied.  Absence of this optional field is a safe instruction for
        # clients to continue using the existing compatibility endpoint.
        try:
            principal = await access_authorizer.principal_for_user(current_user)
            access_authorizer.require_read_data(principal=principal)
            capabilities = await evaluate_market_data_capabilities(db)
        except MarketDataAuthorizationError:
            # Keep the legacy lookup's historic authorization semantics, but
            # never mint or disclose a v2 catalog/identity template to a
            # caller without the independent data-read entitlement.
            contract = None
        except SQLAlchemyError:
            # A current-principal check is optional on this legacy route. Its
            # metadata outage must not invalidate an already completed
            # compatibility lookup, and must never cause a v2 disclosure.
            logger.warning("market-data v2 compatibility authorization unavailable")
            contract = None
        else:
            if not capabilities.response.query_v2_enabled:
                contract = None
            else:
                try:
                    contract = await query_contracts.resolve(
                        asset_type=asset_type,
                        symbol=symbol,
                        period=period,
                    )
                except DatasetContractRegistryError:
                    # The derived family is not executable. Keep the legacy
                    # response usable without advertising a generic v2 route.
                    contract = None
                except SQLAlchemyError:
                    # The optional bridge must never turn a completed legacy
                    # lookup into a 500. Its metadata outage omits only the
                    # optional v2 template.
                    logger.warning("market-data v2 compatibility contract unavailable")
                    contract = None
            if contract is not None:
                # A legacy lookup may advertise a v2 template only with an
                # explicit echo of the exact symbol and canonical identity
                # used to mint it.  Do not let a mixed or malformed metadata
                # response turn an otherwise complete legacy read into a 500,
                # or advertise a contract that the client cannot safely bind.
                contract_request = contract.get("request") if isinstance(contract, dict) else None
                contract_identity = (
                    contract_request.get("identity") if isinstance(contract_request, dict) else None
                )
                canonical_id = (
                    contract_identity.get("canonical_id")
                    if isinstance(contract_identity, dict)
                    else None
                )
                if not isinstance(canonical_id, str) or not canonical_id.strip():
                    logger.warning("market-data v2 compatibility contract malformed")
                else:
                    payload["query_contract"] = contract
                    # The frontend compares all three values before allowing
                    # this compatibility bridge to issue a v2 query, so a
                    # stale/mixed legacy payload cannot redirect a current
                    # symbol to a different canonical instrument.
                    payload["query_contract_symbol"] = symbol.strip()
                    payload["query_contract_canonical_id"] = canonical_id
        return payload
    except LegacyMarketDataOnlineRefreshDisabledError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/market-instruments/options", summary="List selectable market instruments", response_model=None
)
async def list_market_instrument_options(
    asset_type: MarketAssetType = Query("stock", description="Instrument type"),
    search: str = Query("", description="Search by symbol, name, market, or variety"),
    limit: int = Query(80, ge=1, le=200, description="Maximum number of options"),
    current_user: typing.Any = Depends(get_current_user),
    service: MarketInstrumentService = Depends(get_market_instrument_service),
) -> typing.Any:
    """Return selectable instruments for the market data query page."""
    try:
        return await service.list_instruments(
            asset_type=asset_type,
            search=search,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
