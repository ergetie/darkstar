"""Shared replan dispatch helper and goal-change debounce (ev-goal-lifecycle-feedback)."""

import asyncio
import threading
from unittest.mock import AsyncMock, patch

import pytest

from backend.services import scheduler_service as sched_mod
from backend.services.planner_service import PlannerResult
from backend.services.scheduler_service import (
    GOAL_CHANGE_DEBOUNCE_S,
    ReplanReason,
    SchedulerService,
    request_replan,
)


def _ok() -> PlannerResult:
    from datetime import UTC, datetime

    return PlannerResult(success=True, planned_at=datetime.now(UTC))


@pytest.fixture
def fresh_scheduler(monkeypatch):
    svc = SchedulerService()
    monkeypatch.setattr(sched_mod, "scheduler_service", svc)
    return svc


@pytest.mark.asyncio
async def test_plug_replan_on_main_loop_uses_create_task(fresh_scheduler):
    fresh_scheduler.main_loop = asyncio.get_running_loop()
    fresh_scheduler.trigger_now = AsyncMock(return_value=_ok())

    with patch("asyncio.run_coroutine_threadsafe") as threadsafe:
        request_replan(ReplanReason.PLUG_IN, ev_overrides={"ev1": True})
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    threadsafe.assert_not_called()
    fresh_scheduler.trigger_now.assert_awaited_once_with(ev_plug_overrides={"ev1": True})


@pytest.mark.asyncio
async def test_replan_from_other_thread_dispatches_onto_main_loop(fresh_scheduler):
    loop = asyncio.get_running_loop()
    fresh_scheduler.main_loop = loop
    called_on: list[asyncio.AbstractEventLoop] = []

    async def fake_trigger(**_kwargs):
        called_on.append(asyncio.get_running_loop())
        return _ok()

    fresh_scheduler.trigger_now = fake_trigger

    thread = threading.Thread(
        target=lambda: request_replan(ReplanReason.UNPLUG, ev_overrides={"ev1": False})
    )
    thread.start()
    thread.join()
    for _ in range(20):
        if called_on:
            break
        await asyncio.sleep(0.01)

    assert called_on == [loop]


@pytest.mark.asyncio
async def test_goal_change_burst_debounces_into_one_run(fresh_scheduler):
    fresh_scheduler.main_loop = asyncio.get_running_loop()
    fresh_scheduler.trigger_now = AsyncMock(return_value=_ok())
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def fast_sleep(delay, *args, **kwargs):
        sleeps.append(delay)
        await real_sleep(0)

    with (
        patch("backend.services.scheduler_service.planner_service") as planner,
        patch("backend.services.scheduler_service.asyncio.sleep", side_effect=fast_sleep),
    ):
        await fresh_scheduler.request_goal_replan(["ev1"])
        await fresh_scheduler.request_goal_replan(["ev1"])
        await fresh_scheduler.request_goal_replan(["ev2"])
        task = fresh_scheduler._goal_debounce_task
        assert task is not None
        await task

    assert sleeps == [GOAL_CHANGE_DEBOUNCE_S]
    fresh_scheduler.trigger_now.assert_awaited_once_with()
    assert planner.mark_goal_replan_pending.call_count == 3


@pytest.mark.asyncio
async def test_plug_replan_is_not_debounced(fresh_scheduler):
    fresh_scheduler.main_loop = asyncio.get_running_loop()
    fresh_scheduler.trigger_now = AsyncMock(return_value=_ok())

    with patch.object(fresh_scheduler, "request_goal_replan", new_callable=AsyncMock) as goal:
        request_replan(ReplanReason.PLUG_IN, ev_overrides={"ev1": True})
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    goal.assert_not_awaited()
    fresh_scheduler.trigger_now.assert_awaited_once()


@pytest.mark.asyncio
async def test_goal_replan_marks_pending_and_never_runs_executor(fresh_scheduler):
    fresh_scheduler.main_loop = asyncio.get_running_loop()
    with (
        patch("backend.services.scheduler_service.planner_service") as planner,
        patch("backend.services.scheduler_service.GOAL_CHANGE_DEBOUNCE_S", 0),
        patch("executor.engine.ExecutorEngine.run_once", new_callable=AsyncMock) as exec_run,
    ):
        planner.run_once = AsyncMock(return_value=_ok())
        request_replan(ReplanReason.GOAL_CHANGE, charger_ids=["ev1"])
        for _ in range(20):
            await asyncio.sleep(0)
            if planner.run_once.await_count:
                break

    planner.mark_goal_replan_pending.assert_called_with(["ev1"])
    planner.run_once.assert_awaited_once()
    exec_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_queued_result_does_not_overwrite_scheduler_status(fresh_scheduler):
    from datetime import UTC, datetime

    queued = PlannerResult(success=True, planned_at=datetime.now(UTC), queued=True)
    with patch("backend.services.scheduler_service.planner_service") as planner:
        planner.run_once = AsyncMock(return_value=queued)
        await fresh_scheduler.trigger_now()

    assert fresh_scheduler.status.last_run_at is None


@pytest.mark.asyncio
async def test_queued_scheduled_run_does_not_overwrite_scheduler_status(fresh_scheduler):
    from datetime import UTC, datetime

    queued = PlannerResult(success=True, planned_at=datetime.now(UTC), queued=True)
    with patch("backend.services.scheduler_service.planner_service") as planner:
        planner.run_once = AsyncMock(return_value=queued)
        planner.next_retry_at = None
        await fresh_scheduler._run_scheduled({"every_minutes": 60, "jitter_minutes": 0})

    assert fresh_scheduler.status.last_run_at is None
    assert fresh_scheduler.status.last_run_status is None
