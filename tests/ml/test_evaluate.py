"""Tests for ML evaluate spike filtering."""

import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytz

from backend.learning import LearningEngine
from ml.evaluate import _calculate_mae  # type: ignore[reportPrivateUsage]


def test_calculate_mae_filters_spikes():
    """Verify that _calculate_mae filters out spike values."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        config = {
            "system": {"grid": {"max_power_kw": 10.0}},
            "timezone": "Europe/Stockholm",
        }

        engine = LearningEngine.__new__(LearningEngine)
        engine.db_path = str(db_path)
        engine.config = config
        engine.timezone = pytz.timezone("Europe/Stockholm")

        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE slot_observations (
                    slot_start TEXT PRIMARY KEY,
                    load_kwh REAL,
                    pv_kwh REAL,
                    quality_flags TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE slot_forecasts (
                    slot_start TEXT,
                    forecast_version TEXT,
                    load_forecast_kwh REAL,
                    pv_forecast_kwh REAL,
                    PRIMARY KEY (slot_start, forecast_version)
                )
            """)

            tz = pytz.timezone("Europe/Stockholm")
            base_time = tz.localize(datetime(2024, 6, 21, 12, 0))

            test_data = [
                (base_time, 1.5, 2.0, 1.4, 2.1),
                (base_time + timedelta(minutes=15), 100.0, 2.0, 1.5, 2.0),
                (base_time + timedelta(minutes=30), 1.5, 100.0, 1.6, 2.1),
                (base_time + timedelta(minutes=45), 1.7, 1.9, 1.6, 2.0),
            ]

            for slot_start, load_kwh, pv_kwh, load_f, pv_f in test_data:
                conn.execute(
                    "INSERT INTO slot_observations VALUES (?, ?, ?, NULL)",
                    (slot_start.isoformat(), load_kwh, pv_kwh),
                )
                conn.execute(
                    "INSERT INTO slot_forecasts VALUES (?, ?, ?, ?)",
                    (slot_start.isoformat(), "aurora", load_f, pv_f),
                )
            conn.commit()

        start_time = base_time - timedelta(minutes=15)
        end_time = base_time + timedelta(hours=1)
        mae_pv, mae_load = _calculate_mae(engine, start_time, end_time, "aurora")

        assert mae_pv is not None
        assert mae_load is not None

        max_kwh = 10.0 * 0.25 * 2.0
        assert mae_pv < max_kwh
        assert mae_load < max_kwh


def test_calculate_mae_ignores_load_of_slots_with_an_unmeasured_device():
    """A load containing an unmeasured device is no ground truth; PV still counts."""
    import json

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        engine = LearningEngine.__new__(LearningEngine)
        engine.db_path = str(db_path)
        engine.config = {"system": {"grid": {"max_power_kw": 10.0}}}
        engine.timezone = pytz.timezone("Europe/Stockholm")
        base_time = engine.timezone.localize(datetime(2024, 6, 21, 12, 0))
        unknown_ev = json.dumps(
            {
                "recording": {
                    "schema_version": 1,
                    "semantics": "slot-energy-v1",
                    "boundary_fingerprint": "0" * 64,
                    "components": {
                        "ev": {"method": "unknown", "owner": "recorder"},
                        "load": {"method": "derived_history", "owner": "recorder"},
                    },
                    "soc": {"source": "live", "owner": "recorder"},
                }
            }
        )
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "CREATE TABLE slot_observations (slot_start TEXT PRIMARY KEY, load_kwh REAL, "
                "pv_kwh REAL, quality_flags TEXT)"
            )
            conn.execute(
                "CREATE TABLE slot_forecasts (slot_start TEXT, forecast_version TEXT, "
                "load_forecast_kwh REAL, pv_forecast_kwh REAL)"
            )
            for index, flags in enumerate([None, unknown_ev]):
                start = (base_time + timedelta(minutes=15 * index)).isoformat()
                conn.execute(
                    "INSERT INTO slot_observations VALUES (?, ?, ?, ?)", (start, 2.0, 1.0, flags)
                )
                conn.execute("INSERT INTO slot_forecasts VALUES (?, 'aurora', 1.0, 0.5)", (start,))
            conn.commit()

        mae_pv, mae_load = _calculate_mae(
            engine, base_time - timedelta(minutes=15), base_time + timedelta(hours=1), "aurora"
        )
        assert mae_pv == pytest.approx(0.5)
        # Only the measured slot: |2.0 - 1.0|; the contaminated slot is no ground truth.
        assert mae_load == pytest.approx(1.0)
