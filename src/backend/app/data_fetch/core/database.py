"""
Database base class for data fetch operations
"""

import logging
import re
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from types import TracebackType
from typing import Any, Literal, Protocol

import pandas as pd
import pytz
from mysql.connector.types import (
    DescriptionType,
    MySQLConvertibleType,
    RowType,
)

#: A row as the data-fetch plane actually reads it. Every cursor here is created by
#: ``connection.cursor()`` without ``dictionary=True`` (the only ``dictionary=True`` site in the
#: tree, ``scripts/common/currency_fallback.py``, opens its own connector connection and never
#: touches this class), so a row is a positional tuple. It used to be declared as
#: ``RowType | dict[str, RowItemType]``; that phantom dict arm is what made the 39 ``row[0]``
#: reads in the scripts indexable only by ``str``, i.e. a shared-layer lie, not per-file noise.
_DatabaseRow = RowType
_DatabaseParams = Sequence[MySQLConvertibleType] | dict[str, MySQLConvertibleType]


class _DatabaseCursor(Protocol):
    """The default connector cursor operations used by data-fetch services.

    Rows are positional. The connector itself types its cursor rows as ``RowType`` *or* a dict
    (one cursor class serves both flavours), so the concrete cursor cannot satisfy this protocol
    directly; ``mysql_base._PositionalCursor`` is the boundary that checks the shape and hands
    back a row the callers may index by position.
    """

    @property
    def description(self) -> Sequence[DescriptionType] | None: ...

    @property
    def rowcount(self) -> int: ...

    def execute(self, operation: str, params: _DatabaseParams = ()) -> None: ...

    def executemany(self, operation: str, seq_params: Sequence[_DatabaseParams]) -> None: ...

    def fetchone(self) -> _DatabaseRow | None: ...

    def fetchall(self) -> list[_DatabaseRow]: ...

    def close(self) -> None: ...

    def __enter__(self) -> "_DatabaseCursor": ...

    def __exit__(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        traceback: TracebackType,
    ) -> None: ...


class _DatabaseConnection(Protocol):
    """Connection operations required by MySQL-backed data-fetch services."""

    def cursor(self) -> _DatabaseCursor: ...

    def is_connected(self) -> bool: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


