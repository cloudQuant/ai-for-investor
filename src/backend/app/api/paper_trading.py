"""
Paper trading API routes.

Provides a full paper trading workflow: accounts, orders, positions, trades, and WebSocket updates.
"""

import typing

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.websockets import WebSocket, WebSocketDisconnect

from app.api.deps import get_current_user, get_websocket_current_user
from app.schemas.paper_trading import (
    AccountCreate,
    AccountListResponse,
    AccountResponse,
    ManagedPaperCutoverRequest,
    OrderListResponse,
    OrderRequest,
    OrderResponse,
    PositionListResponse,
    PositionResponse,
    TradeListResponse,
)
from app.services.paper_trading_service import PaperTradingService
from app.services.managed_paper_adapter import (
    ManagedPaperOrderAdapter,
    ManagedPaperOrderError,
)
from app.services.legacy_paper_migration import LegacyPaperInventoryError
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


def get_paper_trading_service() -> typing.Any:
    """Dependency injection for PaperTradingService.

    Returns:
        PaperTradingService: An instance of the paper trading service.
    """
    return PaperTradingService()


def get_managed_paper_order_adapter() -> ManagedPaperOrderAdapter:
    """Return the application adapter over the configured service-read owner."""
    return ManagedPaperOrderAdapter()


def _legacy_source(response: Response) -> None:
    """Make the source of historical ledger views explicit to clients."""
    response.headers["X-Paper-Data-Source"] = "legacy"


def _managed_source(response: Response) -> None:
    response.headers["X-Paper-Data-Source"] = "managed_paper"


def _managed_order_http_error(error: ManagedPaperOrderError) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, **error.details},
    )


def _legacy_writer_http_error(error: LegacyPaperInventoryError) -> HTTPException:
    code = error.code
    error_status = (
        status.HTTP_503_SERVICE_UNAVAILABLE
        if code.endswith("UNAVAILABLE")
        else status.HTTP_409_CONFLICT
    )
    return HTTPException(status_code=error_status, detail={"code": code, **error.details})


# ==================== Paper Account API ====================


@router.post("/accounts", response_model=AccountResponse, summary="Create paper trading account")
async def create_paper_account(
    request: AccountCreate,
    response: Response,
    current_user: typing.Any = Depends(get_current_user),
    service: PaperTradingService = Depends(get_paper_trading_service),
) -> typing.Any:
    """Create a new paper trading account.

    Args:
        request: The account creation request containing name, initial_cash,
            commission_rate, and slippage_rate.
        current_user: The authenticated user.
        service: The paper trading service.

    Returns:
        AccountResponse: The created account details.
    """
    _legacy_source(response)
    account = await service.create_account(
        user_id=current_user.sub,
        name=request.name,
        initial_cash=request.initial_cash,
        commission_rate=request.commission_rate,
        slippage_rate=request.slippage_rate,
    )
    return account


@router.post(
    "/accounts/{account_id}/managed-cutover",
    response_model=None,
    summary="Confirm an eligible legacy paper account for managed execution",
)
async def cutover_managed_paper_account(
    account_id: str,
    request: ManagedPaperCutoverRequest,
    response: Response,
    current_user: typing.Any = Depends(get_current_user),
    adapter: ManagedPaperOrderAdapter = Depends(get_managed_paper_order_adapter),
) -> dict[str, typing.Any]:
    """Persist explicit eligibility for an empty or imported legacy account."""

    if request.confirmed is not True:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "EXPLICIT_CUTOVER_CONFIRMATION_REQUIRED"},
        )
    try:
        result = await adapter.prepare_cutover(
            subject=current_user.sub,
            legacy_account_id=account_id,
        )
    except ManagedPaperOrderError as error:
        raise _managed_order_http_error(error) from error
    response.headers["X-Paper-Data-Source"] = "managed_paper"
    return result


