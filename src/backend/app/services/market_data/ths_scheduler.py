"""THS 历史数据每日增量调度服务（迭代 199）。

复用项目既有的 APScheduler 依赖，注册「每日收盘后」任务，调用
``ThsHistoryRunner.collect_daily``（``daily-k-10d`` + 交易日历）。

默认关闭：仅当 ``MARKET_DATA_THS_SCHEDULER_ENABLED`` 为真且 ``THS_API_KEY``
存在时才注册任务。关闭该开关即停止定时任务，已落库数据保留可读。
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

DEFAULT_THS_DAILY_HOUR = 18
DEFAULT_THS_DAILY_MINUTE = 0
DEFAULT_THS_TIMEZONE = "Asia/Shanghai"
THS_DAILY_JOB_ID = "ths-market-data-daily"

_service: ThsMarketDataScheduler | None = None


class ThsMarketDataScheduler:
    """每日收盘后触发 THS 增量采集的调度服务。"""

    def __init__(
        self,
        *,
        enabled: bool,
        hour: int = DEFAULT_THS_DAILY_HOUR,
        minute: int = DEFAULT_THS_DAILY_MINUTE,
        timezone_name: str = DEFAULT_THS_TIMEZONE,
    ) -> None:
        self._enabled = bool(enabled)
        self._hour = int(hour)
        self._minute = int(minute)
        self._timezone_name = timezone_name
        self._scheduler = AsyncIOScheduler(timezone=timezone_name)

    @classmethod
    def from_settings(cls, settings: object) -> ThsMarketDataScheduler:
        """从应用 settings 读取开关与时间。"""
        return cls(
            enabled=bool(getattr(settings, "MARKET_DATA_THS_SCHEDULER_ENABLED", False)),
            hour=int(getattr(settings, "MARKET_DATA_THS_SCHEDULER_HOUR", DEFAULT_THS_DAILY_HOUR)),
            minute=int(
                getattr(settings, "MARKET_DATA_THS_SCHEDULER_MINUTE", DEFAULT_THS_DAILY_MINUTE)
            ),
            timezone_name=str(
                getattr(settings, "MARKET_DATA_THS_SCHEDULER_TIMEZONE", DEFAULT_THS_TIMEZONE)
            ),
        )

    async def start(self) -> None:
        """按开关注册每日任务并启动调度器。"""
        if not self._enabled:
            logger.info("THS market-data scheduler disabled by settings")
            return
        self._scheduler.add_job(
            _run_daily_ths_collection,
            trigger=CronTrigger(
                hour=self._hour,
                minute=self._minute,
                timezone=self._timezone_name,
            ),
            id=THS_DAILY_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        self._scheduler.start()
        logger.info(
            "THS market-data scheduler started: daily at %02d:%02d %s",
            self._hour,
            self._minute,
            self._timezone_name,
        )

    async def shutdown(self) -> None:
        """停止调度器（幂等）。"""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def describe(self) -> dict[str, object]:
        """返回可解释的调度状态（供运维/审计）。"""
        jobs = self._scheduler.get_jobs() if self._scheduler.running else []
        return {
            "enabled": self._enabled,
            "running": self._scheduler.running,
            "job_ids": [job.id for job in jobs],
            "cron": f"{self._hour:02d}:{self._minute:02d} {self._timezone_name}",
        }


async def _run_daily_ths_collection() -> None:
    """任务体：一次每日增量采集（独立 session，失败不抛出到调度器）。"""
    from app.db.database import async_session_maker
    from app.services.market_data.ths_history_runner import ThsHistoryRunner

    try:
        async with async_session_maker() as session:
            runner = ThsHistoryRunner.from_environment(session)
            report = await runner.collect_daily()
            await session.commit()
        logger.info(
            "THS daily collection done: symbols=%s observations=%s",
            report.persisted_symbol_count,
            report.persisted_observation_count,
        )
    except Exception:
        logger.exception("THS daily collection failed")


def get_ths_scheduler_service() -> ThsMarketDataScheduler:
    """进程内单例调度服务。"""
    global _service
    if _service is None:
        _service = ThsMarketDataScheduler(enabled=False)
    return _service
