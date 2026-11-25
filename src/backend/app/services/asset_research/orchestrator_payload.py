"""Asset research task response projection."""

from __future__ import annotations

from app.models.asset_research import AssetAnalysisReport, AssetAnalysisTask
from app.schemas.asset_research import AssetAnalysisTaskResponse


def task_payload(
    task: AssetAnalysisTask, report: AssetAnalysisReport | None = None
) -> AssetAnalysisTaskResponse:
    message_map = {
        "QUEUED": "多资产研究任务已创建",
        "RUNNING": "正在生成多资产研究报告",
        "SUCCEEDED": "多资产研究已完成",
        "FAILED": "多资产研究失败",
        "CANCELLED": "多资产研究已取消",
    }
    return AssetAnalysisTaskResponse(
        task_id=task.id,
        status=task.status,
        asset_type=task.asset_type,
        canonical_id=task.canonical_id,
        progress=task.progress,
        message=message_map.get(task.status),
        error_code=task.error_code,
        report_id=report.id if report else None,
        prediction_id=report.prediction_id if report else None,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
    )
