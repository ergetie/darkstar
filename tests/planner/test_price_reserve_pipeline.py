"""Pipeline integration of the first-unseen-day price reserve."""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
import pytz

import planner.pipeline as pipeline_module
from planner.pipeline import PlannerPipeline, build_price_reserve_inputs
from planner.solver.kepler import KeplerSolver
from tests.fault_injection.test_dst_transitions import planner_config

TZ = pytz.timezone("Europe/Stockholm")
QUARTER = timedelta(minutes=15)
PRICE_HOURS = 12
UNSEEN_HOURS = 24


def future_base() -> datetime:
    """A 15-min-aligned UTC instant in the future (preflight checks the real clock)."""
    now = datetime.now(pytz.UTC) + timedelta(days=2)
    return now.replace(minute=0, second=0, microsecond=0)


def make_full_inputs(start_utc: datetime) -> dict:
    """Price data for PRICE_HOURS plus forecast data covering the 24 h after it."""
    price_data, forecast_data = [], []
    total = (PRICE_HOURS + UNSEEN_HOURS) * 4
    for i in range(total):
        ts = start_utc + i * QUARTER
        if i < PRICE_HOURS * 4:
            price_data.append(
                {
                    "start_time": ts.isoformat(),
                    "end_time": (ts + QUARTER).isoformat(),
                    "import_price_sek_kwh": 0.8,
                    "export_price_sek_kwh": 0.5,
                }
            )
        # Net load only in 4 evening slots of the unseen day
        in_unseen = i >= PRICE_HOURS * 4
        evening = in_unseen and 70 <= i - PRICE_HOURS * 4 < 74
        forecast_data.append(
            {
                "start_time": ts.isoformat(),
                "pv_forecast_kwh": 0.0,
                "load_forecast_kwh": 1.5 if evening else 0.0,
            }
        )
    return {
        "price_data": price_data,
        "forecast_data": forecast_data[: PRICE_HOURS * 4],
        "extended_forecast_data": forecast_data,
        "initial_state": {"battery_soc_percent": 20.0},
    }


