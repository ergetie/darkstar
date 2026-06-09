import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

sys.path.append(str(Path(__file__).parent.parent.parent))
from datetime import datetime, timedelta

import pytest_asyncio

from backend.learning.engine import LearningEngine
from backend.learning.models import Base


@pytest_asyncio.fixture
async def learning_engine(tmp_path):
    """Create a LearningEngine with a temporary database."""
    db_path = tmp_path / "test_learning.db"

    # Create a dummy config
    config_path = tmp_path / "config.yaml"
    with config_path.open("w", encoding="utf-8") as f:
        f.write(f"learning:\n  sqlite_path: {db_path}\ntimezone: Europe/Stockholm\n")

    engine = LearningEngine(str(config_path))

    # Manually create schema for tests using async engine
    async with engine.store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.store.close()


@pytest.mark.asyncio
async def test_schema_creation(learning_engine):
    """Verify that the schema is created correctly, including slot_plans."""
    with sqlite3.connect(learning_engine.db_path) as conn:
        cursor = conn.cursor()

        # Check slot_plans table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='slot_plans'")
        assert cursor.fetchone() is not None

        # Check training_episodes table
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='training_episodes'"
        )
        assert cursor.fetchone() is not None


@pytest.mark.asyncio
async def test_store_plan_and_metrics(learning_engine):
    """Verify storing plans and calculating plan deviation metrics."""
    # 1. Store a plan
    now = datetime.now(learning_engine.timezone).replace(minute=0, second=0, microsecond=0)

    plan_data = [
        {
            "slot_start": now,
            "kepler_charge_kwh": 5.0,
            "kepler_discharge_kwh": 0.0,
            "kepler_soc_percent": 50.0,
            "kepler_import_kwh": 5.0,
            "kepler_export_kwh": 0.0,
            "kepler_cost_sek": 10.0,
        },
        {
            "slot_start": now + timedelta(minutes=15),
            "kepler_charge_kwh": 0.0,
            "kepler_discharge_kwh": 2.0,
            "kepler_soc_percent": 30.0,
            "kepler_import_kwh": 0.0,
            "kepler_export_kwh": 2.0,
            "kepler_cost_sek": -2.0,  # Revenue
        },
    ]
    plan_df = pd.DataFrame(plan_data)
    await learning_engine.log_training_episode({}, plan_df)

    # 2. Store actual observations (deviating from plan)
    # Slot 1: Charged 4.0 instead of 5.0 (Deviation 1.0)
    # Slot 2: Discharged 2.5 instead of 2.0 (Deviation 0.5)
    obs_data = [
        {
            "slot_start": now,
            "slot_end": now + timedelta(minutes=15),
            "batt_charge_kwh": 4.0,
            "batt_discharge_kwh": 0.0,
            "soc_end_percent": 40.0,  # Plan was 50.0
            "import_kwh": 4.0,
            "export_kwh": 0.0,
            "import_price_sek_kwh": 2.0,
            "export_price_sek_kwh": 1.0,
        },
        {
            "slot_start": now + timedelta(minutes=15),
            "slot_end": now + timedelta(minutes=30),
            "batt_charge_kwh": 0.0,
            "batt_discharge_kwh": 2.5,
            "soc_end_percent": 25.0,  # Plan was 30.0
            "import_kwh": 0.0,
            "export_kwh": 2.5,
            "import_price_sek_kwh": 2.0,
            "export_price_sek_kwh": 1.0,
        },
    ]
    obs_df = pd.DataFrame(obs_data)
    await learning_engine.store_slot_observations(obs_df)

    # 3. Calculate Metrics
    metrics = await learning_engine.calculate_metrics(days_back=1)

    # Check Plan Deviation
    # Charge MAE: (|5-4| + |0-0|) / 2 = 0.5
    assert metrics["mae_plan_charge"] == 0.5

    # Discharge MAE: (|0-0| + |2-2.5|) / 2 = 0.25
    assert metrics["mae_plan_discharge"] == 0.25

    # SoC MAE: (|50-40| + |30-25|) / 2 = 7.5
    assert metrics["mae_plan_soc"] == 7.5

    # Check Cost Deviation
    # Planned Cost: 10.0 - 2.0 = 8.0
    # Realized Cost:
    # Slot 1: 4.0 * 2.0 = 8.0
    # Slot 2: -2.5 * 1.0 = -2.5
    # Total Realized: 5.5
    # Deviation: |5.5 - 8.0| = 2.5
    assert metrics["total_planned_cost"] == 8.0
    assert metrics["total_realized_cost"] == 5.5
    assert metrics["cost_deviation"] == 2.5


@pytest.mark.asyncio
async def test_store_training_episode(learning_engine):
    """Verify storing training episodes."""
    episode_id = "test-episode-123"
    inputs = {"foo": "bar"}
    schedule = [{"start": "2023-01-01T00:00:00", "charge": 1.0}]

    await learning_engine.store.store_training_episode(
        episode_id=episode_id, inputs_json=json.dumps(inputs), schedule_json=json.dumps(schedule)
    )

    with sqlite3.connect(learning_engine.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT inputs_json FROM training_episodes WHERE episode_id=?", (episode_id,)
        )
        row = cursor.fetchone()
        assert row is not None
    assert json.loads(row[0]) == inputs


