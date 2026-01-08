import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.append(str(Path(__file__).parent.parent))
from datetime import datetime, timedelta

from backend.learning.engine import LearningEngine


@pytest.fixture
def learning_engine(tmp_path):
    """Create a LearningEngine with a temporary database."""
    db_path = tmp_path / "test_learning.db"

    # Create a dummy config
    config_path = tmp_path / "config.yaml"
    with config_path.open("w", encoding="utf-8") as f:
        f.write(f"learning:\n  sqlite_path: {db_path}\ntimezone: Europe/Stockholm\n")

    engine = LearningEngine(str(config_path))
    return engine


def test_schema_creation(learning_engine):
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


def test_store_plan_and_metrics(learning_engine):
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
    learning_engine.log_training_episode({}, plan_df)

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
    learning_engine.store_slot_observations(obs_df)

    # 3. Calculate Metrics
    metrics = learning_engine.calculate_metrics(days_back=1)

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


def test_store_training_episode(learning_engine):
    """Verify storing training episodes."""
    episode_id = "test-episode-123"
    inputs = {"foo": "bar"}
    schedule = [{"start": "2023-01-01T00:00:00", "charge": 1.0}]

    learning_engine.store.store_training_episode(
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
