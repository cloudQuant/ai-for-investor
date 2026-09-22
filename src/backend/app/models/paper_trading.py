"""
Paper trading models.

Supports accounts, orders, and position management.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.user import User


class OrderType(str, Enum):
    """Order type enum."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderSide(str, Enum):
    """Order side enum."""

    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    """Order status enum."""

    PENDING = "pending"
    PARTIAL_FILLED = "partial_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class Account(Base):
    """Paper trading account table.

    Attributes:
        id: Unique account identifier (UUID).
        user_id: User ID who owns the account.
        name: Account name.
        initial_cash: Initial cash amount.
        current_cash: Current cash amount.
        total_equity: Total equity (cash + position value).
        profit_loss: Profit/loss amount.
        profit_loss_pct: Profit/loss percentage.
        commission_rate: Commission rate.
        slippage_rate: Slippage rate.
        is_active: Whether the account is active.
        created_at: Account creation timestamp.
        updated_at: Last update timestamp.
    """

    __tablename__ = "paper_trading_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    initial_cash: Mapped[float] = mapped_column(Float, default=100000.0, nullable=False)
    current_cash: Mapped[float] = mapped_column(Float, default=100000.0, nullable=False)
    total_equity: Mapped[float] = mapped_column(
        Float, default=100000.0, nullable=False
    )  # Total equity (cash + position value)
    profit_loss: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # Profit/loss
    profit_loss_pct: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )  # Profit/loss percentage
    commission_rate: Mapped[float] = mapped_column(
        Float, default=0.001, nullable=False
    )  # Commission rate
    slippage_rate: Mapped[float] = mapped_column(
        Float, default=0.001, nullable=False
    )  # Slippage rate
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="paper_trading_accounts")
    positions: Mapped[list[Position]] = relationship(
        "Position", back_populates="account", cascade="all, delete-orphan"
    )
    orders: Mapped[list[Order]] = relationship(
        "Order", back_populates="account", cascade="all, delete-orphan"
    )
    trades: Mapped[list[PaperTrade]] = relationship(
        "PaperTrade", back_populates="account", cascade="all, delete-orphan"
    )


class Position(Base):
    """Paper trading position table.

    Attributes:
        id: Unique position identifier (UUID).
        account_id: Associated account ID.
        symbol: Trading symbol.
        size: Position size (positive for long, negative for short).
        avg_price: Average cost price.
        market_value: Market value.
        margin_value: Reserved margin for margin-based instruments.
        multiplier: Contract multiplier.
        margin_rate: Margin rate.
        commission_rate: Commission rate used for this position.
        commission_amount: Fixed commission per lot/contract.
        unrealized_pnl: Unrealized profit/loss.
        unrealized_pnl_pct: Unrealized profit/loss percentage.
        entry_price: Entry price.
        entry_time: Entry time.
        updated_at: Last update timestamp.
    """

    __tablename__ = "paper_trading_positions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("paper_trading_accounts.id"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    size: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )  # Position size (positive for long, negative for short)
    avg_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # Average cost
    market_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # Market value
    margin_value: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )  # Reserved margin
    multiplier: Mapped[float] = mapped_column(
        Float, default=1.0, nullable=False
    )  # Contract multiplier
    margin_rate: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)  # Margin rate
    commission_rate: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )  # Commission rate
    commission_amount: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )  # Fixed commission per lot
    unrealized_pnl: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )  # Unrealized profit/loss
    unrealized_pnl_pct: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )  # Unrealized profit/loss percentage
    entry_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # Entry price
    entry_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # Entry time
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    account: Mapped[Account] = relationship("Account", back_populates="positions")


class Order(Base):
    """Paper trading order table.

    Attributes:
        id: Unique order identifier (UUID).
        account_id: Associated account ID.
        symbol: Trading symbol.
        order_type: Order type (MARKET, LIMIT, STOP, STOP_LIMIT).
        side: Order side (BUY, SELL).
        size: Order size.
        price: Limit order price.
        stop_price: Stop loss price.
        limit_price: Take profit price.
        filled_size: Filled size.
        avg_fill_price: Average fill price.
        status: Order status.
        rejected_reason: Rejection reason.
        commission: Commission amount.
        slippage: Slippage amount.
        created_at: Order creation timestamp.
        updated_at: Last update timestamp.
        filled_at: Fill timestamp.
    """

    __tablename__ = "paper_trading_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("paper_trading_accounts.id"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    order_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # MARKET, LIMIT, STOP, STOP_LIMIT
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # BUY, SELL
    size: Mapped[float] = mapped_column(Float, nullable=False)  # Order size
    price: Mapped[float | None] = mapped_column(Float, nullable=True)  # Limit order price
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # Stop loss price
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # Take profit price
    filled_size: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # Filled size
    avg_fill_price: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )  # Average fill price
    status: Mapped[str] = mapped_column(
        String(20), default=OrderStatus.PENDING.value, nullable=False, index=True
    )
    rejected_reason: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # Rejection reason
    commission: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # Commission
    slippage: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # Slippage
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    filled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # Fill time

    # Relationships
    account: Mapped[Account] = relationship("Account", back_populates="orders")


class PaperTrade(Base):
    """Paper trading trade record table.

    Attributes:
        id: Unique trade identifier (UUID).
        account_id: Associated account ID.
        order_id: Associated order ID.
        symbol: Trading symbol.
        side: Trade side (BUY, SELL).
        size: Trade size.
        price: Trade price.
        commission: Commission amount.
        slippage: Slippage amount.
        pnl: Profit/loss.
        pnl_pct: Profit/loss percentage.
        created_at: Trade timestamp.
    """

    __tablename__ = "paper_trades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("paper_trading_accounts.id"), nullable=False, index=True
    )
    order_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("paper_trading_orders.id"), nullable=True, index=True
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # BUY, SELL
    size: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    commission: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    slippage: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    pnl: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # Profit/loss
    pnl_pct: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )  # Profit/loss percentage
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    account: Mapped[Account] = relationship("Account", back_populates="trades")
    order: Mapped[Order | None] = relationship("Order")
