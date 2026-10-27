"""Risk analytics API routes."""

import math
import typing
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.data.queries import evaluate_market_data_capabilities
from app.api.deps import get_current_user
from app.config import get_settings
from app.db.database import get_db
from app.schemas.risk_analytics import (
    BenchmarkMetricsResult,
    BenchmarkReturnsResult,
    KellyResult,
    MarketRegimeResult,
    PositionSizingResult,
    StressTestRequest,
    StressTestResult,
    VarCvarResult,
)
from app.services.backtest_service import BacktestService
from app.services.market_data.access import (
    MarketDataAccessAuthorizer,
    MarketDataAuthorizationError,
    MarketDataQueryAccess,
)
from app.services.market_data.opendata_credentials import OpendataCredentialsError
from app.services.market_data.source_policy import MarketDataSourcePolicyError
from app.services.market_regime import MarketRegimeDetector
from app.services.risk_analytics import (
    BenchmarkMetricsService,
    BenchmarkService,
    KellyService,
    PositionSizingService,
    StressTestService,
    VarCvarService,
)
from app.services.risk_analytics.benchmark import BENCHMARK_SYMBOLS
from app.services.risk_analytics.opendata_index_benchmark import (
    OPENDATA_INDEX_DAILY_POLICY_ID,
    OPENDATA_INDEX_DAILY_ROUTE_ID,
    OpenDataIndexBenchmarkError,
    OpenDataIndexBenchmarkReader,
)

router = APIRouter(prefix="/risk-analytics", tags=["Risk Analytics"])


@lru_cache
def get_backtest_service() -> BacktestService:
    """Return cached backtest service dependency."""
    return BacktestService()


@lru_cache
def get_var_cvar_service() -> VarCvarService:
    """Return cached VaR/CVaR service dependency."""
    return VarCvarService()


@lru_cache
def get_stress_test_service() -> StressTestService:
    """Return cached stress test service dependency."""
    return StressTestService()


@lru_cache
def get_kelly_service() -> KellyService:
    """Return cached Kelly service dependency."""
    return KellyService()


@lru_cache
def get_position_sizing_service() -> PositionSizingService:
    """Return cached position sizing service dependency."""
    return PositionSizingService()


@lru_cache
def get_benchmark_service() -> BenchmarkService:
    """Return cached benchmark service dependency."""
    return BenchmarkService()


@lru_cache
def get_benchmark_metrics_service() -> BenchmarkMetricsService:
    """Return cached benchmark metrics service dependency."""
    return BenchmarkMetricsService()


@lru_cache
def get_market_regime_detector() -> MarketRegimeDetector:
    """Return cached market regime detector dependency."""
    return MarketRegimeDetector()


@router.get(
    "/var-cvar/{backtest_id}",
    response_model=VarCvarResult,
    summary="Calculate VaR/CVaR for a backtest",
)
async def get_var_cvar(
    backtest_id: str,
    method: Literal["historical", "parametric", "monte_carlo"] = "historical",
    current_user: typing.Any = Depends(get_current_user),
    backtest_service: BacktestService = Depends(get_backtest_service),
    var_cvar_service: VarCvarService = Depends(get_var_cvar_service),
) -> VarCvarResult:
    """Calculate VaR/CVaR from a completed backtest equity curve."""
    result = await backtest_service.get_result(backtest_id, user_id=current_user.sub)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backtest result not found",
        )

    calculation = var_cvar_service.calculate_from_equity_curve(result.equity_curve, method=method)
    calculation.backtest_id = backtest_id
    return calculation


