"""battery-load-balancing 2.x: battery grid charging as a give-way entry."""

from datetime import datetime, timedelta

import pytest

from executor.config import LoadBalancingConfig
from executor.load_balancer import (
    BatteryBalancerInput,
    EVBalancerInput,
    LoadBalancer,
    ShedLoadInput,
)

T0 = datetime(2026, 1, 1, 12, 0, 0)
V = 230.0


def _cfg(**overrides) -> LoadBalancingConfig:
    base = {
        "enabled": True,
        "main_fuse_a": 20,
        "nominal_voltage_v": V,
        "ramp_up_window_s": 60,
        "resume_confirm_s": 10,
        "target_margin_percent": 85.0,
        "increase_step_a": 1,
        "sensor_stale_after_s": 30,
    }
    base.update(overrides)
    return LoadBalancingConfig(**base)


def _battery(
    planned_w=10000.0,
    applied_cap_w=None,
    reducible_w=None,
    active=True,
    min_w=480.0,
) -> BatteryBalancerInput:
    cap = planned_w if applied_cap_w is None else applied_cap_w
    return BatteryBalancerInput(
        planned_w=planned_w,
        applied_cap_w=cap,
        reducible_w=cap if reducible_w is None else reducible_w,
        active=active,
        min_w=min_w,
    )


def _tick(lb: LoadBalancer, now: datetime, currents: dict[int, float], entries):
    return lb.tick(now, currents, dict.fromkeys(currents, now), entries)


class TestBatteryGiveWay:
    def test_reported_20a_fuse_24a_phase_cuts_4a_on_three_phases(self):
        """Washing machine pushes L1 to 24 A during 10 kW grid charging."""
        lb = LoadBalancer(_cfg())
        status = _tick(lb, T0, {1: 24.0, 2: 16.0, 3: 16.0}, [_battery()])
        out = status.battery_output
        assert out is not None
        assert out.state == "throttling"
        assert out.cap_w == pytest.approx(10000 - 4 * V * 3)
        assert out.planned_w == 10000
        assert status.state == "throttling"

    def test_entries_below_see_no_remaining_deficit(self):
        lb = LoadBalancer(_cfg())
        status = _tick(
            lb,
            T0,
            {1: 24.0, 2: 16.0, 3: 16.0},
            [_battery(), ShedLoadInput("tank", "water_heater", [1])],
        )
        assert status.battery_output.state == "throttling"
        assert status.shed_outputs[0].shed is False

    def test_single_phase_overload_spread_over_three_phases(self):
        lb = LoadBalancer(_cfg())
        status = _tick(lb, T0, {1: 10.0, 2: 23.0, 3: 10.0}, [_battery()])
        assert status.battery_output.cap_w == pytest.approx(10000 - 3 * V * 3)

    def test_cut_limited_to_reducible_grid_share(self):
        lb = LoadBalancer(_cfg())
        status = _tick(lb, T0, {1: 24.0, 2: 16.0, 3: 16.0}, [_battery(reducible_w=1000.0)])
        assert status.battery_output.cap_w == pytest.approx(9000.0)

    def test_entry_above_absorbs_deficit(self):
        lb = LoadBalancer(_cfg())
        ev = EVBalancerInput(
            charger_id="ev",
            phases=[1, 2, 3],
            current_setpoint_a=16,
            planner_target_a=16,
            min_current_a=6,
            max_current_a=16,
        )
        status = _tick(lb, T0, {1: 24.0, 2: 16.0, 3: 16.0}, [ev, _battery()])
        assert status.ev_outputs[0].target_a == 12
        assert status.battery_output.cap_w == 10000
        assert status.battery_output.state == "idle"

    def test_non_charge_intent_ignored(self):
        lb = LoadBalancer(_cfg())
        status = _tick(lb, T0, {1: 24.0, 2: 16.0, 3: 16.0}, [_battery(active=False)])
        assert status.battery_output.state == "idle"
        assert status.battery_output.cap_w == 10000

    def test_zero_import_not_reduced(self):
        lb = LoadBalancer(_cfg())
        status = _tick(lb, T0, {1: 24.0, 2: 16.0, 3: 16.0}, [_battery(reducible_w=0.0)])
        assert status.battery_output.cap_w == 10000
        assert status.battery_output.state == "idle"

    def test_cut_below_minimum_pauses(self):
        lb = LoadBalancer(_cfg())
        status = _tick(
            lb,
            T0,
            {1: 24.0, 2: 16.0, 3: 16.0},
            [_battery(planned_w=2000.0, min_w=2000.0)],
        )
        assert status.battery_output.state == "paused"
        assert status.battery_output.cap_w == 0.0
        assert status.state == "paused"

    def test_shed_above_holds_battery_for_relief(self):
        lb = LoadBalancer(_cfg())
        status = _tick(
            lb,
            T0,
            {1: 24.0, 2: 16.0, 3: 16.0},
            [ShedLoadInput("tank", "water_heater", [1]), _battery()],
        )
        assert status.shed_outputs[0].shed is True
        assert status.battery_output.cap_w == 10000

    def test_battery_cut_holds_shed_below_for_one_tick(self):
        """Battery relief is folded and lower entries hold while it is measured."""
        lb = LoadBalancer(_cfg())
        status = _tick(
            lb,
            T0,
            {1: 24.0, 2: 16.0, 3: 16.0},
            [_battery(reducible_w=500.0), ShedLoadInput("tank", "water_heater", [1])],
        )
        assert status.battery_output.cap_w == pytest.approx(9500.0)
        assert status.shed_outputs[0].shed is False


