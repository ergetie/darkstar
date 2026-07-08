"""Tests for EV goal-based (target-SoC-by-ready-time) solver behavior."""

from datetime import date, datetime, timedelta

import pytest
from pytz import timezone as pytz_timezone

from planner.solver.kepler import KeplerSolver
from planner.solver.types import EVChargerInput, KeplerConfig, KeplerInput, KeplerInputSlot


def _slots(
    n: int = 4,
    import_prices: list[float] | None = None,
    load_kwh: float = 0.0,
    pv_kwh: float = 0.0,
    start: datetime | None = None,
) -> list[KeplerInputSlot]:
    if start is None:
        tz = pytz_timezone("Europe/Stockholm")
        # Default to the real current date so that daily_quota logic (which uses
        # date.today()) aligns with the synthetic slots.
        start = tz.localize(datetime.combine(date.today(), datetime.min.time()))
    if import_prices is None:
        import_prices = [1.0] * n
    result = []
    for i in range(n):
        s = start + timedelta(hours=i)
        result.append(
            KeplerInputSlot(
                start_time=s,
                end_time=s + timedelta(hours=1),
                load_kwh=load_kwh,
                pv_kwh=pv_kwh,
                import_price_sek_kwh=import_prices[i],
                export_price_sek_kwh=0.0,
            )
        )
    return result


def _ev(
    required_kwh: float,
    deadline: datetime | None = None,
    daily_quota_kwh: float | None = None,
    max_power_kw: float = 7.4,
    battery_capacity_kwh: float = 100.0,
    soc_percent: float = 0.0,
) -> EVChargerInput:
    return EVChargerInput(
        id="test_ev",
        max_power_kw=max_power_kw,
        battery_capacity_kwh=battery_capacity_kwh,
        current_soc_percent=soc_percent,
        plugged_in=True,
        deadline=deadline,
        required_kwh=required_kwh,
        daily_quota_kwh=daily_quota_kwh,
    )


def _config(ev_chargers: list[EVChargerInput]) -> KeplerConfig:
    return KeplerConfig(
        capacity_kwh=0.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        max_charge_power_kw=0.0,
        max_discharge_power_kw=0.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        ev_chargers=ev_chargers,
    )


def test_goal_met_when_cheap_slots_exist():
    """Solver delivers the full required energy when the deadline is not binding."""
    slots = _slots(n=4, import_prices=[0.1, 0.1, 0.1, 0.1])
    inp = KeplerInput(slots=slots, initial_soc_kwh=0.0)
    cfg = _config([_ev(required_kwh=10.0, deadline=slots[-1].end_time)])

    result = KeplerSolver().solve(inp, cfg)
    assert result.is_optimal

    total_ev = sum(s.ev_charge_kw for s in result.slots)
    shortfall = result.slots[-1].ev_shortfall_kwh.get("test_ev", 0.0)
    assert total_ev >= 10.0 - 0.01
    assert shortfall == pytest.approx(0.0, abs=0.01)


def test_shortfall_when_deadline_is_tight():
    """Solver reports shortfall when the deadline does not allow enough energy."""
    slots = _slots(n=2, import_prices=[1.0, 1.0])
    inp = KeplerInput(slots=slots, initial_soc_kwh=0.0)
    # Max deliverable in 2h at 7.4 kW is 14.8 kWh, target 20 kWh is infeasible
    cfg = _config([_ev(required_kwh=20.0, deadline=slots[-1].end_time, max_power_kw=7.4)])

    result = KeplerSolver().solve(inp, cfg)
    assert result.is_optimal

    total_ev = sum(s.ev_charge_kw for s in result.slots)
    shortfall = result.slots[-1].ev_shortfall_kwh.get("test_ev", 0.0)
    assert total_ev <= 14.8 + 0.01
    assert shortfall > 5.0


def test_daily_quota_caps_todays_energy():
    """daily_quota_kwh limits how much energy is delivered on the current calendar day."""
    tz = pytz_timezone("Europe/Stockholm")
    # Use today's date so the solver's date.today() matches the slot calendar day.
    base = tz.localize(datetime.combine(date.today(), datetime.min.time())) + timedelta(hours=22)
    # 4 slots: two today (22-00), two tomorrow (00-02)
    slots = _slots(n=4, import_prices=[0.1, 0.1, 0.1, 0.1], start=base)
    inp = KeplerInput(slots=slots, initial_soc_kwh=0.0)
    cfg = _config(
        [
            _ev(
                required_kwh=20.0,
                deadline=slots[-1].end_time,
                daily_quota_kwh=3.0,
                max_power_kw=7.4,
            )
        ]
    )

    result = KeplerSolver().solve(inp, cfg)
    assert result.is_optimal

    today_energy = sum(
        s.ev_charge_kw * 1.0
        for s in result.slots
        if s.start_time.date() == base.date()
    )
    assert today_energy <= 3.0 + 0.01
    # The remaining energy is deferred to tomorrow
    tomorrow_energy = sum(
        s.ev_charge_kw * 1.0
        for s in result.slots
        if s.start_time.date() != base.date()
    )
    assert tomorrow_energy > 0.0


def test_deferral_to_cheaper_slots():
    """Solver avoids expensive slots when the goal can be met in cheaper slots."""
    slots = _slots(n=3, import_prices=[5.0, 1.0, 0.1])
    inp = KeplerInput(slots=slots, initial_soc_kwh=0.0)
    # 14 kWh fits in the two cheapest slots (7.4 kW each -> 14.8 kWh max)
    cfg = _config([_ev(required_kwh=14.0, deadline=slots[-1].end_time, max_power_kw=7.4)])

    result = KeplerSolver().solve(inp, cfg)
    assert result.is_optimal

    assert result.slots[0].ev_charge_kw < 0.1, "Should avoid the 5 SEK slot"
    total_ev = sum(s.ev_charge_kw for s in result.slots)
    assert total_ev >= 14.0 - 0.01


def test_charging_stops_after_deadline():
    """No scheduled EV charging occurs after the ready-by deadline."""
    slots = _slots(n=4, import_prices=[0.5, 0.5, 0.5, 0.5])
    deadline = slots[1].end_time
    inp = KeplerInput(slots=slots, initial_soc_kwh=0.0)
    cfg = _config([_ev(required_kwh=5.0, deadline=deadline)])

    result = KeplerSolver().solve(inp, cfg)
    assert result.is_optimal

    post_deadline = sum(s.ev_charge_kw for s in result.slots if s.start_time >= deadline)
    assert post_deadline == pytest.approx(0.0, abs=0.01)