@router.post(
    "/stress-test/{backtest_id}",
    response_model=StressTestResult,
    summary="Run stress scenarios for a backtest",
)
async def run_stress_test(
    backtest_id: str,
    request: StressTestRequest,
    current_user: typing.Any = Depends(get_current_user),
    backtest_service: BacktestService = Depends(get_backtest_service),
    stress_test_service: StressTestService = Depends(get_stress_test_service),
) -> StressTestResult:
    """Run stress scenarios against a completed backtest equity curve."""
    result = await backtest_service.get_result(backtest_id, user_id=current_user.sub)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backtest result not found",
        )

    calculation = stress_test_service.run_scenarios(
        equity_curve=result.equity_curve,
        equity_dates=result.equity_dates,
        scenarios=request.scenarios,
    )
    calculation.backtest_id = backtest_id
    return calculation


@router.get(
    "/kelly/{backtest_id}",
    response_model=KellyResult,
    summary="Calculate Kelly position sizing for a backtest",
)
async def get_kelly(
    backtest_id: str,
    current_user: typing.Any = Depends(get_current_user),
    backtest_service: BacktestService = Depends(get_backtest_service),
    kelly_service: KellyService = Depends(get_kelly_service),
) -> KellyResult:
    """Calculate Kelly position sizing recommendations from backtest trades."""
    result = await backtest_service.get_result(backtest_id, user_id=current_user.sub)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backtest result not found",
        )

    calculation = kelly_service.calculate(result.trades)
    calculation.backtest_id = backtest_id
    return calculation


@router.get(
    "/position-sizing/{backtest_id}",
    response_model=PositionSizingResult,
    summary="Calculate volatility-targeted position sizing for a backtest",
)
async def get_position_sizing(
    backtest_id: str,
    target_volatility: float = 0.15,
    max_position: float = 1.0,
    min_observations: int = 5,
    current_user: typing.Any = Depends(get_current_user),
    backtest_service: BacktestService = Depends(get_backtest_service),
    position_sizing_service: PositionSizingService = Depends(get_position_sizing_service),
) -> PositionSizingResult:
    """Calculate volatility target position sizing from backtest equity curve."""
    result = await backtest_service.get_result(backtest_id, user_id=current_user.sub)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backtest result not found",
        )

    calculation = position_sizing_service.calculate_for_equity_curve(
        result.equity_curve,
        target_volatility=target_volatility,
        max_position=max_position,
        min_observations=min_observations,
    )
    calculation.backtest_id = backtest_id
    return calculation


@router.get(
    "/benchmark/{benchmark_id}",
    response_model=BenchmarkReturnsResult,
    summary="Get benchmark return series",
)
async def get_benchmark_returns(
    benchmark_id: str,
    start_date: str,
    end_date: str,
    current_user: typing.Any = Depends(get_current_user),
    benchmark_service: BenchmarkService = Depends(get_benchmark_service),
    db: AsyncSession = Depends(get_db),
) -> BenchmarkReturnsResult:
    """Fetch benchmark prices and derive return series."""
    settings = get_settings()
    if _uses_opendata_risk_benchmark(settings, benchmark_id):
        reader = await _authorized_opendata_index_benchmark_reader(
            db=db,
            current_user=current_user,
            purpose="display",
            settings=settings,
        )
        await db.rollback()
        try:
            return await benchmark_service.get_benchmark_returns(
                benchmark_id,
                start_date,
                end_date,
                data_fetcher=_opendata_fetcher(reader, benchmark_id),
            )
        except MarketDataAuthorizationError as exc:
            raise _market_data_authorization_http_error(exc) from exc
        except OpenDataIndexBenchmarkError as exc:
            return _opendata_degraded_benchmark(benchmark_id, start_date, end_date, exc.code)
    return await benchmark_service.get_benchmark_returns(benchmark_id, start_date, end_date)


