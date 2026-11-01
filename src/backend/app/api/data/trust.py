"""Market data trust API routes."""

from __future__ import annotations

import typing

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.data.deps import require_authorized_market_data_read
from app.api.deps import get_current_user
from app.config import get_settings
from app.schemas.market_data_trust import (
    AssetSpecResponse,
    DataPrecheckRequest,
    DataPrecheckResponse,
    ExecutionModelResponse,
    MarketDataCoverageMatrixResponse,
    OpenDataStockDailyFreshnessResponse,
)
from app.services.asset_spec_service import get_asset_spec_service
from app.services.backtest.execution_model import ExecutionModel
from app.services.market_data_coverage_service import get_market_data_coverage_service
from app.services.market_data_precheck_service import get_market_data_precheck_service
from app.services.opendata_stock_daily_freshness import (
    OpenDataStockDailyFreshnessError,
    get_opendata_stock_daily_freshness_service,
)
from app.utils.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.get(
    "/opendata/stock-daily/freshness",
    response_model=OpenDataStockDailyFreshnessResponse,
    summary="Read OpenData stock daily freshness",
)
async def get_opendata_stock_daily_freshness(
    _: None = Depends(require_authorized_market_data_read),
) -> OpenDataStockDailyFreshnessResponse:
    """Proxy the fixed OpenData domain freshness route without local fallback."""
    if not bool(getattr(get_settings(), "MARKET_DATA_OPENDATA_ENABLED", False)):
        raise HTTPException(
            status_code=503,
            detail={"code": "OPENDATA_FRESHNESS_DISABLED"},
        )

    try:
        service = get_opendata_stock_daily_freshness_service()
        return await service.read()
    except OpenDataStockDailyFreshnessError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from None
    except Exception:
        # Do not leak upstream bodies, network exception strings, or credentials.
        raise HTTPException(
            status_code=503,
            detail={"code": "OPENDATA_FRESHNESS_UNAVAILABLE"},
        ) from None


def _service_unavailable(exc: Exception) -> HTTPException:
    """Map an internal trust-service failure to a stable public response."""
    del exc
    logger.exception("Market-data trust service failed")
    return HTTPException(
        status_code=503, detail="Market-data trust service is temporarily unavailable"
    )


@router.get(
    "/asset-specs/{symbol}",
    response_model=AssetSpecResponse,
    summary="Resolve asset specification",
)
async def get_asset_spec(
    symbol: str,
    asset_type: str | None = Query(None),
    current_user: typing.Any = Depends(get_current_user),
) -> typing.Any:
    del current_user
    try:
        return await get_asset_spec_service().get_or_create(symbol=symbol, asset_type=asset_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise _service_unavailable(exc) from exc


@router.get(
    "/asset-specs/{symbol}/execution-model",
    response_model=ExecutionModelResponse,
    summary="Resolve backtest execution model",
)
async def get_execution_model(
    symbol: str,
    asset_type: str | None = Query(None),
    current_user: typing.Any = Depends(get_current_user),
) -> typing.Any:
    del current_user
    try:
        spec = await get_asset_spec_service().get_or_create(symbol=symbol, asset_type=asset_type)
        payload = spec.model_dump(mode="python")
        return ExecutionModel.from_asset_spec(payload).to_response()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise _service_unavailable(exc) from exc


@router.get(
    "/coverage",
    response_model=MarketDataCoverageMatrixResponse,
    summary="List market data coverage matrix",
)
async def list_market_data_coverage(
    asset_type: str | None = Query(None),
    symbol: str | None = Query(None),
    timeframe: str | None = Query(None),
    provider: str | None = Query(None),
    refresh_if_empty: bool = Query(True),
    limit: int = Query(200, ge=1, le=1000),
    current_user: typing.Any = Depends(get_current_user),
) -> typing.Any:
    del current_user
    try:
        return await get_market_data_coverage_service().list_coverage(
            asset_type=asset_type,
            symbol=symbol,
            timeframe=timeframe,
            provider=provider,
            limit=limit,
            refresh_if_empty=refresh_if_empty,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise _service_unavailable(exc) from exc


@router.post(
    "/coverage/refresh-local",
    response_model=MarketDataCoverageMatrixResponse,
    summary="Refresh local CSV coverage matrix",
)
async def refresh_local_coverage(
    asset_type: str | None = Query(None),
    symbol: str | None = Query(None),
    timeframe: str | None = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    current_user: typing.Any = Depends(get_current_user),
) -> typing.Any:
    del current_user
    try:
        return await get_market_data_coverage_service().refresh_local_csv_coverage(
            asset_type=asset_type,
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise _service_unavailable(exc) from exc


@router.post(
    "/coverage/refresh-warehouse",
    response_model=MarketDataCoverageMatrixResponse,
    summary="Refresh AkShare warehouse coverage matrix",
)
async def refresh_warehouse_coverage(
    asset_type: str | None = Query(None),
    symbol: str | None = Query(None),
    timeframe: str | None = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    current_user: typing.Any = Depends(get_current_user),
) -> typing.Any:
    del current_user
    try:
        return await get_market_data_coverage_service().refresh_warehouse_coverage(
            asset_type=asset_type,
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise _service_unavailable(exc) from exc


@router.post(
    "/precheck",
    response_model=DataPrecheckResponse,
    summary="Run market data precheck for a backtest",
)
async def run_data_precheck(
    request: DataPrecheckRequest,
    current_user: typing.Any = Depends(get_current_user),
) -> typing.Any:
    del current_user
    try:
        return await get_market_data_precheck_service().precheck(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise _service_unavailable(exc) from exc
