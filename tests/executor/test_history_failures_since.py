"""ExecutionHistory.get_failures_since: the failed-action feed of the plan archive."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine

from backend.learning.models import Base
from executor.history import ExecutionHistory, ExecutionRecord

LOCAL = ZoneInfo("Europe/Stockholm")
T0 = datetime(2026, 11, 21, 10, 0, tzinfo=UTC)


@pytest.fixture
def history(tmp_path):
    path = str(tmp_path / "ticks.db")
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    return ExecutionHistory(path, timezone="Europe/Stockholm")


def _log(history: ExecutionHistory, minutes: int, *, success: int, message: str | None) -> None:
    moment = (T0 + timedelta(minutes=minutes)).astimezone(LOCAL).isoformat()
    history.log_execution(
        ExecutionRecord(
            executed_at=moment, slot_start=moment, success=success, error_message=message
        )
    )


def test_only_newer_failures_are_returned_oldest_first(history):
    _log(history, 0, success=0, message="at cutoff")
    _log(history, -5, success=0, message="older")
    _log(history, 5, success=1, message=None)
    _log(history, 10, success=0, message="second")
    _log(history, 7, success=0, message="first")

    failures, total = history.get_failures_since(T0.isoformat())

    assert [f["error_message"] for f in failures] == ["first", "second"]
    assert total == 2
    assert set(failures[0]) == {"executed_at", "slot_start", "error_message"}


def test_limit_keeps_newest_and_reports_total(history):
    for i in range(1, 6):
        _log(history, i, success=0, message=f"e{i}")

    failures, total = history.get_failures_since(T0.isoformat(), limit=3)

    assert [f["error_message"] for f in failures] == ["e3", "e4", "e5"]
    assert total == 5


def test_naive_since_is_read_as_utc(history):
    _log(history, 5, success=0, message="after")
    failures, _ = history.get_failures_since("2026-11-21T10:00:00")
    assert [f["error_message"] for f in failures] == ["after"]


def test_empty(history):
    assert history.get_failures_since(T0.isoformat()) == ([], 0)
