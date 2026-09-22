"""
Monitoring and alerting models.

Supports account monitoring, strategy monitoring, and system monitoring.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, TypeAlias

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

if TYPE_CHECKING:
    from app.models.backtest import BacktestTask
    from app.models.paper_trading import Account, Order, Position
    from app.models.strategy import Strategy
    from app.models.user import User

JSONValue: TypeAlias = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]


class AlertType(str, Enum):
    """Alert type enum."""

    ACCOUNT = "account"  # Account alert
    POSITION = "position"  # Position alert
    ORDER = "order"  # Order alert
    STRATEGY = "strategy"  # Strategy alert
    SYSTEM = "system"  # System alert
    PERFORMANCE = "performance"  # Performance alert
    RISK = "risk"  # Risk alert


class AlertSeverity(str, Enum):
    """Alert severity enum."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertStatus(str, Enum):
    """Alert status enum."""

    ACTIVE = "active"  # Active
    RESOLVED = "resolved"  # Resolved
    ACKNOWLEDGED = "acknowledged"  # Acknowledged
    IGNORED = "ignored"  # Ignored


class Alert(Base):
    """Alert table.

    Attributes:
        id: Unique alert identifier (UUID).
        user_id: User ID who owns the alert.
        alert_type: Alert type.
        severity: Alert severity.
        status: Alert status.
        title: Alert title.
        message: Alert message.
        details: Additional details (JSON).
        rule_id: Associated alert rule ID.
        strategy_id: Associated strategy ID.
        backtest_task_id: Associated backtest task ID.
        account_id: Associated paper trading account ID.
        position_id: Associated paper trading position ID.
        order_id: Associated paper trading order ID.
        trigger_type: Trigger type (threshold, rate, manual).
        trigger_value: Trigger value.
        threshold_value: Threshold value.
        is_read: Whether the alert is read.
        is_notification_sent: Whether notification was sent.
        resolved_at: Resolution timestamp.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
    """

    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_user_instance_created", "user_id", "instance_id", "created_at"),
        Index("ix_alerts_dedupe_key", "dedupe_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )

    # Alert information
    alert_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # Alert type
    severity: Mapped[str] = mapped_column(
        String(20), default=AlertSeverity.INFO, nullable=False
    )  # Alert severity
    status: Mapped[str] = mapped_column(
        String(20), default=AlertStatus.ACTIVE, nullable=False, index=True
    )  # Alert status
    title: Mapped[str] = mapped_column(String(200), nullable=False)  # Alert title
    message: Mapped[str] = mapped_column(Text, nullable=False)  # Alert message
    details: Mapped[JSONValue | None] = mapped_column(
        JSON, nullable=True
    )  # Additional details (JSON)

    # Associated objects
    rule_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("alert_rules.id"), nullable=True, index=True
    )
    strategy_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("strategies.id"), nullable=True, index=True
    )
    backtest_task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("backtest_tasks.id"), nullable=True, index=True
    )
    account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("paper_trading_accounts.id"), nullable=True, index=True
    )
    position_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("paper_trading_positions.id"), nullable=True, index=True
    )
    order_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("paper_trading_orders.id"), nullable=True, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workspaces.id"), nullable=True, index=True
    )
    unit_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("strategy_units.id"), nullable=True, index=True
    )
    instance_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Trigger conditions
    trigger_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # Trigger type (threshold, rate, manual)
    trigger_value: Mapped[float | None] = mapped_column(Float, nullable=True)  # Trigger value
    threshold_value: Mapped[float | None] = mapped_column(Float, nullable=True)  # Threshold value

    # Meta information
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # Whether read
    is_notification_sent: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )  # Whether notification sent
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # Resolution time
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="alerts")
    strategy: Mapped["Strategy"] = relationship("Strategy", backref="alerts")
    backtest_task: Mapped["BacktestTask"] = relationship("BacktestTask", backref="alerts")
    account: Mapped["Account"] = relationship("Account", backref="alerts")
    position: Mapped["Position"] = relationship("Position", backref="alerts")
    order: Mapped["Order"] = relationship("Order", backref="alerts")
    notifications: Mapped[list["AlertNotification"]] = relationship(
        "AlertNotification", back_populates="alert"
    )


class AlertRule(Base):
    """Alert rule table.

    Attributes:
        id: Unique rule identifier (UUID).
        user_id: User ID who owns the rule.
        alert_type: Alert type.
        severity: Alert severity.
        name: Rule name.
        description: Rule description.
        trigger_type: Trigger type (threshold, rate, cross).
        trigger_config: Trigger configuration (JSON).
        notification_enabled: Whether notifications are enabled.
        notification_channels: Notification channels (JSON).
        is_active: Whether the rule is active.
        triggered_count: Number of times triggered.
        last_triggered_at: Last triggered timestamp.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
    """

    __tablename__ = "alert_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )

    # Rule configuration
    alert_type: Mapped[str] = mapped_column(String(20), nullable=False)  # Alert type
    severity: Mapped[str] = mapped_column(
        String(20), default=AlertSeverity.WARNING, nullable=False
    )  # Alert severity
    name: Mapped[str] = mapped_column(String(200), nullable=False)  # Rule name
    description: Mapped[str | None] = mapped_column(Text, nullable=True)  # Rule description

    # Trigger conditions
    trigger_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # Trigger type (threshold, rate, cross)
    trigger_config: Mapped[dict[str, JSONValue]] = mapped_column(
        JSON, nullable=False
    )  # Trigger configuration

    # Notification configuration
    notification_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )  # Whether notifications enabled
    notification_channels: Mapped[list[JSONValue]] = mapped_column(
        JSON, default=list, nullable=False
    )  # Notification channels

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)  # Whether active
    triggered_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )  # Trigger count
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )  # Last triggered time

    # Meta information
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="alert_rules")
    alerts: Mapped[list["Alert"]] = relationship("Alert", backref="rule")


class AlertNotification(Base):
    """Alert notification record table.

    Attributes:
        id: Unique notification identifier (UUID).
        alert_id: Associated alert ID.
        channel: Notification channel (email, sms, push, webhook).
        status: Notification status (sent, failed, pending).
        message: Notification message.
        error: Error message.
        sent_at: Send timestamp.
        created_at: Creation timestamp.
    """

    __tablename__ = "alert_notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    alert_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("alerts.id"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # Notification channel (email, sms, push, webhook)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # Notification status (sent, failed, pending)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)  # Notification message
    error: Mapped[str | None] = mapped_column(Text, nullable=True)  # Error message
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # Send time
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    alert: Mapped["Alert"] = relationship("Alert", back_populates="notifications")
