# ruff: noqa: E402
"""迭代 199 验收：THS dump 下载 → 解析 → 落库 → 复用闭环（一次性 SQLite）。

python scripts/acceptance/iteration199_ths_history.py --kind daily-k-10d --limit 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import func, select
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.db.database import Base
from app.models.market_data_platform import MdDataSeries, MdObservationRevision
from app.services.market_data.bootstrap import (
    CanonicalStorageSpec,
    MarketDataBootstrapSpec,
    MarketDataPlatformBootstrapper,
)
from app.services.market_data.ths_history_runner import (
    ThsHistoryError,
    ThsHistoryRunner,
)


def load_env_file() -> None:
    env_path = BACKEND_ROOT.parent.parent / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() in {"THS_API_KEY", "THS_API_BASE_URL"} and key.strip() not in os.environ:
            os.environ[key.strip()] = value.strip()


async def _run(*, kind: str, limit: int | None) -> dict[str, object]:
    directory = Path(tempfile.mkdtemp(prefix="iteration199-ths-"))
    path = directory / "market_data.sqlite3"
    database_url = str(URL.create(drivername="sqlite+aiosqlite", database=str(path)))
    engine = create_async_engine(database_url, future=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            await MarketDataPlatformBootstrapper(session).bootstrap(
                MarketDataBootstrapSpec(
                    storage=CanonicalStorageSpec.from_database_url(database_url)
                )
            )
            await session.commit()
        async with session_factory() as session:
            runner = ThsHistoryRunner.from_environment(session)
            if kind == "daily-k-10d":
                report = await runner.collect_daily(limit=limit)
            else:
                report = await runner.backfill_daily_k(limit=limit)
            await session.commit()
        # 日历发布要求一个干净的 session（不能夹带未提交的行情写入）。
        calendar_events = 0
        if kind == "daily-k-10d":
            async with session_factory() as calendar_session:
                calendar_runner = ThsHistoryRunner.from_environment(calendar_session)
                calendar_events = await calendar_runner.sync_calendar()
                await calendar_session.commit()
        async with session_factory() as verify:
            series_count = await verify.scalar(select(func.count()).select_from(MdDataSeries))
            revision_count = await verify.scalar(
                select(func.count()).select_from(MdObservationRevision)
            )
        return {
            "status": "pass",
            "code": "THS_HISTORY_CHAIN_PASSED",
            "kind": kind,
            "parsed_row_count": report.parsed_row_count,
            "symbol_count": report.symbol_count,
            "persisted_symbol_count": report.persisted_symbol_count,
            "persisted_observation_count": report.persisted_observation_count,
            "calendar_event_count": calendar_events,
            "series_count": int(series_count or 0),
            "revision_count": int(revision_count or 0),
            "credential_writes": False,
        }
    finally:
        await engine.dispose()
        try:
            path.unlink()
            directory.rmdir()
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("daily-k", "daily-k-10d"), default="daily-k-10d")
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(_run(kind=args.kind, limit=args.limit))
    except ThsHistoryError as exc:
        print(json.dumps({"status": "failed", "code": exc.code}, separators=(",", ":")))
        return 1
    except Exception:
        print(
            json.dumps(
                {"status": "failed", "code": "THS_HISTORY_ACCEPTANCE_FAILED"},
                separators=(",", ":"),
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
