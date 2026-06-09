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