@router.get(
    "/benchmark-metrics/{backtest_id}",
    response_model=BenchmarkMetricsResult,
    summary="Calculate beta from date-aligned benchmark returns",
)
async def get_benchmark_metrics(
    backtest_id: str,
    benchmark_id: str = "hs300",
    risk_free_rate: float = Query(default=0.0, ge=-1.0, le=1.0),
    current_user: typing.Any = Depends(get_current_user),
    backtest_service: BacktestService = Depends(get_backtest_service),
    benchmark_service: BenchmarkService = Depends(get_benchmark_service),
    benchmark_metrics_service: BenchmarkMetricsService = Depends(get_benchmark_metrics_service),
    db: AsyncSession = Depends(get_db),
) -> BenchmarkMetricsResult:
    """Calculate beta from exactly aligned return intervals."""
    result = await backtest_service.get_result(backtest_id, user_id=current_user.sub)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backtest result not found",
        )

    if not math.isfinite(risk_free_rate) or not -1.0 <= risk_free_rate <= 1.0:
        metrics = BenchmarkMetricsResult(
            status="degraded",
            benchmark_id=benchmark_id,
            risk_free_rate=0.0,
            reason="invalid_risk_free_rate",
            backtest_id=backtest_id,
        )
        return metrics

    try:
        strategy_observations = benchmark_metrics_service.return_observations_from_equity_curve(
            result.equity_curve,
            result.equity_dates,
        )
    except ValueError as exc:
        return BenchmarkMetricsResult(
            status="degraded",
            benchmark_id=benchmark_id,
            risk_free_rate=risk_free_rate,
            reason=str(exc),
            backtest_id=backtest_id,
        )
    if not strategy_observations:
        return BenchmarkMetricsResult(
            status="degraded",
            benchmark_id=benchmark_id,
            risk_free_rate=risk_free_rate,
            reason="insufficient_strategy_history",
            backtest_id=backtest_id,
        )

    benchmark_start_date = strategy_observations[0].start_date
    benchmark_end_date = strategy_observations[-1].end_date
    settings = get_settings()
    if _uses_opendata_risk_benchmark(settings, benchmark_id):
        reader = await _authorized_opendata_index_benchmark_reader(
            db=db,
            current_user=current_user,
            purpose="backtest",
            settings=settings,
        )
        await db.rollback()
        try:
            benchmark = await benchmark_service.get_benchmark_returns(
                benchmark_id,
                benchmark_start_date,
                benchmark_end_date,
                data_fetcher=_opendata_fetcher(reader, benchmark_id),
            )
        except MarketDataAuthorizationError as exc:
            raise _market_data_authorization_http_error(exc) from exc
        except OpenDataIndexBenchmarkError as exc:
            return BenchmarkMetricsResult(
                status="degraded",
                benchmark_id=benchmark_id,
                risk_free_rate=risk_free_rate,
                reason=exc.code,
                backtest_id=backtest_id,
            )
    else:
        benchmark = await benchmark_service.get_benchmark_returns(
            benchmark_id,
            benchmark_start_date,
            benchmark_end_date,
        )
    if benchmark.status != "ok":
        metrics = BenchmarkMetricsResult(
            status="degraded",
            benchmark_id=benchmark_id,
            risk_free_rate=risk_free_rate,
            reason=benchmark.reason,
            backtest_id=backtest_id,
        )
        return metrics
    metrics = benchmark_metrics_service.calculate(
        benchmark_id=benchmark_id,
        strategy_return_observations=strategy_observations,
        benchmark_return_observations=benchmark.return_observations,
        risk_free_rate=risk_free_rate,
    )
    metrics.backtest_id = backtest_id
    return metrics


def _uses_opendata_risk_benchmark(settings: object, benchmark_id: str) -> bool:
    """Select OpenData only for the three fixed A-share indices and explicit opt-in."""
    return bool(
        getattr(settings, "MARKET_DATA_RISK_BENCHMARK_OPENDATA_ENABLED", False)
        and benchmark_id in {"hs300", "csi500", "csi800"}
    )


