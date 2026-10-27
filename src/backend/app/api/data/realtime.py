"""
Realtime market data API routes.

Supports realtime tick subscription and WebSocket streaming across brokers.
"""

import asyncio
import logging
import typing
from dataclasses import dataclass
from math import isfinite

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.data.base as market_data_base
from app.api.data.queries import build_market_data_query_service, evaluate_market_data_capabilities
from app.api.deps import get_current_user, get_websocket_current_user
from app.config import get_settings
from app.db.database import async_session_maker
from app.schemas.realtime_data import (
    RealtimeTickSubscribeRequest,
    RealtimeTickUnsubscribeRequest,
)
from app.services.market_data.access import (
    MarketDataAccessAuthorizer,
    MarketDataAuthorizationError,
    MarketDataQueryAccess,
)
from app.services.market_data.capability_ledger import MarketDataCapabilityEvaluation
from app.services.market_data.legacy_contract import LegacyMarketDataQueryContractResolver
from app.services.market_data.legacy_kline_projection import (
    LegacyKlineBridgeError,
    LegacyKlineInputError,
    parse_legacy_kline_request,
)
from app.services.market_data.query_service import (
    MarketDataQueryService,
    MarketDataQueryServiceError,
)
from app.services.market_data.source_policy import MarketDataSourcePolicyError
from app.services.market_data.store import MarketDataStoreError
from app.services.realtime_data_service import RealTimeDataService
from app.websocket_manager import MessageType
from app.websocket_manager import manager as ws_manager

logger = logging.getLogger(__name__)

router = APIRouter()
_A_SHARE_SHARES_PER_LOT = 100


@dataclass(frozen=True, slots=True)
class _OpenDataHistoricalContext:
    """Authorized request-scoped objects for the direct A-share daily route."""

    db: AsyncSession
    access: MarketDataQueryAccess
    capabilities: MarketDataCapabilityEvaluation
    service: MarketDataQueryService
    query_contracts: LegacyMarketDataQueryContractResolver


def get_realtime_data_service() -> typing.Any:
    """Dependency injection for RealTimeDataService.

    Returns:
        RealTimeDataService: An instance of the realtime data service.
    """
    return RealTimeDataService()


async def build_opendata_historical_context(
    current_user: typing.Any,
    db: AsyncSession,
) -> _OpenDataHistoricalContext:
    """Build the current authorization and direct-query objects for one request."""
    access_authorizer = MarketDataAccessAuthorizer(db)
    try:
        principal = await access_authorizer.principal_for_user(current_user)
        access_authorizer.require_read_data(principal=principal)
    except MarketDataAuthorizationError as exc:
        raise HTTPException(status_code=403, detail={"code": exc.code}) from exc

    try:
        capabilities = await evaluate_market_data_capabilities(db)
        service = build_market_data_query_service(db, capabilities)
        query_contracts = market_data_base.build_legacy_market_data_query_contract_resolver(db)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "OPENDATA_CAPABILITY_UNAVAILABLE"},
        ) from exc

    return _OpenDataHistoricalContext(
        db=db,
        access=MarketDataQueryAccess(principal=principal, authorizer=access_authorizer),
        capabilities=capabilities,
        service=service,
        query_contracts=query_contracts,
    )


# ==================== Realtime Quote Subscription API ====================


@router.post("/ticks/subscribe", summary="Subscribe to realtime quotes", response_model=None)
async def subscribe_realtime_ticks(
    request: RealtimeTickSubscribeRequest,
    current_user: typing.Any = Depends(get_current_user),
    service: RealTimeDataService = Depends(get_realtime_data_service),
) -> typing.Any:
    """Subscribe to realtime tick data for specified symbols.

    Args:
        request: The subscription request containing broker_id and symbols list.
        current_user: The authenticated user.
        service: The realtime data service.

    Returns:
        A dictionary confirming subscription with symbols, broker_id, and status.
    """
    await service.subscribe_ticks(
        user_id=current_user.sub,
        broker_id=request.broker_id,
        symbols=request.symbols,
    )

    return {
        "symbols": request.symbols,
        "broker_id": request.broker_id,
        "status": "subscribed",
        "message": f"Subscribed to {len(request.symbols)} symbols for realtime quotes",
    }


