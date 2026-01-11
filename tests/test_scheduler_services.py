import asyncio
from datetime import datetime
from unittest.mock import patch

from backend.services.planner_service import PlannerResult, PlannerService
from backend.services.scheduler_service import SchedulerService


def test_planner_service_lifecycle():
    asyncio.run(_test_planner_lifecycle_async())


async def _test_planner_lifecycle_async():
    service = PlannerService()

    # Patch the _run_sync method on the PlannerService class
    with patch.object(PlannerService, "_run_sync") as mock_run:
        # Mock must return a PlannerResult object
        mock_run.return_value = PlannerResult(
            success=True, planned_at=datetime.now(), slot_count=48, duration_ms=100.0, error=None
        )

        # Test run_once
        result = await service.run_once()
        assert result.success is True
        assert result.slot_count == 48
        # run_once returns PlannerResult object too, not dict (check code)

        # Verify lock is released
        assert not service._lock.locked()


def test_planner_service_failure():
    asyncio.run(_test_planner_failure_async())


async def _test_planner_failure_async():
    service = PlannerService()
    with patch.object(PlannerService, "_run_sync") as mock_run:
        mock_run.side_effect = Exception("Planner crashed")

        result = await service.run_once()
        # run_once catches exception and returns PlannerResult with success=False
        assert result.success is False
        assert "Planner crashed" in result.error


def test_scheduler_service_lifecycle():
    asyncio.run(_test_scheduler_lifecycle_async())


async def _test_scheduler_lifecycle_async():
    scheduler = SchedulerService()

    # Test startup/shutdown
    assert not scheduler.status.running

    # Default is enabled=False until loop starts/config loaded
    assert not scheduler.status.enabled

    # Test starting (mocks loop to prevent infinite run)
    with patch.object(SchedulerService, "_loop"):
        await scheduler.start()
        assert scheduler.status.running
        assert scheduler._task is not None

        # Test stop signal
        await scheduler.stop()
        assert not scheduler.status.running
        assert scheduler._task is None
