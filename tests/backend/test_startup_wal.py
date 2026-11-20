import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz
from fastapi import FastAPI

from backend.learning.store import LearningStore


def _journal_mode(db_path: str) -> str:
    with sqlite3.connect(db_path) as conn:
        return str(conn.execute("PRAGMA journal_mode").fetchone()[0])


@pytest.mark.asyncio
async def test_ensure_wal_mode_is_idempotent(tmp_path):
    db_path = tmp_path / "planner_learning.db"
    store = LearningStore(str(db_path), pytz.UTC)
    try:
        await store.ensure_wal_mode()
        await store.ensure_wal_mode()
        assert _journal_mode(str(db_path)).lower() == "wal"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_startup_enables_wal_when_executor_disabled(tmp_path, monkeypatch):
    from backend.main import lifespan

    db_path = tmp_path / "planner_learning.db"
    executor = MagicMock()
    executor.config.enabled = False

    monkeypatch.setenv("DB_PATH", str(db_path))

    with (
        patch("ml.bootstrap.ensure_active_models"),
        patch("backend.main.load_yaml", return_value={"timezone": "UTC"}),
        patch("backend.services.scheduler_service.scheduler_service.start", new_callable=AsyncMock),
        patch("backend.services.scheduler_service.scheduler_service.stop", new_callable=AsyncMock),
        patch("backend.services.recorder_service.recorder_service.start", new_callable=AsyncMock),
        patch("backend.services.recorder_service.recorder_service.stop", new_callable=AsyncMock),
        patch("backend.main.get_executor_instance", return_value=executor),
        patch("backend.ha_socket.start_ha_socket_client"),
        patch("backend.ha_socket.stop_ha_socket_client"),
        patch("ml.price_forecast.cleanup_price_forecast_duplicates", return_value=0),
    ):
        async with lifespan(FastAPI()) as _:
            assert _journal_mode(str(db_path)).lower() == "wal"

    executor.start.assert_not_called()


def _lifespan_patches(executor):
    return (
        patch("ml.bootstrap.ensure_active_models"),
        patch("backend.main.load_yaml", return_value={"timezone": "UTC"}),
        patch("backend.services.scheduler_service.scheduler_service.start", new_callable=AsyncMock),
        patch("backend.services.scheduler_service.scheduler_service.stop", new_callable=AsyncMock),
        patch("backend.services.recorder_service.recorder_service.start", new_callable=AsyncMock),
        patch("backend.services.recorder_service.recorder_service.stop", new_callable=AsyncMock),
        patch("backend.main.get_executor_instance", return_value=executor),
        patch("backend.ha_socket.start_ha_socket_client"),
        patch("backend.ha_socket.stop_ha_socket_client"),
        patch("ml.price_forecast.cleanup_price_forecast_duplicates", return_value=0),
    )


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_db_maintenance(tmp_path, monkeypatch):
    from contextlib import ExitStack

    from backend.main import lifespan

    executor = MagicMock()
    executor.config.enabled = False
    db_path = tmp_path / "planner_learning.db"
    monkeypatch.setenv("DB_PATH", str(db_path))

    with ExitStack() as stack:
        for p in _lifespan_patches(executor):
            stack.enter_context(p)
        start = stack.enter_context(
            patch(
                "backend.services.db_maintenance_service.db_maintenance_service.start",
                new_callable=AsyncMock,
            )
        )
        stop = stack.enter_context(
            patch(
                "backend.services.db_maintenance_service.db_maintenance_service.stop",
                new_callable=AsyncMock,
            )
        )
        async with lifespan(FastAPI()) as _:
            start.assert_awaited_once()
            assert start.await_args.args[1] == str(db_path)
            stop.assert_not_awaited()
        stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_survives_db_maintenance_start_failure(tmp_path, monkeypatch):
    from contextlib import ExitStack

    from backend.main import lifespan

    executor = MagicMock()
    executor.config.enabled = False
    monkeypatch.setenv("DB_PATH", str(tmp_path / "planner_learning.db"))

    with ExitStack() as stack:
        for p in _lifespan_patches(executor):
            stack.enter_context(p)
        stack.enter_context(
            patch(
                "backend.services.db_maintenance_service.db_maintenance_service.start",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            )
        )
        entered = False
        async with lifespan(FastAPI()) as _:
            entered = True
        assert entered


@pytest.mark.asyncio
async def test_shutdown_cancels_maintenance_task():
    import asyncio

    from backend.services.db_maintenance_service import DbMaintenanceService

    class Store:
        async def get_system_state(self, key):
            return None

        async def set_system_state(self, key, value):
            pass

    service = DbMaintenanceService()
    await service.start(Store(), "x.db")
    task = service._task
    assert task is not None and not task.done()

    await service.stop()

    assert task.cancelled()
    await asyncio.sleep(0)