@router.post("/ticks/unsubscribe", summary="Unsubscribe from realtime quotes", response_model=None)
async def unsubscribe_realtime_ticks(
    request: RealtimeTickUnsubscribeRequest,
    current_user: typing.Any = Depends(get_current_user),
    service: RealTimeDataService = Depends(get_realtime_data_service),
) -> typing.Any:
    """Unsubscribe from realtime tick data for specified symbols.

    Args:
        request: The unsubscription request containing broker_id and symbols list.
        current_user: The authenticated user.
        service: The realtime data service.

    Returns:
        A dictionary confirming unsubscription with symbols, broker_id, and status.
    """
    await service.unsubscribe_ticks(
        user_id=current_user.sub,
        broker_id=request.broker_id,
        symbols=request.symbols,
    )

    return {
        "symbols": request.symbols,
        "broker_id": request.broker_id,
        "status": "unsubscribed",
        "message": f"Unsubscribed from {len(request.symbols)} symbols",
    }


# ==================== Realtime Quote Data API ====================


@router.get("/ticks", summary="Get realtime quotes", response_model=None)
async def get_realtime_ticks(
    current_user: typing.Any = Depends(get_current_user),
    service: RealTimeDataService = Depends(get_realtime_data_service),
    broker_id: str | None = Query(None, description="Broker ID"),
    symbol: str | None = Query(None, description="Trading symbol"),
) -> typing.Any:
    """Get the latest tick data (single symbol or all subscribed symbols).

    Args:
        current_user: The authenticated user.
        service: The realtime data service.
        broker_id: Filter by broker ID.
        symbol: Get specific symbol data if provided.

    Returns:
        A dictionary containing tick data for the requested symbols.
    """
    if symbol:
        # Get single symbol quote
        tick_data = await service.get_tick(current_user.sub, broker_id, symbol)
        return {"tick": tick_data}
    else:
        # Get all subscribed symbols quotes
        symbols = await service.get_subscribed_symbols(current_user.sub, broker_id)
        ticks_data = await service.get_ticks(current_user.sub, broker_id, symbols)
        return {"ticks": ticks_data}


@router.get("/ticks/batch", summary="Batch get realtime quotes", response_model=None)
async def get_realtime_ticks_batch(
    current_user: typing.Any = Depends(get_current_user),
    service: RealTimeDataService = Depends(get_realtime_data_service),
    broker_id: str = Query(..., description="Broker ID"),
    symbols: str = Query(..., description="Comma-separated symbol list"),
) -> typing.Any:
    """Batch fetch tick data for a broker and comma-separated symbol list.

    Args:
        current_user: The authenticated user.
        service: The realtime data service.
        broker_id: The broker ID to fetch data from.
        symbols: Comma-separated list of symbols to fetch.

    Returns:
        A dictionary containing broker_id and list of tick data.
    """
    symbol_list = symbols.split(",")
    ticks = await service.get_ticks(current_user.sub, broker_id, symbol_list)

    return {
        "broker_id": broker_id,
        "ticks": ticks,
    }


# ==================== Historical Quote API ====================


