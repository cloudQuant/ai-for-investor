"""Transactional paper-trading execution and unbounded position lookup helpers."""

from __future__ import annotations

import asyncio
import logging
import threading
import weakref
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update

from app.db.database import async_session_maker
from app.db.sql_repository import SQLRepository
from app.models.paper_trading import (
    Account,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    PaperTrade,
    Position,
)
from app.services.paper_trading_positions import PositionView
from app.utils.tracing import business_span

if TYPE_CHECKING:
    from app.services.paper_trading_service import PaperTradingService

logger = logging.getLogger(__name__)

_ACCOUNT_LOCKS_BY_LOOP: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[str, asyncio.Lock]
] = weakref.WeakKeyDictionary()
_ACCOUNT_LOCKS_GUARD = threading.Lock()


def get_paper_account_lock(account_id: str) -> asyncio.Lock:
    """Return the per-event-loop ``asyncio.Lock`` serializing mutations for ``account_id``."""
    loop = asyncio.get_running_loop()
    key = str(account_id)
    with _ACCOUNT_LOCKS_GUARD:
        locks = _ACCOUNT_LOCKS_BY_LOOP.get(loop)
        if locks is None:
            locks = {}
            _ACCOUNT_LOCKS_BY_LOOP[loop] = locks
        lock = locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            locks[key] = lock
        return lock


def uses_real_sql_repos(service: PaperTradingService) -> bool:
    """Return True when all core repositories are session-owning SQLRepositories."""
    return all(
        isinstance(repo, SQLRepository) and repo._owns_session
        for repo in (
            service.account_repo,
            service.position_repo,
            service.order_repo,
            service.trade_repo,
        )
    )


async def list_account_positions(
    position_repo: Any,
    account_id: str,
    *,
    open_only: bool = False,
) -> Sequence[Position]:
    """Query all positions for ``account_id`` without ``SQLRepository.list``'s 100-row cap."""
    if isinstance(position_repo, SQLRepository):
        stmt = select(Position).where(Position.account_id == account_id)
        if open_only:
            stmt = stmt.where(Position.size != 0)
        stmt = stmt.order_by(Position.updated_at.desc())
        async with position_repo._session_scope() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())
    return await position_repo.list(filters={"account_id": account_id})


async def cancel_order_transactional(
    service: PaperTradingService,
    order_id: str,
    user_id: str,
) -> bool:
    """Atomically cancel a ``PENDING`` order using CAS under the per-account lock."""
    order = await service.order_repo.get_by_id(order_id)
    if not order:
        return False

    account = await service.account_repo.get_by_id(order.account_id)
    if not account or account.user_id != user_id:
        return False

    async with get_paper_account_lock(str(order.account_id)):
        async with async_session_maker() as session:
            async with session.begin():
                cas_result = await session.execute(
                    update(Order)
                    .where(Order.id == order_id, Order.status == OrderStatus.PENDING)
                    .values(status=OrderStatus.CANCELLED)
                )
                if (cas_result.rowcount or 0) != 1:
                    return False

    order.status = OrderStatus.CANCELLED
    await service._notify_order_update(order.account_id, order)
    return True


def compute_execution_price(
    service: Any,
    order: Order,
    market_price: float,
    slippage_rate: float,
) -> float | None:
    """Return the simulated fill price, or None when the order is not triggered."""
    order_type = service._order_type_value(order.order_type)
    side = service._order_side_value(order.side)
    signed = service._signed_slippage(side, market_price, slippage_rate)

    if order_type == OrderType.MARKET.value:
        return market_price + signed

    if order_type == OrderType.LIMIT.value:
        limit_price = service._limit_price(order)
        if limit_price is None:
            return None
        if side == OrderSide.BUY.value:
            return None if market_price > limit_price else min(market_price + signed, limit_price)
        return None if market_price < limit_price else max(market_price + signed, limit_price)

    if order_type == OrderType.STOP.value:
        stop_price = service._stop_price(order)
        if stop_price is None:
            return None
        if side == OrderSide.BUY.value and market_price < stop_price:
            return None
        if side == OrderSide.SELL.value and market_price > stop_price:
            return None
        return market_price + signed

    if order_type == OrderType.STOP_LIMIT.value:
        stop_price = service._stop_price(order)
        limit_price = service._limit_price(order)
        if stop_price is None or limit_price is None:
            return None
        if side == OrderSide.BUY.value:
            if market_price < stop_price or market_price > limit_price:
                return None
            return min(market_price + signed, limit_price)
        if market_price > stop_price or market_price < limit_price:
            return None
        return max(market_price + signed, limit_price)

    return None


