"""Runtime invariant checks that stay active under ``python -O``."""

from __future__ import annotations

import logging
from typing import TypeVar

T = TypeVar("T")


def require_present(value: T | None, message: str = "Expected non-None invariant value") -> T:
    """Return ``value`` if not ``None``, otherwise raise ``RuntimeError``."""
    if value is None:
        raise RuntimeError(message)
    return value


def require_instance(value: object, expected_type: type[T], message: str | None = None) -> T:
    """Return ``value`` if it is an instance of ``expected_type``, else raise ``TypeError``."""
    if not isinstance(value, expected_type):
        raise TypeError(message or f"Expected {expected_type.__name__}, got {type(value).__name__}")
    return value


def ensure_invariant(condition: bool, message: str = "Invariant check failed") -> None:
    """Raise ``RuntimeError`` if ``condition`` is falsy."""
    if not condition:
        raise RuntimeError(message)


def log_suppressed(logger_name: str, context: str, exc: BaseException) -> None:
    """Log a non-fatal exception caught on a cleanup or fallback path."""
    logging.getLogger(logger_name).debug("%s: %s", context, exc)
