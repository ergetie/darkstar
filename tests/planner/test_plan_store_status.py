"""A failed slot_plans save is surfaced as a PLAN_STORE_FAILED health warning."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from backend.health import HealthChecker
from backend.services.planner_service import PlannerService
from planner.errors import PlannerErrorCode, is_warning_only
from planner.pipeline import _store_plan_history
from planner.plan_store_status import clear_plan_store_failure, get_plan_store_failure

CONFIG = {"learning": {"sqlite_path": "unused.db"}}


@pytest.fixture(autouse=True)
def _reset_status():
    clear_plan_store_failure()
    yield
    clear_plan_store_failure()


def _plan_df() -> pd.DataFrame:
    return pd.DataFrame(
        {"kepler_charge_kwh": [0.5]},
        index=pd.DatetimeIndex([pd.Timestamp("2026-10-04T12:00:00+02:00")], name="start_time"),
    )


def _store(side_effect: Exception | None = None) -> MagicMock:
    store = MagicMock()
    store.store_plan = AsyncMock(side_effect=side_effect)
    return store


def _plan_store_issues() -> list:
    idle_svc = MagicMock(retry_suspended=False, last_error_code=None)
    with patch("backend.services.planner_service.planner_service", idle_svc):
        issues = HealthChecker().check_planner()
    return [i for i in issues if i.code == PlannerErrorCode.PLAN_STORE_FAILED.value]


def test_plan_store_failed_is_warning_only():
    assert is_warning_only(PlannerErrorCode.PLAN_STORE_FAILED)


@pytest.mark.asyncio
async def test_failed_save_is_recorded_logged_and_surfaced(caplog):
    with (
        patch("planner.pipeline.LearningStore", return_value=_store(RuntimeError("database is locked"))),
        caplog.at_level(logging.ERROR, logger="darkstar.planner"),
    ):
        await _store_plan_history(_plan_df(), CONFIG, "Europe/Stockholm")

    failure = get_plan_store_failure()
    assert failure is not None
    assert "database is locked" in failure.summary
    assert any(r.levelno == logging.ERROR and r.exc_info for r in caplog.records)

    issues = _plan_store_issues()
    assert len(issues) == 1
    assert issues[0].category == "planner"
    assert issues[0].severity == "warning"
    assert issues[0].details is not None
    assert "database is locked" in issues[0].details["error"]


@pytest.mark.asyncio
async def test_next_successful_save_clears_warning():
    with patch("planner.pipeline.LearningStore", return_value=_store(RuntimeError("boom"))):
        await _store_plan_history(_plan_df(), CONFIG, "Europe/Stockholm")
    assert _plan_store_issues()

    with patch("planner.pipeline.LearningStore", return_value=_store()):
        await _store_plan_history(_plan_df(), CONFIG, "Europe/Stockholm")
    assert get_plan_store_failure() is None
    assert _plan_store_issues() == []


@pytest.mark.asyncio
async def test_failed_save_keeps_run_successful_and_retry_state_clean():
    svc = PlannerService()
    svc._emit_progress = AsyncMock()
    svc._notify_error = AsyncMock()
    svc._notify_success = AsyncMock()
    svc._count_schedule_slots = lambda: 1

    async def run_planner(**kwargs):
        with patch("planner.pipeline.LearningStore", return_value=_store(RuntimeError("boom"))):
            await _store_plan_history(_plan_df(), CONFIG, "Europe/Stockholm")
        return 0

    with patch("bin.run_planner.main", side_effect=run_planner):
        result = await svc.run_once()

    assert result.success is True
    assert svc._consecutive_failures == 0
    assert svc.retry_suspended is False
    assert svc.last_error_code is None
    assert get_plan_store_failure() is not None

    with patch("backend.services.planner_service.planner_service", svc):
        issues = HealthChecker().check_planner()
    assert [i.code for i in issues] == [PlannerErrorCode.PLAN_STORE_FAILED.value]
    assert issues[0].severity == "warning"
