"""Tests for the quality_flags exclusion filter in _load_slot_observations (fix-observability-gaps #8)."""

import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
import pytz

from backend.learning import LearningEngine
from ml.train import _load_slot_observations, train_models


def _make_db(tmp_path: str) -> None:
    conn = sqlite3.connect(tmp_path)
    conn.execute(
        """
        CREATE TABLE slot_observations (
            slot_start TEXT PRIMARY KEY,
            slot_end TEXT,
            import_kwh REAL DEFAULT 0,
            export_kwh REAL DEFAULT 0,
            pv_kwh REAL DEFAULT 0,
            load_kwh REAL DEFAULT 0,
            water_kwh REAL DEFAULT 0,
            ev_charging_kwh REAL DEFAULT 0,
            batt_charge_kwh REAL,
            batt_discharge_kwh REAL,
            soc_start_percent REAL,
            soc_end_percent REAL,
            import_price_sek_kwh REAL,
            export_price_sek_kwh REAL,
            executed_action TEXT,
            quality_flags TEXT
        )
        """
    )
    conn.commit()
    conn.close()


class TestTrainingQualityFilter:
    def _insert_slot(self, db_path, slot_start, load_kwh, pv_kwh, quality_flags):
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO slot_observations (slot_start, load_kwh, pv_kwh, quality_flags) "
            "VALUES (?, ?, ?, ?)",
            (slot_start, load_kwh, pv_kwh, quality_flags),
        )
        conn.commit()
        conn.close()

    @patch("ml.train.get_max_energy_per_slot")
    def test_excluded_row_omitted_unflagged_row_included(self, mock_max_kwh):
        mock_max_kwh.return_value = 4.0
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "test.db")
            _make_db(db_path)

            excluded_slot = (now - timedelta(hours=2)).isoformat()
            included_slot = (now - timedelta(hours=1)).isoformat()

            self._insert_slot(
                db_path, excluded_slot, 1.0, 0.5, '{"exclude": true, "source": "recorder"}'
            )
            self._insert_slot(db_path, included_slot, 1.0, 0.5, '{"source": "recorder"}')

            mock_engine = MagicMock()
            mock_engine.db_path = db_path
            mock_engine.timezone = tz

            result = _load_slot_observations(mock_engine)

            slot_starts = set(result["slot_start"].dt.tz_convert(tz).apply(lambda d: d.isoformat()))

        assert excluded_slot not in slot_starts
        assert included_slot in slot_starts

    @patch("ml.train.get_max_energy_per_slot")
    def test_source_only_flag_still_included(self, mock_max_kwh):
        """A row with only {"source": "recorder"} (no exclude key) is still included."""
        mock_max_kwh.return_value = 4.0
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "test.db")
            _make_db(db_path)

            slot_start = (now - timedelta(hours=1)).isoformat()
            self._insert_slot(db_path, slot_start, 1.0, 0.5, '{"source":"recorder"}')

            mock_engine = MagicMock()
            mock_engine.db_path = db_path
            mock_engine.timezone = tz

            result = _load_slot_observations(mock_engine)

        assert len(result) == 1


TZ = pytz.timezone("Europe/Stockholm")
NOW = TZ.localize(datetime(2026, 6, 16, 12, 0))
CONFIG = {
    "timezone": "Europe/Stockholm",
    "system": {
        "grid": {"max_power_kw": 20},
        "location": {"latitude": 59.3, "longitude": 18.1},
        "solar_arrays": [{"kwp": 10.0, "tilt": 30, "azimuth": 180}],
    },
}


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW


def _slot_rows() -> list[tuple]:
    """(slot_start, load, pv, baseline, soc, export) for 2026-06-12..15 in 15-minute slots."""
    rows = []
    for day in (12, 13, 14, 15):
        for i in range(96):
            start = TZ.localize(datetime(2026, 6, day, i // 4, 15 * (i % 4)))
            daytime = 8 <= start.hour < 18
            baseline = 0.5 if daytime else 0.0
            rows.append([start, 0.5, 0.4 if daytime else 0.0, baseline, 50.0, 0.5])
    index = {row[0]: row for row in rows}

    def special(hour, minute, pv, baseline, soc=50.0, export=0.5):
        row = index[TZ.localize(datetime(2026, 6, 15, hour, minute))]
        row[2:] = [pv, baseline, soc, export]

    special(9, 0, 0.0, 0.21)  # shaded: kept
    special(9, 15, 0.0, 0.47)  # inverter dropout
    special(12, 0, 4.0, 1.9)  # spike above 10 kWp * 0.25 * 1.05
    special(2, 0, 0.2, 0.03)  # production at night
    special(13, 0, 0.1, 0.41, soc=100.0, export=0.0)  # curtailed by full battery
    return [tuple(r) for r in rows]


@pytest.fixture
def training_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db_path = str(tmp_path / "learning.db")
    _make_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE slot_forecasts (slot_start TEXT, forecast_version TEXT, "
            "openmeteo_pv_forecast_kwh REAL)"
        )
        for start, load, pv, baseline, soc, export in _slot_rows():
            iso = start.isoformat()
            conn.execute(
                "INSERT INTO slot_observations "
                "(slot_start, load_kwh, pv_kwh, soc_end_percent, export_kwh) VALUES (?,?,?,?,?)",
                (iso, load, pv, soc, export),
            )
            conn.execute(
                "INSERT INTO slot_forecasts VALUES (?, 'aurora', ?)",
                (iso, baseline),
            )
    engine = MagicMock(spec=LearningEngine)
    engine.db_path = db_path
    engine.timezone = TZ
    engine.config = CONFIG
    with (
        patch("ml.train.get_learning_engine", return_value=engine),
        patch("ml.train.datetime", _FrozenDatetime),
        patch(
            "backend.learning.pv_openmeteo_backfill.backfill_openmeteo_pv_baselines",
            new=AsyncMock(return_value=0),
        ),
        patch("ml.train.get_vacation_mode_series", return_value=pd.Series(dtype="float32")),
        patch("ml.train.get_alarm_armed_series", return_value=pd.Series(dtype="float32")),
    ):
        yield


def test_pv_training_rows_follow_shared_cleaning(training_env):
    captured: dict[str, pd.DataFrame] = {}

    def fake_regressor(features, target, min_samples, alpha=0.5, sample_weight=None):
        key = "pv" if "physics_forecast_kwh" in features.columns else "load"
        captured.setdefault(key, features)
        return None

    with (
        patch("ml.train.get_historical_weather_series", return_value=pd.DataFrame()),
        patch("ml.train._train_regressor", side_effect=fake_regressor),
    ):
        train_models(min_samples=20)

    baselines = captured["pv"]["physics_forecast_kwh"].round(2)
    assert (baselines == 0.21).sum() == 1  # shaded zero slot kept
    for dropped in (0.47, 1.9, 0.03, 0.41):
        assert (baselines == dropped).sum() == 0, dropped
    assert (baselines == 0.0).sum() == 0  # night slots
    # 4 days x 40 daytime slots, minus the dropout, spike and curtailed slots
    assert len(baselines) == 4 * 40 - 3
    # Load rows are not touched by PV cleaning: every observation slot is used.
    assert len(captured["load"]) == 4 * 96


def test_training_without_weather_still_saves_models(training_env, capsys):
    with patch("ml.train.get_historical_weather_series", return_value=pd.DataFrame()):
        train_models(min_samples=20)

    models = Path("data/ml/models")
    assert (models / "pv_model.lgb").exists()
    assert (models / "load_model.lgb").exists()
    assert "training continues without weather" in capsys.readouterr().out