def make_forecast_db(path: Path, start_utc: datetime, *, price: float = 0.9, evening: float = 2.0):
    """price_forecasts rows (spot_p50) for the unseen day; evening slots are expensive."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE price_forecasts (id INTEGER PRIMARY KEY, slot_start TEXT, "
        "issue_timestamp TEXT, days_ahead INTEGER, spot_p10 REAL, spot_p50 REAL, spot_p90 REAL)"
    )
    unseen_start = start_utc + PRICE_HOURS * 4 * QUARTER
    for i in range(UNSEEN_HOURS * 4):
        slot = (unseen_start + i * QUARTER).astimezone(TZ)
        conn.execute(
            "INSERT INTO price_forecasts (slot_start, issue_timestamp, days_ahead, spot_p50) "
            "VALUES (?, ?, 2, ?)",
            (slot.isoformat(), "2026-01-01T13:30:00+01:00", evening if 70 <= i < 74 else price),
        )
    conn.commit()
    conn.close()


def reserve_config(db_path: Path, *, enabled: bool = True) -> dict:
    config = planner_config()
    config["price_forecast"] = {"enabled": enabled}
    config["learning"] = {"enable": False, "sqlite_path": str(db_path)}
    config["pricing"] = {
        "vat_percent": 25.0,
        "grid_transfer_fee_sek": 0.2,
        "energy_tax_sek": 0.4,
        "transfer_fee_mode": "flat",
    }
    config["s_index"] = {"risk_appetite": 3}
    config["battery"] = {
        **config["battery"],
        "capacity_kwh": 27.0,
        "min_soc_percent": 15,
        "max_charge_w": 8000,
        "max_discharge_w": 8000,
    }
    return config


@pytest.fixture
def captured_solves(monkeypatch):
    """Record the KeplerConfig of each solve while running the real solver."""
    configs = []
    original = KeplerSolver.solve

    def spy(self, kepler_input, kepler_config):
        configs.append(kepler_config)
        return original(self, kepler_input, kepler_config)

    monkeypatch.setattr(KeplerSolver, "solve", spy)
    return configs


async def run_full(config: dict, start_utc: datetime):
    pipeline = PlannerPipeline(config)
    return await pipeline.generate_schedule(
        make_full_inputs(start_utc),
        mode="full",
        save_to_file=False,
        now_override=start_utc.astimezone(TZ),
    )


@pytest.mark.asyncio
async def test_reserve_reaches_solver_target(tmp_path, monkeypatch, captured_solves):
    monkeypatch.chdir(tmp_path)
    start = future_base()
    db = tmp_path / "learning.db"
    make_forecast_db(db, start)

    await run_full(reserve_config(db), start)

    assert len(captured_solves) == 1
    target = captured_solves[0].target_soc_kwh
    min_soc = 0.15 * 27.0
    # 6 kWh evening net load / 0.95 discharge efficiency above min SoC
    assert target == pytest.approx(min_soc + 6.0 / 0.95, abs=0.05)

    events = json.loads(Path("data/strategy_history.json").read_text())
    reserve_events = [e for e in events if e["details"].get("kind") == "price_reserve"]
    assert len(reserve_events) == 1
    assert reserve_events[0]["details"]["active"] is True


@pytest.mark.asyncio
async def test_disabled_forecasting_makes_no_store_query(tmp_path, monkeypatch, captured_solves):
    monkeypatch.chdir(tmp_path)
    start = future_base()

    def forbidden(*args, **kwargs):
        raise AssertionError("price forecast store must not be queried when disabled")

    monkeypatch.setattr(pipeline_module, "_fetch_unseen_forecast_sync", forbidden)

    await run_full(reserve_config(tmp_path / "learning.db", enabled=False), start)

    target = captured_solves[0].target_soc_kwh
    assert target < 0.15 * 27.0 + 6.0  # deficit floor only (small buffer)
    assert not Path("data/strategy_history.json").exists()


@pytest.mark.asyncio
async def test_forecast_read_error_keeps_run_alive(tmp_path, monkeypatch, captured_solves):
    monkeypatch.chdir(tmp_path)
    start = future_base()
    # No price_forecasts table in the DB: reading fails
    sqlite3.connect(tmp_path / "learning.db").close()

    df = await run_full(reserve_config(tmp_path / "learning.db"), start)

    assert not df.empty
    assert len(captured_solves) == 1
    deficit_only = captured_solves[0].target_soc_kwh
    assert deficit_only < 0.15 * 27.0 + 6.0


@pytest.mark.asyncio
async def test_baseline_mode_computes_no_reserve(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    start = future_base()

    async def forbidden(*args, **kwargs):
        raise AssertionError("baseline mode must not compute a price reserve")

    monkeypatch.setattr(pipeline_module, "build_price_reserve_inputs", forbidden)
    pipeline = PlannerPipeline(reserve_config(tmp_path / "learning.db"))

    df = await pipeline.generate_schedule(
        make_full_inputs(start),
        mode="baseline",
        save_to_file=False,
        now_override=start.astimezone(TZ),
    )

    assert not df.empty


def _df_for_inputs(start_utc: datetime) -> pd.DataFrame:
    idx = pd.date_range(start_utc.astimezone(TZ), periods=PRICE_HOURS * 4, freq="15min")
    return pd.DataFrame({"import_price_sek_kwh": 0.8}, index=idx)


@pytest.mark.asyncio
async def test_inputs_use_shared_power_limits_and_tou_prices(tmp_path):
    start = future_base()
    db = tmp_path / "learning.db"
    make_forecast_db(db, start, price=1.0, evening=1.0)
    config = reserve_config(db)
    config["executor"] = {"inverter": {"control_unit": "A"}}
    config["battery"] = {**config["battery"], "max_charge_a": 185, "max_discharge_a": 166}
    config["battery"]["nominal_voltage_v"] = 48
    config["pricing"].update(
        transfer_fee_mode="time_of_use",
        transfer_fee_rules=[{"hours": {"start": 0, "end": 12}, "fee_sek": 1.0}],
    )
    df = _df_for_inputs(start)

    inputs = await build_price_reserve_inputs(
        config, df, df.index[0], df.index[-1], "Europe/Stockholm", 5.0
    )

    assert inputs is not None
    assert inputs.max_charge_kw == pytest.approx(8.88)
    assert inputs.error is None
    assert len(inputs.known_slots) == PRICE_HOURS * 4
    assert len(inputs.unseen_prices) == UNSEEN_HOURS * 4
    # Same forecast spot, different transfer fee by local hour: (1.0 - 0.2) * 1.25 higher
    morning = {p for ts, p in inputs.unseen_prices.items() if ts.astimezone(TZ).hour < 12}
    afternoon = {p for ts, p in inputs.unseen_prices.items() if ts.astimezone(TZ).hour >= 12}
    assert len(morning) == 1 and len(afternoon) == 1
    assert morning.pop() - afternoon.pop() == pytest.approx((1.0 - 0.2) * 1.25)
    assert inputs.forecast_issue_timestamp == "2026-01-01T13:30:00+01:00"


@pytest.mark.asyncio
async def test_inputs_none_when_forecasting_disabled(tmp_path):
    start = future_base()
    df = _df_for_inputs(start)
    result = await build_price_reserve_inputs(
        reserve_config(tmp_path / "x.db", enabled=False),
        df,
        df.index[0],
        df.index[-1],
        "Europe/Stockholm",
        5.0,
    )
    assert result is None


class TestReserveEventDedup:
    @staticmethod
    def debug(applied: float, **extra) -> dict:
        return {
            "price_reserve_applied_kwh": applied,
            "price_reserve_kwh": applied,
            "price_reserve_reason": "active" if applied else "own_day_cheaper",
            "known_cost_sek_kwh": 1.0,
            "own_day_cost_sek_kwh": 1.5,
            **extra,
        }

    @staticmethod
    def events() -> list[dict]:
        path = Path("data/strategy_history.json")
        return json.loads(path.read_text()) if path.exists() else []

    def test_unchanged_reserve_logs_once(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pipeline_module._log_price_reserve_event(self.debug(6.0))
        pipeline_module._log_price_reserve_event(self.debug(6.4))
        pipeline_module._log_price_reserve_event(self.debug(5.5))

        assert len(self.events()) == 1

    def test_material_change_and_flips_log(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pipeline_module._log_price_reserve_event(self.debug(6.0))
        pipeline_module._log_price_reserve_event(self.debug(7.5))  # +1.5 kWh
        pipeline_module._log_price_reserve_event(self.debug(0.0))  # active -> inactive
        pipeline_module._log_price_reserve_event(self.debug(0.0))  # still inactive: no event

        assert len(self.events()) == 3

    def test_inactive_without_prior_event_logs_nothing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pipeline_module._log_price_reserve_event(self.debug(0.0))

        assert self.events() == []

    def test_logging_failure_is_swallowed(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        def boom(**kwargs):
            raise OSError("disk full")

        monkeypatch.setattr("backend.strategy.history.append_strategy_event", boom)
        pipeline_module._log_price_reserve_event(self.debug(6.0))
