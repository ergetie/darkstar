from unittest.mock import AsyncMock, patch

import pytest

from backend.services.planner_service import PlannerService
from planner.errors import PlannerError, PlannerErrorCode


@pytest.mark.asyncio
async def test_planner_service_success_orchestrates_planner_and_notifications():
    service = PlannerService()

    with (
        patch("bin.run_planner.main", new_callable=AsyncMock, return_value=0) as run_planner,
        patch.object(service, "_count_schedule_slots", return_value=3),
        patch("backend.services.planner_service.cache.invalidate", new_callable=AsyncMock) as invalidate,
        patch("backend.services.planner_service.ws_manager.emit", new_callable=AsyncMock) as emit,
    ):
        result = await service.run_once(ev_plugged_in_override=True, ev_charger_id_override="ev1")

    assert result.success is True
    assert result.slot_count == 3
    run_planner.assert_awaited_once()
    assert run_planner.await_args.kwargs["ev_plugged_in_override"] is True
    assert run_planner.await_args.kwargs["ev_charger_id_override"] == "ev1"
    invalidate.assert_awaited_once_with("schedule:current")
    assert any(call.args[0] == "schedule_updated" for call in emit.await_args_list)
    assert service.get_status()["phase"] == "idle"


@pytest.mark.asyncio
async def test_planner_service_records_typed_error_retry_state():
    service = PlannerService()
    error = PlannerError(
        PlannerErrorCode.CONFIG_INVALID,
        "bad config",
        details={"field": "x"},
        fix_hint="fix x",
    )

    with (
        patch("bin.run_planner.main", new_callable=AsyncMock, side_effect=error),
        patch("backend.services.planner_service.ws_manager.emit", new_callable=AsyncMock) as emit,
    ):
        result = await service.run_once()

    assert result.success is False
    assert result.error == "bad config"
    assert result.error_code == PlannerErrorCode.CONFIG_INVALID.value
    assert result.error_details == {"field": "x"}
    assert result.fix_hint == "fix x"
    assert service.retry_suspended is True
    assert any(call.args[0] == "planner_error" for call in emit.await_args_list)


@pytest.mark.asyncio
async def test_planner_service_rejects_concurrent_run():
    service = PlannerService()
    await service._lock.acquire()
    try:
        result = await service.run_once()
    finally:
        service._lock.release()

    assert result.success is False
    assert result.error == "Planner already running"