@router.get("/accounts", response_model=AccountListResponse, summary="List paper trading accounts")
async def list_paper_accounts(
    response: Response,
    current_user: typing.Any = Depends(get_current_user),
    service: PaperTradingService = Depends(get_paper_trading_service),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> typing.Any:
    """List paper trading accounts for the current user.

    Args:
        current_user: The authenticated user.
        service: The paper trading service.
        limit: Maximum number of accounts to return (1-100).
        offset: Number of accounts to skip.

    Returns:
        AccountListResponse: Response containing total count and account list.
    """
    _legacy_source(response)
    accounts, total = await service.list_accounts(
        user_id=current_user.sub,
        limit=limit,
        offset=offset,
    )
    return AccountListResponse(total=total, items=accounts)


@router.get(
    "/accounts/{account_id}",
    response_model=AccountResponse,
    summary="Get paper trading account details",
)
async def get_paper_account(
    account_id: str,
    response: Response,
    current_user: typing.Any = Depends(get_current_user),
    service: PaperTradingService = Depends(get_paper_trading_service),
) -> typing.Any:
    """Get a paper trading account by ID.

    Args:
        account_id: The unique identifier of the account.
        current_user: The authenticated user.
        service: The paper trading service.

    Returns:
        AccountResponse: The account details.

    Raises:
        HTTPException: If the account does not exist (404) or user lacks
            permission to access it (403).
    """
    _legacy_source(response)
    account = await service.get_account(account_id)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Paper trading account not found"
        )

    # Check permissions
    if account.user_id != current_user.sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No permission to access this account"
        )

    return account


@router.delete(
    "/accounts/{account_id}", summary="Delete paper trading account", response_model=None
)
async def delete_paper_account(
    account_id: str,
    response: Response,
    current_user: typing.Any = Depends(get_current_user),
    service: PaperTradingService = Depends(get_paper_trading_service),
) -> typing.Any:
    """Delete a paper trading account.

    Args:
        account_id: The unique identifier of the account to delete.
        current_user: The authenticated user.
        service: The paper trading service.

    Returns:
        A message confirming deletion.

    Raises:
        HTTPException: If the account does not exist or user lacks permission (404).
    """
    try:
        success = await service.delete_account(account_id, current_user.sub)
    except LegacyPaperInventoryError as error:
        raise _legacy_writer_http_error(error) from None
    _legacy_source(response)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paper trading account not found or no permission to delete",
        )
    return {"message": "Account deleted successfully"}


# ==================== Paper Order API ====================


@router.post("/orders", response_model=None, summary="Submit managed paper trading order")
async def submit_paper_order(
    request: OrderRequest,
    http_request: Request,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=256),
    current_user: typing.Any = Depends(get_current_user),
    adapter: ManagedPaperOrderAdapter = Depends(get_managed_paper_order_adapter),
) -> typing.Any:
    """Submit a manual order through the configured managed-paper owner.

    Args:
        request: The order request containing account_id, symbol, side,
            order_type, quantity, price, etc.
        current_user: The authenticated user.
        service: The paper trading service.

    Returns:
        The durable managed order state, linked to the legacy selector account.
    """
    try:
        result = await adapter.submit_manual(
            subject=current_user.sub,
            request=request,
            idempotency_key=idempotency_key,
        )
    except ManagedPaperOrderError as error:
        raise _managed_order_http_error(error) from error
    _managed_source(response)
    result["status_url"] = str(
        http_request.url_for(
            "get_managed_paper_order", intent_id=result["intent_id"]
        ).include_query_params(account_id=request.account_id)
    )
    return result