@pytest.mark.asyncio
async def test_store_slot_observations_live_correction_and_true_zero(learning_engine):
    slot_start = datetime.now(learning_engine.timezone).replace(minute=0, second=0, microsecond=0)
    initial = pd.DataFrame(
        [
            {
                "slot_start": slot_start,
                "slot_end": slot_start + timedelta(minutes=15),
                "pv_kwh": 8.0,
                "ev_charging_kwh": 1.0,
            }
        ]
    )
    correction = pd.DataFrame(
        [
            {
                "slot_start": slot_start,
                "slot_end": slot_start + timedelta(minutes=15),
                "pv_kwh": 2.0,
                "ev_charging_kwh": 0.0,
            }
        ]
    )

    await learning_engine.store_slot_observations(initial)
    await learning_engine.store_slot_observations(correction)

    with sqlite3.connect(learning_engine.db_path) as conn:
        row = conn.execute(
            "SELECT pv_kwh, ev_charging_kwh, quality_flags FROM slot_observations"
        ).fetchone()

    assert row[0] == pytest.approx(2.0)
    assert row[1] == pytest.approx(0.0)
    assert json.loads(row[2])["source"] == "recorder"


@pytest.mark.asyncio
async def test_store_slot_observations_backfill_does_not_overwrite_live(learning_engine):
    slot_start = datetime.now(learning_engine.timezone).replace(minute=0, second=0, microsecond=0)
    live = pd.DataFrame(
        [
            {
                "slot_start": slot_start,
                "slot_end": slot_start + timedelta(minutes=15),
                "load_kwh": 3.0,
                "pv_kwh": 1.0,
            }
        ]
    )
    backfill = pd.DataFrame(
        [
            {
                "slot_start": slot_start,
                "slot_end": slot_start + timedelta(minutes=15),
                "load_kwh": 9.0,
                "pv_kwh": 9.0,
            }
        ]
    )

    await learning_engine.store_slot_observations(live)
    await learning_engine.store_slot_observations(backfill, authoritative=False)

    with sqlite3.connect(learning_engine.db_path) as conn:
        row = conn.execute("SELECT load_kwh, pv_kwh FROM slot_observations").fetchone()

    assert row == pytest.approx((3.0, 1.0))


@pytest.mark.asyncio
async def test_store_slot_observations_missing_measurement_keeps_existing(learning_engine):
    slot_start = datetime.now(learning_engine.timezone).replace(minute=0, second=0, microsecond=0)
    initial = pd.DataFrame(
        [
            {
                "slot_start": slot_start,
                "slot_end": slot_start + timedelta(minutes=15),
                "load_kwh": 4.0,
                "pv_kwh": 2.0,
            }
        ]
    )
    partial = pd.DataFrame(
        [{"slot_start": slot_start, "slot_end": slot_start + timedelta(minutes=15), "pv_kwh": 1.5}]
    )

    await learning_engine.store_slot_observations(initial)
    await learning_engine.store_slot_observations(partial)

    with sqlite3.connect(learning_engine.db_path) as conn:
        row = conn.execute("SELECT load_kwh, pv_kwh FROM slot_observations").fetchone()

    assert row == pytest.approx((4.0, 1.5))


def test_etl_cumulative_spike_filtering_with_config():
    """Test that etl_cumulative_to_slots uses config-derived threshold."""
    from datetime import datetime, timedelta

    import pytz

    # Create engine with 8kW grid config (4.0 kWh max per slot)
    config_content = """
system:
  grid:
    max_power_kw: 8.0
learning:
  sqlite_path: ":memory:"
timezone: Europe/Stockholm
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_content)
        config_path = f.name

    try:
        engine = LearningEngine(config_path)
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)

        # Create cumulative data with spike values
        # Spike at index 2: 100 kWh delta (exceeds 4.0 threshold)
        cumulative_data = {
            "sensor.pv_energy": [
                (now, 1000.0),
                (now + timedelta(minutes=15), 1002.0),  # Normal 2 kWh delta
                (now + timedelta(minutes=30), 1102.0),  # Spike: 100 kWh delta
                (now + timedelta(minutes=45), 1104.0),  # Normal 2 kWh delta
            ]
        }

        result = engine.etl_cumulative_to_slots(cumulative_data, resolution_minutes=15)

        # Verify the function ran without error and returned a DataFrame
        assert isinstance(result, pd.DataFrame)
        # The column name is based on the canonical sensor name
        # "sensor.pv_energy" maps to "pv_energy_kwh"
        pv_col = "pv_energy_kwh"
        assert pv_col in result.columns
        # Verify spike filtering was applied (100 kWh delta should be 0)
        # Note: exact slot assignment depends on timestamp alignment
        assert all(result[pv_col] <= 4.0), (
            f"Found values exceeding 4.0 threshold: {result[pv_col].tolist()}"
        )
    finally:
        Path(config_path).unlink()


def test_etl_cumulative_spike_filtering_fallback():
    """Test that etl_cumulative_to_slots uses fallback when config missing."""
    from datetime import datetime, timedelta

    import pytz

    # Create engine without grid config
    config_content = """
