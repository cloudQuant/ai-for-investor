from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.overfitting_result import OverfittingResultModel
from app.services.overfitting import OverfittingService


@pytest.mark.asyncio
async def test_get_cached_analysis_returns_none_when_user_has_no_matching_cache() -> None:
    service = OverfittingService(backtest_service=MagicMock())
    cached_model = OverfittingResultModel(
        backtest_id="backtest-1",
        user_id="user-1",
        updated_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
        created_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
    )
    service.repo.get_by_fields = AsyncMock(return_value=[cached_model])

    result = await service.get_cached_analysis("backtest-1", user_id="user-2")

    assert result is None
    service.repo.get_by_fields.assert_awaited_once_with({"backtest_id": "backtest-1"}, limit=50)


@pytest.mark.asyncio
async def test_get_cached_analysis_sorts_aware_null_and_naive_timestamps() -> None:
    service = OverfittingService(backtest_service=MagicMock())
    aware_timestamp_model = OverfittingResultModel(
        task_id="aware-timestamp",
        backtest_id="backtest-1",
        user_id="user-1",
        updated_at=datetime(2026, 9, 21, 17, tzinfo=timezone(timedelta(hours=8))),
        created_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
    )
    null_updated_at_model = OverfittingResultModel(
        task_id="null-updated-at",
        backtest_id="backtest-1",
        user_id="user-1",
        updated_at=None,
        created_at=datetime(2026, 9, 21, 8, tzinfo=timezone.utc),
    )
    naive_timestamp_model = OverfittingResultModel(
        task_id="naive-timestamp",
        backtest_id="backtest-1",
        user_id="user-1",
        updated_at=datetime(2026, 9, 21, 10),
        created_at=datetime(2026, 9, 20),
    )
    missing_timestamps_model = OverfittingResultModel(
        task_id="missing-timestamps",
        backtest_id="backtest-1",
        user_id="user-1",
        updated_at=None,
        created_at=None,
    )
    service.repo.get_by_fields = AsyncMock(
        return_value=[
            aware_timestamp_model,
            null_updated_at_model,
            naive_timestamp_model,
            missing_timestamps_model,
        ]
    )

    result = await service.get_cached_analysis("backtest-1", user_id="user-1")

    assert result is not None
    assert result.task_id == "naive-timestamp"
