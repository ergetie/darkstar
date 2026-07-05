"""DST transition fault injection (spec req 5).

Production incident 2026-03-29 (findings.md #6): the planner produced no valid
slots for the spring-forward day for ~31 h; the executor fell back safely from
00:00 to 09:00. These tests reproduce planning across both DST boundaries.
"""

from datetime import datetime, timedelta

import pandas as pd
import pytest
import pytz

from planner.pipeline import PlannerPipeline
from tests.fault_injection.conftest import make_slot, write_schedule

# The planner preflight (planner/preflight.py check_price_data) validates prices
# against the REAL wall clock, not now_override — so these tests must target the
# NEXT real DST transitions, computed dynamically from the tz database.


def next_transitions() -> tuple[datetime, datetime]:
    """Return (next spring-forward, next fall-back) transition instants in UTC."""
    tz = pytz.timezone("Europe/Stockholm")
    now = datetime.now(pytz.UTC)
    spring = None
    fall = None
    transitions = getattr(tz, "_utc_transition_times", [])
    for i, t in enumerate(transitions):
        t_utc = pytz.UTC.localize(t)
        if t_utc <= now or i == 0:
            continue
        before = (t_utc - timedelta(hours=1)).astimezone(tz).utcoffset()
        after = (t_utc + timedelta(hours=1)).astimezone(tz).utcoffset()
        if before is None or after is None:
            continue
        if after > before and spring is None:
            spring = t_utc
        elif after < before and fall is None:
            fall = t_utc
        if spring and fall:
            break
    assert spring is not None and fall is not None
    return spring, fall


def planner_config() -> dict:
    return {
        "timezone": "Europe/Stockholm",
        "system": {
            "has_solar": True,
            "has_battery": True,
            "has_water_heater": False,
            "has_ev_charger": False,
            "inverter": {"max_ac_power_kw": 8, "topology": "dc_coupled"},
        },
        "battery": {
            "capacity_kwh": 13.5,
            "min_soc_percent": 10,
            "max_soc_percent": 100,
            "max_charge_w": 5000,
            "max_discharge_w": 5000,
        },
        "battery_economics": {"battery_cycle_cost_kwh": 0.2},
        "executor": {"inverter": {"control_unit": "W"}},
        "learning": {"enable": False},
    }


def make_inputs(start_utc: datetime, hours: int) -> dict:
    """Build price + forecast data on a 15-min UTC grid (as Nordpool delivery does)."""
    idx = pd.date_range(start=start_utc, periods=hours * 4, freq="15min", tz="UTC")
    price_data = []
    forecast_data = []
    for ts in idx:
        end = ts + pd.Timedelta(minutes=15)
        price_data.append(
            {
                "start_time": ts.isoformat(),
                "end_time": end.isoformat(),
                "import_price_sek_kwh": 1.0,
                "export_price_sek_kwh": 0.5,
            }
        )
        forecast_data.append(
            {
                "start_time": ts.isoformat(),
                "pv_forecast_kwh": 0.1,
                "load_forecast_kwh": 0.15,
            }
        )
    return {
        "price_data": price_data,
        "forecast_data": forecast_data,
        "initial_state": {"battery_soc_percent": 50.0},
    }


def schedule_starts(schedule_df: pd.DataFrame) -> pd.Series:
    if "start_time" in schedule_df.columns:
        return pd.to_datetime(schedule_df["start_time"], utc=True)
    return pd.Series(pd.to_datetime(schedule_df.index, utc=True))


def assert_contiguous_15min(schedule_df: pd.DataFrame) -> None:
    starts = schedule_starts(schedule_df)
    diffs = starts.diff().dropna()
    assert (diffs == pd.Timedelta(minutes=15)).all(), (
        f"non-contiguous slots: {diffs[diffs != pd.Timedelta(minutes=15)]}"
    )
    assert starts.duplicated().sum() == 0, "duplicate slot starts"