async def _authorized_opendata_index_benchmark_reader(
    *,
    db: AsyncSession,
    current_user: object,
    purpose: str,
    settings: object,
) -> OpenDataIndexBenchmarkReader:
    """Build the reader only after current user, route, and source checks pass."""
    authorizer = MarketDataAccessAuthorizer(db)
    try:
        principal = await authorizer.principal_for_user(current_user)
        authorizer.require_read_data(principal=principal)
    except MarketDataAuthorizationError as exc:
        raise _market_data_authorization_http_error(exc) from exc

    try:
        capabilities = await evaluate_market_data_capabilities(db, settings=settings)
    except (SQLAlchemyError, OpendataCredentialsError, MarketDataSourcePolicyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "OPENDATA_RISK_BENCHMARK_CAPABILITY_UNAVAILABLE"},
        ) from exc
    if not capabilities.response.online_fetch_enabled or not capabilities.route_is_effective(
        OPENDATA_INDEX_DAILY_ROUTE_ID
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "OPENDATA_RISK_BENCHMARK_ROUTE_UNAVAILABLE"},
        )

    try:
        policy = capabilities.effective_source_policies.resolve(OPENDATA_INDEX_DAILY_POLICY_ID)
    except MarketDataSourcePolicyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "OPENDATA_RISK_BENCHMARK_POLICY_UNAVAILABLE"},
        ) from exc
    route = next(
        (
            candidate
            for candidate in policy.routes
            if candidate.route_id == OPENDATA_INDEX_DAILY_ROUTE_ID
        ),
        None,
    )
    if route is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "OPENDATA_RISK_BENCHMARK_ROUTE_UNAVAILABLE"},
        )

    try:
        access = MarketDataQueryAccess(principal=principal, authorizer=authorizer)
        grant = await authorizer.authorize_policy(
            principal=principal,
            policy=policy,
            routes=(route,),
            asset_type="index",
            market="CN-SSE",
            purpose=purpose,
        )
        return OpenDataIndexBenchmarkReader(
            access=access,
            policy=policy,
            route=route,
            grant=grant,
        )
    except MarketDataAuthorizationError as exc:
        raise _market_data_authorization_http_error(exc) from exc
    except OpenDataIndexBenchmarkError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "OPENDATA_RISK_BENCHMARK_ROUTE_CONTRACT_INVALID"},
        ) from exc


def _opendata_fetcher(
    reader: OpenDataIndexBenchmarkReader,
    benchmark_id: str,
):
    """Bind one public benchmark selector to the reader's fixed allowlist."""

    async def fetch(symbol: str, start_date: str, end_date: str) -> list[dict[str, object]]:
        return await reader.fetch_prices(benchmark_id, symbol, start_date, end_date)

    return fetch


def _opendata_degraded_benchmark(
    benchmark_id: str,
    start_date: str,
    end_date: str,
    reason: str,
) -> BenchmarkReturnsResult:
    """Keep provider failures in the risk API's existing degraded-result shape."""
    return BenchmarkReturnsResult(
        status="degraded",
        benchmark_id=benchmark_id,
        symbol=BENCHMARK_SYMBOLS.get(benchmark_id),
        start_date=start_date,
        end_date=end_date,
        reason=reason,
    )


def _market_data_authorization_http_error(exc: MarketDataAuthorizationError) -> HTTPException:
    """Map current read/source denials to the same authenticated 403 boundary."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": exc.code},
    )


@router.get(
    "/market-regime/{backtest_id}",
    response_model=MarketRegimeResult,
    summary="Classify market regime for a backtest",
)
async def get_market_regime(
    backtest_id: str,
    current_user: typing.Any = Depends(get_current_user),
    backtest_service: BacktestService = Depends(get_backtest_service),
    detector: MarketRegimeDetector = Depends(get_market_regime_detector),
) -> MarketRegimeResult:
    """Classify volatility and trend regime from backtest equity curve."""
    result = await backtest_service.get_result(backtest_id, user_id=current_user.sub)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backtest result not found",
        )
    regime = detector.detect(result.equity_curve)
    regime.backtest_id = backtest_id
    return regime
