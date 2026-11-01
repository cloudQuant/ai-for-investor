"""Managed-paper execution and gateway asset metadata for AI risk checks.

AI live-order submission is unavailable until an authorized service-v2 scope is configured.
"""

from __future__ import annotations

import logging
from typing import Any

from app.schemas.ai_trading import TradingIntent
from app.services.trading_asset_info_service import (
    normalize_asset_spec,
    query_gateway_asset_spec,
    symbol_aliases,
)

logger = logging.getLogger(__name__)


def _managed_paper_message(result: dict[str, Any]) -> str:
    state = result.get("state")
    intent_id = result.get("intent_id", "")
    if state == "FILLED":
        return f"managed paper order filled: {intent_id}"
    if state == "PARTIALLY_FILLED":
        return f"managed paper order partially filled: {intent_id}"
    if state == "ACKED":
        return f"managed paper order accepted and awaiting completion: {intent_id}"
    if state == "REJECTED":
        return f"managed paper order rejected: {intent_id}"
    if state == "CANCELLED":
        return f"managed paper order cancelled: {intent_id}"
    return f"managed paper order state is unknown; reconcile before retrying: {intent_id}"


def _managed_paper_error_message(code: str) -> str:
    if code == "LEGACY_PAPER_CUTOVER_NOT_READY":
        return "旧模拟账户含未迁移状态或与托管账户初始条件不一致，已拒绝提交。"
    if code == "PAPER_ACCOUNT_REQUIRED":
        return "请选择已授权的纸面账户，未创建默认账户。"
    if code == "UNSUPPORTED_PAPER_ACTION":
        return "托管纸面执行暂不支持该交易动作，未提交。"
    return f"托管纸面执行不可用（{code}），未使用旧撮合回退。"


class DirectOrderService:
    """Submits managed-paper intents and exposes gateway asset metadata."""

    async def execute_paper_trade(
        self,
        intent: TradingIntent,
        user_id: str,
        account_id: str | None = None,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Submit one confirmed AI trade through the configured paper owner.

        Args:
            intent: The parsed trading intent.
            user_id: The user's ID.
            account_id: Required legacy account selector mapped by trusted config.
            operation_id: Stable AI ``trade_id`` reused for retries and confirm.

        Returns:
            Execution result containing the durable managed order projection.
        """
        if not operation_id:
            return {
                "success": False,
                "error": "stable_operation_id_required",
                "message": "AI 纸面订单缺少稳定交易编号，未提交。",
            }
        try:
            from app.services.managed_paper_adapter import (
                ManagedPaperOrderAdapter,
                ManagedPaperOrderError,
            )
        except Exception as error:
            return {
                "success": False,
                "error": type(error).__name__,
                "message": "托管纸面执行适配器不可用，未使用旧撮合回退。",
            }
        try:
            result = await ManagedPaperOrderAdapter().submit_ai(
                subject=user_id,
                legacy_account_id=account_id,
                intent=intent,
                trade_id=operation_id,
            )
            state = result.get("state")
            result["success"] = state in {
                "ACKED",
                "PARTIALLY_FILLED",
                "FILLED",
            }
            result["type"] = "managed_paper_trade"
            result["message"] = _managed_paper_message(result)
            return result
        except ManagedPaperOrderError as error:
            return {
                "success": False,
                "error": error.code,
                "message": _managed_paper_error_message(error.code),
            }
        except Exception as error:
            logger.error("Managed paper trade failed: %s", type(error).__name__)
            return {
                "success": False,
                "error": type(error).__name__,
                "message": "托管纸面执行异常，结果未确认；请先查询订单状态再重试。",
            }

    def _gateway_asset_spec(
        self,
        gateway_id: str | None,
        symbol: str | None,
    ) -> dict[str, Any]:
        if not gateway_id or not symbol:
            return {}
        try:
            gateway = self._get_gateways_dict().get(gateway_id)
        except Exception:
            gateway = None
        if not isinstance(gateway, dict):
            return {}

        merged: dict[str, Any] = {}
        for source in self._gateway_metadata_sources(gateway):
            spec = self._asset_spec_from_metadata(source, symbol)
            if spec:
                merged.update(spec)
        gateway_spec = query_gateway_asset_spec(gateway, symbol)
        if gateway_spec:
            merged.update(gateway_spec)
        return normalize_asset_spec(
            merged,
            symbol=symbol,
            source=str(merged.get("source") or "direct_order"),
        )

    @classmethod
    def _gateway_metadata_sources(cls, gateway: dict[str, Any]) -> list[Any]:
        sources: list[Any] = [gateway]
        config = gateway.get("config")
        if config is not None:
            sources.append(config)
        params = gateway.get("params")
        if isinstance(params, dict):
            sources.append(params)
        if config is not None:
            config_params = cls._source_field_value(config, "params")
            if isinstance(config_params, dict):
                sources.append(config_params)
        return sources

    @classmethod
    def _asset_spec_from_metadata(cls, source: Any, symbol: str) -> dict[str, Any]:
        aliases = symbol_aliases(symbol)
        for container_name in ("contract_metadata", "contracts", "contract_specs", "symbol_specs"):
            container = cls._source_field_value(source, container_name)
            if not isinstance(container, dict):
                continue
            for alias in aliases:
                item = container.get(alias)
                if isinstance(item, dict):
                    return dict(item)
        return {}

    @staticmethod
    def _source_field_value(source: Any, field: str) -> Any:
        if isinstance(source, dict):
            return source.get(field)
        return getattr(source, field, None)

    def _get_gateways_dict(self) -> dict[str, Any]:
        """Get gateway metadata for live risk enrichment."""
        try:
            from app.services.live_trading_manager import get_live_trading_manager

            manager = get_live_trading_manager()
            return manager._gateways
        except Exception:
            return {}
