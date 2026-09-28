"""Persistence semantics of the batched forecast and plan upserts."""

import logging
import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import pytest
import pytest_asyncio
import pytz

from backend.learning.models import Base
from backend.learning.store import LearningStore

TZ = pytz.timezone("Europe/Stockholm")
START = TZ.localize(datetime(2026, 9, 28, 0, 0))


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "batched.db")


@pytest_asyncio.fixture
async def store(db_path):
    store = LearningStore(db_path, TZ)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield store
    await store.close()


def _forecast(i: int, **overrides):
    row = {
        "slot_start": START + timedelta(minutes=15 * i),
        "pv_forecast_kwh": 0.1 * i,
        "openmeteo_pv_forecast_kwh": 0.2 * i,
        "load_forecast_kwh": 0.3,
        "pv_p10": 0.05 * i,
        "pv_p90": 0.15 * i,
        "load_p10": 0.2,
        "load_p90": 0.4,
        "base_load_forecast_kwh": 0.25,
        "base_load_p10": 0.2,
        "base_load_p90": 0.3,
        "temp_c": 12.5,
    }
    row.update(overrides)
    return row


def _forecast_rows(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM slot_forecasts WHERE forecast_version = 'aurora' "
                "ORDER BY slot_start"
            ).fetchall()
        ]


@pytest.mark.asyncio
async def test_store_forecasts_inserts_all_rows(store, db_path):
    await store.store_forecasts([_forecast(i) for i in range(672)], "aurora")

    rows = _forecast_rows(db_path)
    assert len(rows) == 672
    assert rows[10]["slot_start"] == (START + timedelta(minutes=150)).isoformat()
    assert rows[10]["pv_forecast_kwh"] == pytest.approx(1.0)
    assert rows[10]["openmeteo_pv_forecast_kwh"] == pytest.approx(2.0)
    assert rows[10]["temp_c"] == 12.5


@pytest.mark.asyncio
async def test_store_forecasts_updates_existing_rows(store, db_path):
    await store.store_forecasts([_forecast(i) for i in range(4)], "aurora")
    await store.store_forecasts(
        [
            _forecast(
                i,
                pv_forecast_kwh=9.0,
                openmeteo_pv_forecast_kwh=8.0,
                load_forecast_kwh=7.0,
                pv_p10=1.0,
                pv_p90=2.0,
                load_p10=3.0,
                load_p90=4.0,
                base_load_forecast_kwh=5.0,
                base_load_p10=6.0,
                base_load_p90=6.5,
                temp_c=-1.0,
            )
            for i in range(4)
        ],
        "aurora",
    )

    rows = _forecast_rows(db_path)
    assert len(rows) == 4
    for row in rows:
        assert row["pv_forecast_kwh"] == 9.0
        assert row["openmeteo_pv_forecast_kwh"] == 8.0
        assert row["load_forecast_kwh"] == 7.0
        assert (row["pv_p10"], row["pv_p90"]) == (1.0, 2.0)
        assert (row["load_p10"], row["load_p90"]) == (3.0, 4.0)
        assert row["base_load_forecast_kwh"] == 5.0
        assert (row["base_load_p10"], row["base_load_p90"]) == (6.0, 6.5)
        assert row["temp_c"] == -1.0


@pytest.mark.asyncio
async def test_store_forecasts_null_openmeteo_keeps_stored_value(store, db_path):
    await store.store_forecasts([_forecast(i) for i in range(1, 3)], "aurora")
    await store.store_forecasts(
        [
            _forecast(1, openmeteo_pv_forecast_kwh=None, pv_forecast_kwh=5.0),
            _forecast(2, openmeteo_pv_forecast_kwh=3.0),
        ],
        "aurora",
    )

    rows = _forecast_rows(db_path)
    assert rows[0]["openmeteo_pv_forecast_kwh"] == pytest.approx(0.2)
    assert rows[0]["pv_forecast_kwh"] == 5.0
    assert rows[1]["openmeteo_pv_forecast_kwh"] == 3.0


