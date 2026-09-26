import asyncio
from typing import Any
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
        result = await service.run_once(ev_plug_overrides={"ev1": True})

    assert result.success is True
    assert result.slot_count == 3
    run_planner.assert_awaited_once()
    assert run_planner.await_args.kwargs["ev_plug_overrides"] == {"ev1": True}
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


class _GatedPlanner:
    """Fake run_planner.main whose runs block until released, recording overrides."""

    def __init__(self, fail_first: bool = False) -> None:
        self.calls: list[dict[str, bool] | None] = []
        self.gates: list[asyncio.Event] = []
        self.started = asyncio.Event()
        self.fail_first = fail_first

    async def __call__(self, **kwargs: Any) -> int:
        gate = asyncio.Event()
        self.gates.append(gate)
        self.calls.append(kwargs.get("ev_plug_overrides"))
        self.started.set()
        await gate.wait()
        if self.fail_first and len(self.calls) == 1:
            raise RuntimeError("boom")
        return 0

    def release_all(self) -> None:
        for gate in self.gates:
            gate.set()


async def _drain(service: PlannerService) -> None:
    for _ in range(50):
        if service._followup_task is None and not service._lock.locked():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("follow-up did not finish")


def _patches(service: PlannerService, fake: _GatedPlanner):
    return (
        patch("bin.run_planner.main", new=fake),
        patch.object(service, "_count_schedule_slots", return_value=1),
        patch("backend.services.planner_service.cache.invalidate", new_callable=AsyncMock),
        patch("backend.services.planner_service.ws_manager.emit", new_callable=AsyncMock),
    )


async def _run_with_followup(service: PlannerService, fake: _GatedPlanner, requests):
    """Start one run, issue `requests` while it is running, then release everything."""
    first = asyncio.create_task(service.run_once())
    await fake.started.wait()
    results = [await service.run_once(ev_plug_overrides=o) for o in requests]
    # Release the first run and any follow-up as it starts.
    while True:
        fake.release_all()
        await asyncio.sleep(0.01)
        if first.done() and service._followup_task is None:
            break
    return await first, results


@pytest.mark.asyncio
async def test_request_during_run_is_queued_and_runs_once_more():
    service = PlannerService()
    fake = _GatedPlanner()
    p1, p2, p3, p4 = _patches(service, fake)
    with p1, p2, p3, p4:
        first, results = await _run_with_followup(service, fake, [None])
        await _drain(service)

    assert first.success is True
    assert results[0].queued is True
    assert results[0].error is None
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_several_requests_collapse_into_one_followup_with_merged_overrides():
    service = PlannerService()
    fake = _GatedPlanner()
    p1, p2, p3, p4 = _patches(service, fake)
    with p1, p2, p3, p4:
        await _run_with_followup(
            service,
            fake,
            [{"ev_a": True}, {"ev_b": False}, {"ev_a": False}],
        )
        await _drain(service)

    assert len(fake.calls) == 2
    assert fake.calls[1] == {"ev_a": False, "ev_b": False}


@pytest.mark.asyncio
async def test_followup_runs_after_failed_run():
    service = PlannerService()
    fake = _GatedPlanner(fail_first=True)
    p1, p2, p3, p4 = _patches(service, fake)
    with p1, p2, p3, p4:
        first, _ = await _run_with_followup(service, fake, [None])
        await _drain(service)

    assert first.success is False
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_waiting_request_returns_followup_result():
    service = PlannerService()
    fake = _GatedPlanner()
    p1, p2, p3, p4 = _patches(service, fake)
    with p1, p2, p3, p4:
        first = asyncio.create_task(service.run_once())
        await fake.started.wait()
        waiter = asyncio.create_task(service.run_once(wait=True))
        while not waiter.done():
            fake.release_all()
            await asyncio.sleep(0.01)
        await first
        result = await waiter
        await _drain(service)

    assert result.success is True
    assert result.queued is False
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_goal_pending_flag_lifecycle():
    service = PlannerService()
    fake = _GatedPlanner()
    p1, p2, p3, p4 = _patches(service, fake)
    with p1, p2, p3, p4:
        service.mark_goal_replan_pending(["ev_a"])
        assert service.goal_replan_pending("ev_a") is True
        run = asyncio.create_task(service.run_once())
        await fake.started.wait()
        # Running with the goal: still pending until the run reports.
        assert service.goal_replan_pending("ev_a") is True
        # A goal edited during the run needs the follow-up.
        service.mark_goal_replan_pending(["ev_b"])
        fake.release_all()
        await run
        assert service.goal_replan_pending("ev_a") is False
        assert service.goal_replan_pending("ev_b") is True


@pytest.mark.asyncio
async def test_goal_pending_cleared_on_failure():
    service = PlannerService()
    service.mark_goal_replan_pending(["ev_a"])
    with (
        patch("bin.run_planner.main", new_callable=AsyncMock, side_effect=RuntimeError("x")),
        patch("backend.services.planner_service.ws_manager.emit", new_callable=AsyncMock),
    ):
        result = await service.run_once()
    assert result.success is False
    assert service.goal_replan_pending("ev_a") is False
