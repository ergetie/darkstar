"""EV target-SoC-by-ready-by solver tests (Module 4 §4.8).

Covers the spec scenarios in ``specs/ev-target-charging/spec.md``:
- Configured current-type charger (in ``excess_pv.priority[]``) charges from
  surplus PV instead of exporting.
- Reaches ``target_soc`` by deadline when feasible (cheapest slots).
- Reports shortfall (stays feasible) when not reachable in time.
- ``daily_quota_kwh`` caps today's energy.
- No incentive-bucket code path remains (structural assertion).
- Shortfall penalty defaults to 50.0 and is overridden by
  ``kepler.ev_shortfall_penalty_sek_per_kwh`` when set.
- Binary charger in ``excess_pv.priority[]`` is silently dropped (no
  ``ev_surplus_kw``) but still receives scheduled charging per its soft
  deadline-target.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from pytz import timezone as pytz_timezone

from planner.solver.kepler import EV_SHORTFALL_PENALTY_DEFAULT, KeplerSolver
from planner.solver.types import (
    EVChargerInput,
    ExcessPVSinkEntry,
    KeplerConfig,
    KeplerInput,
    KeplerInputSlot,
)

TZ = pytz_timezone("Europe/Stockholm")


def _slots(
    n: int = 4,
    *,
    import_prices: list[float] | None = None,
    export_prices: list[float] | None = None,
    pv_kwh: float = 0.0,
    load_kwh: float = 0.0,
    start: datetime | None = None,
    slot_hours: float = 1.0,
) -> list[KeplerInputSlot]:
    if start is None:
        start = TZ.localize(datetime.combine(date.today(), datetime.min.time()))
    if import_prices is None:
        import_prices = [1.0] * n
    if export_prices is None:
        export_prices = [0.0] * n
    out: list[KeplerInputSlot] = []
    for i in range(n):
        s = start + timedelta(hours=i * slot_hours)
        out.append(
            KeplerInputSlot(
                start_time=s,
                end_time=s + timedelta(hours=slot_hours),
                load_kwh=load_kwh,
                pv_kwh=pv_kwh,
                import_price_sek_kwh=import_prices[i],
                export_price_sek_kwh=export_prices[i],
            )
        )
    return out


def _ev(
    *,
    id: str = "ev1",
    required_kwh: float,
    deadline: datetime | None = None,
    quota_by_day: dict[date, float] | None = None,
    max_power_kw: float = 7.4,
    battery_capacity_kwh: float = 100.0,
    soc_percent: float = 0.0,
    control_type: str = "current",
) -> EVChargerInput:
    return EVChargerInput(
        id=id,
        max_power_kw=max_power_kw,
        battery_capacity_kwh=battery_capacity_kwh,
        current_soc_percent=soc_percent,
        plugged_in=True,
        deadline=deadline,
        required_kwh=required_kwh,
        quota_by_day=quota_by_day,
        control_type=control_type,
    )


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


def _ev_priority(charger_id: str, reward: float) -> ExcessPVSinkEntry:
    return ExcessPVSinkEntry(type="ev", effective_reward_sek_per_kwh=reward, charger_id=charger_id)


# ---------------------------------------------------------------------------
# Scenario: configured current-type charger charges from surplus PV instead of
# exporting.
# ---------------------------------------------------------------------------
def test_charges_from_surplus_pv_instead_of_exporting():
    capacity = 10.0
    initial_soc = capacity * 0.97  # above the 95% SoC threshold

    # Each slot has 8 kWh PV and 1 kWh load → 7 kWh surplus available.
    slots = _slots(n=4, pv_kwh=8.0, load_kwh=1.0, export_prices=[0.05] * 4)
    ev = _ev(required_kwh=10.0, deadline=slots[-1].end_time, max_power_kw=7.4)
    cfg = KeplerConfig(
        **_base_config(capacity_kwh=capacity),
        excess_pv_slots=[True] * 4,
        excess_pv_priority=[_ev_priority("ev1", reward=2.0)],
        excess_pv_soc_threshold_percent=95.0,
        ev_chargers=[ev],
    )

    result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=initial_soc), cfg)
    assert result.is_optimal

    surplus_to_ev = sum(s.ev_surplus_kw.get("ev1", 0.0) for s in result.slots)
    exported = sum(s.grid_export_kwh for s in result.slots)
    assert surplus_to_ev > 0.0, "current-type EV listed in priority should absorb surplus PV"
    # Export should be strictly less than the available surplus (some went to the EV).
    available_surplus = sum(max(0.0, s.pv_kwh - s.load_kwh) for s in slots)
    assert exported < available_surplus


# ---------------------------------------------------------------------------
# Scenario: target reachable → deliver at least required_kwh by deadline using
# the cheapest slots, preferring free surplus PV over grid import.
# ---------------------------------------------------------------------------
def test_reaches_target_by_deadline_using_cheapest_slots():
    # 4 slots, midday surplus in slots 1-2 (free), import prices varying.
    slots = _slots(
        n=4,
        import_prices=[5.0, 5.0, 0.1, 0.1],
        pv_kwh=0.0,
    )
    ev = _ev(required_kwh=10.0, deadline=slots[-1].end_time, max_power_kw=7.4)
    cfg = KeplerConfig(**_base_config(capacity_kwh=0.0), ev_chargers=[ev])

    result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=0.0), cfg)
    assert result.is_optimal

    total_ev = sum(s.ev_charge_kw for s in result.slots)
    shortfall = result.slots[-1].ev_shortfall_kwh.get("ev1", 0.0)
    assert total_ev >= 10.0 - 0.01
    assert shortfall == pytest.approx(0.0, abs=0.01)
    # Avoids the expensive slots entirely when the goal fits in the cheap ones.
    assert result.slots[0].ev_charge_kw < 0.1
    assert result.slots[1].ev_charge_kw < 0.1


# ---------------------------------------------------------------------------
# Scenario: target not reachable in time → solve stays feasible; charger
# charges as much as possible and reports a shortfall.
# ---------------------------------------------------------------------------
def test_reports_shortfall_when_target_unreachable():
    # 2 slots at 7.4 kW → max 14.8 kWh, target 20 kWh is infeasible to deliver.
    slots = _slots(n=2, import_prices=[1.0, 1.0])
    ev = _ev(required_kwh=20.0, deadline=slots[-1].end_time, max_power_kw=7.4)
    cfg = KeplerConfig(**_base_config(capacity_kwh=0.0), ev_chargers=[ev])

    result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=0.0), cfg)
    assert result.is_optimal

    total_ev = sum(s.ev_charge_kw for s in result.slots)
    shortfall = result.slots[-1].ev_shortfall_kwh.get("ev1", 0.0)
    assert total_ev <= 14.8 + 0.01
    assert shortfall > 5.0


# ---------------------------------------------------------------------------
# Scenario: quota_by_day caps today's energy; remainder deferred to other
# (later) days within the deadline horizon (per-day quota, not just today).
# ---------------------------------------------------------------------------
def test_daily_quota_caps_todays_energy():
    # 4 slots starting late tonight: two today (22-00), two tomorrow (00-02).
    base = TZ.localize(datetime.combine(date.today(), datetime.min.time())) + timedelta(hours=22)
    slots = _slots(n=4, import_prices=[0.1] * 4, start=base)
    tomorrow = base.date() + timedelta(days=1)
    ev = _ev(
        required_kwh=20.0,
        deadline=slots[-1].end_time,
        quota_by_day={base.date(): 3.0, tomorrow: 17.0},
        max_power_kw=7.4,
    )
    cfg = KeplerConfig(**_base_config(capacity_kwh=0.0), ev_chargers=[ev])

    result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=0.0), cfg)
    assert result.is_optimal

    today_energy = sum(
        s.ev_charge_kw * 1.0 for s in result.slots if s.start_time.date() == base.date()
    )
    assert today_energy <= 3.0 + 0.01
    tomorrow_energy = sum(
        s.ev_charge_kw * 1.0 for s in result.slots if s.start_time.date() != base.date()
    )
    assert tomorrow_energy > 0.0


# ---------------------------------------------------------------------------
# Scenario: no incentive-bucket code path remains (structural assertions).
# ---------------------------------------------------------------------------
def test_no_incentive_bucket_code_path_remains():
    # The retired reward field/attribute must not exist anywhere on config or
    # result, and the EVChargerInput dataclass carries no `incentive_buckets`.
    assert not hasattr(KeplerConfig, "incentive_buckets")
    assert not hasattr(EVChargerInput, "incentive_buckets")
    for retired in ("ev_bucket_charged", "value_sek", "incentive_buckets", "penalty_levels"):
        assert not hasattr(KeplerConfig, retired), retired
        assert not hasattr(EVChargerInput, retired), retired

    slots = _slots(n=2, import_prices=[0.1, 0.1])
    ev = _ev(required_kwh=5.0, deadline=slots[-1].end_time)
    cfg = KeplerConfig(**_base_config(capacity_kwh=0.0), ev_chargers=[ev])
    result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=0.0), cfg)

    for s in result.slots:
        assert not hasattr(s, "ev_bucket_charged")
        assert not hasattr(s, "value_sek")


# ---------------------------------------------------------------------------
# Scenario: shortfall penalty defaults to 50.0 and is overridden by
# ``kepler.ev_shortfall_penalty_sek_per_kwh`` when set.
# ---------------------------------------------------------------------------
def test_shortfall_penalty_default_is_50():
    assert EV_SHORTFALL_PENALTY_DEFAULT == 50.0
    slots = _slots(n=2, import_prices=[1.0, 1.0])
    ev = _ev(required_kwh=20.0, deadline=slots[-1].end_time, max_power_kw=7.4)
    cfg = KeplerConfig(**_base_config(capacity_kwh=0.0), ev_chargers=[ev])
    # Default applies when the field is left at its dataclass default.
    assert cfg.ev_shortfall_penalty_sek_per_kwh == 50.0


def test_shortfall_penalty_override_changes_solver_behaviour():
    # A tiny unreachable target: 2 slots * 7.4 kW = 14.8 kWh, target 20 kWh.
    # With a low penalty the solver may rationally under-charge EV (import is
    # cheaper than the penalty); with a high penalty it charges the full
    # deliverable amount. We assert the high-penalty run delivers strictly more
    # EV energy than the low-penalty run.
    slots = _slots(
        n=2,
        import_prices=[3.0, 3.0],  # expensive grid import — makes it costly to charge
    )
    ev = _ev(required_kwh=20.0, deadline=slots[-1].end_time, max_power_kw=7.4)
    base = _base_config(capacity_kwh=0.0)

    low_cfg = KeplerConfig(**base, ev_chargers=[ev], ev_shortfall_penalty_sek_per_kwh=0.1)
    high_cfg = KeplerConfig(**base, ev_chargers=[ev], ev_shortfall_penalty_sek_per_kwh=5000.0)
    assert low_cfg.ev_shortfall_penalty_sek_per_kwh == 0.1
    assert high_cfg.ev_shortfall_penalty_sek_per_kwh == 5000.0

    low = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=0.0), low_cfg)
    high = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=0.0), high_cfg)
    assert low.is_optimal and high.is_optimal

    low_ev = sum(s.ev_charge_kw for s in low.slots)
    high_ev = sum(s.ev_charge_kw for s in high.slots)
    assert high_ev > low_ev, (
        f"high penalty ({high_cfg.ev_shortfall_penalty_sek_per_kwh}) should deliver more EV "
        f"energy than low penalty ({low_cfg.ev_shortfall_penalty_sek_per_kwh}); "
        f"got high={high_ev} low={low_ev}"
    )

    low_shortfall = low.slots[-1].ev_shortfall_kwh.get("ev1", 0.0)
    high_shortfall = high.slots[-1].ev_shortfall_kwh.get("ev1", 0.0)
    assert low_shortfall > high_shortfall


# ---------------------------------------------------------------------------
# Scenario: a binary charger in ``excess_pv.priority[]`` is silently dropped
# (no ``ev_surplus_kw`` variable created) but still receives scheduled charging
# per its soft deadline-target.
# ---------------------------------------------------------------------------
def test_binary_charger_in_priority_silently_dropped_but_still_scheduled():
    capacity = 10.0
    initial_soc = capacity * 0.97

    slots = _slots(n=4, pv_kwh=8.0, load_kwh=1.0, export_prices=[0.05] * 4)
    ev = _ev(
        id="binary_ev",
        required_kwh=10.0,
        deadline=slots[-1].end_time,
        max_power_kw=7.4,
        control_type="binary",
    )
    cfg = KeplerConfig(
        **_base_config(capacity_kwh=capacity),
        excess_pv_slots=[True] * 4,
        excess_pv_priority=[_ev_priority("binary_ev", reward=2.0)],
        excess_pv_soc_threshold_percent=95.0,
        ev_chargers=[ev],
    )

    result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=initial_soc), cfg)
    assert result.is_optimal

    # No surplus variable created for a binary charger.
    for s in result.slots:
        assert "binary_ev" not in s.ev_surplus_kw

    # But the soft deadline-target scheduled charging still fires.
    scheduled = sum(s.ev_charger_results.get("binary_ev", 0.0) for s in result.slots)
    assert scheduled > 0.0, "binary charger should still receive scheduled charging"
