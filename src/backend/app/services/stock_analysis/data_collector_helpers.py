"""Stock-analysis financial scalar helpers."""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any


def text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def report_date(value: Any) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) != 8:
        return None
    try:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:])).isoformat()
    except ValueError:
        return None


def number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def has_financial_data(financials: dict[str, Any]) -> bool:
    return bool(financials.get("annual") or financials.get("quarterly"))


def infer_exchange(symbol: str) -> str | None:
    code = symbol.strip().upper()
    if "." in code:
        code = code.split(".", 1)[0]
    if code.startswith(("6", "9")):
        return "SH"
    if code.startswith(("0", "2", "3")):
        return "SZ"
    if code.startswith(("4", "8")):
        return "BJ"
    return None
