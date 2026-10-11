"""ev-charging-losses 2.4: Kepler credits EV goals after charging losses."""

from datetime import datetime, timedelta

from planner.solver.kepler import KeplerSolver
from planner.solver.types import (
    EVChargerInput,
    ExcessPVSinkEntry,
    KeplerConfig,
    KeplerInput,
    KeplerInputSlot,
)


def _slots(prices: list[float], minutes: int = 60, pv_kwh: float = 0.0, export_price: float = 0.0):
    start = datetime(2026, 1, 1, 0, 0)
    return [
        KeplerInputSlot(
            start_time=start + timedelta(minutes=minutes * i),
            end_time=start + timedelta(minutes=minutes * (i + 1)),
            load_kwh=0.0,
            pv_kwh=pv_kwh,
            import_price_sek_kwh=p,
            export_price_sek_kwh=export_price,
        )
        for i, p in enumerate(prices)
    ]


def _ev(required_kwh: float, **kw) -> EVChargerInput:
    base: dict = dict(
        id="ev",
        max_power_kw=7.0,
        min_power_kw=2.3,
        battery_capacity_kwh=60.0,
        current_soc_percent=50.0,
        plugged_in=True,
        deadline=None,
        required_kwh=required_kwh,
        control_type="current",
    )
    base.update(kw)
    return EVChargerInput(**base)


def _config(ev: EVChargerInput, **kw) -> KeplerConfig:
    base: dict = dict(
        capacity_kwh=0.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        max_charge_power_kw=0.0,
        max_discharge_power_kw=0.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        ev_chargers=[ev],
    )
    base.update(kw)
    return KeplerConfig(**base)


def _wall_kwh(result, minutes: int = 60) -> list[float]:
    return [s.ev_charger_results.get("ev", 0.0) * minutes / 60 for s in result.slots]


def test_fewer_higher_power_slots_preferred():
    ev = _ev(10.0, charge_overhead_kw=0.25, start_loss_kwh=0.15, charge_efficiency=0.95)
    result = KeplerSolver().solve(KeplerInput(slots=_slots([1.0] * 8), initial_soc_kwh=0.0), _config(ev))
    assert result.is_optimal
    on = [i for i, kwh in enumerate(_wall_kwh(result)) if kwh > 1e-6]
    assert len(on) == 2, on
    assert on[1] - on[0] == 1, "one continuous session (single start)"


def test_efficiency_raises_wallbox_energy():
    ev = _ev(10.0, charge_overhead_kw=0.0, start_loss_kwh=0.0, charge_efficiency=0.95)
    result = KeplerSolver().solve(KeplerInput(slots=_slots([1.0] * 8), initial_soc_kwh=0.0), _config(ev))
    assert sum(_wall_kwh(result)) >= 10.0 / 0.95 - 1e-4  # ~10.53


def _solve_running(charging_now: bool) -> float:
    ev = _ev(
        7.0,
        min_power_kw=1.4,
        charge_overhead_kw=0.0,
        start_loss_kwh=1.0,
        charge_efficiency=1.0,
        charging_now=charging_now,
    )
    prices = [0.5, 1.0, 1.0, 1.0]
    result = KeplerSolver().solve(KeplerInput(slots=_slots(prices), initial_soc_kwh=0.0), _config(ev))
    assert result.is_optimal
    return sum(_wall_kwh(result))


def test_continuing_running_session_costs_no_start():
    assert abs(_solve_running(True) - 7.0) < 1e-3
    assert _solve_running(False) >= 8.0 - 1e-3


def _solve_surplus(overhead: float):
    ev = _ev(
        2.0,
        min_power_kw=0.0,
        charge_overhead_kw=overhead,
        start_loss_kwh=0.0,
        charge_efficiency=1.0,
    )
    config = _config(
        ev,
        capacity_kwh=10.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        enable_export=True,
        max_export_power_kw=50.0,
        excess_pv_slots=[True] * 4,
        excess_pv_priority=[
            ExcessPVSinkEntry(type="ev", effective_reward_sek_per_kwh=0.0, charger_id="ev")
        ],
        excess_pv_soc_threshold_percent=0.0,
    )
    slots = _slots([5.0] * 4, minutes=15, pv_kwh=3.0, export_price=0.5)
    result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=10.0), config)
    assert result.is_optimal
    surplus = [s.ev_surplus_kw.get("ev", 0.0) * 0.25 for s in result.slots]
    scheduled = sum(_wall_kwh(result, minutes=15))
    return surplus, scheduled


def test_surplus_slot_pays_overhead():
    surplus, scheduled = _solve_surplus(0.0)
    assert abs(sum(surplus) + scheduled - 2.0) < 1e-3
    surplus, scheduled = _solve_surplus(1.0)
    assert scheduled < 1e-6
    on_slots = sum(1 for kwh in surplus if kwh > 1e-6)
    assert on_slots >= 1
    assert sum(surplus) >= 2.0 + 1.0 * 0.25 * on_slots - 1e-3


def test_adapter_fills_losses_and_charging_now():
    from planner.solver.adapter import build_ev_charger_inputs

    cfg = {"id": "ev", "type": "binary", "rated_power_kw": 7.0, "battery_capacity_kwh": 60.0}
    tuned = {**cfg, "charge_overhead_kw": 0.3, "start_loss_kwh": 0.2, "charge_efficiency": 0.9}
    running = build_ev_charger_inputs([tuned], [{"id": "ev", "power_kw": 6.8}], 230.0)[0]
    assert (running.charge_overhead_kw, running.start_loss_kwh, running.charge_efficiency) == (
        0.3,
        0.2,
        0.9,
    )
    assert running.charging_now is True
    idle = build_ev_charger_inputs([cfg], [{"id": "ev", "power_kw": 0.02}], 230.0)[0]
    assert idle.charging_now is False
    assert (idle.charge_overhead_kw, idle.start_loss_kwh, idle.charge_efficiency) == (
        0.25,
        0.15,
        0.95,
    )