@pytest.mark.asyncio
async def test_store_forecasts_skips_rows_without_slot_start(store, db_path):
    no_start = _forecast(1)
    no_start.pop("slot_start")
    string_start = _forecast(2)
    string_start.pop("slot_start")
    string_start["start_time"] = (START + timedelta(minutes=30)).isoformat()

    await store.store_forecasts([_forecast(0), no_start, string_start], "aurora")

    rows = _forecast_rows(db_path)
    assert [r["slot_start"] for r in rows] == [
        START.isoformat(),
        (START + timedelta(minutes=30)).isoformat(),
    ]


@pytest.mark.asyncio
async def test_store_forecasts_duplicate_slot_last_wins(store, db_path):
    await store.store_forecasts(
        [_forecast(0, pv_forecast_kwh=1.0), _forecast(0, pv_forecast_kwh=2.0)], "aurora"
    )

    rows = _forecast_rows(db_path)
    assert len(rows) == 1
    assert rows[0]["pv_forecast_kwh"] == 2.0


@pytest.mark.asyncio
async def test_store_forecasts_all_rows_skipped_is_noop(store, db_path):
    row = _forecast(0)
    row.pop("slot_start")
    await store.store_forecasts([row], "aurora")
    assert _forecast_rows(db_path) == []


def _plan_rows(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(r) for r in conn.execute("SELECT * FROM slot_plans ORDER BY slot_start").fetchall()
        ]


@pytest.mark.asyncio
async def test_store_plan_scales_energy_by_slot_duration(store, db_path):
    slots = []
    for i, minutes in enumerate([15, 30, 60]):
        start = START + timedelta(hours=2 * i)
        slots.append(
            {
                "start_time": start,
                "end_time": start + timedelta(minutes=minutes),
                "water_heating_kw": 2.0,
                "ev_charging_kw": 4.0,
                "kepler_charge_kwh": 1.5,
            }
        )
    await store.store_plan(pd.DataFrame(slots))

    rows = _plan_rows(db_path)
    assert [r["planned_water_heating_kwh"] for r in rows] == [0.5, 1.0, 2.0]
    assert [r["planned_ev_charging_kwh"] for r in rows] == [1.0, 2.0, 4.0]
    assert all(r["planned_charge_kwh"] == 1.5 for r in rows)
    assert rows[1]["slot_end"] == (START + timedelta(hours=2, minutes=30)).isoformat()


@pytest.mark.asyncio
async def test_store_plan_missing_end_stored_null_with_warning(store, db_path, caplog):
    slots = [
        {"start_time": START, "water_heating_kw": 2.0},
        {"start_time": START + timedelta(minutes=15), "water_heating_kw": 2.0},
    ]
    with caplog.at_level(logging.WARNING, logger="darkstar.learning.store"):
        await store.store_plan(pd.DataFrame(slots))

    rows = _plan_rows(db_path)
    assert [r["slot_end"] for r in rows] == [None, None]
    assert [r["planned_water_heating_kwh"] for r in rows] == [0.5, 0.5]
    warnings = [r for r in caplog.records if "missing or invalid end" in r.getMessage()]
    assert len(warnings) == 2


@pytest.mark.asyncio
async def test_store_plan_update_refreshes_created_at(store, db_path):
    slot = {
        "start_time": START,
        "end_time": START + timedelta(minutes=15),
        "kepler_charge_kwh": 1.0,
    }
    await store.store_plan(pd.DataFrame([slot]))
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE slot_plans SET created_at = '2000-01-01 00:00:00'")

    await store.store_plan(pd.DataFrame([{**slot, "kepler_charge_kwh": 2.0}]))

    rows = _plan_rows(db_path)
    assert len(rows) == 1
    assert rows[0]["planned_charge_kwh"] == 2.0
    assert rows[0]["created_at"] != "2000-01-01 00:00:00"
