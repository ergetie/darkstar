from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest

from backend.api.routers import energy
from backend.baseline import BaselineBattery
from backend.battery_comparison import CalibrationResult


@pytest.mark.asyncio
async def test_fit_cache_runs_off_loop_and_invalidates_for_config_and_end(tmp_path, monkeypatch):
    db = tmp_path / "learning.db"
    db.write_bytes(b"recording identity")
    store = type("Store", (), {"db_path": str(db)})()
    battery = BaselineBattery(10, 10, 95, 4000, 4000)
    observations = []
    now = datetime.now(UTC)
    event_loop_thread = threading.get_ident()
    worker_threads: list[int] = []
    calls = []

    def fake_fit(rows, capacity, end):
        worker_threads.append(threading.get_ident())
        calls.append((capacity, end))
        return CalibrationResult("insufficient_data", "too_few_grid_observations")

    monkeypatch.setattr(energy, "fit_calibration", fake_fit)
    energy._BATTERY_FIT_CACHE.clear()
    cfg = {"input_sensors": {"pv_power": "sensor.a"}}
    try:
        first = await energy._calibrated_fit(store, battery, cfg, observations, now, now)
        cached = await energy._calibrated_fit(store, battery, cfg, observations, now, now)
        await energy._calibrated_fit(
            store, battery, {"input_sensors": {"pv_power": "sensor.b"}}, observations, now, now
        )
        await energy._calibrated_fit(
            store, battery, cfg, observations, now + timedelta(minutes=1), now
        )
        assert first is cached
        assert len(calls) == 3
        assert worker_threads and all(
            thread_id != event_loop_thread for thread_id in worker_threads
        )
    finally:
        energy._BATTERY_FIT_CACHE.clear()


@pytest.mark.asyncio
async def test_cache_expires_and_remains_bounded(tmp_path, monkeypatch):
    db = tmp_path / "learning.db"
    db.write_bytes(b"identity")
    store = type("Store", (), {"db_path": str(db)})()
    battery = BaselineBattery(10, 10, 95, 4000, 4000)
    now = datetime.now(UTC)
    calls = []
    clock = [10.0]

    def fit(*args):
        calls.append(args)
        return CalibrationResult("insufficient_data", "too_few_grid_observations")

    monkeypatch.setattr(energy, "fit_calibration", fit)
    monkeypatch.setattr(energy.time, "monotonic", lambda: clock[0])
    energy._BATTERY_FIT_CACHE.clear()
    try:
        await energy._calibrated_fit(store, battery, {}, [], now, now)
        clock[0] += 899
        await energy._calibrated_fit(store, battery, {}, [], now, now)
        assert len(calls) == 1
        clock[0] += 1
        await energy._calibrated_fit(store, battery, {}, [], now, now)
        assert len(calls) == 2
        for index in range(20):
            boundary = now + timedelta(minutes=15 * (index + 1))
            await energy._calibrated_fit(store, battery, {}, [], boundary, boundary)
        assert len(energy._BATTERY_FIT_CACHE) == 16
    finally:
        energy._BATTERY_FIT_CACHE.clear()


@pytest.mark.asyncio
async def test_changed_database_identity_does_not_reuse_fit(tmp_path, monkeypatch):
    db = tmp_path / "learning.db"
    db.write_bytes(b"identity")
    store = type("Store", (), {"db_path": str(db)})()
    battery = BaselineBattery(10, 10, 95, 4000, 4000)
    now = datetime.now(UTC)
    calls = []

    def fit(*args):
        calls.append(args)
        return CalibrationResult("insufficient_data", "too_few_grid_observations")

    monkeypatch.setattr(energy, "fit_calibration", fit)
    energy._BATTERY_FIT_CACHE.clear()
    try:
        await energy._calibrated_fit(store, battery, {}, [], now, now)
        db.write_bytes(b"replacement observation database")
        await energy._calibrated_fit(store, battery, {}, [], now, now)
        assert len(calls) == 2
    finally:
        energy._BATTERY_FIT_CACHE.clear()
