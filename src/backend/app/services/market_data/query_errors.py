"""Safe provider error-code projection."""

from __future__ import annotations

from app.services.market_data.query_cursor import _require_text


def provider_error_code(exc: Exception) -> str:
    candidate = getattr(exc, "code", None)
    if isinstance(candidate, str):
        try:
            return _require_text(candidate, field_name="provider error code", maximum=128)
        except (TypeError, ValueError):
            pass
    return "PROVIDER_FETCH_FAILED"
