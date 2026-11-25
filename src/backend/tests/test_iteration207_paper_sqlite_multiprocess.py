from __future__ import annotations

import asyncio
import multiprocessing
import os
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


def _process_worker(
    database_url: str,
    account_id: str,
    order_id: str,
    barrier: multiprocessing.synchronize.Barrier,
) -> None:
    os.environ["AFI_DISABLE_DOTENV"] = "1"
    os.environ["APP_ENV"] = "test"
    os.environ["DATABASE_URL"] = database_url
    os.environ["SQL_ECHO"] = "false"
    os.environ["SECRET_KEY"] = "iteration207-multiprocess-secret-key-0123456789"
    os.environ["JWT_SECRET_KEY"] = "iteration207-multiprocess-jwt-key-0123456789"

    from app.services.paper_trading_service import PaperTradingService

    def synchronized_asset_spec(_symbol: str):
        try:
            barrier.wait(timeout=3)
        except threading.BrokenBarrierError:
            pass
        return None

    async def run() -> None:
        service = PaperTradingService()
        service._local_asset_spec_for_symbol = synchronized_asset_spec
        service._get_simulated_price = AsyncMock(return_value=10.5)
        service._notify_order_update = AsyncMock()
        service._notify_account_update = AsyncMock()
        service._notify_position_update = AsyncMock()
        account = await service.get_account(account_id)
        assert account is not None
        await service._process_order(order_id, account_id, account)

    try:
        asyncio.run(run())
    except BaseException:
        traceback.print_exc()
        raise


@pytest.mark.asyncio
async def test_sqlite_multiprocess_orders_serialize_one_account_snapshot(tmp_path: Path) -> None:
    from app.db.database import Base
    from app.models.paper_trading import Account, Order, OrderSide, OrderType, PaperTrade, Position

    database_path = tmp_path / "paper-multiprocess.sqlite3"
    database_url = f"sqlite+aiosqlite:///{database_path}"
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        account = Account(
            id="iteration207-shared-account",
            user_id="iteration207-user",
            name="Shared cash",
            initial_cash=1100.0,
            current_cash=1100.0,
            total_equity=1100.0,
            commission_rate=0.0,
            slippage_rate=0.0,
            created_at=datetime.now(timezone.utc),
        )
        session.add(account)
        session.add_all(
            [
                Order(
                    id=f"iteration207-order-{index}",
                    account_id=account.id,
                    symbol="000001.SZ",
                    order_type=OrderType.MARKET.value,
                    side=OrderSide.BUY.value,
                    size=100.0,
                    status="pending",
                    created_at=datetime.now(timezone.utc),
                )
                for index in (1, 2)
            ]
        )
        await session.commit()
    await engine.dispose()

    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    processes = [
        context.Process(
            target=_process_worker,
            args=(database_url, account.id, f"iteration207-order-{index}", barrier),
        )
        for index in (1, 2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0

    verification_engine = create_async_engine(database_url)
    async with AsyncSession(verification_engine, expire_on_commit=False) as session:
        stored_account = await session.get(Account, account.id)
        orders = list(
            (
                await session.scalars(
                    select(Order).where(Order.account_id == account.id).order_by(Order.id)
                )
            ).all()
        )
        positions = list(
            (await session.scalars(select(Position).where(Position.account_id == account.id))).all()
        )
        trades = list(
            (
                await session.scalars(select(PaperTrade).where(PaperTrade.account_id == account.id))
            ).all()
        )
    await verification_engine.dispose()

    assert sorted(order.status for order in orders) == ["filled", "rejected"]
    assert stored_account.current_cash == pytest.approx(50.0)
    assert len(positions) == 1
    assert positions[0].size == pytest.approx(100.0)
    assert len(trades) == 1


@pytest.mark.parametrize("dialect_name", ["mysql", "postgresql"])
def test_non_sqlite_account_reads_retain_for_update(dialect_name: str) -> None:
    from sqlalchemy import select
    from sqlalchemy.dialects import mysql, postgresql

    from app.models.paper_trading import Account

    dialect = mysql.dialect() if dialect_name == "mysql" else postgresql.dialect()
    statement = select(Account).where(Account.id == "account").with_for_update()

    assert "FOR UPDATE" in str(statement.compile(dialect=dialect))
