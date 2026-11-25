"""Query helpers for BacktestService listing and metric sorting."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import asc, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import async_session_maker
from app.models.backtest import BacktestResultModel, BacktestTask
from app.services.robustness_validation_service import get_robustness_validation_service

TASK_SORT_FIELDS = frozenset({"created_at", "updated_at", "strategy_id", "symbol", "status"})
RESULT_SORT_FIELDS = frozenset(
    {
        "total_return",
        "annual_return",
        "sharpe_ratio",
        "max_drawdown",
        "win_rate",
        "total_trades",
    }
)


async def list_backtest_results_page(
    *,
    task_repo: Any,
    result_repo: Any,
    user_id: str,
    sort_by: str,
    sort_desc: bool,
    offset: int,
    limit: int,
    build_result: Callable[[BacktestTask, BacktestResultModel | None], Any],
    apply_robustness: Callable[[Any, Any], Any],
) -> tuple[int, list[Any]]:
    """Fetch one page of backtest results with SQL sorting and batched robustness."""
    total = await task_repo.count(filters={"user_id": user_id})
    tasks, result_by_task_id = await list_tasks_and_results_for_page(
        task_repo=task_repo,
        result_repo=result_repo,
        user_id=user_id,
        sort_by=sort_by,
        sort_desc=sort_desc,
        offset=offset,
        limit=limit,
    )
    task_ids = [str(task.id) for task in tasks]
    latest_by_task = (
        await get_robustness_validation_service().get_latest_by_backtest_ids(
            backtest_ids=task_ids,
            user_id=user_id,
        )
        if task_ids
        else {}
    )
    items = merge_batch_robustness(
        tasks=tasks,
        result_by_task_id=result_by_task_id,
        latest_by_task=latest_by_task,
        build_result=build_result,
        apply_robustness=apply_robustness,
    )
    return total, items


async def list_tasks_and_results_for_page(
    *,
    task_repo: Any,
    result_repo: Any,
    user_id: str,
    sort_by: str,
    sort_desc: bool,
    offset: int,
    limit: int,
) -> tuple[list[BacktestTask], dict[str, BacktestResultModel]]:
    """Fetch paginated tasks and matching result models without N+1 queries."""
    normalized_sort = str(sort_by or "created_at").strip()
    if normalized_sort in RESULT_SORT_FIELDS:
        return await _list_sorted_by_result_metric(
            user_id=user_id,
            sort_by=normalized_sort,
            sort_desc=sort_desc,
            offset=offset,
            limit=limit,
            external_session=getattr(task_repo, "_external_session", None),
        )

    effective_sort = normalized_sort if normalized_sort in TASK_SORT_FIELDS else "created_at"
    tasks = await task_repo.list(
        filters={"user_id": user_id},
        skip=offset,
        limit=limit,
        order_by=effective_sort,
        order_desc=sort_desc,
    )
    task_ids = [str(task.id) for task in tasks]
    result_models = (
        await result_repo.list(filters={"task_id": task_ids}, limit=len(task_ids) or 1)
        if task_ids
        else []
    )
    return tasks, {str(item.task_id): item for item in result_models}


async def _list_sorted_by_result_metric(
    *,
    user_id: str,
    sort_by: str,
    sort_desc: bool,
    offset: int,
    limit: int,
    external_session: AsyncSession | None = None,
) -> tuple[list[BacktestTask], dict[str, BacktestResultModel]]:
    metric_column = getattr(BacktestResultModel, sort_by)
    order_clause = desc(metric_column).nullslast() if sort_desc else asc(metric_column).nullslast()
    stmt = (
        select(BacktestTask, BacktestResultModel)
        .outerjoin(BacktestResultModel, BacktestResultModel.task_id == BacktestTask.id)
        .where(BacktestTask.user_id == user_id)
        .order_by(order_clause, desc(BacktestTask.created_at))
        .offset(offset)
        .limit(limit)
    )
    if external_session is not None:
        rows = (await external_session.execute(stmt)).all()
    else:
        async with async_session_maker() as session:
            rows = (await session.execute(stmt)).all()

    tasks: list[BacktestTask] = []
    result_by_task_id: dict[str, BacktestResultModel] = {}
    for task, result_model in rows:
        tasks.append(task)
        if result_model is not None:
            result_by_task_id[str(task.id)] = result_model
    return tasks, result_by_task_id


def merge_batch_robustness(
    *,
    tasks: list[BacktestTask],
    result_by_task_id: dict[str, BacktestResultModel],
    latest_by_task: dict[str, Any],
    build_result: Callable[[BacktestTask, BacktestResultModel | None], Any],
    apply_robustness: Callable[[Any, Any], Any],
) -> list[Any]:
    return [
        apply_robustness(
            build_result(task, result_by_task_id.get(str(task.id))),
            latest_by_task.get(str(task.id)),
        )
        for task in tasks
    ]