async def process_order_transactional(
    service: PaperTradingService,
    order_id: str,
    account_id: str,
    account: Account,
) -> None:
    """Execute order validation, CAS transition, trade insert, position & cash update atomically."""
    notify_rejected_order: Order | None = None
    notify_account: Account | None = None
    notify_positions: Sequence[PositionView] = ()

    async with get_paper_account_lock(str(account_id)):
        async with async_session_maker() as session:
            async with session.begin():
                dialect_name = session.bind.dialect.name if session.bind is not None else ""
                use_row_lock = dialect_name != "sqlite"

                acct_stmt = select(Account).where(Account.id == account_id)
                if use_row_lock:
                    acct_stmt = acct_stmt.with_for_update()
                fresh_account = (await session.execute(acct_stmt)).scalar_one_or_none()
                if fresh_account is None:
                    logger.error(
                        "Account not found while processing order %s: %s", order_id, account_id
                    )
                    return

                ord_stmt = select(Order).where(Order.id == order_id)
                if use_row_lock:
                    ord_stmt = ord_stmt.with_for_update()
                order = (await session.execute(ord_stmt)).scalar_one_or_none()
                if not order:
                    logger.error("Order not found: %s", order_id)
                    return
                if service._order_status_value(order.status) != OrderStatus.PENDING.value:
                    logger.info("Skip paper order processing for non-pending order: %s", order_id)
                    return

                try:
                    order_type, side, normalized_size = service._validate_order_request(
                        order_type=order.order_type,
                        side=order.side,
                        size=order.size,
                        price=service._optional_order_number(order, "price"),
                        stop_price=service._optional_order_number(order, "stop_price"),
                        limit_price=service._optional_order_number(order, "limit_price"),
                    )
                    asset_spec = await asyncio.to_thread(
                        service._local_asset_spec_for_symbol, order.symbol
                    )
                    service._validate_asset_order_constraints(
                        symbol=order.symbol,
                        size=normalized_size,
                        price=service._optional_order_number(order, "price"),
                        stop_price=service._optional_order_number(order, "stop_price"),
                        limit_price=service._optional_order_number(order, "limit_price"),
                        order_type=order_type,
                        asset_spec=asset_spec,
                    )
                except ValueError as exc:
                    cas_reject = await session.execute(
                        update(Order)
                        .where(Order.id == order.id, Order.status == OrderStatus.PENDING)
                        .values(status=OrderStatus.REJECTED, rejected_reason=str(exc))
                    )
                    if (cas_reject.rowcount or 0) == 1:
                        order.status = OrderStatus.REJECTED
                        order.rejected_reason = str(exc)
                        notify_rejected_order = order
                    return

                current_price = await service._get_simulated_price(order.symbol)
                fill_price = service._execution_price(
                    order, current_price, fresh_account.slippage_rate
                )
                if fill_price is None:
                    return

                tx_account_repo = SQLRepository(Account, session=session)
                tx_position_repo = SQLRepository(Position, session=session)
                tx_trade_repo = SQLRepository(PaperTrade, session=session)

                spec = service._contract_spec_for_symbol(
                    order.symbol, fresh_account, asset_spec=asset_spec
                )
                position = await service._get_position(
                    account_id, order.symbol, position_repo=tx_position_repo
                )
                fill_size = float(order.size or 0.0)
                signed_fill_size = fill_size if side == OrderSide.BUY.value else -fill_size
                fill_time = datetime.now(timezone.utc)
                commission_breakdown = service._fill_commission_breakdown(
                    position,
                    signed_fill_size,
                    fill_price,
                    spec,
                    as_of=fill_time,
                )
                commission = float(commission_breakdown["total_commission"] or 0.0)
                if service._uses_margin_accounting(spec):
                    required_cash = service._margin_required_cash_before_fill(
                        position,
                        signed_fill_size,
                        fill_price,
                        commission,
                        spec,
                    )
                else:
                    required_cash = service._cash_required_before_fill(
                        position,
                        signed_fill_size,
                        fill_price,
                        commission,
                        spec,
                    )
                if fresh_account.current_cash < required_cash:
                    cas_funds = await session.execute(
                        update(Order)
                        .where(Order.id == order.id, Order.status == OrderStatus.PENDING)
                        .values(status=OrderStatus.REJECTED, rejected_reason="Insufficient funds")
                    )
                    if (cas_funds.rowcount or 0) == 1:
                        order.status = OrderStatus.REJECTED
                        order.rejected_reason = "Insufficient funds"
                        notify_rejected_order = order
                    return

                with business_span(
                    "backtrader.live.on_fill",
                    symbol=order.symbol,
                    order_id=order.id,
                ):
                    cas_fill = await session.execute(
                        update(Order)
                        .where(Order.id == order.id, Order.status == OrderStatus.PENDING)
                        .values(
                            status=OrderStatus.FILLED,
                            filled_size=order.size,
                            avg_fill_price=fill_price,
                            commission=commission,
                            filled_at=fill_time,
                        )
                    )
                    if (cas_fill.rowcount or 0) != 1:
                        logger.info("Skip fill for order %s: status already transitioned", order.id)
                        return
                    order.status = OrderStatus.FILLED
                    order.filled_size = order.size
                    order.avg_fill_price = fill_price
                    order.commission = commission
                    order.filled_at = fill_time
                    await tx_trade_repo.create(
                        PaperTrade(
                            account_id=order.account_id,
                            order_id=order.id,
                            symbol=order.symbol,
                            side=order.side,
                            size=order.size,
                            price=fill_price,
                            commission=commission,
                            slippage=0.0,
                            pnl=0.0,
                            pnl_pct=0.0,
                        )
                    )

                position_event = await service._update_position(
                    fresh_account,
                    order,
                    fill_price,
                    commission,
                    spec=spec,
                    current_position=position,
                    commission_breakdown=commission_breakdown,
                    fill_time=fill_time,
                    position_repo=tx_position_repo,
                    trade_repo=tx_trade_repo,
                )
                notify_positions = await service._update_account(
                    fresh_account,
                    order,
                    fill_price,
                    commission,
                    spec=spec,
                    position_event=position_event,
                    account_repo=tx_account_repo,
                    position_repo=tx_position_repo,
                    send_notifications=False,
                )
                notify_account = fresh_account
                if account is not None and account is not fresh_account:
                    account.current_cash = fresh_account.current_cash
                    account.total_equity = fresh_account.total_equity
                    account.profit_loss = fresh_account.profit_loss
                    account.profit_loss_pct = fresh_account.profit_loss_pct

                logger.info("Order filled: %s at %s", order_id, fill_price)

    if notify_rejected_order is not None:
        await service._notify_order_update(account_id, notify_rejected_order)
    if notify_account is not None:
        await service._notify_account_update(notify_account)
        for pos in notify_positions:
            await service._notify_position_update(pos)
