"""After-close SSE 50 signal batch with durable run ownership and no execution side effects."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db.database import async_session_maker
from app.models.stock_signal import StockSignalPrediction, StockSignalRun
from app.services.market_instrument import MarketInstrumentService
from app.services.stock_analysis.data_collector import StockAnalysisDataCollector
from app.services.stock_signal.calendar import TradingCalendar
from app.services.stock_signal.decision_policy import SignalPolicy
from app.services.stock_signal.opendata_sse50_benchmark import OpenDataSse50BenchmarkReader
from app.services.stock_signal.quality import DataQualityGate
from app.services.stock_signal.service import StockSignalService
from app.services.stock_signal.universe import (
    PointInTimeSse50UniverseProvider,
    Sse50UniverseMemberEvidence,
    Sse50UniversePITSnapshot,
    Sse50UniverseProvider,
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SSE50_DECISION_TIME = time(19, 10)
_SSE50_RUNTIME_CUTOFF_POLICY = "sse50-runtime-after-close-asia-shanghai-v1"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _digest(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _shanghai_today() -> date:
    """Return the current business date in the exchange's local timezone."""
    return datetime.now(_SHANGHAI).date()


@dataclass(frozen=True)
class _ResolvedUniverse:
    members: list[dict[str, str]]
    provenance: dict[str, Any]
    snapshot_sha256: str