@router.get("/ticks/historical", summary="Get historical quotes", response_model=None)
async def get_historical_ticks(
    http_request: Request,
    broker_id: str = Query(
        ..., description="Broker ID; use opendata when the OpenData route is enabled"
    ),
    symbol: str = Query(..., description="Trading symbol (e.g., BTC/USDT)"),
    start_date: str = Query(..., description="Start date (ISO 8601 format)"),
    end_date: str = Query(..., description="End date (ISO 8601 format)"),
    frequency: str = Query("1d", description="Data frequency; OpenData mode accepts only 1d"),
    current_user: typing.Any = Depends(get_current_user),
    service: RealTimeDataService = Depends(get_realtime_data_service),
) -> typing.Any:
    """Get historical tick data for a symbol.

    Args:
        broker_id: The broker ID to fetch data from.
        symbol: The trading symbol (e.g., BTC/USDT).
        start_date: Start date in ISO 8601 format.
        end_date: End date in ISO 8601 format.
        frequency: Data frequency (e.g., 1m, 5m, 1h, 1d).
        current_user: The authenticated user.
        service: The realtime data service.

    Returns:
        A dictionary containing symbol, frequency, ticks list, and total count.

    Raises:
        HTTPException: If the date selector or enabled OpenData contract is invalid.
    """
    if bool(getattr(get_settings(), "MARKET_DATA_OPENDATA_ENABLED", False)):
        try:
            async with async_session_maker() as db:
                opendata_context = await build_opendata_historical_context(current_user, db)
                return await _get_opendata_historical_ticks(
                    http_request=http_request,
                    broker_id=broker_id,
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    frequency=frequency,
                    context=opendata_context,
                )
        except HTTPException:
            raise
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "OPENDATA_QUERY_UNAVAILABLE"},
            ) from exc
        except Exception as exc:
            logger.warning("OpenData historical request setup failed")
            raise HTTPException(
                status_code=503,
                detail={"code": "OPENDATA_QUERY_UNAVAILABLE"},
            ) from exc

    from datetime import datetime

    # Validate date format
    try:
        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid date format: {e}"
        ) from e

    try:
        ticks = await service.get_historical_data(
            user_id=current_user.sub,
            broker_id=broker_id,
            symbol=symbol,
            start_date=start_dt,
            end_date=end_dt,
            frequency=frequency,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return {
        "symbol": symbol,
        "frequency": frequency,
        "ticks": ticks,
        "total": len(ticks),
    }


async def _get_opendata_historical_ticks(
    *,
    http_request: Request,
    broker_id: str,
    symbol: str,
    start_date: str,
    end_date: str,
    frequency: str,
    context: _OpenDataHistoricalContext,
) -> dict[str, typing.Any]:
    """Serve only the exact reviewed OpenData A-share daily contract.

    This route intentionally does not use ``RealTimeDataService``. That
    service is also consumed by risk analytics, so its shared AkShare-backed
    behavior remains untouched while this endpoint takes the direct REST path.
    """
    try:
        allowed_query_keys = {
            "broker_id",
            "symbol",
            "start_date",
            "end_date",
            "frequency",
        }
        query_keys = set(http_request.query_params.keys())
        if query_keys - allowed_query_keys or any(
            len(http_request.query_params.getlist(key)) != 1 for key in query_keys
        ):
            raise HTTPException(status_code=422, detail={"code": "OPENDATA_REQUEST_INVALID"})
        if broker_id != "opendata":
            raise HTTPException(
                status_code=422,
                detail={"code": "OPENDATA_BROKER_UNSUPPORTED"},
            )
        if frequency != "1d":
            raise HTTPException(
                status_code=422,
                detail={"code": "OPENDATA_FREQUENCY_UNSUPPORTED"},
            )

        try:
            request = parse_legacy_kline_request(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                period="daily",
            )
        except LegacyKlineInputError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "OPENDATA_REQUEST_INVALID"},
            ) from exc

        if not context.capabilities.response.query_v2_enabled:
            raise HTTPException(
                status_code=503,
                detail={"code": "OPENDATA_QUERY_V2_DISABLED"},
            )
        route_is_effective = getattr(context.capabilities, "route_is_effective", None)
        if not callable(route_is_effective) or not route_is_effective("opendata-stock-daily-v1"):
            raise HTTPException(
                status_code=503,
                detail={"code": "OPENDATA_ROUTE_NOT_EFFECTIVE"},
            )

        contract = await context.query_contracts.resolve(
            asset_type="stock",
            symbol=request.symbol,
            period="daily",
        )
        if contract is None:
            raise HTTPException(
                status_code=422,
                detail={"code": "OPENDATA_INSTRUMENT_UNSUPPORTED"},
            )
        direct_request = market_data_base._request_from_public_kline_contract(
            contract,
            request=request,
        )
        direct_result = await context.service.read_opendata_direct(
            direct_request,
            access=context.access,
        )
        projection = market_data_base._project_opendata_legacy_kline(
            direct_result,
            request=request,
        )
        ticks = _project_opendata_historical_legacy_ticks(direct_result, projection)
        return {
            "symbol": symbol,
            "frequency": frequency,
            "ticks": ticks,
            "total": len(ticks),
        }
    except HTTPException:
        await context.db.rollback()
        raise
    except MarketDataAuthorizationError as exc:
        await context.db.rollback()
        status_code = 403 if exc.code in market_data_base._KLINE_DATA_READ_DENIAL_CODES else 503
        raise HTTPException(status_code=status_code, detail={"code": exc.code}) from exc
    except (
        LegacyKlineBridgeError,
        MarketDataQueryServiceError,
        MarketDataSourcePolicyError,
        MarketDataStoreError,
    ) as exc:
        await context.db.rollback()
        raise HTTPException(
            status_code=503,
            detail={"code": getattr(exc, "code", "OPENDATA_QUERY_FAILED")},
        ) from exc
    except SQLAlchemyError as exc:
        await context.db.rollback()
        raise HTTPException(
            status_code=503,
            detail={"code": "OPENDATA_QUERY_UNAVAILABLE"},
        ) from exc
    except Exception as exc:
        await context.db.rollback()
        logger.warning("OpenData historical query failed with unexpected error")
        raise HTTPException(
            status_code=503,
            detail={"code": "OPENDATA_QUERY_FAILED"},
        ) from exc


