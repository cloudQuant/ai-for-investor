"""Monitoring background-task shutdown hook."""

from typing import Any

from fastapi import FastAPI


async def shutdown(app: FastAPI, settings: Any) -> None:
    """Cancel any active monitoring tasks when the FastAPI application shuts down."""
    del app, settings
    from app.services.monitoring_service import get_monitoring_task_manager

    await get_monitoring_task_manager().shutdown()
