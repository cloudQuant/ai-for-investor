"""
Monitoring and alerts API routes.

Provides:
- Alert rule management (CRUD)
- Alert listing and status updates
- Real-time notifications via WebSocket
"""

import asyncio
import logging
import typing

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_websocket_current_user
from app.db.database import get_db
from app.models.alerts import Alert
from app.models.paper_trading import Account
from app.models.portfolio_composition import PortfolioCompositionVersion
from app.schemas.monitoring import (
    AlertListResponse,
    AlertResponse,
    AlertRuleCreate,
    AlertRuleListResponse,
    AlertRuleResponse,
    AlertRuleUpdate,
)
from app.services.monitoring_control import (
    OwnerControlDeployment,
    OwnerControlError,
    OwnerControlRequest,
    control_implementation_status,
    get_deployment_setting,
)
from app.services.monitoring_service import MonitoringService
from app.websocket_manager import MessageType
from app.websocket_manager import manager as ws_manager

logger = logging.getLogger(__name__)

router = APIRouter()


def get_owner_control_deployment() -> OwnerControlDeployment:
    """Load the dedicated operator-owned owner-control map, fail-closed."""
    try:
        deployment = OwnerControlDeployment.from_secret(get_deployment_setting())
    except OwnerControlError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": exc.code},
        ) from None
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "OWNER_CONTROL_NOT_CONFIGURED"},
        )
    return deployment


def _raise_owner_control_error(error: OwnerControlError) -> typing.NoReturn:
    conflict_codes = {"IDEMPOTENCY_KEY_CONFLICT", "ISSUER_COMMAND_UNRESOLVED"}
    raise HTTPException(
        status_code=(
            status.HTTP_409_CONFLICT
            if error.code in conflict_codes
            else status.HTTP_503_SERVICE_UNAVAILABLE
        ),
        detail={"code": error.code},
    ) from None


async def _require_owned_control_target(
    *,
    alert_id: str,
    subject: str,
    portfolio_ref: str | None,
    session: AsyncSession,
    deployment: OwnerControlDeployment,
    require_active: bool = True,
) -> tuple[Alert, typing.Any]:
    alert = await session.scalar(
        select(Alert).where(Alert.id == alert_id, Alert.user_id == subject)
    )
    if alert is None or alert.account_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Control target not found"
        )
    account_id = await session.scalar(
        select(Account.id).where(
            Account.id == alert.account_id,
            Account.user_id == subject,
        )
    )
    if account_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Control target not found"
        )
    if portfolio_ref is not None:
        owned_portfolio = await session.scalar(
            select(PortfolioCompositionVersion.id)
            .where(
                PortfolioCompositionVersion.owner_subject == subject,
                PortfolioCompositionVersion.portfolio_ref == portfolio_ref,
            )
            .limit(1)
        )
        if owned_portfolio is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Control target not found"
            )
    try:
        binding = deployment.binding_for(
            subject=subject,
            afi_account_id=str(account_id),
            portfolio_ref=portfolio_ref,
            require_active=require_active,
        )
    except OwnerControlError as exc:
        _raise_owner_control_error(exc)
    if binding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Control target not found"
        )
    return alert, binding


@router.post(
    "/control/alerts/{alert_id}",
    summary="Submit a signed owner control command for an owned alert",
)
async def control_alert_risk(
    alert_id: str,
    request_body: OwnerControlRequest,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=256),
    current_user: typing.Any = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    deployment: OwnerControlDeployment = Depends(get_owner_control_deployment),
) -> typing.Any:
    """Run a supported control through the signed Monitor ledger and owner thread.

    Acknowledging or resolving this alert remains an independent operation and
    does not alter any owner RiskGate cause.
    """
    _, binding = await _require_owned_control_target(
        alert_id=alert_id,
        subject=current_user.sub,
        portfolio_ref=request_body.portfolio_ref,
        session=session,
        deployment=deployment,
    )
    try:
        implementation = control_implementation_status(request_body.action)
    except OwnerControlError as exc:
        _raise_owner_control_error(exc)
    if implementation not in {"FREEZE_SUPPORTED", "STOP_NEW_SUPPORTED"}:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={"code": implementation},
        )
    try:
        projected = await asyncio.to_thread(
            deployment.submit_control,
            binding,
            action=request_body.action,
            subject=current_user.sub,
            alert_id=alert_id,
            idempotency_key=idempotency_key,
        )
    except OwnerControlError as exc:
        _raise_owner_control_error(exc)
    response.status_code = (
        status.HTTP_200_OK
        if projected.get("owner_final") is True or projected.get("status") == "expired"
        else status.HTTP_202_ACCEPTED
    )
    return projected


