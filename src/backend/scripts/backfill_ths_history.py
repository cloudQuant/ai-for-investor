# ruff: noqa: E402
"""THS 历史数据全量回填 CLI（迭代 199）。

把同花顺全市场历史数据回填到本地规范存储（``md_*``）。默认 dry-run，只有显式
``--apply`` 才提交写入。

    python scripts/backfill_ths_history.py --dataset daily-k --limit 5 --apply
    python scripts/backfill_ths_history.py --dataset calendar --apply

数据域：
    daily-k               全市场日 K（market-dumps，~10 年）
    calendar              交易日历（近一年）
    （financials / adjustment-factors / index 见 runner 的逐标的实现，后续接入）
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

SUPPORTED_DATASETS = (
    "daily-k",
    "calendar",
    "adjustment-factors",
    "financials-income",
    "financials-balance",
    "financials-cashflow",
)


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
    parser.add_argument(
        "--dataset",
        action="append",
        choices=SUPPORTED_DATASETS,
        required=True,
        help="要回填的数据域（可重复）。",
    )
    parser.add_argument("--limit", type=int, default=None, help="限制标的数（用于小规模验证）。")
    parser.add_argument(
        "--dump-file",
        default=None,
        help="本地 Parquet 缓存路径（默认系统临时目录）；已存在则复用，避免重复下载。",
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="不跳过本地已有 series 的标的（默认跳过，用于断点续跑）。",
    )
    parser.add_argument("--apply", action="store_true", help="提交写入；缺省为 dry-run。")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> dict[str, object]:
    import os
    import tempfile

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise ThsHistoryError("DATABASE_URL_UNAVAILABLE")
    engine = create_async_engine(database_url, future=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    results: dict[str, object] = {}
    try:
        async with session_factory() as session:
            runner = ThsHistoryRunner.from_environment(session)
            for dataset in args.dataset:
                if dataset == "daily-k":
                    cache_path = args.dump_file or str(
                        Path(tempfile.gettempdir()) / "ths_daily_k_full.parquet"
                    )
                    report = await runner.backfill_daily_k(
                        limit=args.limit,
                        cache_path=cache_path,
                        commit_every=200 if args.apply else None,
                        skip_existing=not args.no_skip_existing,
                    )
                    results[dataset] = {
                        "dump_kind": report.dump_kind,
                        "parsed_row_count": report.parsed_row_count,
                        "symbol_count": report.symbol_count,
                        "persisted_symbol_count": report.persisted_symbol_count,
                        "persisted_observation_count": report.persisted_observation_count,
                    }
                elif dataset == "calendar":
                    if args.apply and session.in_transaction():
                        await session.commit()
                    event_count = await runner.sync_calendar(apply=args.apply)
                    results[dataset] = {"calendar_event_count": event_count}
                elif dataset == "adjustment-factors":
                    results[dataset] = await runner.backfill_adjustment_factors(
                        limit=args.limit,
                        commit_every=100 if args.apply else None,
                    )
                elif dataset.startswith("financials-"):
                    statement = dataset.split("-", 1)[1]
                    results[dataset] = await runner.backfill_financials(
                        statement=statement,
                        limit=args.limit,
                        commit_every=100 if args.apply else None,
                    )
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
            json.dumps({"status": "failed", "code": "THS_BACKFILL_FAILED"}, separators=(",", ":"))
        )
        return 1
    print(
        json.dumps(
            {
                "status": "applied" if args.apply else "dry_run",
                "datasets": args.dataset,
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
