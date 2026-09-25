import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import pytest
import pytest_asyncio
import pytz

from backend.learning.models import Base
from backend.learning.store import LearningStore

# Mock timezone
TZ = pytz.timezone("Europe/Stockholm")


@pytest.fixture
def memory_db_path(tmp_path):
    return str(tmp_path / "test_learning.db")


@pytest_asyncio.fixture
async def store(memory_db_path):
    store = LearningStore(memory_db_path, TZ)
    # Manually create schema for tests using async engine
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield store

    # Cleanup threads
    await store.close()


@pytest.mark.asyncio
async def test_store_plan_mappings(store, memory_db_path):
    """
    Verify that store_plan correctly maps:
    - soc_target_percent -> planned_soc_percent
    - water_heating_kw -> planned_water_heating_kwh (converted)
    """

    # 1. Create a dummy DataFrame
    now = datetime.now(TZ).replace(second=0, microsecond=0)

    # Create 4 slots (1 hour)
    slots = []
    for i in range(4):
        t = now + timedelta(minutes=15 * i)
        slots.append(
            {
                "start_time": t,
                "kepler_charge_kwh": 0.0,
                "kepler_discharge_kwh": 0.0,
                "kepler_soc_percent": 0.0,  # Old column, should be ignored for target
                "soc_target_percent": 50.0 + i,  # New column we want to Map
                "water_heating_kw": 2.0,  # 2 kW -> 0.5 kWh per 15min slot
                "planned_cost_sek": 10.0,
            }
        )

    df = pd.DataFrame(slots)

    # 2. Store the plan
    await store.store_plan(df)

    # 3. Verify DB contents using sqlite3 (sync)
    with sqlite3.connect(memory_db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Check SoC Target Mapping
        cursor.execute("SELECT planned_soc_percent FROM slot_plans ORDER BY slot_start")
        rows = cursor.fetchall()
        assert len(rows) == 4
        assert rows[0]["planned_soc_percent"] == 50.0
        assert rows[1]["planned_soc_percent"] == 51.0

        # Check Water Heating Mapping & Conversion
        # 2.0 kW * 0.25h = 0.5 kWh
        cursor.execute("SELECT planned_water_heating_kwh FROM slot_plans ORDER BY slot_start")
        rows = cursor.fetchall()
        assert rows[0]["planned_water_heating_kwh"] == 0.5
        assert rows[1]["planned_water_heating_kwh"] == 0.5


@pytest.mark.asyncio
async def test_store_plan_projected_soc_percent(store, memory_db_path):
    """
    Verify that store_plan correctly persists projected_soc_percent to database.
    """
    now = datetime.now(TZ).replace(second=0, microsecond=0)

    # Create 4 slots with varying projected SoC values
    slots = []
    for i in range(4):
        t = now + timedelta(minutes=15 * i)
        slots.append(
            {
                "start_time": t,
                "kepler_charge_kwh": 1.0,
                "kepler_discharge_kwh": 0.0,
                "soc_target_percent": 80.0,  # Target SoC (same for all slots in a charge block)
                "projected_soc_percent": 50.0 + (i * 10),  # Projected SoC increases each slot
                "kepler_import_kwh": 0.0,
                "kepler_export_kwh": 0.0,
                "water_heating_kw": 0.0,
                "planned_cost_sek": 5.0,
            }
        )

    df = pd.DataFrame(slots)
    await store.store_plan(df)

    # Verify DB contents using sqlite3 (sync)
    with sqlite3.connect(memory_db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Check Projected SoC values
        cursor.execute("SELECT projected_soc_percent FROM slot_plans ORDER BY slot_start")
        rows = cursor.fetchall()
        assert len(rows) == 4
        assert rows[0]["projected_soc_percent"] == 50.0
        assert rows[1]["projected_soc_percent"] == 60.0
        assert rows[2]["projected_soc_percent"] == 70.0
        assert rows[3]["projected_soc_percent"] == 80.0


@pytest.mark.asyncio
async def test_store_plan_round_trips_planned_ev_kwh(store):
    """ev_charging_kw is stored as kWh per 15-min slot and returned by get_plans_range."""
    now = datetime.now(TZ).replace(second=0, microsecond=0)
    df = pd.DataFrame(
        [
            {"start_time": now, "ev_charging_kw": 11.0},
            {"start_time": now + timedelta(minutes=15), "ev_charging_kw": 0.0},
        ]
    )
    await store.store_plan(df)

    plans = await store.get_plans_range(now)

    assert [p["planned_ev_charging_kwh"] for p in plans] == [2.75, 0.0]


@pytest.mark.asyncio
async def test_get_plans_range_returns_projected_soc_percent(store):
    """
    Verify that get_plans_range returns projected_soc_percent for each slot.
    """
    now = datetime.now(TZ).replace(second=0, microsecond=0)

    # Create and store slots with projected_soc_percent
    slots = []
    for i in range(4):
        t = now + timedelta(minutes=15 * i)
        slots.append(
            {
                "start_time": t,
                "kepler_charge_kwh": 1.0,
                "kepler_discharge_kwh": 0.0,
                "soc_target_percent": 80.0,
                "projected_soc_percent": 50.0 + (i * 10),
                "kepler_import_kwh": 0.0,
                "kepler_export_kwh": 0.0,
                "water_heating_kw": 0.0,
                "planned_cost_sek": 5.0,
            }
        )

    df = pd.DataFrame(slots)
    await store.store_plan(df)

    # Retrieve plans using get_plans_range
    plans = await store.get_plans_range(now)

    # Verify projected_soc_percent is returned
    assert len(plans) == 4
    assert plans[0]["projected_soc_percent"] == 50.0
    assert plans[1]["projected_soc_percent"] == 60.0
    assert plans[2]["projected_soc_percent"] == 70.0
    assert plans[3]["projected_soc_percent"] == 80.0
