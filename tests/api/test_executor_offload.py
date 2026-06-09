from unittest.mock import MagicMock, patch

import pytest

from backend.api.routers import executor as executor_router


@pytest.mark.asyncio
async def test_executor_history_route_returns_records_after_offload():
    records = [{"slot_start": "2026-04-01T00:00:00", "success": True}]
    executor = MagicMock()
    executor.history.get_history.return_value = records

    with patch("backend.api.routers.executor.get_executor_instance", return_value=executor):
        result = await executor_router.get_history(limit=10, success_only="true")

    assert result == {"records": records, "count": 1}
    executor.history.get_history.assert_called_once_with(
        limit=10,
        offset=0,
        slot_start=None,
        success_only=True,
        start_date=None,
        end_date=None,
    )


@pytest.mark.asyncio
async def test_executor_stats_route_returns_stats_after_offload():
    stats = {"total_runs": 4, "success_rate": 0.75}
    executor = MagicMock()
    executor.get_stats.return_value = stats

    with patch("backend.api.routers.executor.get_executor_instance", return_value=executor):
        result = await executor_router.get_stats(days=14)

    assert result == stats
    executor.get_stats.assert_called_once_with(days=14)
