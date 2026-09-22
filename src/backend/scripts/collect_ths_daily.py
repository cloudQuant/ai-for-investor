# ruff: noqa: E402
"""THS 每日增量采集 CLI（迭代 199）。

每日收盘后运行：拉取 ``daily-k-10d``（近 10 交易日全市场日 K）+ 同步交易日历。
默认 dry-run，只有显式 ``--apply`` 才提交写入。可被 APScheduler 调度复用。

    python scripts/collect_ths_daily.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.services.market_data.ths_history_runner import ThsHistoryError, ThsHistoryRunner


def load_env_file() -> None:
    """从仓库根 .env 注入 THS/DATABASE 环境变量（不覆盖已存在值）。"""
    import os

    env_path = BACKEND_ROOT.parent.parent / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key in {"THS_API_KEY", "THS_API_BASE_URL", "DATABASE_URL"} and key not in os.environ:
            os.environ[key] = value.strip()


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="限制标的数（用于小规模验证）。")
    parser.add_argument("--apply", action="store_true", help="提交写入；缺省为 dry-run。")
    parser.add_argument("--skip-calendar", action="store_true", help="跳过日历同步。")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> dict[str, object]:
    import os

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise ThsHistoryError("DATABASE_URL_UNAVAILABLE")
    engine = create_async_engine(database_url, future=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    results: dict[str, object] = {}
    try:
        async with session_factory() as session:
            runner = ThsHistoryRunner.from_environment(session)
            report = await runner.collect_daily(
                limit=args.limit,
                commit_every=200 if args.apply else None,
            )
            results["daily_k"] = {
                "dump_kind": report.dump_kind,
                "parsed_row_count": report.parsed_row_count,
                "symbol_count": report.symbol_count,
                "persisted_symbol_count": report.persisted_symbol_count,
                "persisted_observation_count": report.persisted_observation_count,
            }
            if not args.skip_calendar:
                if args.apply and session.in_transaction():
                    await session.commit()
                results["calendar"] = {
                    "calendar_event_count": await runner.sync_calendar(apply=args.apply)
                }
            if args.apply:
                await session.commit()
            else:
                await session.rollback()
    finally:
        await engine.dispose()
    return results


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    args = _arguments(argv)
    try:
        results = asyncio.run(_run(args))
    except ThsHistoryError as exc:
        print(json.dumps({"status": "failed", "code": exc.code}, separators=(",", ":")))
        return 1
    except Exception:
        print(
            json.dumps(
                {"status": "failed", "code": "THS_DAILY_COLLECT_FAILED"}, separators=(",", ":")
            )
        )
        return 1
    print(
        json.dumps(
            {
                "status": "applied" if args.apply else "dry_run",
                "results": results,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
