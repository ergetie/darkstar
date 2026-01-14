import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import pytest
import pytz

from backend.learning.store import LearningStore

# Mock timezone
TZ = pytz.timezone("Europe/Stockholm")


@pytest.fixture
def memory_db_path(tmp_path):
    return str(tmp_path / "test_learning.db")


@pytest.fixture
def store(memory_db_path):
    return LearningStore(memory_db_path, TZ)


def test_store_plan_mappings(store, memory_db_path):
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
    store.store_plan(df)

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
