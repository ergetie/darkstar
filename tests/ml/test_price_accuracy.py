"""Shared price forecast accuracy computation (endpoint and planner use the same code)."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ml.price_accuracy import compute_forecast_accuracy, fetch_accuracy_rows, load_forecast_accuracy


def _row(slot_start: str, forecast: float, actual: float) -> dict:
    return {"slot_start": slot_start, "spot_p50": forecast, "export_price_sek_kwh": actual}


def _slot(days_back: int, hour: int = 12) -> str:
    day = datetime.now() - timedelta(days=days_back)
    return day.replace(hour=hour, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")


@pytest.fixture
def db(tmp_path: Path) -> str:
    path = tmp_path / "learning.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE price_forecasts (id INTEGER PRIMARY KEY, slot_start TEXT, "
        "days_ahead INTEGER, spot_p50 REAL)"
    )
    conn.execute(
        "CREATE TABLE slot_observations (id INTEGER PRIMARY KEY, slot_start TEXT, "
        "export_price_sek_kwh REAL)"
    )
    conn.commit()
    conn.close()
    return str(path)


def _seed(db: str, slot: str, days_ahead: int, forecast: float, actual: float) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO price_forecasts (slot_start, days_ahead, spot_p50) VALUES (?, ?, ?)",
        (slot, days_ahead, forecast),
    )
    conn.execute(
        "INSERT INTO slot_observations (slot_start, export_price_sek_kwh) VALUES (?, ?)",
        (slot, actual),
    )
    conn.commit()
    conn.close()


class TestCompute:
    def test_metrics_and_sign(self):
        rows = [_row("2026-01-01T10:00", 1.5, 1.0), _row("2026-01-02T10:00", 0.8, 1.0)]
        acc = compute_forecast_accuracy(rows)
        assert acc.status == "ok" and acc.ok
        assert acc.bias == pytest.approx(0.15)  # forecast minus actual: (0.5 - 0.2) / 2
        assert acc.mae == pytest.approx(0.35)
        assert acc.debiased_mae == pytest.approx(0.35)  # |0.5 - 0.15|, |-0.2 - 0.15|
        assert acc.sample_days == 2

    def test_constant_offset_has_zero_debiased_mae(self):
        rows = [_row(f"2026-01-0{d}T10:00", 1.30, 1.0) for d in (1, 2, 3)]
        acc = compute_forecast_accuracy(rows)
        assert acc.bias == pytest.approx(0.30)
        assert acc.mae == pytest.approx(0.30)
        assert acc.debiased_mae == pytest.approx(0.0)

    def test_sample_days_counts_distinct_dates(self):
        rows = [_row("2026-01-01T10:00", 1.0, 1.0), _row("2026-01-01T11:00", 1.0, 1.0)]
        acc = compute_forecast_accuracy(rows)
        assert acc.status == "insufficient_data"
        assert acc.sample_days == 1
        assert acc.bias is None and acc.mae is None and acc.debiased_mae is None

    def test_empty_rows(self):
        acc = compute_forecast_accuracy([])
        assert acc.status == "insufficient_data" and acc.sample_days == 0


class TestLoad:
    def test_horizon_selects_only_its_rows(self, db):
        for back in (1, 2):
            _seed(db, _slot(back), 1, 1.10, 1.0)
            _seed(db, _slot(back, 13), 2, 1.40, 1.0)
        d1 = load_forecast_accuracy(db, 1)
        d2 = load_forecast_accuracy(db, 2)
        assert d1.bias == pytest.approx(0.10)
        assert d2.bias == pytest.approx(0.40)
        assert load_forecast_accuracy(db, 3).status == "insufficient_data"
        assert load_forecast_accuracy(db).bias == d1.bias  # default horizon is D+1

    def test_rows_older_than_seven_days_ignored(self, db):
        _seed(db, _slot(1), 1, 1.10, 1.0)
        _seed(db, _slot(2), 1, 1.10, 1.0)
        _seed(db, _slot(30), 1, 9.0, 1.0)
        rows = fetch_accuracy_rows(db, 1)
        assert len(rows) == 2
        assert load_forecast_accuracy(db, 1).bias == pytest.approx(0.10)

    def test_null_values_ignored(self, db):
        _seed(db, _slot(1), 1, 1.10, 1.0)
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO price_forecasts (slot_start, days_ahead, spot_p50) VALUES (?, 1, NULL)",
            (_slot(2),),
        )
        conn.execute(
            "INSERT INTO slot_observations (slot_start, export_price_sek_kwh) VALUES (?, 1.0)",
            (_slot(2),),
        )
        conn.commit()
        conn.close()
        assert len(fetch_accuracy_rows(db, 1)) == 1
