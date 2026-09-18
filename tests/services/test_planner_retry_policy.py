"""Unit tests for PlannerService retry policy."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from backend.services.planner_service import _BACKOFF_STEPS, PlannerService
from planner.errors import PlannerErrorCode


def _fresh_service() -> PlannerService:
    return PlannerService()


def test_config_blocking_sets_suspended():
    svc = _fresh_service()
    svc._consecutive_failures = 1
    svc._apply_retry_policy(PlannerErrorCode.CONFIG_INVALID)
    assert svc._retry_suspended is True
    assert svc._next_retry_at is None


def test_clear_retry_suspension_resets_and_schedules_immediate():
    svc = _fresh_service()
    svc._retry_suspended = True
    svc._next_retry_at = None
    before = datetime.now(UTC)
    svc.clear_retry_suspension()
    assert svc._retry_suspended is False
    assert svc._next_retry_at is not None
    assert svc._next_retry_at >= before


def test_clear_retry_suspension_is_due_immediately_on_utc_plus_2(stockholm_tz):
    svc = _fresh_service()
    svc.clear_retry_suspension()
    assert svc.next_retry_at <= datetime.now(UTC) + timedelta(seconds=1)


def test_transient_backoff_is_60s_on_utc_plus_2(stockholm_tz):
    svc = _fresh_service()
    svc._consecutive_failures = 1
    svc._apply_retry_policy(PlannerErrorCode.PRICES_UNAVAILABLE)
    assert svc.next_retry_at is not None
    remaining = (svc.next_retry_at - datetime.now(UTC)).total_seconds()
    assert 55 <= remaining <= 65


def test_transient_backoff_three_failures():
    svc = _fresh_service()
    expected_delays = _BACKOFF_STEPS[:3]

    for i, expected_delay in enumerate(expected_delays, start=1):
        svc._consecutive_failures = i
        before = datetime.now(UTC)
        svc._apply_retry_policy(PlannerErrorCode.PRICES_UNAVAILABLE)

        assert svc._retry_suspended is False
        delay = (svc._next_retry_at - before).total_seconds()
        assert abs(delay - expected_delay) < 2.0, (
            f"Failure #{i}: expected ~{expected_delay}s delay, got {delay:.1f}s"
        )


def test_transient_backoff_caps_at_300():
    svc = _fresh_service()
    svc._consecutive_failures = 99  # Far past the cap
    before = datetime.now(UTC)
    svc._apply_retry_policy(PlannerErrorCode.FORECAST_UNAVAILABLE)
    delay = (svc._next_retry_at - before).total_seconds()
    assert abs(delay - 300) < 2.0, f"Expected cap at 300s, got {delay:.1f}s"


def test_invariant_failure_uses_60s_cadence():
    svc = _fresh_service()
    svc._consecutive_failures = 1
    before = datetime.now(UTC)
    svc._apply_retry_policy(PlannerErrorCode.SOLVER_INFEASIBLE)
    delay = (svc._next_retry_at - before).total_seconds()
    assert abs(delay - 60) < 2.0, f"Expected 60s for invariant, got {delay:.1f}s"


def test_warning_only_codes_do_not_set_last_error_code():
    svc = _fresh_service()
    svc._consecutive_failures = 1
    svc._apply_retry_policy(PlannerErrorCode.DATA_STALE)
    svc._apply_retry_policy(PlannerErrorCode.EV_DEADLINE_PAST)
    # warning_only codes don't modify retry state — _last_error_code is still None
    assert svc._retry_suspended is False
    assert svc._next_retry_at is None


def test_success_resets_all_state():
    svc = _fresh_service()
    svc._consecutive_failures = 5
    svc._retry_suspended = True
    svc._last_error_code = PlannerErrorCode.CONFIG_INVALID
    svc._last_error_at = datetime.now(UTC)
    svc._last_error_details = {"x": 1}
    svc._next_retry_at = datetime.now(UTC) + timedelta(minutes=5)

    svc._on_success()

    assert svc._consecutive_failures == 0
    assert svc._retry_suspended is False
    assert svc._last_error_code is None
    assert svc._last_error_at is None
    assert svc._last_error_details is None
    assert svc._next_retry_at is None


def test_retry_in_s_returns_none_when_suspended():
    svc = _fresh_service()
    svc._retry_suspended = True
    assert svc.retry_in_s is None


def test_retry_in_s_returns_seconds_remaining():
    svc = _fresh_service()
    svc._retry_suspended = False
    svc._next_retry_at = datetime.now(UTC) + timedelta(seconds=120)
    remaining = svc.retry_in_s
    assert remaining is not None
    assert 118 <= remaining <= 121


def test_suspension_ceiling_expires_after_1800_seconds(stockholm_tz):
    svc = _fresh_service()
    svc._retry_suspended = True
    svc._suspended_since = datetime.now(UTC) - timedelta(seconds=1801)
    assert svc.suspension_expired is True


@pytest.mark.asyncio
async def test_ha_outage_is_transient_and_recovers():
    svc = _fresh_service()
    svc._emit_progress = AsyncMock()
    svc._notify_error = AsyncMock()
    svc._notify_success = AsyncMock()
    svc._count_schedule_slots = lambda: 1

    calls = 0

    async def run_planner(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            from planner.errors import PlannerError

            raise PlannerError(PlannerErrorCode.HA_UNAVAILABLE)
        return 0

    with patch("bin.run_planner.main", side_effect=run_planner):
        first = await svc.run_once()
        second = await svc.run_once()

    assert first.error_code == PlannerErrorCode.HA_UNAVAILABLE.value
    assert first.planned_at.tzinfo == UTC
    assert svc.retry_suspended is False
    assert second.success is True


@pytest.mark.asyncio
async def test_unexpected_planner_failure_result_uses_aware_utc_timestamp():
    svc = _fresh_service()
    svc._emit_progress = AsyncMock()
    svc._notify_error = AsyncMock()

    async def run_planner(**kwargs):
        raise RuntimeError("unexpected failure")

    with patch("bin.run_planner.main", side_effect=run_planner):
        result = await svc.run_once()

    assert result.error_code == PlannerErrorCode.UNKNOWN.value
    assert result.planned_at.tzinfo == UTC
