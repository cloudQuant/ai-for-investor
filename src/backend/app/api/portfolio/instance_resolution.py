"""Resolve live instances and determine their effective runtime time bounds."""

import os
import sys
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from app.api.portfolio.portfolio_common import (
    _ACTIVE_TRADING_STATUSES,
    _PORTFOLIO_TIMEZONE,
    _PortfolioSource,
    _safe_dict,
)
from app.services.live_trading_manager import LiveTradingManager
from app.services.log_parser.normalize import normalize_dt_text
from app.services.log_parser_service import find_latest_log_dir, parse_run_info, parse_value_log
from app.services.strategy_service import get_strategy_dir


def _coerce_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _coerce_started_day(value: Any) -> str | None:
    text = normalize_dt_text(value).strip()
    if not text:
        return None
    return text[:10]


def _infer_started_day_from_pid(pid: int) -> str | None:
    if pid <= 0:
        return None
    if sys.platform == "win32":
        return None

    stat_path = Path(f"/proc/{pid}/stat")
    if not stat_path.is_file():
        return None

    try:
        stat_text = stat_path.read_text(encoding="utf-8")
        close_paren = stat_text.rfind(")")
        if close_paren < 0:
            return None
        parts = stat_text[close_paren + 2 :].split()
        if len(parts) < 20:
            return None
        start_ticks = int(parts[19])
    except (OSError, ValueError):
        return None

    try:
        with Path("/proc/stat").open(encoding="utf-8") as handle:
            boot_time: float | None = None
            for line in handle:
                if not line.startswith("btime"):
                    continue
                boot_time = float(line.split()[1])
                break
    except OSError:
        return None
    if boot_time is None:
        return None

    try:
        clock_ticks = os.sysconf("SC_CLK_TCK")
        epoch_seconds = boot_time + start_ticks / clock_ticks
        return datetime.fromtimestamp(epoch_seconds).strftime("%Y-%m-%d")
    except (AttributeError, OSError, ValueError):
        return None