class TestBatteryRampAndRestore:
    def _warm(self, lb: LoadBalancer, currents, entries_fn, start: datetime, seconds: int):
        status = None
        for s in range(0, seconds + 1, 5):
            status = _tick(lb, start + timedelta(seconds=s), currents, entries_fn())
        return status

    def test_ramp_back_after_hold_off_and_never_above_plan(self):
        lb = LoadBalancer(_cfg(increase_step_a=5))
        status = _tick(lb, T0, {1: 24.0, 2: 16.0, 3: 16.0}, [_battery()])
        cap = status.battery_output.cap_w
        quiet = {1: 8.0, 2: 8.0, 3: 8.0}
        # Inside ramp_up_window_s: hold.
        status = _tick(lb, T0 + timedelta(seconds=30), quiet, [_battery(applied_cap_w=cap)])
        assert status.battery_output.cap_w == cap
        caps = [cap]
        for s in range(35, 200, 5):
            status = _tick(
                lb, T0 + timedelta(seconds=s), quiet, [_battery(applied_cap_w=caps[-1])]
            )
            caps.append(status.battery_output.cap_w)
        assert caps[-1] == 10000
        assert all(b >= a for a, b in zip(caps, caps[1:], strict=False))
        assert max(caps) <= 10000
        assert status.battery_output.state == "idle"

    def test_paused_battery_blocks_restore_of_shed_above(self):
        lb = LoadBalancer(_cfg(resume_delay_s=0))
        over = {1: 30.0, 2: 16.0, 3: 16.0}

        def entries(cap):
            return [
                ShedLoadInput("tank", "water_heater", [1]),
                _battery(planned_w=2000.0, applied_cap_w=cap, min_w=2000.0),
            ]

        # Tick 1: shed gives way, battery holds for relief.
        status = _tick(lb, T0, over, entries(2000.0))
        assert status.shed_outputs[0].shed is True
        # Tick 2: still over (shed relief insufficient): battery pauses.
        status = _tick(lb, T0 + timedelta(seconds=15), over, entries(2000.0))
        assert status.battery_output.state == "paused"
        # Load drops: shed load may not restore while the battery is paused.
        quiet = {1: 15.0, 2: 15.0, 3: 15.0}
        status = _tick(lb, T0 + timedelta(seconds=10), quiet, entries(0.0))
        assert status.battery_output.state == "paused"
        assert status.shed_outputs[0].shed is True

    def test_paused_battery_resumes_after_confirm(self):
        lb = LoadBalancer(_cfg(ramp_up_window_s=0))
        status = _tick(
            lb, T0, {1: 24.0, 2: 16.0, 3: 16.0}, [_battery(planned_w=2000.0, min_w=2000.0)]
        )
        assert status.battery_output.state == "paused"
        quiet = {1: 5.0, 2: 5.0, 3: 5.0}
        status = _tick(
            lb,
            T0 + timedelta(seconds=5),
            quiet,
            [_battery(planned_w=2000.0, applied_cap_w=0.0, min_w=2000.0)],
        )
        assert status.battery_output.state == "paused"
        status = _tick(
            lb,
            T0 + timedelta(seconds=16),
            quiet,
            [_battery(planned_w=2000.0, applied_cap_w=0.0, min_w=2000.0)],
        )
        assert status.battery_output.state == "idle"
        assert status.battery_output.cap_w == 2000.0


class TestBatteryStale:
    def test_stale_phase_forces_minimum_charge(self):
        """Same ladder as the EV: the cap drops to the profile minimum at once,
        whatever the (untrusted) stale reading says."""
        lb = LoadBalancer(_cfg())
        stale_at = {1: T0 - timedelta(seconds=120), 2: T0, 3: T0}
        status = lb.tick(
            T0, {1: 30.0, 2: 16.0, 3: 16.0}, stale_at, [_battery(applied_cap_w=6000.0)]
        )
        assert status.battery_output.cap_w == 480.0
        assert status.battery_output.state == "throttling"
        assert "stale" in status.battery_output.reason
        status = lb.tick(
            T0, {1: 5.0, 2: 5.0, 3: 5.0}, stale_at, [_battery(applied_cap_w=6000.0)]
        )
        assert status.battery_output.cap_w == 480.0


class TestBatteryOrdering:
    def test_battery_below_shed_and_charger(self):
        lb = LoadBalancer(_cfg())
        ev = EVBalancerInput(
            charger_id="ev",
            phases=[1],
            current_setpoint_a=6,
            planner_target_a=6,
            min_current_a=6,
            max_current_a=16,
        )
        status = _tick(lb, T0, {1: 24.0, 2: 16.0, 3: 16.0}, [ev, _battery()])
        # Charger at its floor cannot absorb: battery cuts the deficit.
        assert status.battery_output.cap_w == pytest.approx(10000 - 4 * V * 3)

    def test_no_battery_entry_no_output(self):
        lb = LoadBalancer(_cfg())
        status = _tick(lb, T0, {1: 10.0, 2: 10.0, 3: 10.0}, [])
        assert status.battery_output is None
