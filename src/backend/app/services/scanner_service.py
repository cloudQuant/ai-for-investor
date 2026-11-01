from __future__ import annotations

import ast
from typing import Any

from app.services.scanner_universe import SCANNER_DATA_UNAVAILABLE, ScannerUniverseService

_ALLOWED_NAMES = {
    "price",
    "volume",
    "amount",
    "change_pct",
    "indicator",
    "factor",
    "news_sentiment",
    "portfolio_exposure",
    "lookback_days",
    "timeframe",
}
_ALLOWED_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.Compare,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.Gt,
    ast.GtE,
    ast.Lt,
    ast.LtE,
    ast.Eq,
    ast.NotEq,
)


class ScannerService:
    def __init__(self, universe_service: ScannerUniverseService | None = None) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self.universe_service = universe_service or ScannerUniverseService()

    def run(
        self,
        universe: list[str],
        condition: str,
        *,
        lookback_days: int = 20,
        timeframe: str = "1d",
        universe_pool_id: str | None = None,
        user_id: str = "default",
    ) -> dict[str, Any]:
        parsed = ast.parse(condition, mode="eval")
        for node in ast.walk(parsed):
            if not isinstance(node, _ALLOWED_NODES):
                raise ValueError("unsafe_expression")
            if isinstance(node, ast.Name) and node.id not in _ALLOWED_NAMES:
                raise ValueError("unsafe_expression")
        # Spot snapshots do not yet have verified source, observation-time, and
        # unit contracts. Fail before resolving a provider or touching caches/tasks.
        raise ValueError(SCANNER_DATA_UNAVAILABLE)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        payload = self._tasks.get(task_id)
        if payload is None:
            return None
        result = dict(payload)
        if result.get("data_status") != "verified":
            result["legacy_status"] = result.get("status")
            result["status"] = "legacy_unverified"
            result["data_status"] = "legacy_unverified"
        return result


_scanner_service = ScannerService()


def get_scanner_service() -> ScannerService:
    return _scanner_service