@router.get(
    "/control/commands/{command_id}",
    summary="Read the persisted owner-control result",
)
async def get_owner_control_status(
    command_id: str,
    response: Response,
    current_user: typing.Any = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    deployment: OwnerControlDeployment = Depends(get_owner_control_deployment),
) -> typing.Any:
    """Project only the exact persisted command receipt for its mapped owner."""
    try:
        found = await asyncio.to_thread(
            deployment.status_for_command, command_id, subject=current_user.sub
        )
    except OwnerControlError as exc:
        _raise_owner_control_error(exc)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Control command not found"
        )
    binding, alert_id, projected = found
    _, authorized_binding = await _require_owned_control_target(
        alert_id=alert_id,
        subject=current_user.sub,
        portfolio_ref=binding.config.portfolio_ref,
        session=session,
        deployment=deployment,
        require_active=False,
    )
    if authorized_binding is not binding:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Control command not found"
        )
    response.status_code = (
        status.HTTP_200_OK
        if projected.get("owner_final") is True or projected.get("status") == "expired"
        else status.HTTP_202_ACCEPTED
    )
    return projected


def get_monitoring_service() -> MonitoringService:
    """Dependency injection for MonitoringService.

    Note:
        We intentionally do NOT cache this with ``@lru_cache``. Existing tests
        patch ``app.api.monitoring.MonitoringService`` per-test; caching would
        leak the first test's mock across the whole module. ``MonitoringService``
        is also stateless aside from repo instances, so per-request construction
        is cheap.

    Returns:
        MonitoringService: A fresh instance of the monitoring service.
    """
    return MonitoringService()


# ==================== Alert Rule API ====================


@router.post("/rules", response_model=AlertRuleResponse, summary="Create alert rule")
async def create_alert_rule(
    request: AlertRuleCreate,
    current_user: typing.Any = Depends(get_current_user),
    service: MonitoringService = Depends(get_monitoring_service),
) -> typing.Any:
    """Create a new alert rule.

    Args:
        request: The alert rule creation request containing name, description,
            alert_type, severity, trigger_type, trigger_config, and
            notification settings.
        current_user: The authenticated user.
        service: The monitoring service.

    Returns:
        AlertRuleResponse: The created alert rule details.
    """
    rule = await service.create_alert_rule(
        user_id=current_user.sub,
        name=request.name,
        description=request.description,
        alert_type=request.alert_type,
        severity=request.severity,
        trigger_type=request.trigger_type,
        trigger_config=request.trigger_config,
        notification_enabled=request.notification_enabled,
        notification_channels=request.notification_channels,
    )

    return rule


@router.get("/rules", response_model=AlertRuleListResponse, summary="List alert rules")
async def list_alert_rules(
    current_user: typing.Any = Depends(get_current_user),
    service: MonitoringService = Depends(get_monitoring_service),
    alert_type: str | None = Query(None, description="Alert type filter"),
    severity: str | None = Query(None, description="Alert severity filter"),
    is_active: bool | None = Query(None, description="Active status filter"),
) -> typing.Any:
    """Get the current user's alert rule list.

    Args:
        current_user: The authenticated user.
        service: The monitoring service.
        alert_type: Filter by alert type.
        severity: Filter by severity level.
        is_active: Filter by active status.

    Returns:
        AlertRuleListResponse: Response containing total count and rule list.
    """
    rules, total = await service.list_alert_rules(
        user_id=current_user.sub,
        alert_type=alert_type,
        severity=severity,
        is_active=is_active,
    )

    return AlertRuleListResponse(total=total, items=rules)


@router.get("/rules/{rule_id}", response_model=AlertRuleResponse, summary="Get alert rule details")
async def get_alert_rule(
    rule_id: str,
    current_user: typing.Any = Depends(get_current_user),
    service: MonitoringService = Depends(get_monitoring_service),
) -> typing.Any:
    """Get an alert rule by ID.

    Args:
        rule_id: The unique identifier of the alert rule.
        current_user: The authenticated user.
        service: The monitoring service.

    Returns:
        AlertRuleResponse: The alert rule details.

    Raises:
        HTTPException: If user lacks permission (403) or rule not found (404).
    """
    try:
        rule = await service.get_alert_rule(rule_id=rule_id, user_id=current_user.sub)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No permission to access this rule"
        ) from exc

    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert rule not found")
    return rule


