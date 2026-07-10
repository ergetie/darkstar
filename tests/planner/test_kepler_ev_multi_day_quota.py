"""Solver tests for multi-day EV quota enforcement and the net-excess cap
(price-forecasting-module-5 fixes, tasks 4.2/4.4/4.7/4.8).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from pytz import timezone as pytz_timezone

from planner.solver.kepler import KeplerSolver
from planner.solver.types import (
    EVChargerInput,
    ExcessPVSinkEntry,
    KeplerConfig,
    KeplerInput,
    KeplerInputSlot,
)

TZ = pytz_timezone("Europe/Stockholm")


def _base_config(**overrides) -> dict:
    base = dict(
        capacity_kwh=10.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        enable_export=True,
        max_export_power_kw=10.0,
    )
    base.update(overrides)
    return base


def _slots(n, *, start, import_prices, export_prices=None, pv_kwh=0.0, load_kwh=0.0):
    if export_prices is None:
        export_prices = [0.0] * n
    out = []
    for i in range(n):
        s = start + timedelta(hours=i)
        out.append(
            KeplerInputSlot(
                start_time=s,
                end_time=s + timedelta(hours=1),
                load_kwh=load_kwh,
                pv_kwh=pv_kwh,
                import_price_sek_kwh=import_prices[i],
                export_price_sek_kwh=export_prices[i],
            )
        )
    return out


def test_two_day_horizon_quota_enforced_per_day():
    """Each in-horizon day is capped at its own quota, and the horizon total
    never exceeds the sum of in-horizon quotas."""
    start = TZ.localize(datetime(2026, 7, 8, 0, 0))
    n = 48  # today + tomorrow, hourly
    # Today is cheap (so the solver wants to use up today's quota), tomorrow
    # is expensive (so it only spills over what today's quota can't hold).
    import_prices = [0.1] * 24 + [1.0] * 24
    slots = _slots(n, start=start, import_prices=import_prices)
    today = start.date()
    tomorrow = today + timedelta(days=1)

    # EV charging is all-or-nothing per hourly slot (binary "on" at
    # max_power_kw), so quotas must be exact multiples of max_power_kw to be
    # physically achievable: 1 slot today (5.0 kWh), 3 slots tomorrow (15.0 kWh).
    quota_by_day = {today: 5.0, tomorrow: 15.0}
    ev = EVChargerInput(
        id="ev1",
        max_power_kw=5.0,
        battery_capacity_kwh=82.0,
        current_soc_percent=30.0,
        plugged_in=True,
        deadline=slots[-1].end_time,
        required_kwh=20.0,
        quota_by_day=quota_by_day,
        control_type="current",
    )
    cfg = KeplerConfig(**_base_config(capacity_kwh=0.0), ev_chargers=[ev])
    result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=0.0), cfg)
    assert result.is_optimal

    today_energy = sum(s.ev_charge_kw for s in result.slots if s.start_time.date() == today)
    tomorrow_energy = sum(s.ev_charge_kw for s in result.slots if s.start_time.date() == tomorrow)

    assert today_energy <= 5.0 + 0.01
    assert tomorrow_energy <= 15.0 + 0.01
    assert today_energy + tomorrow_energy <= sum(quota_by_day.values()) + 0.01
    # Spreading actually spreads: some energy lands on each day.
    assert today_energy > 0.0
    assert tomorrow_energy > 0.0


def test_net_excess_magnitude_sinks_get_zero_when_battery_covers_excess():
    """PV=10, load=2 -> net excess=8 in slot 0. A pricey slot 1 (load=8, no
    PV) gives the battery a genuine reason to charge fully from the "free"
    excess in slot 0, rather than curtail it, so it can discharge for slot
    1's load instead of an expensive grid import. When it does, sinks (EV
    surplus) in slot 0 must get 0 — grid import can't sneak in disguised as
    'surplus' charging alongside the battery soaking up the same excess."""
    start = TZ.localize(datetime(2026, 7, 8, 12, 0))
    slots = _slots(
        2,
        start=start,
        import_prices=[5.0, 5.0],
        pv_kwh=0.0,
        load_kwh=0.0,
    )
    slots[0].pv_kwh = 10.0
    slots[0].load_kwh = 2.0
    slots[1].load_kwh = 8.0

    ev = EVChargerInput(
        id="ev1",
        max_power_kw=8.0,
        battery_capacity_kwh=82.0,
        current_soc_percent=30.0,
        plugged_in=True,
        deadline=slots[-1].end_time,
        required_kwh=0.0,  # no scheduled-charging pressure; isolate the surplus path
        control_type="current",
    )
    cfg = KeplerConfig(
        **_base_config(capacity_kwh=10.0, max_charge_power_kw=8.0, max_discharge_power_kw=8.0),
        excess_pv_slots=[True, False],
        excess_pv_priority=[
            ExcessPVSinkEntry(type="ev", effective_reward_sek_per_kwh=2.0, charger_id="ev1")
        ],
        excess_pv_soc_threshold_percent=0.0,  # always eligible to activate sinks
        ev_chargers=[ev],
    )
    result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=0.0), cfg)
    assert result.is_optimal

    battery_charge_kwh = result.slots[0].charge_kwh
    sink_kwh = result.slots[0].ev_surplus_kw.get("ev1", 0.0)

    # The battery consumes (close to) the full net excess, so sinks must get ~0.
    assert battery_charge_kwh == pytest.approx(8.0, abs=0.1)
    assert sink_kwh == pytest.approx(0.0, abs=0.05), (
        f"sinks should get ~0 when the battery consumes the excess; got {sink_kwh}"
    )


def test_surplus_counts_toward_day_quota():
    """EV surplus charging is counted against the day's quota, not a free
    bonus on top of it — scheduled + surplus energy stays within the cap."""
    start = TZ.localize(datetime(2026, 7, 8, 10, 0))
    n = 4
    slots = _slots(
        n,
        start=start,
        import_prices=[3.0] * n,  # expensive scheduled charging -> prefers surplus
        pv_kwh=10.0,
        load_kwh=1.0,
        export_prices=[0.05] * n,
    )
    today = start.date()
    quota_by_day = {today: 5.0}

    ev = EVChargerInput(
        id="ev1",
        max_power_kw=7.4,
        battery_capacity_kwh=82.0,
        current_soc_percent=30.0,
        plugged_in=True,
        deadline=slots[-1].end_time,
        required_kwh=20.0,
        quota_by_day=quota_by_day,
        control_type="current",
    )
    cfg = KeplerConfig(
        **_base_config(capacity_kwh=10.0),
        excess_pv_slots=[True] * n,
        excess_pv_priority=[
            ExcessPVSinkEntry(type="ev", effective_reward_sek_per_kwh=2.0, charger_id="ev1")
        ],
        excess_pv_soc_threshold_percent=95.0,
        ev_chargers=[ev],
    )
    initial_soc = cfg.capacity_kwh * 0.97
    result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=initial_soc), cfg)
    assert result.is_optimal

    scheduled_today = sum(s.ev_charge_kw for s in result.slots if s.start_time.date() == today)
    surplus_today = sum(
        s.ev_surplus_kw.get("ev1", 0.0) for s in result.slots if s.start_time.date() == today
    )
    assert scheduled_today + surplus_today <= 5.0 + 0.05, (
        f"scheduled ({scheduled_today}) + surplus ({surplus_today}) must respect today's quota"
    )
