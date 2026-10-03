import json
import sqlite3
import sys
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