@router.put("/rules/{rule_id}", response_model=AlertRuleResponse, summary="Update alert rule")
async def update_alert_rule(
    rule_id: str,
    request: AlertRuleUpdate,
    current_user: typing.Any = Depends(get_current_user),
    service: MonitoringService = Depends(get_monitoring_service),
) -> typing.Any:
    """Update an alert rule.

    Args:
        rule_id: The unique identifier of the alert rule.
        request: The update request containing fields to modify.
        current_user: The authenticated user.
        service: The monitoring service.

    Returns:
        AlertRuleResponse: The updated alert rule details.
    """
    rule = await service.update_alert_rule(
        rule_id=rule_id, user_id=current_user.sub, update_data=request.model_dump(exclude_none=True)
    )

    return rule


@router.delete("/rules/{rule_id}", summary="Delete alert rule", response_model=None)
async def delete_alert_rule(
    rule_id: str,
    current_user: typing.Any = Depends(get_current_user),
    service: MonitoringService = Depends(get_monitoring_service),
) -> typing.Any:
    """Delete an alert rule.

    Args:
        rule_id: The unique identifier of the alert rule.
        current_user: The authenticated user.
        service: The monitoring service.

    Returns:
        A message confirming deletion.

    Raises:
        HTTPException: If the rule does not exist or user lacks permission (404).
    """
    success = await service.delete_alert_rule(rule_id, current_user.sub)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert rule not found or no permission to delete",
        )

    return {"message": "Alert rule has been deleted"}


# ==================== Alert API ====================


@router.get("/", response_model=AlertListResponse, summary="List alerts")
async def list_alerts(
    current_user: typing.Any = Depends(get_current_user),
    service: MonitoringService = Depends(get_monitoring_service),
    alert_type: str | None = Query(None, description="Alert type filter"),
    severity: str | None = Query(None, description="Alert severity filter"),
    status: str | None = Query(None, description="Alert status filter"),
    is_read: bool | None = Query(None, description="Read status filter"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> typing.Any:
    """Get the list of alerts for the current user.

    Args:
        current_user: The authenticated user.
        service: The monitoring service.
        alert_type: Filter by alert type.
        severity: Filter by severity level.
        status: Filter by alert status.
        is_read: Filter by read status.
        limit: Maximum number of alerts to return (1-100).
        offset: Number of alerts to skip.

    Returns:
        AlertListResponse: Response containing total count and alert list.
    """
    alerts, total = await service.list_alerts(
        user_id=current_user.sub,
        alert_type=alert_type,
        severity=severity,
        status=status,
        is_read=is_read,
        limit=limit,
        offset=offset,
    )

    return AlertListResponse(total=total, items=alerts)


@router.get("/{alert_id}", response_model=AlertResponse, summary="Get alert details")
async def get_alert(
    alert_id: str,
    current_user: typing.Any = Depends(get_current_user),
    service: MonitoringService = Depends(get_monitoring_service),
) -> typing.Any:
    """Get an alert by ID.

    Args:
        alert_id: The unique identifier of the alert.
        current_user: The authenticated user.
        service: The monitoring service.

    Returns:
        AlertResponse: The alert details.

    Raises:
        HTTPException: If user lacks permission (403) or alert not found (404).
    """
    try:
        alert = await service.get_alert(alert_id=alert_id, user_id=current_user.sub)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No permission to access this alert"
        ) from exc

    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    return alert


@router.put("/{alert_id}/read", summary="Mark alert as read", response_model=None)
async def mark_alert_read(
    alert_id: str,
    current_user: typing.Any = Depends(get_current_user),
    service: MonitoringService = Depends(get_monitoring_service),
) -> typing.Any:
    """Mark an alert as read.

    Args:
        alert_id: The unique identifier of the alert.
        current_user: The authenticated user.
        service: The monitoring service.

    Returns:
        A message confirming the alert has been marked as read.

    Raises:
        HTTPException: If the alert does not exist or user lacks permission (404).
    """
    success = await service.mark_alert_read(alert_id, current_user.sub)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found or no permission to mark"
        )

    return {"message": "Alert has been marked as read"}