@router.get("/orders", response_model=OrderListResponse, summary="List paper trading orders")
async def list_paper_orders(
    response: Response,
    current_user: typing.Any = Depends(get_current_user),
    service: PaperTradingService = Depends(get_paper_trading_service),
    account_id: str | None = Query(None, description="Account ID"),
    symbol: str | None = Query(None, description="Trading symbol"),
    status: str | None = Query(None, description="Order status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> typing.Any:
    """List paper trading orders with optional filters.

    Args:
        current_user: The authenticated user.
        service: The paper trading service.
        account_id: Filter by account ID.
        symbol: Filter by trading symbol.
        status: Filter by order status.
        limit: Maximum number of orders to return (1-100).
        offset: Number of orders to skip.

    Returns:
        OrderListResponse: Response containing total count and order list.
    """
    _legacy_source(response)
    filters = {"user_id": current_user.sub}
    if account_id:
        filters["account_id"] = account_id
    if symbol:
        filters["symbol"] = symbol
    if status:
        filters["status"] = status

    orders, total = await service.list_orders(
        filters=filters,
        limit=limit,
        offset=offset,
    )
    return OrderListResponse(total=total, items=orders)


@router.get(
    "/orders/{order_id}", response_model=OrderResponse, summary="Get paper trading order details"
)
async def get_paper_order(
    order_id: str,
    response: Response,
    current_user: typing.Any = Depends(get_current_user),
    service: PaperTradingService = Depends(get_paper_trading_service),
) -> typing.Any:
    """Get a paper trading order by ID.

    Args:
        order_id: The unique identifier of the order.
        current_user: The authenticated user.
        service: The paper trading service.

    Returns:
        OrderResponse: The order details.

    Raises:
        HTTPException: If the order does not exist (404) or user lacks
            permission to access it (403).
    """
    _legacy_source(response)
    order = await service.get_order(order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Paper trading order not found"
        )

    # Check permissions
    account = await service.get_account(order.account_id)
    if not account or account.user_id != current_user.sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No permission to access this order"
        )

    return order


@router.get("/managed-orders/{intent_id}", response_model=None, summary="Read managed paper order")
async def get_managed_paper_order(
    intent_id: str,
    response: Response,
    account_id: str = Query(..., min_length=1, max_length=256, description="Legacy account selector"),
    current_user: typing.Any = Depends(get_current_user),
    adapter: ManagedPaperOrderAdapter = Depends(get_managed_paper_order_adapter),
) -> typing.Any:
    """Read a managed journal record without mutating or migrating either ledger."""
    try:
        result = await adapter.read_order(
            subject=current_user.sub,
            legacy_account_id=account_id,
            intent_id=intent_id,
        )
    except ManagedPaperOrderError as error:
        raise _managed_order_http_error(error) from error
    _managed_source(response)
    return result


@router.delete("/orders/{order_id}", summary="Cancel paper trading order", response_model=None)
async def cancel_paper_order(
    order_id: str,
    response: Response,
    current_user: typing.Any = Depends(get_current_user),
    service: PaperTradingService = Depends(get_paper_trading_service),
) -> typing.Any:
    """Cancel a pending paper trading order.

    Args:
        order_id: The unique identifier of the order to cancel.
        current_user: The authenticated user.
        service: The paper trading service.

    Returns:
        A message confirming cancellation.

    Raises:
        HTTPException: If the order does not exist, is already filled,
            or user lacks permission (404).
    """
    try:
        success = await service.cancel_order(order_id, current_user.sub)
    except LegacyPaperInventoryError as error:
        raise _legacy_writer_http_error(error) from None
    _legacy_source(response)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paper trading order not found, already filled, or no permission to cancel",
        )
    return {"message": "Order has been cancelled"}


# ==================== Paper Position API ====================


@router.get(
    "/positions", response_model=PositionListResponse, summary="List paper trading positions"
)
async def list_paper_positions(
    response: Response,
    current_user: typing.Any = Depends(get_current_user),
    service: PaperTradingService = Depends(get_paper_trading_service),
    account_id: str | None = Query(None, description="Account ID"),
    symbol: str | None = Query(None, description="Trading symbol"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> typing.Any:
    """List paper trading positions with optional filters.

    Args:
        current_user: The authenticated user.
        service: The paper trading service.
        account_id: Filter by account ID.
        symbol: Filter by trading symbol.
        limit: Maximum number of positions to return (1-100).
        offset: Number of positions to skip.

    Returns:
        PositionListResponse: Response containing total count and position list.
    """
    _legacy_source(response)
    filters = {"user_id": current_user.sub}
    if account_id:
        filters["account_id"] = account_id
    if symbol:
        filters["symbol"] = symbol

    positions, total = await service.list_positions(
        filters=filters,
        limit=limit,
        offset=offset,
    )
    return PositionListResponse(total=total, items=positions)


@router.get(
    "/positions/{position_id}",
    response_model=PositionResponse,
    summary="Get paper trading position details",
)
async def get_paper_position(
    position_id: str,
    response: Response,
    current_user: typing.Any = Depends(get_current_user),
    service: PaperTradingService = Depends(get_paper_trading_service),
) -> typing.Any:
    """Get a paper trading position by ID.

    Args:
        position_id: The unique identifier of the position.
        current_user: The authenticated user.
        service: The paper trading service.

    Returns:
        PositionResponse: The position details.

    Raises:
        HTTPException: If the position does not exist (404) or user lacks
            permission to access it (403).
    """
    _legacy_source(response)
    position = await service.get_position(position_id)
    if not position:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Paper trading position not found"
        )

    # Check permissions
    account = await service.get_account(position.account_id)
    if not account or account.user_id != current_user.sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No permission to access this position"
        )

    return position