def _project_opendata_historical_legacy_ticks(
    direct_result: market_data_base.OpendataDirectRead,
    projection: dict[str, object],
) -> list[dict[str, object]]:
    """Convert share-based OpenData bars to the old realtime ticks contract.

    ``stock_zh_a_hist`` reports integer lots, while the reviewed OpenData
    stock-daily contract reports shares.  Reject quantities that cannot be
    represented exactly in the old integer-lot field; truncation would hide
    source data and silently change its meaning. The legacy service defaulted
    a missing ``change_pct`` to zero, but this direct contract fails closed on
    missing/invalid change data rather than fabricating a neutral change.
    """
    projected_records = projection.get("records")
    if not isinstance(projected_records, list):
        raise LegacyKlineBridgeError("KLINE_DIRECT_RESULT_INVALID")
    observations = sorted(direct_result.fetch_result.observations, key=lambda item: item.event_at)
    if len(projected_records) != len(observations):
        raise LegacyKlineBridgeError("KLINE_DIRECT_RESULT_INVALID")

    ticks: list[dict[str, object]] = []
    for projected, observation in zip(projected_records, observations, strict=True):
        if not isinstance(projected, dict) or not isinstance(projected.get("date"), str):
            raise LegacyKlineBridgeError("KLINE_DIRECT_RESULT_INVALID")
        shares = market_data_base._direct_safe_integer(
            observation.fields.get("volume"),
            "volume",
        )
        if shares % _A_SHARE_SHARES_PER_LOT:
            raise LegacyKlineBridgeError("KLINE_VOLUME_UNIT_CONVERSION_INVALID")
        tick: dict[str, object] = {"date": projected["date"]}
        for field_name in ("open", "high", "low", "close"):
            tick[field_name] = _legacy_python_round_two_decimals(
                observation.fields.get(field_name),
                field_name=field_name,
            )
        tick["volume"] = shares // _A_SHARE_SHARES_PER_LOT
        tick["change"] = _legacy_python_round_two_decimals(
            observation.fields.get("change_pct"),
            field_name="change_pct",
        )
        ticks.append(tick)
    return ticks


def _legacy_python_round_two_decimals(value: object, *, field_name: str) -> float:
    """Match the previous ``round(float(value), 2)`` wire behavior."""
    decimal_value = market_data_base._direct_finite_decimal(value, field_name)
    try:
        rendered = round(float(decimal_value), 2)
    except (OverflowError, TypeError, ValueError) as exc:
        raise LegacyKlineBridgeError("KLINE_FIELD_QUALITY_INVALID") from exc
    if not isfinite(rendered):
        raise LegacyKlineBridgeError("KLINE_FIELD_QUALITY_INVALID")
    return rendered


# ==================== WebSocket Real-time Push ====================


@router.websocket("/ws/ticks/{broker_id}")
async def realtime_tick_websocket(
    websocket: WebSocket,
    broker_id: str,
) -> typing.Any:
    """WebSocket endpoint for realtime tick streaming.

    URL:
        ws://host/api/v1/realtime/ws/ticks/{broker_id}

    Args:
        websocket: The WebSocket connection instance.
        broker_id: The broker ID for which to stream tick data.
    """
    current_user, accepted_subprotocol = get_websocket_current_user(websocket)
    if current_user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    client_id = f"ws-realtime-client-{id(websocket)}"
    channel = f"ticks:{current_user.sub}:{broker_id}"

    # Establish connection
    await ws_manager.connect(websocket, channel, client_id, accepted_subprotocol)

    try:
        # Send initial message
        await ws_manager.send_to_task(
            channel,
            {
                "type": MessageType.CONNECTED,
                "broker_id": broker_id,
                "streaming_enabled": False,
                "push_mode": "keepalive_only",
                "message": "Realtime quote WebSocket connected; live tick push is not available yet",
            },
        )

        # Keep connection alive
        while True:
            await asyncio.sleep(1)

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Realtime tick WebSocket error for broker %s", broker_id)
    finally:
        ws_manager.disconnect(websocket, channel, client_id)
