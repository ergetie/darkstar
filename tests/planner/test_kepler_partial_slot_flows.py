"""In-progress slot uses one remaining-time basis (planner capability).

Every flow, limit and cost of slot 0 uses the time left in it; the adapter
scales the slot-0 forecast energy to it and reports kW as energy / remaining.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest
import pytz
from pytz import timezone as pytz_timezone

from planner.solver.adapter import (
    kepler_result_to_dataframe,
    scale_first_slot_to_remaining,
)
from planner.solver.kepler import KeplerSolver
from planner.solver.types import KeplerConfig, KeplerInput, KeplerInputSlot

TZ = pytz_timezone("Europe/Stockholm")
SLOT_START = TZ.localize(datetime(2026, 10, 21, 10, 15))
IMPORT_LIMIT_KW = 11.0
MAX_CHARGE_KW = 6.0
REMAINING_H = 4 / 60


def _slots(
    prices: list[float], load_kwh: float = 0.0, pv_kwh: float = 0.0
) -> list[KeplerInputSlot]:
    out: list[KeplerInputSlot] = []
    for i, price in enumerate(prices):
        start = SLOT_START + timedelta(minutes=15 * i)
        out.append(
            KeplerInputSlot(
                start_time=start,
                end_time=start + timedelta(minutes=15),
                load_kwh=load_kwh,
                pv_kwh=pv_kwh,
                import_price_sek_kwh=price,
                export_price_sek_kwh=0.0,
            )
        )
    return out


def _config() -> KeplerConfig:
    return KeplerConfig(
        capacity_kwh=20.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        max_charge_power_kw=MAX_CHARGE_KW,
        max_discharge_power_kw=MAX_CHARGE_KW,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        max_import_power_kw=IMPORT_LIMIT_KW,
    )


def _solve(slots, remaining_h, initial_soc_kwh=2.0):
    inp = KeplerInput(
        slots=slots, initial_soc_kwh=initial_soc_kwh, first_slot_remaining_h=remaining_h
    )
    result = KeplerSolver().solve(inp, _config())
    assert result.is_optimal
    return result


def test_grid_import_in_partial_slot_respects_the_limit():
    """Cheap first slot, heavy house load: with 4 min left the import (kWh over
    the remaining time) must still map to at most the import limit in kW."""
    slots = _slots([0.1, 2.0, 2.0], load_kwh=3.0)  # 3 kWh in a full slot
    scale_input = KeplerInput(slots=slots, initial_soc_kwh=2.0, first_slot_remaining_h=REMAINING_H)
    scale_first_slot_to_remaining(scale_input)
    result = KeplerSolver().solve(scale_input, _config())
    assert result.is_optimal
    df = kepler_result_to_dataframe(result, 20.0, 2.0)
    first = df.iloc[0]
    assert first["grid_import_kw"] <= IMPORT_LIMIT_KW + 1e-6
    assert first["battery_charge_kw"] <= MAX_CHARGE_KW + 1e-6


def test_battery_energy_bounded_by_remaining_time_and_soc_reflects_it():
    slots = _slots([0.1, 5.0, 5.0])
    result = _solve(slots, REMAINING_H)

    first = result.slots[0]
    assert first.charge_kwh <= MAX_CHARGE_KW * REMAINING_H + 1e-6
    # The SoC trajectory only reflects what can really be charged in 4 minutes.
    assert first.soc_kwh <= 2.0 + MAX_CHARGE_KW * REMAINING_H + 1e-6
    assert first.duration_h == pytest.approx(REMAINING_H)
    assert result.slots[1].duration_h == pytest.approx(0.25)


def test_reported_kw_is_energy_over_remaining_time():
    slots = _slots([0.1, 5.0, 5.0])
    result = _solve(slots, REMAINING_H)
    df = kepler_result_to_dataframe(result, 20.0, 2.0)
    first = result.slots[0]
    assert df.iloc[0]["battery_charge_kw"] == pytest.approx(first.charge_kwh / REMAINING_H)
    # Full slots keep the slot length.
    assert df.iloc[1]["battery_charge_kw"] == pytest.approx(result.slots[1].charge_kwh / 0.25)


def test_forecast_energy_is_scaled_to_remaining_time():
    slots = _slots([1.0, 1.0], load_kwh=1.0, pv_kwh=2.0)
    inp = KeplerInput(slots=slots, initial_soc_kwh=2.0, first_slot_remaining_h=0.125)
    scale_first_slot_to_remaining(inp)
    assert inp.slots[0].load_kwh == pytest.approx(0.5)
    assert inp.slots[0].pv_kwh == pytest.approx(1.0)
    # Later slots are untouched.
    assert inp.slots[1].load_kwh == 1.0
    assert inp.slots[1].pv_kwh == 2.0


@pytest.mark.parametrize("remaining_h", [None, 0.25, 0.3])
def test_boundary_plan_is_unchanged(remaining_h):
    """Planning on a slot boundary (or with no remaining time set): identical."""
    baseline = _slots([0.1, 2.0, 2.0], load_kwh=0.5, pv_kwh=0.2)
    reference = KeplerSolver().solve(KeplerInput(slots=baseline, initial_soc_kwh=2.0), _config())

    slots = _slots([0.1, 2.0, 2.0], load_kwh=0.5, pv_kwh=0.2)
    inp = KeplerInput(slots=slots, initial_soc_kwh=2.0, first_slot_remaining_h=remaining_h)
    scale_first_slot_to_remaining(inp)
    result = KeplerSolver().solve(inp, _config())

    assert [s.charge_kwh for s in result.slots] == pytest.approx(
        [s.charge_kwh for s in reference.slots]
    )
    assert [s.grid_import_kwh for s in result.slots] == pytest.approx(
        [s.grid_import_kwh for s in reference.slots]
    )
    assert result.total_cost_sek == pytest.approx(reference.total_cost_sek)
    assert slots[0].load_kwh == 0.5 and slots[0].pv_kwh == 0.2


def test_dataframe_without_duration_uses_slot_length():
    slots = _slots([0.1, 5.0])
    result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=2.0), _config())
    for s in result.slots:
        s.duration_h = None
    df = kepler_result_to_dataframe(result, 20.0, 2.0)
    assert isinstance(df, pd.DataFrame)
    assert df.iloc[0]["battery_charge_kw"] == pytest.approx(result.slots[0].charge_kwh / 0.25)


@pytest.mark.parametrize("seconds", [1, 15, 30, 59])
def test_last_minute_uses_actual_remaining_time(seconds):
    remaining = seconds / 3600
    result = _solve(_slots([0.1, 5.0, 5.0]), remaining)
    first = result.slots[0]
    assert first.duration_h == pytest.approx(remaining)
    assert first.charge_kwh <= MAX_CHARGE_KW * remaining + 1e-6
    assert first.grid_import_kwh <= IMPORT_LIMIT_KW * remaining + 1e-6


@pytest.mark.asyncio
async def test_pipeline_now_override_keeps_the_in_progress_slot(tmp_path, monkeypatch):
    from planner.pipeline import PlannerPipeline
    from tests.fault_injection.test_dst_transitions import make_inputs, planner_config

    monkeypatch.chdir(tmp_path)
    config = planner_config()
    config["learning"] = {"enable": False, "sqlite_path": str(tmp_path / "learning.db")}
    now = SLOT_START + timedelta(minutes=7)
    captured = []
    original = KeplerSolver.solve

    def capture(self, solver_input, solver_config):
        captured.append(solver_input)
        return original(self, solver_input, solver_config)

    monkeypatch.setattr(KeplerSolver, "solve", capture)
    inputs = make_inputs(SLOT_START.astimezone(pytz.UTC), hours=8)
    await PlannerPipeline(config).generate_schedule(
        inputs, mode="baseline", now_override=now, save_to_file=False
    )
    assert captured
    first = captured[0]
    assert first.slots[0].start_time == SLOT_START
    assert first.first_slot_remaining_h == pytest.approx(8 / 60)