@router.put("/{alert_id}/resolve", summary="Resolve alert", response_model=None)
async def resolve_alert(
    alert_id: str,
    current_user: typing.Any = Depends(get_current_user),
    service: MonitoringService = Depends(get_monitoring_service),
) -> typing.Any:
    """Resolve an alert.

    Args:
        alert_id: The unique identifier of the alert.
        current_user: The authenticated user.
        service: The monitoring service.

    Returns:
        A message confirming the alert has been resolved.

    Raises:
        HTTPException: If the alert does not exist or user lacks permission (404).
    """
    success = await service.resolve_alert(alert_id, current_user.sub)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found or no permission to resolve",
        )

    return {"message": "Alert has been resolved"}


@router.put("/{alert_id}/acknowledge", summary="Acknowledge alert", response_model=None)
async def acknowledge_alert(
    alert_id: str,
    current_user: typing.Any = Depends(get_current_user),
    service: MonitoringService = Depends(get_monitoring_service),
) -> typing.Any:
    """Acknowledge an alert.

    Args:
        alert_id: The unique identifier of the alert.
        current_user: The authenticated user.
        service: The monitoring service.

    Returns:
        A message confirming the alert has been acknowledged.

    Raises:
        HTTPException: If the alert does not exist or user lacks permission (404).
    """
    success = await service.acknowledge_alert(alert_id, current_user.sub)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found or no permission to acknowledge",
        )

    return {"message": "Alert has been acknowledged"}


# ==================== Alert Statistics API ====================


@router.get("/statistics/summary", summary="Get alert statistics summary", response_model=None)
async def get_alert_summary(
    current_user: typing.Any = Depends(get_current_user),
    service: MonitoringService = Depends(get_monitoring_service),
) -> typing.Any:
    """Get the alert statistics summary for the current user.

    Args:
        current_user: The authenticated user.
        service: The monitoring service.

    Returns:
        A dictionary containing alert statistics summary.
    """
    return await service.get_alert_summary(user_id=current_user.sub)


@router.get("/statistics/by-type", summary="Get alert statistics by type", response_model=None)
async def get_alerts_by_type(
    current_user: typing.Any = Depends(get_current_user),
    service: MonitoringService = Depends(get_monitoring_service),
    start_date: str = Query(..., description="Start date"),
    end_date: str = Query(..., description="End date"),
) -> typing.Any:
    """Get alert statistics grouped by type for a date range.

    Args:
        current_user: The authenticated user.
        service: The monitoring service.
        start_date: Start date in ISO 8601 format.
        end_date: End date in ISO 8601 format.

    Returns:
        A dictionary containing start_date, end_date, and statistics by type.

    Raises:
        HTTPException: If date format is invalid (400).
    """
    from datetime import datetime

    try:
        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid date format: {e}"
        ) from e

    stats = await service.get_alerts_by_type(
        user_id=current_user.sub, start_dt=start_dt, end_dt=end_dt
    )
    return {"start_date": start_date, "end_date": end_date, **stats}


# ==================== WebSocket Endpoint ====================


@router.websocket("/ws/alerts")
async def alerts_websocket(
    websocket: WebSocket,
) -> typing.Any:
    """WebSocket endpoint for alert real-time updates.

    Pushes:
        - New alert creation
        - Alert status updates
        - Alert resolution notifications
        - Alert statistics updates

    Connection URL: ws://host/api/v1/monitoring/ws/alerts

    Message types:
        - connected: Connection successful
        - alert_created: New alert
        - alert_updated: Alert updated
        - alert_resolved: Alert resolved
        - alert_acknowledged: Alert acknowledged
        - stats_update: Statistics update

    Args:
        websocket: The WebSocket connection instance.
    """
    current_user, accepted_subprotocol = get_websocket_current_user(websocket)
    if current_user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    client_id = f"ws-alerts-client-{id(websocket)}"
    channel = f"alert:{current_user.sub}"

    # Establish connection
    await ws_manager.connect(websocket, channel, client_id, accepted_subprotocol)

    try:
        # Send initial message
        await ws_manager.send_to_task(
            channel,
            {
                "type": MessageType.CONNECTED,
                "message": "Alert monitoring WebSocket connection successful",
            },
        )

        # Keep connection alive
        while True:
            await asyncio.sleep(1)

            # Latest alerts should be fetched from monitoring service
            # and pushed via WebSocket
            # Temporarily using polling; should use event-driven in production

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Alerts WebSocket error for user %s", current_user.sub)
    finally:
        ws_manager.disconnect(websocket, channel, client_id)
