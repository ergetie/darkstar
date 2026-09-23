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
        source=None,
    )


@pytest.mark.asyncio
async def test_executor_history_route_passes_source_filter():
    executor = MagicMock()
    executor.history.get_history.return_value = []

    with patch("backend.api.routers.executor.get_executor_instance", return_value=executor):
        await executor_router.get_history(source="ev_charger")

    assert executor.history.get_history.call_args.kwargs["source"] == "ev_charger"


@pytest.mark.asyncio
async def test_executor_history_download_passes_source_filter():
    executor = MagicMock()
    executor.history.get_history_csv.return_value = ""

    with patch("backend.api.routers.executor.get_executor_instance", return_value=executor):
        await executor_router.download_history(source="native")

    assert executor.history.get_history_csv.call_args.kwargs["source"] == "native"


def test_executor_history_rejects_unknown_source():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(executor_router.router)
    with patch("backend.api.routers.executor.get_executor_instance", return_value=MagicMock()):
        response = TestClient(app).get("/api/executor/history", params={"source": "bogus"})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_executor_stats_route_returns_stats_after_offload():
    stats = {"total_runs": 4, "success_rate": 0.75}
    executor = MagicMock()
    executor.get_stats.return_value = stats

    with patch("backend.api.routers.executor.get_executor_instance", return_value=executor):
        result = await executor_router.get_stats(days=14)

    assert result == stats
    executor.get_stats.assert_called_once_with(days=14)


@pytest.mark.asyncio
async def test_load_balancer_status_route_disabled():
    """universal-load-balancing 6.2: disabled state."""
    disabled_payload = {
        "enabled": False,
        "state": "disabled",
        "reason": "Load balancing disabled or unconfigured",
        "main_fuse_a": None,
        "phase_current_a": {},
        "phase_headroom_a": {},
        "ev": [],
        "shed": [],
    }
    executor = MagicMock()
    executor.get_load_balancer_status.return_value = disabled_payload

    with patch("backend.api.routers.executor.get_executor_instance", return_value=executor):
        result = await executor_router.get_load_balancer_status(executor)

    assert result == disabled_payload
    assert result["enabled"] is False


@pytest.mark.asyncio
async def test_load_balancer_status_route_enabled():
    """universal-load-balancing 6.2: enabled state with throttling detail."""
    enabled_payload = {
        "enabled": True,
        "state": "throttling",
        "reason": "Reduced 16A -> 10A (headroom -6.0A)",
        "main_fuse_a": 20,
        "phase_current_a": {1: 26.0, 2: 5.0, 3: 5.0},
        "phase_headroom_a": {1: -6.0, 2: 15.0, 3: 15.0},
        "ev": [
            {
                "charger_id": "goe",
                "setpoint_a": 10,
                "planned_target_a": 16,
                "state": "throttling",
                "reason": "Reduced 16A -> 10A (headroom -6.0A)",
            }
        ],
        "shed": [],
    }
    executor = MagicMock()
    executor.get_load_balancer_status.return_value = enabled_payload

    with patch("backend.api.routers.executor.get_executor_instance", return_value=executor):
        result = await executor_router.get_load_balancer_status(executor)

    assert result == enabled_payload
    assert result["enabled"] is True
    assert result["ev"][0]["setpoint_a"] == 10
