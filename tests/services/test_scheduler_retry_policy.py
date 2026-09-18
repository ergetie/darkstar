"""Regression tests for scheduler retry decisions and skip logging."""

from datetime import UTC, datetime, timedelta

import pytest

import backend.services.scheduler_service as scheduler_module
from backend.services.planner_service import PlannerResult, PlannerService
from backend.services.scheduler_service import SchedulerService
from planner.errors import PlannerErrorCode


def test_skip_reason_change_logs_immediately(caplog):
    scheduler = SchedulerService()
    due_at = datetime.now(UTC) + timedelta(seconds=30)

    with caplog.at_level("INFO", logger="darkstar.services.scheduler"):
        scheduler._log_skip("retry_pending", due_at)
        scheduler._log_skip("suspended", None)

    assert len(caplog.records) == 2
    assert "retry_pending" in caplog.records[0].message
    assert "suspended" in caplog.records[1].message


def test_repeated_skip_reason_is_rate_limited(caplog):
    scheduler = SchedulerService()
    due_at = datetime.now(UTC) + timedelta(seconds=30)

    with caplog.at_level("INFO", logger="darkstar.services.scheduler"):
        for _ in range(10):
            scheduler._log_skip("retry_pending", due_at)

    assert len(caplog.records) == 1


@pytest.mark.asyncio
async def test_suspension_retries_after_ceiling(monkeypatch, stockholm_tz):
    scheduler = SchedulerService()
    svc = PlannerService()
    svc._retry_suspended = True
    svc._suspended_since = datetime.now(UTC) - timedelta(seconds=1801)
    attempts = 0

    async def fail_again():
        nonlocal attempts
        attempts += 1
        svc._consecutive_failures += 1
        svc._last_error_code = PlannerErrorCode.CONFIG_INVALID
        svc._apply_retry_policy(PlannerErrorCode.CONFIG_INVALID)
        scheduler._running = False
        return PlannerResult(
            success=False,
            planned_at=datetime.now(UTC),
            error="configuration remains invalid",
            error_code=PlannerErrorCode.CONFIG_INVALID.value,
        )

    svc.run_once = fail_again
    monkeypatch.setattr(scheduler_module, "planner_service", svc)
    monkeypatch.setattr(scheduler_module.asyncio, "sleep", lambda _seconds: _completed())
    scheduler._load_config = lambda: {"enabled": True, "every_minutes": 30, "jitter_minutes": 0}
    scheduler._running = True

    await scheduler._loop()

    assert attempts == 1
    assert svc.retry_suspended is True
    assert svc._suspended_since is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("next_retry_at", "expected_reason"),
    [
        ("future", "retry_pending"),
        ("due", "cadence_pending"),
    ],
)
async def test_scheduler_logs_non_run_reason(monkeypatch, caplog, next_retry_at, expected_reason):
    scheduler = SchedulerService()
    svc = PlannerService()
    now = datetime.now(UTC)
    svc._next_retry_at = now + timedelta(minutes=5) if next_retry_at == "future" else now

    async def tick(_seconds):
        scheduler._running = False

    monkeypatch.setattr(scheduler_module, "planner_service", svc)
    monkeypatch.setattr(scheduler_module.asyncio, "sleep", tick)
    scheduler._load_config = lambda: {"enabled": True, "every_minutes": 30, "jitter_minutes": 0}
    scheduler._running = True

    with caplog.at_level("INFO", logger="darkstar.services.scheduler"):
        await scheduler._loop()

    assert any(expected_reason in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_scheduler_logs_active_suspension_without_running(monkeypatch, caplog):
    scheduler = SchedulerService()
    svc = PlannerService()
    svc._retry_suspended = True
    svc._suspended_since = datetime.now(UTC)

    async def tick(_seconds):
        scheduler._running = False

    monkeypatch.setattr(scheduler_module, "planner_service", svc)
    monkeypatch.setattr(scheduler_module.asyncio, "sleep", tick)
    scheduler._load_config = lambda: {"enabled": True, "every_minutes": 30, "jitter_minutes": 0}
    scheduler._running = True

    with caplog.at_level("INFO", logger="darkstar.services.scheduler"):
        await scheduler._loop()

    assert any("suspended" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_new_planner_attempts_after_restart(monkeypatch):
    scheduler = SchedulerService()
    svc = PlannerService()
    attempts = 0

    async def run_once():
        nonlocal attempts
        attempts += 1
        scheduler._running = False
        return PlannerResult(success=True, planned_at=datetime.now(UTC))

    async def tick(_seconds):
        scheduler._status.next_run_at = datetime.now(UTC) - timedelta(seconds=1)

    svc.run_once = run_once
    monkeypatch.setattr(scheduler_module, "planner_service", svc)
    monkeypatch.setattr(scheduler_module.asyncio, "sleep", tick)
    scheduler._load_config = lambda: {"enabled": True, "every_minutes": 30, "jitter_minutes": 0}
    scheduler._running = True

    await scheduler._loop()

    assert attempts == 1


@pytest.mark.asyncio
async def test_settings_saved_retry_runs_on_next_scheduler_tick(monkeypatch):
    scheduler = SchedulerService()
    svc = PlannerService()
    svc._retry_suspended = True
    svc.clear_retry_suspension()
    attempts = 0

    async def run_once():
        nonlocal attempts
        attempts += 1
        scheduler._running = False
        return PlannerResult(success=True, planned_at=datetime.now(UTC))

    async def tick(_seconds):
        scheduler._status.next_run_at = datetime.now(UTC) - timedelta(seconds=1)

    svc.run_once = run_once
    monkeypatch.setattr(scheduler_module, "planner_service", svc)
    monkeypatch.setattr(scheduler_module.asyncio, "sleep", tick)
    scheduler._load_config = lambda: {"enabled": True, "every_minutes": 30, "jitter_minutes": 0}
    scheduler._running = True

    await scheduler._loop()

    assert attempts == 1


async def _completed():
    return None
