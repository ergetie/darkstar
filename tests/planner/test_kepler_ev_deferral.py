"""Kepler EV goal model with tiered deferral value (ev-planning-model §3.4)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pytz import timezone as pytz_timezone

from planner.solver.kepler import KeplerSolver
from planner.solver.types import EVChargerInput, KeplerConfig, KeplerInput, KeplerInputSlot

TZ = pytz_timezone("Europe/Stockholm")
Q = timedelta(minutes=15)


def _slots(start: datetime, prices: list[float]) -> list[KeplerInputSlot]:
    return [
        KeplerInputSlot(
            start_time=start + i * Q,
            end_time=start + (i + 1) * Q,
            load_kwh=0.2,
            pv_kwh=0.0,
            import_price_sek_kwh=p,
            export_price_sek_kwh=0.0,
        )
        for i, p in enumerate(prices)
    ]


def _cfg(ev: EVChargerInput) -> KeplerConfig:
    return KeplerConfig(
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


def _ev(required: float, deadline: datetime, tiers=None, max_kw: float = 6.9) -> EVChargerInput:
    return EVChargerInput(
        id="ev1",
        max_power_kw=max_kw,
        min_power_kw=4.18,
        battery_capacity_kwh=80.0,
        current_soc_percent=30.0,
        plugged_in=True,
        deadline=deadline,
        required_kwh=required,
        deferral_tiers=tiers or [],
        control_type="current",
    )


def _energy(result, pred=lambda s: True) -> float:
    return sum(s.ev_charger_results.get("ev1", 0.0) * 0.25 for s in result.slots if pred(s))


def _solve(slots, ev):
    result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=0.0), _cfg(ev))
    assert result.is_optimal
    return result


def test_prod_2026_09_25_all_prices_known_cheaper_tomorrow_no_charging_today():
    """22.2 kWh by 2026-09-26 23:00, both days published, today ≈2.4, tomorrow night ≈1.0."""
    now = TZ.localize(datetime(2026, 9, 25, 14, 0))
    tomorrow = TZ.localize(datetime(2026, 9, 26, 0, 0))
    n_today = int((tomorrow - now) / Q)
    prices = [2.4] * n_today + [1.0] * 28 + [1.8] * 68  # tomorrow: cheap night, dearer day
    slots = _slots(now, prices)
    deadline = TZ.localize(datetime(2026, 9, 26, 23, 0))

    result = _solve(slots, _ev(22.2, deadline))

    assert _energy(result, lambda s: s.start_time < tomorrow) == pytest.approx(0.0, abs=0.01)
    assert _energy(result) == pytest.approx(22.2, abs=0.05)
    assert result.ev_deferred_kwh == {}
    assert result.ev_shortfall_kwh["ev1"] == pytest.approx(0.0, abs=0.01)


def test_forecast_cheaper_than_every_known_slot_defers_everything():
    now = TZ.localize(datetime(2026, 9, 25, 14, 0))
    slots = _slots(now, [2.0] * 40)
    deadline = now + timedelta(days=3)
    result = _solve(slots, _ev(10.0, deadline, tiers=[(1.1, 20.0), (1.4, 20.0)]))

    assert _energy(result) == pytest.approx(0.0, abs=0.01)
    assert result.ev_deferred_kwh["ev1"][0] == pytest.approx(10.0, abs=0.01)
    assert result.ev_deferred_kwh["ev1"][1] == pytest.approx(0.0, abs=0.01)


def test_known_slot_cheaper_than_forecast_charges_now():
    now = TZ.localize(datetime(2026, 9, 25, 14, 0))
    prices = [2.0] * 40
    prices[10:14] = [0.5] * 4  # one cheap hour: 6.9 kWh capacity
    slots = _slots(now, prices)
    deadline = now + timedelta(days=3)
    result = _solve(slots, _ev(10.0, deadline, tiers=[(1.1, 20.0)]))

    cheap_hour = {slots[i].start_time for i in range(10, 14)}
    assert _energy(result, lambda s: s.start_time in cheap_hour) == pytest.approx(6.9, abs=0.05)
    assert sum(result.ev_deferred_kwh["ev1"]) == pytest.approx(3.1, abs=0.05)


def test_large_requirement_uses_dearer_tier_and_cheaper_known_slots():
    now = TZ.localize(datetime(2026, 9, 25, 14, 0))
    prices = [2.0] * 40
    prices[0:8] = [1.3] * 8  # 2 h at 1.3: cheaper than tier 2 (1.5), dearer than tier 1 (1.0)
    slots = _slots(now, prices)
    deadline = now + timedelta(days=3)
    result = _solve(slots, _ev(20.0, deadline, tiers=[(1.0, 5.0), (1.5, 30.0)]))

    deferred = result.ev_deferred_kwh["ev1"]
    assert deferred[0] == pytest.approx(5.0, abs=0.01)  # cheapest tier full
    # In-horizon 1.3 slots beat the marginal 1.5 tier.
    assert _energy(result, lambda s: s.start_time < slots[8].start_time) == pytest.approx(13.8, abs=0.05)
    assert deferred[1] == pytest.approx(20.0 - 5.0 - 13.8, abs=0.05)
    assert _energy(result, lambda s: s.start_time >= slots[8].start_time) == pytest.approx(0.0, abs=0.01)


def test_tail_too_short_forces_in_horizon_minimum():
    """30 kWh at 6.9 kW with a 2 h post-horizon tail (13.8 kWh) -> ≥16.2 kWh in horizon."""
    now = TZ.localize(datetime(2026, 9, 25, 14, 0))
    slots = _slots(now, [2.5] * 40)  # 10 h of expensive known slots
    deadline = slots[-1].end_time + timedelta(hours=2)
    result = _solve(slots, _ev(30.0, deadline, tiers=[(0.8, 13.8)]))

    assert sum(result.ev_deferred_kwh["ev1"]) == pytest.approx(13.8, abs=0.01)
    assert _energy(result) == pytest.approx(16.2, abs=0.05)
    assert result.ev_shortfall_kwh["ev1"] == pytest.approx(0.0, abs=0.01)


def test_unreachable_target_stays_feasible_with_shortfall():
    now = TZ.localize(datetime(2026, 9, 25, 14, 0))
    slots = _slots(now, [2.0] * 8)  # 2 h in horizon -> 13.8 kWh
    deadline = slots[-1].end_time + timedelta(hours=1)
    result = _solve(slots, _ev(40.0, deadline, tiers=[(1.0, 6.9)]))

    assert _energy(result) == pytest.approx(13.8, abs=0.05)
    assert sum(result.ev_deferred_kwh["ev1"]) == pytest.approx(6.9, abs=0.01)
    assert result.ev_shortfall_kwh["ev1"] == pytest.approx(40.0 - 13.8 - 6.9, abs=0.05)