class Sse50SignalBatchRunner:
    """Generate one public, auditable SSE 50 snapshot for a completed session."""

    source = "nightly_sse50"
    universe_code = "SSE50"

    def __init__(
        self,
        *,
        calendar: TradingCalendar | None = None,
        universe: Sse50UniverseProvider | PointInTimeSse50UniverseProvider | None = None,
    ) -> None:
        settings = get_settings()
        self.settings = settings
        self.calendar = calendar or TradingCalendar()
        self.universe = universe or Sse50UniverseProvider()
        self.policy = SignalPolicy(
            round_trip_cost_bps=float(settings.STOCK_SIGNAL_ROUND_TRIP_COST_BPS or 0.0),
            buy_success_threshold_bps=float(settings.STOCK_SIGNAL_BUY_SUCCESS_THRESHOLD_BPS or 0.0),
            sell_success_threshold_bps=float(
                settings.STOCK_SIGNAL_SELL_SUCCESS_THRESHOLD_BPS or 0.0
            ),
        )
        self.quality_gate = DataQualityGate(
            min_history_bars=settings.STOCK_SIGNAL_MIN_HISTORY_BARS,
            max_financial_age_days=settings.STOCK_SIGNAL_MAX_FINANCIAL_AGE_DAYS,
            max_news_age_days=settings.STOCK_SIGNAL_MAX_NEWS_AGE_DAYS,
        )

    def configuration_ready(self) -> bool:
        universe = str(getattr(self.settings, "STOCK_SIGNAL_UNIVERSE", "sse50") or "").lower()
        return universe == "sse50" and all(
            value is not None
            for value in (
                self.settings.STOCK_SIGNAL_ROUND_TRIP_COST_BPS,
                self.settings.STOCK_SIGNAL_BUY_SUCCESS_THRESHOLD_BPS,
                self.settings.STOCK_SIGNAL_SELL_SUCCESS_THRESHOLD_BPS,
            )
        )

    async def run(self, *, as_of_date: date | None = None) -> StockSignalRun | None:
        """Run only on an official exchange date; never submit an order."""
        business_today = _shanghai_today()
        target_date = as_of_date or business_today
        if target_date < business_today:
            raise RuntimeError("historical_sse50_signal_replay_unavailable")
        if target_date > business_today:
            raise RuntimeError("future_sse50_signal_date_not_supported")
        if not self.configuration_ready():
            raise RuntimeError("stock_signal_evaluation_configuration_incomplete")
        self._require_shanghai_timezone()
        if not await self.calendar.is_trading_day(target_date):
            return None
        self._require_after_close(_now().astimezone(_SHANGHAI))
        next_trading_date = await self.calendar.next_trading_day(target_date)
        if next_trading_date is None:
            raise RuntimeError("next_trading_date_unavailable")
        universe = await self._resolve_universe(target_date, current_business_date=business_today)
        run, claimed = await self._claim_run(target_date, universe)
        if not claimed:
            return run

        semaphore = asyncio.Semaphore(self.settings.STOCK_SIGNAL_MAX_CONCURRENCY)

        async def process(member: dict[str, str]) -> tuple[str, str | None]:
            async with semaphore:
                return await self._process_member(
                    run_id=run.id,
                    member=member,
                    as_of_date=target_date,
                    next_trading_date=next_trading_date,
                )

        results = await asyncio.gather(
            *(process(member) for member in universe.members), return_exceptions=True
        )
        created = eligible = degraded = failed = 0
        errors: dict[str, str] = {}
        for member, result in zip(universe.members, results, strict=True):
            if isinstance(result, BaseException):
                failed += 1
                errors[member["symbol"]] = f"{type(result).__name__}:{result}"
                continue
            status, error = result
            if error:
                failed += 1
                errors[member["symbol"]] = error
                continue
            created += 1
            if status == "eligible":
                eligible += 1
            else:
                degraded += 1
        async with async_session_maker() as session:
            persisted = await session.get(StockSignalRun, run.id)
            if persisted is None:
                raise RuntimeError("stock_signal_run_lost")
            persisted.created_count = created
            persisted.eligible_count = eligible
            persisted.degraded_count = degraded
            persisted.failed_count = failed
            persisted.error_summary_json = errors
            persisted.status = "completed" if created else "failed"
            persisted.finished_at = _now()
            await session.commit()
            await session.refresh(persisted)
            return persisted

    async def _claim_run(
        self, as_of_date: date, universe: _ResolvedUniverse
    ) -> tuple[StockSignalRun, bool]:
        run_key = _digest(
            {
                "source": self.source,
                "universe_code": self.universe_code,
                "as_of_date": as_of_date.isoformat(),
                "feature_version": "ohlcv-v1",
                "policy_version": self.policy.decision_policy_version,
                "model_version": self.policy.model_version,
                "universe_snapshot_sha256": universe.snapshot_sha256,
            }
        )
        async with async_session_maker() as session:
            existing = await session.scalar(
                select(StockSignalRun).where(StockSignalRun.run_key == run_key)
            )
            if existing is not None:
                return existing, False
            run = StockSignalRun(
                run_key=run_key,
                owner_scope="system",
                source=self.source,
                universe_code=self.universe_code,
                as_of_date=as_of_date,
                scheduled_for_at=_now(),
                started_at=_now(),
                status="running",
                expected_count=len(universe.members),
                universe_snapshot_json=universe.members,
                config_snapshot_json={
                    "max_concurrency": self.settings.STOCK_SIGNAL_MAX_CONCURRENCY,
                    "policy": self.policy.snapshot(),
                    "universe": universe.provenance,
                },
            )
            try:
                async with session.begin_nested():
                    session.add(run)
                    await session.flush()
            except IntegrityError:
                existing = await session.scalar(
                    select(StockSignalRun).where(StockSignalRun.run_key == run_key)
                )
                if existing is not None:
                    return existing, False
                raise
            await session.commit()
            await session.refresh(run)
            return run, True

    async def _resolve_universe(
        self, as_of_date: date, *, current_business_date: date | None = None
    ) -> _ResolvedUniverse:
        """Resolve a complete current or evidence-backed point-in-time membership set.

        Current-date runs may use either a current-only source or a provider
        that supplies membership evidence. Historical runs remain disabled until
        the signal and market-data layers can preserve the same point-in-time
        decision and availability timestamps end to end.
        """
        today = current_business_date or _shanghai_today()
        if as_of_date < today:
            raise RuntimeError("historical_sse50_signal_replay_unavailable")
        if as_of_date > today:
            raise RuntimeError("future_sse50_signal_date_not_supported")
        self._require_shanghai_timezone()
        known_by = _now().astimezone(_SHANGHAI)
        self._require_after_close(known_by)
        resolver = getattr(self.universe, "resolve_pit", None)
        if callable(resolver):
            resolution = await resolver(as_of_date=as_of_date, known_by=known_by)
            return self._prepare_pit_universe(
                resolution,
                as_of_date,
                known_by,
                cutoff_policy=_SSE50_RUNTIME_CUTOFF_POLICY,
            )

        members_loader = getattr(self.universe, "members", None)
        if not callable(members_loader):
            raise RuntimeError("sse50_universe_unavailable")
        raw_members = await members_loader()
        members = self._normalize_members(raw_members)
        source = str(getattr(self.universe, "source", "injected.current_only") or "").strip()
        if not source:
            raise RuntimeError("sse50_universe_source_missing")
        identity = {
            "temporal_scope": "current_only",
            "decision_cutoff_policy": _SSE50_RUNTIME_CUTOFF_POLICY,
            "source": source,
            "members": members,
        }
        observed_at = _now().isoformat()
        return _ResolvedUniverse(
            members=members,
            snapshot_sha256=_digest(identity),
            provenance={
                "temporal_scope": "current_only",
                "point_in_time_status": "UNVERIFIED",
                "source": source,
                "target_date": as_of_date.isoformat(),
                "decision_cutoff_policy": _SSE50_RUNTIME_CUTOFF_POLICY,
                "observed_at": observed_at,
                "snapshot_sha256": _digest(identity),
            },
        )

    @classmethod
    def _prepare_pit_universe(
        cls,
        resolution: Any,
        as_of_date: date,
        known_by: datetime,
        *,
        cutoff_policy: str,
    ) -> _ResolvedUniverse:
        if not isinstance(resolution, Sse50UniversePITSnapshot):
            raise RuntimeError("sse50_universe_pit_evidence_invalid")
        source = cls._required_text(resolution.source)
        snapshot_version = cls._required_text(resolution.snapshot_version)
        snapshot_evidence_ref = cls._required_text(resolution.evidence_ref)
        if not isinstance(resolution.members, tuple) or len(resolution.members) != 50:
            raise RuntimeError("sse50_universe_pit_member_count_invalid")

        rows: list[tuple[Sse50UniverseMemberEvidence, dict[str, str]]] = []
        seen: set[str] = set()
        for item in resolution.members:
            if not isinstance(item, Sse50UniverseMemberEvidence):
                raise RuntimeError("sse50_universe_pit_evidence_invalid")
            symbol = cls._required_text(item.symbol)
            name = cls._required_text(item.name)
            cls._required_text(item.evidence_ref)
            if not re.fullmatch(r"\d{6}\.(?:SH|SZ)", symbol) or symbol in seen:
                raise RuntimeError("sse50_universe_pit_member_identity_invalid")
            seen.add(symbol)
            if type(item.valid_from) is not date or (
                item.valid_to is not None and type(item.valid_to) is not date
            ):
                raise RuntimeError("sse50_universe_pit_validity_invalid")
            if item.valid_to is not None and item.valid_to <= item.valid_from:
                raise RuntimeError("sse50_universe_pit_validity_invalid")
            if item.valid_from > as_of_date or (
                item.valid_to is not None and as_of_date >= item.valid_to
            ):
                raise RuntimeError("sse50_universe_pit_validity_gap")
            if not cls._aware(item.published_at) or not cls._aware(item.platform_available_at):
                raise RuntimeError("sse50_universe_pit_timestamp_invalid")
            if item.published_at > known_by or item.platform_available_at > known_by:
                raise RuntimeError("sse50_universe_pit_evidence_after_cutoff")
            if item.platform_available_at < item.published_at:
                raise RuntimeError("sse50_universe_pit_evidence_time_order_invalid")
            rows.append((item, {"symbol": symbol, "name": name}))

        rows.sort(key=lambda item: item[1]["symbol"])
        members = [member for _, member in rows]
        member_evidence = [
            {
                "symbol": item.symbol,
                "valid_from": item.valid_from.isoformat(),
                "valid_to_exclusive": (
                    item.valid_to.isoformat() if item.valid_to is not None else None
                ),
                "published_at": item.published_at.isoformat(),
                "platform_available_at": item.platform_available_at.isoformat(),
                "evidence_ref": item.evidence_ref,
            }
            for item, _ in rows
        ]
        identity = {
            "temporal_scope": "point_in_time",
            "decision_cutoff_policy": cutoff_policy,
            "source": source,
            "snapshot_version": snapshot_version,
            "snapshot_evidence_ref": snapshot_evidence_ref,
            "members": members,
            "member_evidence": member_evidence,
        }
        snapshot_sha256 = _digest(identity)
        return _ResolvedUniverse(
            members=members,
            snapshot_sha256=snapshot_sha256,
            provenance={
                **identity,
                "temporal_scope": "point_in_time",
                "point_in_time_status": "PROVIDER_ATTESTED",
                "evidence_validation": "contract_and_temporal_bounds_only",
                "target_date": as_of_date.isoformat(),
                "known_by": known_by.isoformat(),
                "observed_at": _now().isoformat(),
                "snapshot_sha256": snapshot_sha256,
            },
        )

    def _require_shanghai_timezone(self) -> None:
        if getattr(self.settings, "STOCK_SIGNAL_SCHEDULE_TIMEZONE", None) != "Asia/Shanghai":
            raise RuntimeError("stock_signal_business_timezone_unsupported")

    @staticmethod
    def _require_after_close(now: datetime) -> None:
        if now.time().replace(tzinfo=None) < _SSE50_DECISION_TIME:
            raise RuntimeError("stock_signal_decision_cutoff_not_reached")

    @classmethod
    def _normalize_members(cls, raw_members: Any) -> list[dict[str, str]]:
        if not isinstance(raw_members, (list, tuple)) or len(raw_members) != 50:
            raise RuntimeError("sse50_universe_member_count_invalid")
        members: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in raw_members:
            if not isinstance(item, dict):
                raise RuntimeError("sse50_universe_member_invalid")
            symbol = cls._required_text(item.get("symbol"))
            name = cls._required_text(item.get("name"))
            if not re.fullmatch(r"\d{6}\.(?:SH|SZ)", symbol) or symbol in seen:
                raise RuntimeError("sse50_universe_member_identity_invalid")
            seen.add(symbol)
            members.append({"symbol": symbol, "name": name})
        return sorted(members, key=lambda item: item["symbol"])

    @staticmethod
    def _required_text(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError("sse50_universe_evidence_text_invalid")
        return value.strip()

    @staticmethod
    def _aware(value: Any) -> bool:
        return (
            isinstance(value, datetime)
            and value.tzinfo is not None
            and value.utcoffset() is not None
        )

    async def _process_member(
        self,
        *,
        run_id: str,
        member: dict[str, str],
        as_of_date: date,
        next_trading_date: date,
    ) -> tuple[str, str | None]:
        async with async_session_maker() as session:
            collector = StockAnalysisDataCollector(session)
            snapshot = await collector.collect(
                user_id="system",
                symbol=member["symbol"],
                market_type="A股",
                analysis_date=as_of_date,
            )
            prediction = await StockSignalService(
                session,
                policy=self.policy,
                quality_gate=self.quality_gate,
            ).create_prediction(
                snapshot=snapshot,
                symbol=member["symbol"],
                market_type="A股",
                as_of_date=as_of_date,
                owner_scope="system",
                source=self.source,
                universe_code=self.universe_code,
                next_trading_date=next_trading_date,
                run_id=run_id,
            )
            if not prediction.symbol_name and member.get("name"):
                prediction.symbol_name = member["name"]
            await session.commit()
            return prediction.eligibility_status, None

    async def score_pending(self, *, through_date: date | None = None) -> int:
        """Refresh mature outcomes using subsequent market rows; never alter prediction inputs."""
        target_date = through_date or date.today()
        async with async_session_maker() as session:
            records = list(
                (
                    await session.execute(
                        select(StockSignalPrediction).where(
                            StockSignalPrediction.outcome_status.in_(("pending", "partial")),
                            StockSignalPrediction.as_of_date <= target_date,
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not records:
                return 0
            for record in records:
                if record.next_trading_date is not None:
                    continue
                try:
                    record.next_trading_date = await self.calendar.next_trading_day(
                        record.as_of_date
                    )
                except RuntimeError as exc:
                    logger.warning(
                        "Unable to resolve next trading date for stock signal %s: %s",
                        record.id,
                        exc,
                    )
            records = [
                record
                for record in records
                if record.next_trading_date is not None and record.next_trading_date <= target_date
            ]
            if not records:
                await session.commit()
                return 0
            service = StockSignalService(session)
            market = MarketInstrumentService()
            first_entry_date = min(
                record.next_trading_date
                for record in records
                if record.next_trading_date is not None
            )
            benchmark_rows = await self._sse50_benchmark_rows(
                start_date=first_entry_date,
                end_date=target_date,
            )
            updated = 0
            for record in records:
                if record.next_trading_date is None:
                    continue
                try:
                    payload = await market.lookup(
                        asset_type="stock",
                        symbol=record.symbol,
                        start_date=record.next_trading_date,
                        end_date=target_date,
                        period="daily",
                        # This scheduled path only consumes persisted local
                        # data; online provider I/O belongs to the v2 pipeline.
                        refresh_online=False,
                    )
                except Exception as exc:
                    logger.warning(
                        "Unable to score stock signal %s for %s: %s",
                        record.id,
                        record.symbol,
                        exc,
                    )
                    continue
                await service.apply_outcome(
                    prediction=record,
                    price_rows=(payload.get("history") or {}).get("rows") or [],
                    benchmark_rows=benchmark_rows,
                )
                updated += 1
            await session.commit()
            return updated

    async def _sse50_benchmark_rows(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """Read benchmark rows without treating an empty result as data readiness.

        A valid empty OpenData response is logged separately from a failed read. In
        either case, existing stock-only scoring can still persist ``scored`` with
        benchmark and excess returns unset. Returned rows do not prove source
        completeness; production enablement requires verified 000016 coverage,
        daily comparison against Eastmoney, and operational observability.
        """
        if getattr(self.settings, "STOCK_SIGNAL_BENCHMARK_OPENDATA_ENABLED", False):
            # This branch is deliberately source-pinned and fail-closed. A failed
            # OpenData read must not silently change the benchmark source.
            try:
                reader = OpenDataSse50BenchmarkReader.from_environment()
                rows = await reader.fetch_rows(start_date=start_date, end_date=end_date)
                if not rows:
                    logger.warning(
                        "OpenData SSE50 benchmark empty code=OPENDATA_SSE50_EMPTY_SUCCESS"
                    )
                return rows
            except Exception as exc:
                error_code = getattr(exc, "code", "OPENDATA_SSE50_READER_UNAVAILABLE")
                logger.warning("OpenData SSE50 benchmark unavailable code=%s", error_code)
                return []

        # Keep the established path until the 000016 OpenData history has been
        # compared against the existing Eastmoney benchmark.
        try:
            return await asyncio.to_thread(
                self._fetch_sse50_benchmark_rows,
                start_date,
                end_date,
            )
        except Exception as exc:
            logger.warning("Unable to load SSE50 benchmark rows for signal scoring: %s", exc)
            return []

    @staticmethod
    def _fetch_sse50_benchmark_rows(start_date: date, end_date: date) -> list[dict[str, Any]]:
        import akshare as ak

        frame = ak.stock_zh_index_daily_em(
            symbol="sh000016",
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        if frame is None or frame.empty:
            return []
        required = {"date", "open", "close"}
        if not required.issubset(frame.columns):
            return []
        return [
            {
                "date": str(row["date"])[:10],
                "open": row["open"],
                "close": row["close"],
            }
            for row in frame.to_dict(orient="records")
        ]