class TestPlannerSpringForward:
    @pytest.mark.asyncio
    async def test_planner_run_evening_before_spring_forward(self, tmp_path, monkeypatch):
        """Reproduces the production failure shape (#6): a planner run the evening
        before the 23-hour day, horizon crossing the nonexistent hour. Must
        produce a continuous schedule covering the DST morning."""
        monkeypatch.chdir(tmp_path)
        tz = pytz.timezone("Europe/Stockholm")
        spring, _ = next_transitions()
        start_utc = spring - timedelta(hours=5)  # evening before, horizon crosses jump
        now_override = start_utc.astimezone(tz)

        pipeline = PlannerPipeline(planner_config())
        df = await pipeline.generate_schedule(
            make_inputs(start_utc, hours=30),
            mode="baseline",
            save_to_file=False,
            now_override=now_override,
        )

        assert not df.empty
        assert_contiguous_15min(df)
        # The DST morning must be covered — exactly what was missing in production (#6).
        starts = schedule_starts(df)
        morning_utc = pd.Timestamp(spring + timedelta(hours=4))  # well past the jump
        assert (starts == morning_utc).any(), "schedule does not cover the spring-forward morning"

    @pytest.mark.asyncio
    async def test_planner_run_during_spring_forward_night(self, tmp_path, monkeypatch):
        """A run shortly before the jump, planning the rest of the DST day."""
        monkeypatch.chdir(tmp_path)
        tz = pytz.timezone("Europe/Stockholm")
        spring, _ = next_transitions()
        start_utc = spring - timedelta(minutes=30)
        now_override = start_utc.astimezone(tz)

        pipeline = PlannerPipeline(planner_config())
        df = await pipeline.generate_schedule(
            make_inputs(start_utc, hours=20),
            mode="baseline",
            save_to_file=False,
            now_override=now_override,
        )

        assert not df.empty
        assert_contiguous_15min(df)


class TestPlannerFallBack:
    @pytest.mark.asyncio
    async def test_planner_run_evening_before_fall_back(self, tmp_path, monkeypatch):
        """25-hour day: one local hour occurs twice. Slot sequence in UTC must
        stay continuous and duplicate-free. This path has never run in
        production (system started 2025-11-03; findings.md #6 note)."""
        monkeypatch.chdir(tmp_path)
        tz = pytz.timezone("Europe/Stockholm")
        _, fall = next_transitions()
        start_utc = fall - timedelta(hours=5)
        now_override = start_utc.astimezone(tz)

        pipeline = PlannerPipeline(planner_config())
        df = await pipeline.generate_schedule(
            make_inputs(start_utc, hours=32),
            mode="baseline",
            save_to_file=False,
            now_override=now_override,
        )

        assert not df.empty
        assert_contiguous_15min(df)


class TestExecutorAcrossTransitions:
    def test_load_slot_before_and_after_spring_jump(self, fi_engine, temp_schedule):
        """Executor slot lookup on both sides of the spring-forward jump."""
        tz = pytz.timezone("Europe/Stockholm")
        # slots in UTC covering 00:30-02:30 UTC (01:30 CET -> 04:30 CEST local)
        base = datetime(2026, 3, 29, 0, 0, tzinfo=pytz.UTC)
        slots = [make_slot((base + timedelta(minutes=15 * i)).astimezone(tz)) for i in range(10)]
        write_schedule(temp_schedule, slots, generated_at=base.astimezone(tz))

        before = datetime(2026, 3, 29, 0, 50, tzinfo=pytz.UTC).astimezone(tz)  # 01:50 CET
        after = datetime(2026, 3, 29, 1, 5, tzinfo=pytz.UTC).astimezone(tz)  # 03:05 CEST

        slot_b, _ = fi_engine._load_current_slot(before)
        slot_a, _ = fi_engine._load_current_slot(after)

        assert slot_b is not None, "no slot found just before the DST jump"
        assert slot_a is not None, "no slot found just after the DST jump"

    def test_load_slot_during_ambiguous_fall_back_hour(self, fi_engine, temp_schedule):
        """Executor slot lookup inside the repeated 02:00-03:00 hour (fall-back)."""
        tz = pytz.timezone("Europe/Stockholm")
        base = datetime(2026, 10, 25, 0, 0, tzinfo=pytz.UTC)  # 02:00 CEST (first pass)
        slots = [make_slot((base + timedelta(minutes=15 * i)).astimezone(tz)) for i in range(12)]
        write_schedule(temp_schedule, slots, generated_at=base.astimezone(tz))

        first_pass = datetime(2026, 10, 25, 0, 20, tzinfo=pytz.UTC).astimezone(tz)  # 02:20 CEST
        second_pass = datetime(2026, 10, 25, 1, 20, tzinfo=pytz.UTC).astimezone(tz)  # 02:20 CET

        slot_1, start_1 = fi_engine._load_current_slot(first_pass)
        slot_2, start_2 = fi_engine._load_current_slot(second_pass)

        assert slot_1 is not None, "no slot found in first pass of ambiguous hour"
        assert slot_2 is not None, "no slot found in second pass of ambiguous hour"
        assert start_1 != start_2, "both passes of the ambiguous hour matched the same slot"
