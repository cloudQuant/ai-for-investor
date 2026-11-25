"""Monitoring owner-control scalar validation."""

from __future__ import annotations

from typing import Any


def cancel_count(value: Any, *, maximum: int) -> int | None:
    if type(value) is not int or value < 0 or value > maximum:
        return None
    return value


def cancel_text(value: Any, *, max_bytes: int) -> bool:
    if type(value) is not str or not value or value != value.strip():
        return False
    try:
        return len(value.encode("utf-8", errors="strict")) <= max_bytes and value.isprintable()
    except UnicodeEncodeError:
        return False