class Database:
    def __init__(self, db_config: dict[str, Any], logger: logging.Logger | None = None):
        self.db_config = db_config
        self.logger = logger or logging.getLogger("DBBase")
        # The live handle and its cursor. They are genuinely nullable: ``connect_db`` establishes
        # them, ``disconnect_db`` drops them. Read them through ``require_connection()`` /
        # ``require_cursor()``, which is the accessor that hands back a usable object instead of
        # the union; the bare attributes stay nullable because that is what they are.
        self.connection: _DatabaseConnection | None = None
        self.cursor: _DatabaseCursor | None = None
        self.batch_size = 1000

    def require_connection(self) -> _DatabaseConnection:
        """Return the established connection, or raise instead of returning ``None``.

        Without this accessor a call site that runs before ``connect_db`` (or after
        ``disconnect_db``) dereferences ``None`` and dies with ``'NoneType' object has no
        attribute`` noise; with it the failure names the missing step.
        """
        connection = self.connection
        if connection is None:
            raise RuntimeError("MySQL connection is not established; call connect_db() first")
        return connection

    def require_cursor(self) -> _DatabaseCursor:
        """Return the cursor established with the connection, or raise instead of ``None``.

        Tuple rows only (see ``_DatabaseRow``); a dictionary-mode cursor is not produced anywhere
        on this plane, so there is no dict entry point to keep in sync.
        """
        cursor = self.cursor
        if cursor is None:
            raise RuntimeError("MySQL cursor is not established; call connect_db() first")
        return cursor

    def _setup_logging(self, name: str) -> logging.Logger:
        logger = logging.getLogger(name)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

    def connect_db(self) -> None:
        raise NotImplementedError

    def disconnect_db(self) -> None:
        raise NotImplementedError

    def __enter__(self) -> "Database":
        self.connect_db()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.disconnect_db()

    def _execute_batch(self, insert_sql: str, batch: list[Any]) -> int:
        """Execute one batch and return the number of rows the server applied.

        ``rowcount`` is what the server actually persisted; with ``INSERT
        IGNORE`` a duplicate-heavy batch can apply fewer rows than it offered.
        Implementations must return an ``int`` (0 is valid) rather than a bare
        success flag so callers can report the truth.
        """
        raise NotImplementedError

    def save_data(
        self,
        df: pd.DataFrame,
        table_name: str,
        on_duplicate_update: bool = False,
        unique_keys: list[str] | None = None,
    ) -> int | Literal[False]:
        raise NotImplementedError

    def delete_data(self, table_name: str, conditions: dict[str, Any]) -> bool:
        raise NotImplementedError

    def get_current_datetime(self) -> str:
        """获取当前日期时间字符串"""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def get_current_date(self) -> str:
        """获取当前日期字符串"""
        return datetime.now().strftime("%Y-%m-%d")

    def get_previous_date(self, tz: str = "Asia/Shanghai") -> str:
        """获取指定时区的前一天日期"""
        try:
            timezone = pytz.timezone(tz)
            now = datetime.now(timezone)
            previous_day = now - timedelta(days=1)
            return previous_day.strftime("%Y-%m-%d")
        except Exception as e:
            self.logger.error(f"日期计算失败: {str(e)}")
            raise

    def get_next_date(
        self, base_date: date | datetime | str | None = None, tz: str = "Asia/Shanghai"
    ) -> str:
        """获取指定时区的后一天日期"""
        try:
            if base_date is None:
                timezone = pytz.timezone(tz)
                now = datetime.now(timezone)
                next_day = now + timedelta(days=1)
            else:
                if isinstance(base_date, (datetime, date)):
                    # Ensure we work with datetime for strftime compatibility
                    if isinstance(base_date, datetime):
                        next_day = base_date + timedelta(days=1)
                    else:  # date
                        # Convert date to datetime, then add timedelta
                        temp_datetime = datetime.combine(base_date, datetime.min.time())
                        next_day = temp_datetime + timedelta(days=1)
                else:
                    date_str = str(base_date).strip()
                    date_formats = ["%Y-%m-%d", "%Y%m%d", "%Y/%m/%d", "%Y.%m.%d"]
                    parsed_date = None
                    for fmt in date_formats:
                        try:
                            parsed_date = datetime.strptime(date_str, fmt)
                            break
                        except ValueError:
                            continue
                    if parsed_date is None:
                        raise ValueError(f"不支持的日期格式: {base_date}")
                    next_day = parsed_date + timedelta(days=1)
            return next_day.strftime("%Y-%m-%d")
        except Exception as e:
            self.logger.error(f"日期计算失败: {str(e)}")
            raise

    def get_previous_month(self) -> str:
        """获取上个月，格式YYYYMM"""
        today = datetime.now()
        first_day_of_prev_month = today.replace(day=1) - timedelta(days=1)
        return first_day_of_prev_month.strftime("%Y%m")

    def get_current_month(self) -> str:
        """获取当前月份，格式YYYYMM"""
        today = datetime.now()
        return today.strftime("%Y%m")

    def get_next_month(self, base_month: str | date | datetime | None = None) -> str:
        """获取下个月，格式YYYYMM"""
        try:
            if base_month is None:
                base_month = self.get_current_month()

            if isinstance(base_month, (datetime, date)):
                # Convert date to datetime if needed for replace() compatibility
                if isinstance(base_month, datetime):
                    base_date = base_month
                else:  # date
                    base_date = datetime.combine(base_month, datetime.min.time())
            else:
                date_str = str(base_month).strip()
                date_formats = ["%Y%m", "%Y%m%d", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"]
                base_date = None
                for fmt in date_formats:
                    try:
                        base_date = datetime.strptime(date_str, fmt)
                        break
                    except ValueError:
                        continue
            if base_date is None:
                raise ValueError(f"不支持的日期格式: {base_month}")
            if base_date.month == 12:
                next_month = base_date.replace(year=base_date.year + 1, month=1, day=1)
            else:
                next_month = base_date.replace(month=base_date.month + 1, day=1)

            return next_month.strftime("%Y%m")
        except Exception as e:
            self.logger.error(f"获取下个月份失败: {str(e)}")
            raise


_RECORDS_DUPLICATES_RE = re.compile(r"Records:\s*(\d+)\s+Duplicates:\s*(\d+)", re.IGNORECASE)


def _extract_mysql_info_message(cursor: object, connection: object | None = None) -> str | None:
    """Read MySQL's OK-packet info string (e.g. ``Records: 3  Duplicates: 2``) if exposed."""
    candidates: list[object] = [
        getattr(cursor, "info", None),
        getattr(getattr(cursor, "_result", None), "message", None),
        getattr(getattr(getattr(cursor, "_cursor", None), "_result", None), "message", None),
        getattr(connection, "info", None) if connection is not None else None,
    ]
    for candidate in candidates:
        if callable(candidate):
            try:
                candidate = candidate()
            except Exception:
                continue
        if isinstance(candidate, bytes):
            decoded = candidate.decode("utf-8", errors="ignore").strip()
            if decoded:
                return decoded
        elif isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def resolve_batch_affected_rows(
    insert_sql: str,
    batch_size: int,
    cursor: object,
    connection: object | None = None,
) -> int:
    """Compute distinct logical rows written/updated for one executed MySQL batch.

    For ``INSERT IGNORE`` / plain ``INSERT``, MySQL reports 1 per inserted row and
    0 for ignored duplicates. For ``ON DUPLICATE KEY UPDATE``, MySQL adds 2 to
    ``rowcount`` for every updated row and 1 for every newly inserted row; when
    the driver exposes MySQL's ``Records: R  Duplicates: D`` info message for the
    batch, deduplicate the double-counted updates so receipts reflect distinct
    persisted/modified rows.
    """
    if batch_size <= 0:
        return 0
    reported = getattr(cursor, "rowcount", -1)
    if not isinstance(reported, int) or isinstance(reported, bool) or reported < 0:
        return batch_size
    if reported == 0:
        return 0

    if "ON DUPLICATE KEY UPDATE" in insert_sql.upper():
        info_message = _extract_mysql_info_message(cursor, connection)
        if info_message:
            matched = _RECORDS_DUPLICATES_RE.search(info_message)
            if matched:
                records = int(matched.group(1))
                duplicates = int(matched.group(2))
                if records == batch_size and 0 <= duplicates <= records:
                    inserted = records - duplicates
                    remainder = reported - inserted
                    if remainder >= 0 and remainder % 2 == 0:
                        updated = min(duplicates, remainder // 2)
                        return min(inserted + updated, batch_size)

    return min(reported, batch_size)