def _infer_started_day_from_log_dir(
    log_dir: Path,
    *,
    allow_mtime_fallback: bool = True,
    parse_run_info_fn: Callable[[Path], dict[str, Any]] = parse_run_info,
    parse_value_log_fn: Callable[..., dict[str, Any]] = parse_value_log,
) -> str | None:
    if not log_dir.is_dir():
        return None

    # Prefer an explicit run-level timestamp if strategy runtime persisted it.
    run_info = parse_run_info_fn(log_dir)
    started_day = _coerce_started_day(
        run_info.get("started_at")
        or run_info.get("start_time")
        or run_info.get("startedAt")
        or run_info.get("startTime")
    )
    value_log = log_dir / "value.log"
    if not value_log.is_file():
        return None
    value_data = parse_value_log_fn(log_dir, prefer_log_time=True)
    dates = list(value_data.get("dates", []))
    try:
        mtime_day = _coerce_started_day(
            datetime.fromtimestamp(value_log.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        )
        if not mtime_day:
            return None
    except OSError:
        return None
    if not dates:
        return None
    sorted_dates = sorted(dates)
    latest_date = sorted_dates[-1]
    if started_day and mtime_day <= started_day:
        return started_day
    if mtime_day <= latest_date:
        for dt in sorted_dates:
            if dt >= mtime_day:
                return dt
        return latest_date
    if mtime_day > latest_date:
        if allow_mtime_fallback:
            return mtime_day
        return latest_date
    return latest_date


def _trading_day(value: Any) -> str:
    """Return a timestamp's calendar day in the portfolio's local timezone."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:10]
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_PORTFOLIO_TIMEZONE)
    return parsed.date().isoformat()


def _source_started_day(
    source: _PortfolioSource,
    *,
    infer_started_day_from_pid_fn: Callable[[int], str | None] = _infer_started_day_from_pid,
    infer_started_day_from_log_dir_fn: Callable[..., str | None] = _infer_started_day_from_log_dir,
) -> str | None:
    """Return the source start day when available."""
    snapshot = _safe_dict(source.snapshot)
    explicit_started_day = (
        _coerce_started_day(source.started_at)
        or _coerce_started_day(snapshot.get("started_at"))
        or _coerce_started_day(snapshot.get("instance_started_at"))
        or _coerce_started_day(snapshot.get("start_time"))
        or _coerce_started_day(snapshot.get("startedAt"))
    )

    if str(source.status or "").strip().lower() not in _ACTIVE_TRADING_STATUSES:
        return explicit_started_day

    inferred_started_days: list[str] = []
    updated_started_day = _coerce_started_day(source.updated_at)
    if updated_started_day:
        inferred_started_days.append(updated_started_day)
    if source.pid:
        pid_started = infer_started_day_from_pid_fn(source.pid)
        if pid_started:
            inferred_started_days.append(pid_started)

    if source.log_dir:
        inferred_started = infer_started_day_from_log_dir_fn(
            source.log_dir,
            allow_mtime_fallback=source.pid is not None,
        )
        if inferred_started:
            inferred_started_days.append(inferred_started)

    if inferred_started_days:
        return max(inferred_started_days)
    return explicit_started_day


def _row_date(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        text = _trading_day(value)
        if text:
            return text
    return ""


def _filter_rows_after_source_start(
    rows: list[dict[str, Any]],
    source_started_day: str | None,
    keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Drop log rows that start before the active process start."""
    if not source_started_day:
        return rows

    started_day = _trading_day(source_started_day)
    if not started_day:
        return rows

    filtered: list[dict[str, Any]] = []
    for row in rows:
        dt = _row_date(row, keys)
        if not dt or dt >= started_day:
            filtered.append(row)
    return filtered


def _trim_curve_by_source_start(
    dates: list[str],
    equity: list[float],
    cash: list[float],
    source_started_day: str | None,
) -> tuple[list[str], list[float], list[float]]:
    if not source_started_day:
        return dates, equity, cash

    filtered_dates: list[str] = []
    filtered_equity: list[float] = []
    filtered_cash: list[float] = []
    for dt, value, cash_value in zip(dates, equity, cash, strict=False):
        if dt >= source_started_day:
            filtered_dates.append(dt)
            filtered_equity.append(value)
            filtered_cash.append(cash_value)
    return filtered_dates, filtered_equity, filtered_cash


def _current_user_id(current_user: Any) -> str | None:
    user_id = str(getattr(current_user, "sub", None) or getattr(current_user, "id", "") or "")
    return user_id.strip() or None


def _list_user_instances(
    mgr: LiveTradingManager,
    current_user: Any,
    *,
    include_inactive: bool = False,
) -> list[Mapping[str, object]]:
    user_id = _current_user_id(current_user)
    try:
        instances = mgr.list_instances(user_id=user_id) if user_id else mgr.list_instances()
    except TypeError:
        instances = mgr.list_instances()
    normalized: list[Mapping[str, object]] = []
    for inst in instances:
        if not isinstance(inst, dict):
            continue
        status = str(inst.get("status") or "").strip().lower()
        instance_id = str(inst.get("id") or "").strip()
        if not instance_id or not status:
            if include_inactive:
                normalized.append(inst)
            continue
        effective: Mapping[str, object] = inst
        if status in _ACTIVE_TRADING_STATUSES and hasattr(mgr, "get_instance"):
            try:
                live_instance = mgr.get_instance(instance_id, user_id=user_id)
            except Exception:
                live_instance = None
            if isinstance(live_instance, dict):
                merged = dict(inst)
                merged_status = str(live_instance.get("status") or "").strip().lower()
                if merged_status:
                    status = merged_status
                    merged["status"] = merged_status
                merged_started = str(live_instance.get("started_at") or "").strip()
                if merged_started:
                    merged["started_at"] = merged_started
                merged_updated = str(live_instance.get("updated_at") or "").strip()
                if merged_updated:
                    merged["updated_at"] = merged_updated
                live_pid = _coerce_int(live_instance.get("pid"))
                if live_pid is not None:
                    merged["pid"] = live_pid
                effective = merged
                if include_inactive is False and merged_status not in _ACTIVE_TRADING_STATUSES:
                    continue
        elif not include_inactive and status not in _ACTIVE_TRADING_STATUSES:
            continue
        normalized.append(effective)
    if include_inactive:
        return normalized
    return [
        inst
        for inst in normalized
        if str(inst.get("status") or "").strip().lower() in _ACTIVE_TRADING_STATUSES
    ]


def _as_path(value: Any) -> Path | None:
    text = str(value or "").strip()
    return Path(text).expanduser() if text else None


def _resolve_instance_log_dir(
    inst: Mapping[str, object],
    *,
    find_latest_log_dir_fn: Callable[[Path], Path | None] = find_latest_log_dir,
    get_strategy_dir_fn: Callable[[str], Path] = get_strategy_dir,
) -> Path | None:
    explicit_log_dir = _as_path(inst.get("log_dir"))
    if explicit_log_dir is not None and explicit_log_dir.is_dir():
        return explicit_log_dir

    runtime_dir = _as_path(inst.get("runtime_dir"))
    if runtime_dir is not None:
        latest = find_latest_log_dir_fn(runtime_dir)
        if latest:
            return Path(latest)

    try:
        strategy_id = inst["strategy_id"]
        if not isinstance(strategy_id, str):
            return None
        strategy_dir = Path(get_strategy_dir_fn(strategy_id))
    except ValueError:
        return None
    latest = find_latest_log_dir_fn(strategy_dir)
    return Path(latest) if latest else None


def _manager_instances_by_id(
    mgr: LiveTradingManager,
    user_id: str | None,
    instance_ids: list[str],
) -> dict[str, Mapping[str, object]] | None:
    """Load one validated instance snapshot, with the legacy manager fallback."""
    get_active_instances = getattr(mgr, "get_active_instances", None)
    if callable(get_active_instances):
        try:
            instances = get_active_instances(instance_ids, user_id=user_id)
        except TypeError:
            try:
                instances = get_active_instances(instance_ids)
            except Exception:
                instances = None
        except Exception:
            instances = None
        if instances is not None:
            return {
                str(instance.get("id") or "").strip(): instance
                for instance in instances
                if isinstance(instance, dict) and str(instance.get("id") or "").strip()
            }

    list_instances = getattr(mgr, "list_instances", None)
    if not callable(list_instances):
        return None
    try:
        instances = list_instances(user_id=user_id) if user_id else list_instances()
    except TypeError:
        try:
            instances = list_instances()
        except Exception:
            return None
    except Exception:
        return None

    return {
        str(instance.get("id") or "").strip(): instance
        for instance in instances
        if isinstance(instance, dict) and str(instance.get("id") or "").strip()
    }
