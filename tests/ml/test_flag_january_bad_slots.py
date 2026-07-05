"""Tests for scripts/flag_january_bad_slots.py (fix-observability-gaps #8)."""

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts.flag_january_bad_slots import SELECT_CANDIDATES, main, merge_exclude_flag


def _make_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE slot_observations (
            slot_start TEXT PRIMARY KEY,
            import_kwh REAL,
            pv_kwh REAL,
            batt_charge_kwh REAL,
            quality_flags TEXT
        )
        """
    )
    # Matching: in window, batt_charge>0.3, import<0.05, pv < 0.5*batt_charge
    conn.execute(
        "INSERT INTO slot_observations VALUES (?, ?, ?, ?, ?)",
        ("2026-01-17T10:00:00+01:00", 0.0, 0.1, 1.0, '{"source": "recorder"}'),
    )
    # Non-matching: outside the January window
    conn.execute(
        "INSERT INTO slot_observations VALUES (?, ?, ?, ?, ?)",
        ("2026-02-17T10:00:00+01:00", 0.0, 0.1, 1.0, '{"source": "recorder"}'),
    )
    # Non-matching: import too high
    conn.execute(
        "INSERT INTO slot_observations VALUES (?, ?, ?, ?, ?)",
        ("2026-01-18T10:00:00+01:00", 1.0, 0.1, 1.0, '{"source": "recorder"}'),
    )
    conn.commit()
    conn.close()


class TestFlagJanuaryBadSlots:
    def test_dry_run_reports_count_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "test.db")
            _make_db(db_path)

            with (
                patch("scripts.flag_january_bad_slots.load_db_path", return_value=db_path),
                patch("scripts.flag_january_bad_slots.parse_args") as mock_args,
            ):
                mock_args.return_value.apply = False
                main()

            conn = sqlite3.connect(db_path)
            rows = conn.execute("SELECT quality_flags FROM slot_observations").fetchall()
            conn.close()
            assert all("exclude" not in (r[0] or "") for r in rows)

    def test_apply_flags_only_matching_rows_preserves_source_and_measurements(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "test.db")
            _make_db(db_path)

            with (
                patch("scripts.flag_january_bad_slots.load_db_path", return_value=db_path),
                patch("scripts.flag_january_bad_slots.parse_args") as mock_args,
            ):
                mock_args.return_value.apply = True
                main()

            conn = sqlite3.connect(db_path)
            fetched = conn.execute(
                "SELECT slot_start, quality_flags, import_kwh, pv_kwh, batt_charge_kwh "
                "FROM slot_observations"
            ).fetchall()
            conn.close()
            rows = {r[0]: (r[1], r[2], r[3], r[4]) for r in fetched}

            matching_flags = json.loads(rows["2026-01-17T10:00:00+01:00"][0])
            assert matching_flags == {"exclude": True, "source": "recorder"}
            assert rows["2026-01-17T10:00:00+01:00"][1:] == (0.0, 0.1, 1.0)

            non_matching_flags = json.loads(rows["2026-02-17T10:00:00+01:00"][0])
            assert "exclude" not in non_matching_flags

            non_matching_flags2 = json.loads(rows["2026-01-18T10:00:00+01:00"][0])
            assert "exclude" not in non_matching_flags2

    def test_merge_exclude_flag_preserves_source(self):
        assert json.loads(merge_exclude_flag('{"source": "backfill"}')) == {
            "exclude": True,
            "source": "backfill",
        }

    def test_select_candidates_query_matches_criteria(self):
        assert "batt_charge_kwh > 0.3" in SELECT_CANDIDATES
        assert "import_kwh < 0.05" in SELECT_CANDIDATES
        assert "pv_kwh < 0.5 * batt_charge_kwh" in SELECT_CANDIDATES