learning:
  sqlite_path: ":memory:"
timezone: Europe/Stockholm
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_content)
        config_path = f.name

    try:
        engine = LearningEngine(config_path)
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)

        # Create cumulative data with spike values
        # Spike at index 2: 100 kWh delta (exceeds 50.0 fallback threshold)
        cumulative_data = {
            "sensor.pv_energy": [
                (now, 1000.0),
                (now + timedelta(minutes=15), 1020.0),  # Normal 20 kWh delta
                (now + timedelta(minutes=30), 1100.0),  # Spike: 80 kWh delta
                (now + timedelta(minutes=45), 1120.0),  # Normal 20 kWh delta
            ]
        }

        result = engine.etl_cumulative_to_slots(cumulative_data, resolution_minutes=15)

        # Verify the function ran without error and returned a DataFrame
        assert isinstance(result, pd.DataFrame)
        pv_col = "pv_energy_kwh"
        assert pv_col in result.columns
        # Verify spike filtering was applied with 50.0 fallback (80 kWh delta should be 0)
        assert all(result[pv_col] <= 50.0), (
            f"Found values exceeding 50.0 fallback: {result[pv_col].tolist()}"
        )
    finally:
        Path(config_path).unlink()


def test_etl_power_spike_filtering():
    """Test that etl_power_to_slots uses config-derived threshold."""
    from datetime import datetime, timedelta

    import pytz

    # Create engine with 8kW grid config (4.0 kWh max per slot)
    config_content = """
system:
  grid:
    max_power_kw: 8.0
learning:
  sqlite_path: ":memory:"
timezone: Europe/Stockholm
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_content)
        config_path = f.name

    try:
        engine = LearningEngine(config_path)
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)

        # Create power data with spike values
        # Spike at index 1: 100 kW (25 kWh in 15 min, exceeds 4.0 threshold)
        power_data = {
            "sensor.pv_power": [
                (now, 8000.0),  # 8 kW = 2 kWh
                (now + timedelta(minutes=5), 100000.0),  # 100 kW = 25 kWh (spike)
                (now + timedelta(minutes=10), 100000.0),
                (now + timedelta(minutes=15), 8000.0),  # 8 kW = 2 kWh
            ]
        }

        result = engine.etl_power_to_slots(power_data, resolution_minutes=15)

        assert len(result) >= 1
        # Energy should be filtered - spike values should be 0
        # The exact values depend on resampling, but spikes should be gone
        pv_values = result["pv_kwh"].values
        assert all(v <= 4.0 for v in pv_values), f"Found values exceeding threshold: {pv_values}"
    finally:
        Path(config_path).unlink()


def test_etl_cumulative_subtracts_controllable_loads_for_backfill():
    from datetime import datetime, timedelta

    import pytz

    config_content = """
system:
  grid:
    max_power_kw: 20.0
learning:
  sqlite_path: ":memory:"
timezone: Europe/Stockholm
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_content)
        config_path = f.name

    try:
        engine = LearningEngine(config_path)
        engine.sensor_map["sensor.ev_power"] = "ev_charging"
        tz = pytz.timezone("Europe/Stockholm")
        start = tz.localize(datetime(2024, 1, 1, 12, 0))
        cumulative_data = {
            "sensor.load": [(start, 100.0), (start + timedelta(minutes=15), 105.0)]
        }
        controllable_power_data = {
            "sensor.ev_power": [(start, 8.0), (start + timedelta(minutes=15), 8.0)],
            "sensor.water_power": [(start, 2.0), (start + timedelta(minutes=15), 2.0)],
        }

        result = engine.etl_cumulative_to_slots(
            cumulative_data, controllable_power_data, resolution_minutes=15
        )

        assert result.iloc[0]["load_kwh"] == pytest.approx(2.5)
        assert result.iloc[0]["ev_charging_kwh"] == pytest.approx(2.0)
        assert result.iloc[0]["water_kwh"] == pytest.approx(0.5)
    finally:
        Path(config_path).unlink()


def test_etl_cumulative_clamps_negative_base_load():
    from datetime import datetime, timedelta

    import pytz

    config_content = """
system:
  grid:
    max_power_kw: 20.0
learning:
  sqlite_path: ":memory:"
timezone: Europe/Stockholm
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_content)
        config_path = f.name

    try:
        engine = LearningEngine(config_path)
        engine.sensor_map["sensor.ev_power"] = "ev_charging"
        tz = pytz.timezone("Europe/Stockholm")
        start = tz.localize(datetime(2024, 1, 1, 12, 0))
        cumulative_data = {
            "sensor.load": [(start, 100.0), (start + timedelta(minutes=15), 101.0)]
        }
        controllable_power_data = {
            "sensor.ev_power": [(start, 8.0), (start + timedelta(minutes=15), 8.0)]
        }

        result = engine.etl_cumulative_to_slots(
            cumulative_data, controllable_power_data, resolution_minutes=15
        )

        assert result.iloc[0]["load_kwh"] == pytest.approx(0.0)
    finally:
        Path(config_path).unlink()
