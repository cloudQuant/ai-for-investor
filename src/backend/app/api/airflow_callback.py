"""
Airflow task execution callback endpoint.

Receives execution results from Airflow DAG tasks and persists them
to the TaskExecution table for unified monitoring.
"""

import hashlib
import hmac
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.database import get_db
from app.models.akshare_mgmt import TaskExecution, TaskStatus
from app.schemas.airflow import AirflowCallbackPayload
from app.utils.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


async def _verify_airflow_callback_auth(request: Request) -> None:
    """Verify Airflow callback Bearer token or HMAC-SHA256 body signature."""
    secret = str(getattr(get_settings(), "AIRFLOW_CALLBACK_SECRET", "") or "").strip()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Airflow callback authentication is not configured",
        )

    signature_header = (request.headers.get("X-Airflow-Signature") or "").strip()
    if signature_header:
        provided = signature_header.removeprefix("sha256=").strip().lower()
        body = await request.body()
        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if not secrets.compare_digest(provided, expected):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid Airflow callback signature",
            )
        return

    token = ""
    auth_header = (request.headers.get("Authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    elif request.headers.get("X-Airflow-Callback-Token"):
        token = request.headers.get("X-Airflow-Callback-Token", "").strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Airflow callback credentials",
        )
    if not secrets.compare_digest(token, secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Airflow callback token",
        )


@router.post("/airflow/callback", dependencies=[Depends(_verify_airflow_callback_auth)])
async def receive_airflow_callback(
    payload: AirflowCallbackPayload,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Receive execution result callback from Airflow tasks.

    Creates a TaskExecution record with the Airflow execution details.
    This endpoint is called by DAG on_success/on_failure callbacks.

    Args:
        payload: Airflow callback payload with execution details.
        db: Database session.

    Returns:
        Confirmation with the created execution_id.
    """
    status = TaskStatus.COMPLETED if payload.status == "success" else TaskStatus.FAILED

    execution = TaskExecution(
        execution_id=payload.execution_id or str(uuid.uuid4()),
        script_id=payload.task_id,
        status=status,
        start_time=payload.start_time,
        end_time=payload.end_time,
        duration=payload.duration,
        error_message=payload.error_message,
        error_trace=payload.error_trace,
        rows_before=payload.rows_before,
        rows_after=payload.rows_after,
        result=payload.result,
        airflow_dag_id=payload.dag_id,
        airflow_run_id=payload.dag_run_id,
        airflow_task_id=payload.task_id,
    )

    db.add(execution)
    await db.commit()

    logger.info(
        f"Airflow callback received: dag={payload.dag_id} "
        f"task={payload.task_id} status={payload.status}"
    )

    return {"execution_id": execution.execution_id, "status": status.value}
