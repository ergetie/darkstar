import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backend.db_safety import RetentionConfig
from backend.services import db_maintenance_service as svc_module
from backend.services.db_maintenance_service import (
    CHECK_INTERVAL_SECONDS,
    FIRST_CHECK_SECONDS,
    LAST_RUN_KEY,
    DbMaintenanceService,
)

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


class FakeStore:
    def __init__(self, last_run: str | None = None) -> None:
        self.state: dict[str, str] = {} if last_run is None else {LAST_RUN_KEY: last_run}

    async def get_system_state(self, key: str) -> str | None:
        return self.state.get(key)

    async def set_system_state(self, key: str, value: str) -> None:
        self.state[key] = value


@pytest.fixture
def calls(monkeypatch):
    log: list[str] = []
    monkeypatch.setattr(
        svc_module, "prune", lambda *a, **k: log.append("prune") or {"execution_log": 3}
    )
    monkeypatch.setattr(svc_module, "incremental_vacuum", lambda *a, **k: log.append("vacuum") or 7)
    return log


def _service() -> DbMaintenanceService:
    return DbMaintenanceService(retention_loader=RetentionConfig, now=lambda: NOW)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("last_run", "due"),
    [
        (None, True),
        ((NOW - timedelta(hours=25)).isoformat(), True),
        ((NOW - timedelta(hours=24)).isoformat(), True),
        ((NOW - timedelta(hours=23)).isoformat(), False),
        ("garbage", True),
    ],
)
async def test_due_logic(calls, last_run, due):
    store = FakeStore(last_run)

    ran = await _service().run_if_due(store, Path("x.db"))

    assert ran is due
    assert calls == (["prune", "vacuum"] if due else [])
    if due:
        assert store.state[LAST_RUN_KEY] == NOW.isoformat()
    else:
        assert store.state[LAST_RUN_KEY] == last_run


@pytest.mark.asyncio
async def test_failure_does_not_write_key(monkeypatch, calls):
    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(svc_module, "prune", boom)
    store = FakeStore()

    assert await _service().run_if_due(store, Path("x.db")) is False
    assert LAST_RUN_KEY not in store.state
    assert calls == []


@pytest.mark.asyncio
async def test_locked_database_ends_run_without_key(monkeypatch, calls):
    def locked(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(svc_module, "prune", locked)
    store = FakeStore()

    assert await _service().run_if_due(store, Path("x.db")) is False
    assert LAST_RUN_KEY not in store.state
    assert "vacuum" not in calls


@pytest.mark.asyncio
async def test_loop_first_check_after_ten_minutes_then_hourly(calls):
    sleeps: list[float] = []
    stop = asyncio.Event()

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) >= 3:
            stop.set()
            await asyncio.sleep(3600)

    service = DbMaintenanceService(
        retention_loader=RetentionConfig, now=lambda: NOW, sleep=fake_sleep
    )
    store = FakeStore()
    await service.start(store, "x.db")
    await asyncio.wait_for(stop.wait(), 5)
    await service.stop()

    assert sleeps == [FIRST_CHECK_SECONDS, CHECK_INTERVAL_SECONDS, CHECK_INTERVAL_SECONDS]
    assert FIRST_CHECK_SECONDS == 600
    assert CHECK_INTERVAL_SECONDS == 3600
    assert calls == ["prune", "vacuum"]  # second check is not due


@pytest.mark.asyncio
async def test_real_prune_and_vacuum_run_on_database(tmp_path):
    db = tmp_path / "m.db"
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        conn.execute("CREATE TABLE execution_log (id INTEGER PRIMARY KEY, executed_at TEXT)")
        conn.execute("INSERT INTO execution_log (executed_at) VALUES ('2020-01-01T00:00:00+00:00')")
    store = FakeStore()

    assert await _service().run_if_due(store, db) is True

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM execution_log").fetchone()[0] == 0
