"""E2E test: retry policy sequence — config-blocking → settings_saved → success."""

from datetime import UTC, datetime, timedelta

import pytest

from backend.services.planner_service import PlannerService
from planner.errors import PlannerErrorCode


@pytest.mark.asyncio
async def test_config_blocking_then_settings_saved_then_success(stockholm_tz):
    """Simulate: config-blocking fail → clear_retry_suspension (settings_saved) → success."""
    svc = PlannerService()

    # Simulate config-blocking failure
    svc._consecutive_failures = 1
    svc._apply_retry_policy(PlannerErrorCode.CONFIG_INVALID)
    assert svc._retry_suspended is True
    assert svc._next_retry_at is None

    # Simulate settings_saved event → clear_retry_suspension
    svc.clear_retry_suspension()
    assert svc._retry_suspended is False
    assert svc._next_retry_at is not None
    assert svc._next_retry_at <= datetime.now(UTC) + timedelta(seconds=1)

    # Simulate successful run
    svc._on_success()
    assert svc._consecutive_failures == 0
    assert svc._last_error_code is None
    assert svc._retry_suspended is False
