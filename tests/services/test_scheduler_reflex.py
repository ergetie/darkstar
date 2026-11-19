"""Daily Aurora Reflex scheduling in SchedulerService.

Reflex used to run daily from the legacy backend/scheduler.py; the async
SchedulerService must keep doing that when learning.reflex_enabled is true.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytz

from backend.services.scheduler_service import (
    REFLEX_RUN_HOUR,
    REFLEX_RUN_MINUTE,
    SchedulerService,
)

STOCKHOLM = pytz.timezone("Europe/Stockholm")
ENABLED = {"learning": {"enable": True, "reflex_enabled": True}, "timezone": "Europe/Stockholm"}


def _local(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return STOCKHOLM.localize(datetime(year, month, day, hour, minute)).astimezone(UTC)


@pytest.mark.parametrize(
    ("learning", "expected"),
    [
        ({"enable": True, "reflex_enabled": True}, True),
        ({"enable": True, "reflex_enabled": False}, False),
        ({"enable": False, "reflex_enabled": True}, False),
        ({}, False),
    ],
)
def test_reflex_enabled_requires_learning_and_reflex(learning, expected):
    assert SchedulerService._reflex_enabled({"learning": learning}) is expected


def test_next_reflex_later_today_when_before_run_time():
    now = _local(2026, 11, 19, 2, 0)
    nxt = SchedulerService()._compute_next_reflex(ENABLED, now=now)
    assert nxt == _local(2026, 11, 19, REFLEX_RUN_HOUR, REFLEX_RUN_MINUTE)


def test_next_reflex_tomorrow_when_run_time_passed():
    now = _local(2026, 11, 19, 10, 0)
    nxt = SchedulerService()._compute_next_reflex(ENABLED, now=now)
    assert nxt == _local(2026, 11, 20, REFLEX_RUN_HOUR, REFLEX_RUN_MINUTE)


def test_next_reflex_keeps_local_time_across_dst():
    # 2026-10-25 is the CET switch; 04:30 local must stay 04:30 local (03:30 UTC).
    now = _local(2026, 10, 24, 12, 0)
    nxt = SchedulerService()._compute_next_reflex(ENABLED, now=now)
    assert nxt.astimezone(STOCKHOLM).hour == REFLEX_RUN_HOUR
    assert nxt == datetime(2026, 10, 25, 3, 30, tzinfo=UTC)


async def test_check_reflex_runs_when_due_and_reschedules():
    svc = SchedulerService()
    svc._status.reflex_enabled = True
    svc._status.next_reflex_at = datetime.now(UTC) - timedelta(minutes=1)

    with patch("backend.learning.reflex.AuroraReflex", autospec=True) as reflex_cls:
        reflex_cls.return_value.run = AsyncMock(return_value=["No updates needed."])
        await svc._check_reflex(ENABLED)

    reflex_cls.return_value.run.assert_awaited_once_with(dry_run=False)
    assert svc._status.last_reflex_status == "success"
    assert svc._status.current_task == "idle"
    assert svc._status.next_reflex_at > datetime.now(UTC)


async def test_check_reflex_skips_when_not_due():
    svc = SchedulerService()
    svc._status.reflex_enabled = True
    svc._status.next_reflex_at = datetime.now(UTC) + timedelta(hours=1)

    with patch("backend.learning.reflex.AuroraReflex", autospec=True) as reflex_cls:
        await svc._check_reflex(ENABLED)

    reflex_cls.assert_not_called()


async def test_check_reflex_skips_when_busy():
    svc = SchedulerService()
    svc._status.reflex_enabled = True
    svc._status.next_reflex_at = datetime.now(UTC) - timedelta(minutes=1)
    svc._status.current_task = "ml_training"

    with patch("backend.learning.reflex.AuroraReflex", autospec=True) as reflex_cls:
        await svc._check_reflex(ENABLED)

    reflex_cls.assert_not_called()


async def test_check_reflex_disabled_clears_schedule():
    svc = SchedulerService()
    svc._status.reflex_enabled = True
    svc._status.next_reflex_at = datetime.now(UTC) - timedelta(minutes=1)

    with patch("backend.learning.reflex.AuroraReflex", autospec=True) as reflex_cls:
        await svc._check_reflex({"learning": {"enable": True, "reflex_enabled": False}})

    reflex_cls.assert_not_called()
    assert svc._status.reflex_enabled is False
    assert svc._status.next_reflex_at is None


async def test_enabling_reflex_live_schedules_instead_of_running():
    svc = SchedulerService()
    svc._status.reflex_enabled = False
    svc._status.next_reflex_at = None

    with patch("backend.learning.reflex.AuroraReflex", autospec=True) as reflex_cls:
        await svc._check_reflex(ENABLED)

    reflex_cls.assert_not_called()
    assert svc._status.next_reflex_at is not None
    assert svc._status.next_reflex_at > datetime.now(UTC)


async def test_failed_reflex_run_still_advances_schedule():
    svc = SchedulerService()
    svc._status.reflex_enabled = True
    svc._status.next_reflex_at = datetime.now(UTC) - timedelta(minutes=1)

    with patch("backend.learning.reflex.AuroraReflex", autospec=True) as reflex_cls:
        reflex_cls.return_value.run = AsyncMock(side_effect=RuntimeError("boom"))
        await svc._check_reflex(ENABLED)

    assert svc._status.last_reflex_status == "error"
    assert svc._status.current_task == "idle"
    assert svc._status.next_reflex_at > datetime.now(UTC)
