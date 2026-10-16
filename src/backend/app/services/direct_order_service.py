"""Managed paper execution and gateway asset metadata for AI risk checks."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from math import isfinite
from typing import Any

from app.schemas.ai_trading import OrderType, TradeAction, TradingIntent
from app.services.trading_asset_info_service import (
    normalize_asset_spec,
    query_gateway_asset_spec,
    symbol_aliases,
)

logger = logging.getLogger(__name__)


class DirectOrderService:
    """Executes trading intents against paper or live accounts."""

    async def execute_paper_trade(
        self,
        intent: TradingIntent,
        user_id: str,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a trade against the paper trading system.

        Args:
            intent: The parsed trading intent.
            user_id: The user's ID.
            account_id: Optional paper trading account ID. If None, uses
                the user's first active account or creates one.

        Returns:
            Execution result dict with success status and order details.
        """
        from app.services.paper_trading_service import PaperTradingService

        service = PaperTradingService()

        try:
            # Resolve account
            resolved_account_id = await self._resolve_paper_account(service, user_id, account_id)

            if intent.action == TradeAction.QUERY:
                return await self._query_positions(service, resolved_account_id)

            if intent.action == TradeAction.CLOSE:
                return await self._close_position(service, resolved_account_id, intent)

            if intent.action not in (TradeAction.BUY, TradeAction.SELL):
                return {
                    "success": False,
                    "error": f"Unsupported action for paper trading: {intent.action.value}",
                }

            # Map intent to paper trading order params
            side = "buy" if intent.action == TradeAction.BUY else "sell"
            order_type_str = self._map_order_type(intent.order_type)
            size = self._normalise_order_size(intent.quantity, default=None)

            stop_price = (
                intent.stop_loss
                if intent.order_type
                in {
                    OrderType.STOP,
                    OrderType.STOP_LIMIT,
                }
                else None
            )

            order = await service.submit_order(
                account_id=resolved_account_id,
                symbol=intent.symbol or "UNKNOWN",
                order_type=order_type_str,
                side=side,
                size=size,
                price=intent.price,
                stop_price=stop_price,
                limit_price=intent.price if intent.order_type == OrderType.STOP_LIMIT else None,
            )

            return {
                "success": True,
                "type": "paper_trade",
                "order_id": order.id,
                "account_id": resolved_account_id,
                "action": intent.action.value,
                "symbol": intent.symbol,
                "quantity": size,
                "price": intent.price,
                "order_type": order_type_str,
                "side": side,
                "status": order.status if hasattr(order, "status") else "submitted",
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "message": (
                    f"模拟订单已提交: {side} {size} {intent.symbol} @ {intent.price or '市价'}"
                ),
            }

        except ValueError as e:
            return {"success": False, "error": str(e), "message": f"下单失败: {e}"}
        except Exception as e:
            logger.error("Paper trade execution failed: %s", e, exc_info=True)
            return {"success": False, "error": str(e), "message": f"执行异常: {e}"}



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

    @classmethod
    def _first_number(cls, *values: Any, default: float | None = None) -> float | None:
        for value in values:
            if value in (None, ""):
                continue
            try:
                number = float(value)
            except (OverflowError, TypeError, ValueError):
                continue
            if isfinite(number):
                return number
        return default








    @staticmethod
    def _source_field_value(source: Any, field: str) -> Any:
        if isinstance(source, dict):
            return source.get(field)
        return getattr(source, field, None)




    @staticmethod
    def _normalise_order_size(
        value: Any, *, default: float | None = 1.0, integer_required: bool = False
    ) -> int | float:
        raw = default if value in (None, "") else value
        size = DirectOrderService._first_number(raw)
        if size is None:
            raise ValueError("quantity must be a positive number")
        if size <= 0:
            raise ValueError("quantity must be positive")
        if integer_required:
            if abs(size - round(size)) > 1e-12:
                raise ValueError("CTP/futures order quantity must be an integer lot size")
            return int(round(size))
        return int(round(size)) if abs(size - round(size)) <= 1e-12 else size









    @staticmethod
    def _symbol_candidates(value: Any) -> set[str]:
        raw = str(value or "").strip()
        if not raw:
            return set()
        candidates = set(symbol_aliases(raw))
        if "." in raw:
            left, right = raw.split(".", 1)
            candidates.update(
                {left, left.upper(), left.lower(), right, right.upper(), right.lower()}
            )
        if "_" in raw:
            left, right = raw.split("_", 1)
            candidates.update(
                {left, left.upper(), left.lower(), right, right.upper(), right.lower()}
            )
        return {item.upper() for item in candidates if item}

    @staticmethod
    def _position_symbol(row: dict[str, Any]) -> str:
        return str(
            row.get("data_name")
            or row.get("symbol")
            or row.get("instrument")
            or row.get("instrument_id")
            or row.get("InstrumentID")
            or row.get("instId")
            or row.get("contract_symbol")
            or row.get("position_symbol_name")
            or row.get("symbol_name")
            or row.get("localSymbol")
            or row.get("local_symbol")
            or row.get("contractDesc")
            or row.get("contract_desc")
            or row.get("description")
            or row.get("ticker")
            or row.get("conid")
            or ""
        ).strip()

    @staticmethod
    def _position_size(row: dict[str, Any]) -> float:
        for key in (
            "size",
            "volume",
            "position",
            "qty",
            "quantity",
            "trade_volume",
            "position_volume",
            "positionAmt",
            "pos",
            "availPos",
            "pa",
            "Position",
            "Volume",
            "Qty",
            "Quantity",
            "TradeVolume",
        ):
            value = row.get(key)
            if value in (None, ""):
                continue
            size = DirectOrderService._first_number(value)
            if size is not None:
                return size
        return 0.0

    @classmethod
    def _position_direction(cls, row: dict[str, Any]) -> str:
        for key in (
            "direction",
            "side",
            "position_side",
            "position_direction",
            "positionSide",
            "positionIdx",
            "position_idx",
            "posSide",
            "PositionSide",
            "PosiDirection",
            "posi_direction",
            "trade_action",
            "position_type",
            "type",
        ):
            direction = cls._position_direction_from_value(key, row.get(key))
            if direction:
                return direction
        size = cls._position_size(row)
        return "short" if size < 0 else "long"

    @staticmethod
    def _position_direction_from_value(key: str, value: Any) -> str | None:
        text = str(value or "").strip().lower()
        if not text:
            return None
        if text in {"short", "sell", "sold", "position_type_sell", "deal_type_sell"}:
            return "short"
        if text in {"long", "buy", "bought", "position_type_buy", "deal_type_buy"}:
            return "long"

        key_text = str(key or "").strip().lower()
        number = DirectOrderService._first_number(text)
        code = int(number) if number is not None else None
        if key_text in {"trade_action", "position_type", "type"}:
            if code == 0:
                return "long"
            if code == 1:
                return "short"
        if key_text in {"posidirection", "posi_direction", "position_direction"}:
            if code == 2:
                return "long"
            if code == 3:
                return "short"
        if key_text in {"positionidx", "position_idx"}:
            if code == 1:
                return "long"
            if code == 2:
                return "short"
        return None

    @classmethod
    def _desired_close_direction(cls, intent: TradingIntent) -> str | None:
        params = intent.additional_params if isinstance(intent.additional_params, dict) else {}
        for key in (
            "position_side",
            "positionSide",
            "posSide",
            "close_side",
            "closeSide",
            "side_to_close",
            "sideToClose",
            "target_side",
            "targetSide",
            "position_direction",
            "positionDirection",
            "direction",
            "side",
        ):
            direction = cls._position_direction_from_value(key, params.get(key))
            if direction:
                return direction
        return cls._desired_close_direction_from_text(intent.raw_input)

    @staticmethod
    def _desired_close_direction_from_text(value: Any) -> str | None:
        text = str(value or "").strip().lower()
        if not text:
            return None

        long_markers = (
            "平多",
            "平多仓",
            "平掉多",
            "平掉多仓",
            "平掉多单",
            "多头平仓",
            "多单平仓",
            "多仓",
            "多单",
            "多头",
            "close long",
            "close the long",
            "sell long",
        )
        short_markers = (
            "平空",
            "平空仓",
            "平掉空",
            "平掉空仓",
            "平掉空单",
            "空头平仓",
            "空单平仓",
            "空仓",
            "空单",
            "空头",
            "close short",
            "close the short",
            "cover short",
            "buy to cover",
        )
        wants_long = any(marker in text for marker in long_markers)
        wants_short = any(marker in text for marker in short_markers)
        if wants_long == wants_short:
            return None
        return "long" if wants_long else "short"


    @classmethod
    def _matching_close_positions(
        cls,
        positions: list[dict[str, Any]],
        symbol: str | None,
        desired_direction: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        nonzero = [pos for pos in positions if abs(cls._position_size(pos)) > 0]
        if symbol:
            requested = cls._symbol_candidates(symbol)
            matches = [
                pos
                for pos in nonzero
                if requested and requested & cls._symbol_candidates(cls._position_symbol(pos))
            ]
        else:
            matches = nonzero

        if desired_direction in {"long", "short"}:
            matches = [pos for pos in matches if cls._position_direction(pos) == desired_direction]

        if not matches:
            return [], "no_position"
        if not symbol and len(matches) > 1:
            return [], "ambiguous_position"

        directions = {cls._position_direction(pos) for pos in matches}
        if len(directions) > 1:
            return [], "ambiguous_position"
        return matches, None


    @classmethod
    def _requested_close_size(cls, intent: TradingIntent, available_size: float) -> float:
        available = abs(float(available_size or 0.0))
        if available <= 0:
            raise ValueError("no available position size to close")
        if intent.quantity in (None, ""):
            return available
        requested = cls._first_number(intent.quantity)
        if requested is None or requested <= 0:
            raise ValueError("close quantity must be positive")
        if requested > available + 1e-12:
            raise ValueError(
                f"close quantity {requested} exceeds available position size {available}"
            )
        return min(requested, available)










    def _get_gateways_dict(self) -> dict[str, Any]:
        """Get the gateways dict from LiveTradingManager."""
        try:
            from app.services.live_trading_manager import get_live_trading_manager

            manager = get_live_trading_manager()
            return manager._gateways
        except Exception:
            return {}





    async def _resolve_paper_account(
        self,
        service: Any,
        user_id: str,
        account_id: str | None,
    ) -> str:
        """Resolve or create a paper trading account for the user."""
        if account_id:
            return account_id

        # Try to find user's first active account
        accounts, _ = await service.list_accounts(
            user_id=user_id,
            limit=1,
            offset=0,
        )
        if accounts:
            return accounts[0].id

        # Create a default AI trading account
        account = await service.create_account(
            user_id=user_id,
            name="AI Trading 模拟账户",
            initial_cash=100000.0,
            commission_rate=0.001,
            slippage_rate=0.001,
        )
        return account.id

    async def _query_positions(self, service: Any, account_id: str) -> dict[str, Any]:
        """Query current positions for an account."""
        try:
            positions, _ = await service.list_positions(
                filters={"account_id": account_id},
                limit=50,
                offset=0,
            )
            position_list = [
                {
                    "symbol": p.symbol,
                    "size": p.size,
                    "avg_price": p.avg_price,
                    "unrealized_pnl": p.unrealized_pnl,
                }
                for p in positions
            ]
            return {
                "success": True,
                "type": "query",
                "account_id": account_id,
                "positions": position_list,
                "message": (
                    f"当前持仓 {len(position_list)} 个品种" if position_list else "当前无持仓"
                ),
            }
        except Exception as e:
            return {
                "success": False,
                "type": "query",
                "positions": [],
                "error": str(e),
                "message": f"查询持仓失败: {e}",
            }

    async def _close_position(
        self, service: Any, account_id: str, intent: TradingIntent
    ) -> dict[str, Any]:
        """Close a position by submitting a counter-order."""
        try:
            positions, _ = await service.list_positions(
                filters={"account_id": account_id},
                limit=50,
                offset=0,
            )
            desired_direction = self._desired_close_direction(intent)
            position_rows = [self._paper_position_row(p) for p in positions]
            matches, select_error = self._matching_close_positions(
                position_rows,
                intent.symbol,
                desired_direction=desired_direction,
            )

            if not matches:
                if select_error == "ambiguous_position":
                    return {
                        "success": False,
                        "error": "ambiguous_position",
                        "message": f"{intent.symbol or '当前账户'} 存在多个可平持仓，请指定合约或方向",
                    }
                return {
                    "success": False,
                    "error": "no_position",
                    "message": f"未找到 {intent.symbol or '指定品种'} 的持仓",
                }

            # Submit counter-order to close
            target_row = matches[0]
            target = target_row["_paper_position"]
            side = "sell" if self._position_direction(target_row) == "long" else "buy"
            try:
                size = self._requested_close_size(intent, abs(self._position_size(target_row)))
                size = self._normalise_order_size(size)
            except ValueError as e:
                return {"success": False, "error": "invalid_order", "message": str(e)}

            order = await service.submit_order(
                account_id=account_id,
                symbol=target.symbol,
                order_type="market",
                side=side,
                size=size,
            )

            return {
                "success": True,
                "type": "close_position",
                "order_id": order.id,
                "symbol": target.symbol,
                "size": size,
                "side": side,
                "message": f"平仓订单已提交: {side} {size} {target.symbol}",
            }
        except Exception as e:
            return {"success": False, "error": str(e), "message": f"平仓失败: {e}"}

    @classmethod
    def _paper_position_row(cls, position: Any) -> dict[str, Any]:
        row: dict[str, Any] = {
            "_paper_position": position,
            "symbol": getattr(position, "symbol", ""),
            "size": getattr(position, "size", 0.0),
        }
        for field in (
            "direction",
            "side",
            "position_side",
            "positionSide",
            "posSide",
            "position_direction",
        ):
            value = getattr(position, field, None)
            if isinstance(value, (str, int, float)) and value not in (None, ""):
                row[field] = value
        return row

    @staticmethod
    def _map_order_type(order_type: OrderType) -> str:
        """Map schema OrderType to paper trading order type string."""
        mapping = {
            OrderType.MARKET: "market",
            OrderType.LIMIT: "limit",
            OrderType.STOP: "stop",
            OrderType.STOP_LIMIT: "stop_limit",
        }
        return mapping.get(order_type, "market")
