"""Tests for the quality_flags exclusion filter in _load_slot_observations (fix-observability-gaps #8)."""

import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytz

from ml.train import _load_slot_observations


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