# ==================== Paper Trade API ====================


@router.get("/trades", response_model=TradeListResponse, summary="List paper trading trades")
async def list_paper_trades(
    response: Response,
    current_user: typing.Any = Depends(get_current_user),
    service: PaperTradingService = Depends(get_paper_trading_service),
    account_id: str | None = Query(None, description="Account ID"),
    symbol: str | None = Query(None, description="Trading symbol"),
    side: str | None = Query(None, description="Trade side (buy/sell)"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> typing.Any:
    """List paper trading trades with optional filters.

    Args:
        current_user: The authenticated user.
        service: The paper trading service.
        account_id: Filter by account ID.
        symbol: Filter by trading symbol.
        side: Filter by trade side.
        limit: Maximum number of trades to return (1-100).
        offset: Number of trades to skip.

    Returns:
        TradeListResponse: Response containing total count and trade list.
    """
    _legacy_source(response)
    filters = {"user_id": current_user.sub}
    if account_id:
        filters["account_id"] = account_id
    if symbol:
        filters["symbol"] = symbol
    if side:
        filters["side"] = side

    trades, total = await service.list_trades(
        filters=filters,
        limit=limit,
        offset=offset,
    )
    return TradeListResponse(total=total, items=trades)


# ==================== WebSocket Endpoint ====================


@router.websocket("/ws/account/{account_id}")
async def websocket_account_endpoint(websocket: WebSocket, account_id: str) -> typing.Any:
    """WebSocket endpoint for paper trading real-time updates.

    Pushes:
        - Account updates (cash, equity, profit/loss)
        - Order updates (status, fills)
        - Position updates (quantity, market value, unrealized PnL)
        - Trade updates (new trades)

    Connection URL: ws://host/api/v1/paper-trading/ws/account/{account_id}

    Message types:
        - connected: Connection successful
        - account_update: Account data update
        - order_update: Order status update
        - position_update: Position data update
        - trade_update: New trade notification

    Args:
        websocket: The WebSocket connection instance.
        account_id: The unique identifier of the paper trading account.
    """
    import asyncio

    from app.websocket_manager import MessageType
    from app.websocket_manager import manager as ws_manager

    current_user, accepted_subprotocol = get_websocket_current_user(websocket)
    if current_user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Verify account exists and belongs to the authenticated websocket user.
    service = PaperTradingService()
    account = await service.get_account(account_id)
    if not account or account.user_id != current_user.sub:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    client_id = f"ws-client-{id(websocket)}"

    # Establish connection
    await ws_manager.connect(
        websocket,
        f"account:{account_id}",
        client_id,
        accepted_subprotocol,
    )

    try:
        # Send initial account information
        await ws_manager.send_to_task(
            f"account:{account_id}",
            {
                "type": MessageType.CONNECTED,
                "account_id": account_id,
                "message": "Paper trading WebSocket connection successful",
                "data": {
                    "current_cash": account.current_cash,
                    "total_equity": account.total_equity,
                    "profit_loss": account.profit_loss,
                    "profit_loss_pct": account.profit_loss_pct,
                },
            },
        )

        # Keep connection alive and push updates
        while True:
            await asyncio.sleep(1)

            # Latest account, order, and position information should be
            # fetched from the service and pushed via WebSocket
            # Temporarily using polling; should use event-driven in production

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, f"account:{account_id}", client_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket, f"account:{account_id}", client_id)
