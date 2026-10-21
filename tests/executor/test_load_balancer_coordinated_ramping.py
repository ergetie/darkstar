"""load-balancer-coordinated-ramping: ledger, shared room gate, restore power,
fresh-sample rule, battery cut/resume/stale, pacing, trace and a full
simulation. Pure balancer tests (no HA, no engine)."""

import logging
from datetime import datetime, timedelta

import pytest

from executor.config import LoadBalancingConfig
from executor.load_balancer import (
    BALANCER_TRACE_TICKS,
    BATTERY_FLAP_KEY,
    BalancerTrace,
    BatteryBalancerInput,
    EVBalancerInput,
    LoadBalancer,
    PendingLedger,
    Relief,
    ShedLoadInput,
    relief_needed,
)

T0 = datetime(2026, 10, 21, 12, 0, 0)
TICK_S = 5
V = 230.0
STEP_W = 3 * V  # one ampere on each of the three battery phases


def make_lb(**overrides) -> LoadBalancer:
    """20 A fuse, 90 % target (18 A), no averaging window: the room gate is
    exercised without warm-up ticks."""
    cfg = LoadBalancingConfig(
        enabled=True,
        main_fuse_a=20,
        resume_delay_s=120,
        target_margin_percent=90,
        pause_debounce_s=0,
        ramp_up_window_s=0,
        increase_step_a=1,
        sensor_stale_after_s=30,
        nominal_voltage_v=V,
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return LoadBalancer(cfg)


def fresh(at: datetime, *phases: int) -> dict[int, datetime]:
    return dict.fromkeys(phases or (1, 2, 3), at)


def grid(l1: float, l2: float | None = None, l3: float | None = None) -> dict[int, float]:
    return {1: l1, 2: l1 if l2 is None else l2, 3: l1 if l3 is None else l3}


def battery(planned_w=6000.0, applied_cap_w=None, min_w=480.0, reducible_w=None, **kw):
    cap = planned_w if applied_cap_w is None else applied_cap_w
    return BatteryBalancerInput(
        planned_w=planned_w,
        applied_cap_w=cap,
        reducible_w=cap if reducible_w is None else reducible_w,
        active=True,
        min_w=min_w,
        step_w=100.0,
        **kw,
    )


def ev(setpoint, target=16, **kw) -> EVBalancerInput:
    return EVBalancerInput(
        "goe", [1, 2, 3], setpoint, target, min_current_a=6, max_current_a=16, **kw
    )


# --- 1.2 Pending ledger -----------------------------------------------------


class TestPendingLedger:
    def test_grant_counts_per_phase_and_sums_entries(self):
        ledger = PendingLedger()
        ledger.grant("a", {1: 2.0, 2: 2.0}, 8.0, 0.5, T0)
        ledger.grant("b", {1: 3.0}, 3000.0, 100.0, T0)
        assert ledger.pending_a(1) == 5.0
        assert ledger.pending_a(2) == 2.0
        assert ledger.pending_a(3) == 0.0
        assert ledger.pending_a(1, exclude="a") == 3.0

    def test_second_grant_of_same_entry_accumulates(self):
        ledger = PendingLedger()
        ledger.grant("a", {1: 1.0}, 7.0, 0.5, T0)
        ledger.grant("a", {1: 1.0}, 8.0, 0.5, T0 + timedelta(seconds=30))
        assert ledger.pending_a(1) == 2.0
        # Settles against the latest granted value only.
        ledger.expire(T0 + timedelta(seconds=31), 60, {"a": 8.0})
        assert ledger.pending_a(1) == 0.0

    def test_settled_measurement_expires_item(self):
        ledger = PendingLedger()
        ledger.grant("a", {1: 1.0}, 8.0, 0.5, T0)
        ledger.expire(T0 + timedelta(seconds=5), 60, {"a": 7.0})
        assert ledger.pending_a(1) == 1.0
        ledger.expire(T0 + timedelta(seconds=10), 60, {"a": 7.6})
        assert ledger.pending_a(1) == 0.0

    def test_timeout_expires_unmeasured_item(self):
        ledger = PendingLedger()
        ledger.grant("a", {1: 1.0}, 8.0, 0.5, T0)
        ledger.expire(T0 + timedelta(seconds=59), 60, {"a": None})
        assert ledger.pending_a(1) == 1.0
        ledger.expire(T0 + timedelta(seconds=60), 60, {"a": None})
        assert ledger.pending_a(1) == 0.0

    def test_clear_removes_item(self):
        ledger = PendingLedger()
        ledger.grant("a", {1: 1.0}, 8.0, 0.5, T0)
        ledger.clear("a")
        assert ledger.pending_a(1) == 0.0


class TestReliefTrigger:
    def test_default_trigger_is_instant_threshold(self):
        assert relief_needed(20.0, 20.0, 125.0) == Relief(0.0, False)
        assert relief_needed(23.0, 20.0, 125.0) == Relief(3.0, False)
        assert relief_needed(26.0, 20.0, 125.0) == Relief(6.0, True)

    def test_swapped_trigger_changes_only_when_a_reduction_starts(self):
        """A trigger that tolerates a 3 A overload: the same ladder reduces
        only once the trigger asks for relief."""

        def tolerant(momentary: float, fuse: float, severe: float) -> Relief:
            return relief_needed(momentary - 3.0, fuse, severe)

        lb = make_lb()
        lb._relief_trigger = tolerant
        out = lb.tick(T0, grid(22.0), fresh(T0), [ev(16)]).ev_outputs[0]
        assert out.target_a == 16  # 22 A is within the tolerated 3 A
        t1 = T0 + timedelta(seconds=TICK_S)
        out = lb.tick(t1, grid(26.0), fresh(t1), [ev(16)]).ev_outputs[0]
        assert out.target_a == 13  # 3 A of relief, same ladder


# --- 7.1 Plan step-up ramps (root cause 1) ----------------------------------


class TestPlanStepUpRamps:
    def test_plan_rise_from_3_to_6_kw_is_one_step_not_a_jump(self):
        lb = make_lb()
        status = lb.tick(
            T0, grid(5.0), fresh(T0), [battery(planned_w=6000.0, applied_cap_w=3000.0)]
        )
        out = status.battery_output
        assert out.cap_w == pytest.approx(3000.0 + STEP_W)
        assert out.state == "throttling"
        assert "ramping" in out.reason

    def test_plan_decrease_is_immediate(self):
        lb = make_lb()
        out = lb.tick(
            T0, grid(5.0), fresh(T0), [battery(planned_w=2000.0, applied_cap_w=3000.0)]
        ).battery_output
        assert out.cap_w == 2000.0
        assert out.state == "idle"

    def test_next_step_waits_for_pacing_when_unmeasured(self):
        lb = make_lb(max_step_interval_s=30)
        out = lb.tick(T0, grid(5.0), fresh(T0), [battery(6000.0, 3000.0)]).battery_output
        cap = out.cap_w
        t1 = T0 + timedelta(seconds=10)
        held = lb.tick(t1, grid(5.0), fresh(t1), [battery(6000.0, cap)]).battery_output
        assert held.cap_w == cap
        assert "settling" in held.reason
        t2 = T0 + timedelta(seconds=30)
        stepped = lb.tick(t2, grid(5.0), fresh(t2), [battery(6000.0, cap)]).battery_output
        assert stepped.cap_w == pytest.approx(cap + STEP_W)

    def test_fast_actuator_next_step_as_soon_as_settled(self):
        lb = make_lb(max_step_interval_s=30)
        cap = lb.tick(T0, grid(5.0), fresh(T0), [battery(6000.0, 3000.0)]).battery_output.cap_w
        t1 = T0 + timedelta(seconds=TICK_S)
        # The measured charge reached the granted step: settled, no 30 s wait.
        out = lb.tick(
            t1, grid(5.0), fresh(t1), [battery(6000.0, cap, measured_w=cap)]
        ).battery_output
        assert out.cap_w == pytest.approx(cap + STEP_W)

    def test_step_is_gated_by_room(self):
        lb = make_lb()
        # 17.5 A averaged: 18 A target leaves 0.5 A, less than one 1 A step.
        out = lb.tick(T0, grid(17.5), fresh(T0), [battery(6000.0, 3000.0)]).battery_output
        assert out.cap_w == 3000.0


# --- 7.2 EV plus battery ramp together (root causes 2, 3) -------------------


class TestSharedRoomGate:
    def test_only_one_entry_gets_the_step_rearmost_first(self):
        lb = make_lb()
        # 16.5 A averaged leaves 1.5 A of the 18 A target: one 1 A step fits.
        status = lb.tick(T0, grid(16.5), fresh(T0), [ev(10, target=16), battery(6000.0, 3000.0)])
        assert status.battery_output.cap_w == pytest.approx(3000.0 + STEP_W)
        assert status.ev_outputs[0].target_a == 10

    def test_lagging_average_does_not_hide_a_granted_step(self):
        lb = make_lb()
        lb.tick(T0, grid(16.5), fresh(T0), [ev(10, target=16), battery(6000.0, 3000.0)])
        # The average still reads 16.5 A (the step is not measured yet): the
        # granted 1 A is subtracted, so neither entry gets another step.
        t1 = T0 + timedelta(seconds=TICK_S)
        cap = 3000.0 + STEP_W
        status = lb.tick(t1, grid(16.5), fresh(t1), [ev(10, target=16), battery(6000.0, cap)])
        assert status.battery_output.cap_w == cap
        assert status.ev_outputs[0].target_a == 10

    def test_ev_and_battery_never_overshoot_over_a_ramp(self):
        """Both want to ramp against a lagging 60 s average: the summed granted
        amperes never exceed the room under the target."""
        lb = make_lb(ramp_up_window_s=60, max_step_interval_s=30)
        house = 8.0
        setpoint = 6
        cap = 1000.0
        now = T0
        # Warm up the averaging window.
        for i in range(13):
            now = T0 + timedelta(seconds=i * TICK_S)
            lb.tick(now, grid(house), fresh(now), [])
        peak = 0.0
        for _ in range(120):
            now += timedelta(seconds=TICK_S)
            # Cars draw what is commanded within the tick; the grid shows it.
            battery_a = cap / STEP_W
            load = house + setpoint + battery_a
            peak = max(peak, load)
            status = lb.tick(
                now,
                grid(load),
                fresh(now),
                [
                    ev(setpoint, target=16, measured_a=float(setpoint)),
                    battery(6000.0, cap, measured_w=cap),
                ],
            )
            setpoint = status.ev_outputs[0].target_a or setpoint
            cap = status.battery_output.cap_w
        assert peak <= 18.0 + 1.0  # target 18 A, never near the 20 A fuse
        assert peak < 20.0


# --- 7.3 Restore needs the load's power (root cause 4) ----------------------


def shed_overload(lb, heater, at=T0):
    status = lb.tick(at, grid(30.0, 5.0, 5.0), fresh(at), [heater])
    assert status.shed_outputs[0].shed
    return at


class TestRestoreByPower:
    def heater(self, **kw):
        defaults = {"power_w": 3100.0, "power_source": "configured", "min_off_s": 0}
        defaults.update(kw)
        return ShedLoadInput("wh", "water_heater", [1], **defaults)

    def test_heater_waits_for_room_for_its_power(self):
        lb = make_lb()
        heater = self.heater()
        t = shed_overload(lb, heater)
        # 3.1 kW / 230 V = 13.5 A needed; target 18 A. 10 A averaged = 8 A room.
        t += timedelta(seconds=125)
        status = lb.tick(t, grid(10.0, 5.0, 5.0), fresh(t), [heater])
        assert status.shed_outputs[0].shed
        assert "13.5A" in status.shed_outputs[0].reason
        # 4 A averaged: 14 A of room, the heater fits back in.
        t += timedelta(seconds=5)
        status = lb.tick(t, grid(4.0, 5.0, 5.0), fresh(t), [heater])
        assert not status.shed_outputs[0].shed

    def test_unknown_power_needs_the_whole_phase_free(self):
        lb = make_lb()
        heater = self.heater(power_w=None, power_source="worst_case")
        t = shed_overload(lb, heater)
        t += timedelta(seconds=125)
        status = lb.tick(t, grid(5.0, 5.0, 5.0), fresh(t), [heater])
        out = status.shed_outputs[0]
        assert out.shed
        assert out.power_source == "worst_case"
        assert "power unknown" in out.reason
        t += timedelta(seconds=5)
        status = lb.tick(t, grid(0.0, 5.0, 5.0), fresh(t), [heater])
        assert not status.shed_outputs[0].shed

    def test_restore_waits_for_minimum_off_time(self):
        lb = make_lb()
        heater = self.heater(min_off_s=300)
        t = shed_overload(lb, heater)
        t += timedelta(seconds=130)  # resume_delay_s passed, min off not
        assert lb.tick(t, grid(1.0), fresh(t), [heater]).shed_outputs[0].shed
        t += timedelta(seconds=171)
        assert not lb.tick(t, grid(1.0), fresh(t), [heater]).shed_outputs[0].shed

    def test_restore_is_counted_in_the_ledger_for_entries_above(self):
        lb = make_lb()
        heater = self.heater()
        t = shed_overload(lb, heater)
        t += timedelta(seconds=125)
        lb.tick(t, grid(1.0), fresh(t), [heater])
        assert lb._ledger.pending_a(1) == pytest.approx(3100.0 / V)


# --- 7.4 Shed waits for the charger debounce (root cause 5) -----------------


class TestShedRespectsEntriesAbove:
    def test_shed_waits_for_charger_pause_debounce(self):
        lb = make_lb(pause_debounce_s=5)
        charger = EVBalancerInput("goe", [1], 6, 16, min_current_a=6, max_current_a=16)
        heater = ShedLoadInput("wh", "water_heater", [1], power_w=3000.0, power_source="configured")
        entries = [charger, heater]
        status = lb.tick(T0, grid(22.0, 5.0, 5.0), fresh(T0), entries)
        assert status.ev_outputs[0].target_a == 6
        assert not status.shed_outputs[0].shed
        t1 = T0 + timedelta(seconds=3)
        status = lb.tick(t1, grid(22.0, 5.0, 5.0), fresh(t1), entries)
        assert not status.shed_outputs[0].shed
        t2 = T0 + timedelta(seconds=6)
        status = lb.tick(t2, grid(22.0, 5.0, 5.0), fresh(t2), entries)
        assert status.ev_outputs[0].state == "paused"

    def test_severe_overload_does_not_wait_for_debounce(self):
        lb = make_lb(pause_debounce_s=30)
        charger = EVBalancerInput("goe", [1], 6, 16, min_current_a=6, max_current_a=16)
        heater = ShedLoadInput("wh", "water_heater", [1], power_w=3000.0, power_source="configured")
        status = lb.tick(T0, grid(32.0, 5.0, 5.0), fresh(T0), [charger, heater])
        assert status.ev_outputs[0].state == "paused"
        # The severe pause bypasses debounce, but a second actuator waits
        # for a fresh sample and response before another cut.
        assert not status.shed_outputs[0].shed


# --- 7.5 Battery cut with lagging measured charge (root cause 6) ------------


class TestBatteryCutIndependentOfMeasuredCharge:
    def test_cut_with_measured_charge_below_the_cap(self):
        lb = make_lb()
        # Cap 6 kW, the inverter is still ramping: measured charge 1 kW.
        out = lb.tick(
            T0,
            grid(24.0, 5.0, 5.0),
            fresh(T0),
            [battery(6000.0, 6000.0, reducible_w=6000.0, measured_w=1000.0)],
        ).battery_output
        assert out.cap_w == pytest.approx(6000.0 - 4 * STEP_W)
        assert out.urgent

    def test_lagging_measurement_is_not_credited_as_relief(self):
        """The ordered cut holds lower entries until its response is measured."""
        lb = make_lb()
        heater = ShedLoadInput("wh", "water_heater", [1], power_w=2000.0, power_source="configured")
        status = lb.tick(
            T0,
            grid(24.0, 5.0, 5.0),
            fresh(T0),
            [battery(6000.0, 6000.0, measured_w=1000.0), heater],
        )
        assert status.battery_output.cap_w < 6000.0
        assert not status.shed_outputs[0].shed
        assert lb._pool[1] < 0  # no fictional measured relief

    def test_measured_voltage_converts_watts_to_amperes(self):
        lb = make_lb()
        volts = {1: 236.0, 2: 236.0, 3: 236.0}
        out = lb.tick(
            T0,
            grid(24.0, 5.0, 5.0),
            fresh(T0),
            [battery(6000.0, 6000.0)],
            phase_voltage_v=volts,
        ).battery_output
        assert out.cap_w == pytest.approx(6000.0 - 4 * 3 * 236.0)

    def test_nominal_voltage_is_the_fallback(self):
        lb = make_lb()
        out = lb.tick(
            T0, grid(24.0, 5.0, 5.0), fresh(T0), [battery(6000.0, 6000.0)], phase_voltage_v={}
        ).battery_output
        assert out.cap_w == pytest.approx(6000.0 - 4 * 3 * V)


# --- 7.6 No double cut on the same sample (root cause 7) --------------------


class TestFreshSampleRule:
    def test_same_sample_is_not_cut_twice(self):
        lb = make_lb()
        first = lb.tick(T0, grid(24.0, 5.0, 5.0), fresh(T0), [ev(16)]).ev_outputs[0]
        assert first.target_a == 12
        # Next tick, same L1 sample (timestamp unchanged), setpoint applied.
        t1 = T0 + timedelta(seconds=1)
        second = lb.tick(t1, grid(24.0, 5.0, 5.0), fresh(T0), [ev(12)]).ev_outputs[0]
        assert second.target_a == 12
        assert "waiting for relief" in second.reason

    def test_cut_not_yet_reflected_waits_for_response(self):
        lb = make_lb()
        cap = lb.tick(
            T0, grid(24.0, 5.0, 5.0), fresh(T0), [battery(6000.0, 6000.0)]
        ).battery_output.cap_w
        t1 = T0 + timedelta(seconds=5)  # a new sample, still showing the overload
        held = lb.tick(
            t1, grid(24.0, 5.0, 5.0), fresh(t1), [battery(6000.0, cap, measured_w=6000.0)]
        ).battery_output
        assert held.cap_w == cap

    def test_overload_after_response_timeout_cuts_again(self):
        lb = make_lb()
        cap = lb.tick(
            T0, grid(24.0, 5.0, 5.0), fresh(T0), [battery(6000.0, 6000.0)]
        ).battery_output.cap_w
        # Samples arrive every 5 s: response timeout is two intervals (10 s).
        for sec in (5,):
            t = T0 + timedelta(seconds=sec)
            lb.tick(t, grid(24.0, 5.0, 5.0), fresh(t), [battery(6000.0, cap)])
        t = T0 + timedelta(seconds=11)
        again = lb.tick(t, grid(24.0, 5.0, 5.0), fresh(t), [battery(6000.0, cap)]).battery_output
        assert again.cap_w < cap

    def test_response_timeout_is_capped_at_15_seconds(self):
        lb = make_lb()
        # A slow sensor: one sample every 30 s.
        for sec in (0, 30):
            t = T0 + timedelta(seconds=sec)
            lb.tick(t, grid(5.0), fresh(t), [])
        assert lb._response_timeout_s(1) == 15.0

    def test_response_timeout_is_two_detected_intervals(self):
        lb = make_lb()
        for sec in (0, 3, 6, 9):
            t = T0 + timedelta(seconds=sec)
            lb.tick(t, grid(5.0), fresh(t), [])
        assert lb._response_timeout_s(1) == pytest.approx(6.0)

    def test_urgent_overload_still_waits_for_prior_response(self):
        lb = make_lb(pause_debounce_s=5)
        charger = EVBalancerInput("goe", [1], 8, 16, min_current_a=6, max_current_a=16)
        lb.tick(T0, grid(22.0, 5.0, 5.0), fresh(T0), [charger])
        t1 = T0 + timedelta(seconds=5)
        out = lb.tick(
            t1,
            grid(30.0, 5.0, 5.0),
            fresh(t1),
            [EVBalancerInput("goe", [1], 6, 16, min_current_a=6, max_current_a=16)],
        ).ev_outputs[0]
        assert out.target_a == 6
        assert out.state == "throttling"


# --- 7.7 Battery flap back-off and resume amount (root cause 8) -------------


class TestBatteryResume:
    QUIET = grid(5.0)

    def _pause(self, lb, at):
        out = lb.tick(
            at, grid(40.0, 5.0, 5.0), fresh(at), [battery(6000.0, 6000.0, reducible_w=6000.0)]
        ).battery_output
        assert out.state == "paused"

    def _resume(self, lb, start, seconds):
        t = start
        for _ in range(seconds // TICK_S + 2):
            t += timedelta(seconds=TICK_S)
            out = lb.tick(
                t, self.QUIET, fresh(t), [battery(6000.0, 0.0, min_w=2000.0)]
            ).battery_output
            if out.state != "paused":
                return t, out
        return t, out

    def test_resumes_at_profile_minimum_not_full_headroom(self):
        lb = make_lb()
        self._pause(lb, T0)
        _t, out = self._resume(lb, T0, 40)
        assert out.state == "throttling"
        assert out.cap_w == 2000.0  # min_w, with ~12 A of headroom available

    def test_flapping_lengthens_the_confirm_time(self):
        lb = make_lb()
        self._pause(lb, T0)
        assert lb.refit_confirm_s(BATTERY_FLAP_KEY) == 10
        t, _ = self._resume(lb, T0, 40)
        self._pause(lb, t + timedelta(seconds=5))
        assert lb.refit_confirm_s(BATTERY_FLAP_KEY) == 30
        t, _ = self._resume(lb, t + timedelta(seconds=5), 60)
        self._pause(lb, t + timedelta(seconds=5))
        assert lb.refit_confirm_s(BATTERY_FLAP_KEY) == 120


# --- 7.8 Battery stale fail-safe (root cause 9) -----------------------------


class TestBatteryStaleFailSafe:
    def test_min_charge_then_pause_then_recover_through_confirm(self):
        lb = make_lb()
        stale = {1: T0 - timedelta(seconds=120), 2: T0, 3: T0}
        out = lb.tick(T0, grid(5.0), stale, [battery(6000.0, 6000.0, min_w=480.0)]).battery_output
        assert out.cap_w == 480.0
        assert out.state == "throttling"

        t1 = T0 + timedelta(seconds=125)  # past resume_delay_s since first stale
        stale1 = {1: T0 - timedelta(seconds=120), 2: t1, 3: t1}
        out = lb.tick(t1, grid(5.0), stale1, [battery(6000.0, 480.0, min_w=480.0)]).battery_output
        assert out.state == "paused"
        assert out.cap_w == 0.0

        # The sensor is back: recovery goes through the resume confirm window.
        t2 = t1 + timedelta(seconds=5)
        out = lb.tick(t2, grid(5.0), fresh(t2), [battery(6000.0, 0.0, min_w=480.0)]).battery_output
        assert out.state == "paused"
        t3 = t2 + timedelta(seconds=15)
        out = lb.tick(t3, grid(5.0), fresh(t3), [battery(6000.0, 0.0, min_w=480.0)]).battery_output
        assert out.state != "paused"


# --- 7.9 Pacing for EV current ---------------------------------------------


class TestEvPacing:
    def test_fast_charger_ramps_as_soon_as_step_is_measured(self):
        lb = make_lb()
        out = lb.tick(T0, grid(5.0), fresh(T0), [ev(8, target=16, measured_a=8.0)]).ev_outputs[0]
        assert out.target_a == 9
        t1 = T0 + timedelta(seconds=TICK_S)
        out = lb.tick(t1, grid(5.0), fresh(t1), [ev(9, target=16, measured_a=9.0)]).ev_outputs[0]
        assert out.target_a == 10

    def test_unmeasured_charger_waits_max_step_interval(self):
        lb = make_lb(max_step_interval_s=30)
        out = lb.tick(T0, grid(5.0), fresh(T0), [ev(8, target=16)]).ev_outputs[0]
        assert out.target_a == 9
        t1 = T0 + timedelta(seconds=10)
        out = lb.tick(t1, grid(5.0), fresh(t1), [ev(9, target=16)]).ev_outputs[0]
        assert out.target_a == 9
        assert "settling" in out.reason
        t2 = T0 + timedelta(seconds=30)
        out = lb.tick(t2, grid(5.0), fresh(t2), [ev(9, target=16)]).ev_outputs[0]
        assert out.target_a == 10

    def test_reductions_are_never_paced(self):
        lb = make_lb(max_step_interval_s=30)
        lb.tick(T0, grid(5.0), fresh(T0), [ev(8, target=16)])
        t1 = T0 + timedelta(seconds=1)
        out = lb.tick(t1, grid(23.0, 5.0, 5.0), fresh(t1), [ev(9, target=16)]).ev_outputs[0]
        assert out.target_a == 6  # cut at once, 1 s after the last increase


# --- 7.12 Trace and log -----------------------------------------------------


class TestTrace:
    def test_ring_buffer_keeps_newest_ticks(self):
        trace = BalancerTrace(size=3)
        for i in range(5):
            trace.add({"i": i})
        assert [t["i"] for t in trace.snapshot()] == [2, 3, 4]
        assert len(trace) == 3

    def test_default_size_is_600_ticks(self):
        assert BALANCER_TRACE_TICKS == 600
        lb = make_lb()
        for i in range(BALANCER_TRACE_TICKS + 20):
            t = T0 + timedelta(seconds=i)
            lb.tick(t, grid(5.0), fresh(t), [])
        assert len(lb.trace) == BALANCER_TRACE_TICKS

    def test_tick_snapshot_contents(self):
        lb = make_lb()
        heater = ShedLoadInput("wh", "water_heater", [1])
        lb.tick(
            T0,
            grid(24.0, 5.0, 5.0),
            fresh(T0),
            [ev(16, measured_a=16.0), battery(6000.0, 6000.0, measured_w=500.0), heater],
        )
        lb.trace.note_written("battery", 5000.0)
        snap = lb.trace.snapshot()[-1]
        assert snap["raw_a"]["1"] == 24.0
        assert snap["age_s"]["1"] == 0.0
        assert snap["relief_a"]["1"] == 4.0
        assert {"charger:goe", "battery", "shed:wh"} <= set(snap["entries"])
        assert snap["entries"]["battery"]["measured_w"] == 500.0
        assert snap["entries"]["charger:goe"]["plan_a"] == 16
        assert "ledger" in snap and "shed" in snap
        assert snap["written"] == {"battery": 5000.0}

    def test_decision_change_is_logged_once(self, caplog):
        lb = make_lb()
        caplog.set_level(logging.INFO, logger="executor.load_balancer")
        lb.tick(T0, grid(24.0, 5.0, 5.0), fresh(T0), [battery(6000.0, 6000.0)])
        changes = [r for r in caplog.records if "Load balancer battery" in r.getMessage()]
        assert len(changes) == 1
        assert "throttling" in changes[0].getMessage()
        # Same decision, new fresh sample (held, awaiting response): no new line.
        cap = lb.trace.snapshot()[-1]["entries"]["battery"]["cap_w"]
        t1 = T0 + timedelta(seconds=TICK_S)
        lb.tick(t1, grid(24.0, 5.0, 5.0), fresh(t1), [battery(6000.0, cap)])
        changes = [r for r in caplog.records if "Load balancer battery" in r.getMessage()]
        assert len(changes) == 1

    def test_pause_transition_is_logged(self, caplog):
        lb = make_lb()
        caplog.set_level(logging.INFO, logger="executor.load_balancer")
        lb.tick(T0, grid(24.0, 5.0, 5.0), fresh(T0), [battery(6000.0, 6000.0)])
        t1 = T0 + timedelta(seconds=20)
        lb.tick(t1, grid(40.0, 5.0, 5.0), fresh(t1), [battery(6000.0, 4000.0)])
        messages = [
            r.getMessage() for r in caplog.records if "Load balancer battery" in r.getMessage()
        ]
        assert len(messages) == 2
        assert "paused" in messages[1]


# --- 7.13 Simulation: battery + EV + 3.1 kW heater, ten minutes -------------


class TestSimulation:
    @pytest.mark.parametrize("appliance_spike", [False, True])
    def test_no_oscillation_and_no_sustained_overload(self, appliance_spike):
        """Battery, EV and a 3.1 kW heater under a steady house load with a
        first-order lagging 'real world': the heater is not cycled faster than
        its minimum off time and no phase stays over the fuse for longer than
        a sensor interval."""
        lb = make_lb(
            ramp_up_window_s=60, max_step_interval_s=30, pause_debounce_s=5, main_fuse_a=16
        )
        fuse = 16.0
        heater_a = 3100.0 / V
        heater = ShedLoadInput(
            "wh",
            "water_heater",
            [1],
            power_w=3100.0,
            power_source="configured",
            min_off_s=300,
            min_on_s=300,
        )
        # Physically valid startup: the heater is either already shed or is
        # the only load on, below the fuse.
        # Both flexible loads request full plans from the first tick.
        heater_on = appliance_spike
        shed_at: list[datetime] = []
        restore_at: list[datetime] = []
        ev_set: int | None = None
        ev_draw = 0.0
        cap = 0.0
        bat_draw = 0.0
        over_since: datetime | None = None
        worst_over_s = 0.0
        ev_ramped = battery_ramped = False

        for elapsed in range(0, 601, TICK_S):
            now = T0 + timedelta(seconds=elapsed)
            # An appliance provokes one shed. Later the charging plans finish,
            # making room for an actual restore after the 300 s hold.
            house = 4.0 if appliance_spike and 120 <= elapsed < 180 else 0.5
            charging = elapsed < 420
            l1 = house + ev_draw + bat_draw + (heater_a if heater_on else 0.0)
            others = house + ev_draw + bat_draw
            if l1 > fuse:
                over_since = over_since or now
                worst_over_s = max(worst_over_s, (now - over_since).total_seconds() + TICK_S)
            else:
                over_since = None
            heater.current_on = heater_on
            heater.requested_on = True
            status = lb.tick(
                now,
                grid(l1, others, others),
                fresh(now),
                [
                    heater,
                    ev(ev_set, target=16 if charging else None, measured_a=ev_draw),
                    battery(6000.0 if charging else 0.0, cap, measured_w=bat_draw * STEP_W),
                ],
            )
            previous_ev, previous_cap = ev_set, cap
            ev_set = status.ev_outputs[0].target_a
            bat = status.battery_output
            cap = 0.0 if bat.state == "paused" else bat.cap_w
            ev_ramped |= (ev_set or 0) > (previous_ev or 0)
            battery_ramped |= cap > previous_cap
            shed = status.shed_outputs[0].shed
            if heater_on and shed:
                shed_at.append(now)
            if not heater_on and not shed:
                restore_at.append(now)
            heater_on = not shed
            # First-order actuator lag is visible in the next sensor sample.
            ev_draw += ((ev_set or 0) - ev_draw) * 0.6
            bat_draw += (cap / STEP_W - bat_draw) * 0.5

        assert worst_over_s <= TICK_S
        assert ev_ramped and battery_ramped
        assert len(restore_at) == 1
        assert len(shed_at) == int(appliance_spike)
        last_off = shed_at[0] if shed_at else T0
        assert (restore_at[0] - last_off).total_seconds() >= 300


class TestAllIncreasePaths:
    def test_initial_ev_start_uses_averaged_room(self):
        lb = make_lb(ramp_up_window_s=60)
        for sec in range(0, 65, 5):
            t = T0 + timedelta(seconds=sec)
            lb.tick(t, grid(17.0), fresh(t), [])
        t += timedelta(seconds=5)
        out = lb.tick(t, grid(1.0), fresh(t), [ev(None)]).ev_outputs[0]
        assert out.target_a is None

    def test_battery_resume_and_ev_ramp_spend_in_reverse_order(self):
        lb = make_lb(resume_confirm_s=5)
        lb._battery_paused_at = T0
        lb._battery_fit_since = T0
        t = T0 + timedelta(seconds=10)
        # Room fits battery minimum OR one EV step, not both.
        out = lb.tick(t, grid(17.0), fresh(t), [ev(6), battery(6000, 0, min_w=STEP_W)])
        assert out.battery_output.cap_w == STEP_W
        assert out.ev_outputs[0].target_a == 6

    def test_battery_ramp_precedes_higher_listed_shed_restore(self):
        lb = make_lb(resume_delay_s=0)
        heater = ShedLoadInput(
            "heater", "water_heater", [1], power_w=230, power_source="configured"
        )
        lb._shed_at["heater"] = T0
        out = lb.tick(T0, grid(17.0), fresh(T0), [heater, battery(6000, 3000)])
        assert out.battery_output.cap_w == 3000 + STEP_W
        assert out.shed_outputs[0].shed

    def test_unknown_power_does_not_treat_one_amp_as_free(self):
        lb = make_lb(resume_delay_s=0)
        heater = ShedLoadInput("heater", "custom_entity", [1])
        lb._shed_at["heater"] = T0
        assert lb.tick(T0, grid(0.5), fresh(T0), [heater]).shed_outputs[0].shed

    def test_phase_expansion_checks_momentary_room(self):
        lb = make_lb()
        lb.tick(T0, grid(5, 19, 5), fresh(T0), [])
        assert not lb.three_phase_fits([1, 2, 3], [1], 6, 6, T0, "goe")
        assert not lb._ledger.snapshot()

    def test_measured_cut_response_allows_next_cut_before_timeout(self):
        lb = make_lb()
        first = lb.tick(T0, grid(24), fresh(T0), [battery(6000, 6000, measured_w=6000)])
        cap = first.battery_output.cap_w
        t = T0 + timedelta(seconds=5)
        second = lb.tick(t, grid(24), fresh(t), [battery(6000, cap, measured_w=cap)])
        assert second.battery_output.cap_w < cap

    def test_severe_duplicate_sample_does_not_cut_again(self):
        lb = make_lb()
        first = lb.tick(T0, grid(30), fresh(T0), [battery(6000, 6000)])
        cap = first.battery_output.cap_w
        t = T0 + timedelta(seconds=5)
        second = lb.tick(t, grid(30), fresh(T0), [battery(6000, cap)])
        assert second.battery_output.cap_w == cap


class TestPlannedSwitches:
    def test_custom_plan_switch_uses_min_times_and_room(self):
        lb = make_lb(resume_delay_s=0)
        load = ShedLoadInput(
            "pump",
            "custom_entity",
            [1],
            power_w=2300,
            power_source="configured",
            min_on_s=300,
            min_off_s=300,
            requested_on=False,
        )
        assert lb.tick(T0, grid(5), fresh(T0), [load]).shed_outputs[0].shed
        load.requested_on = True
        early = T0 + timedelta(seconds=60)
        assert lb.tick(early, grid(5), fresh(early), [load]).shed_outputs[0].shed
        later = T0 + timedelta(seconds=301)
        # Ten amps of power do not fit into eight amps of room.
        assert lb.tick(later, grid(10), fresh(later), [load]).shed_outputs[0].shed
        later += timedelta(seconds=5)
        assert not lb.tick(later, grid(5), fresh(later), [load]).shed_outputs[0].shed
        load.requested_on = False
        off = later + timedelta(seconds=60)
        assert not lb.tick(off, grid(15), fresh(off), [load]).shed_outputs[0].shed
        off = later + timedelta(seconds=301)
        assert lb.tick(off, grid(15), fresh(off), [load]).shed_outputs[0].shed

    def test_planned_off_lower_entry_does_not_block_higher_restore(self):
        lb = make_lb(resume_delay_s=0)
        higher = ShedLoadInput(
            "higher",
            "custom_entity",
            [1],
            power_w=230,
            power_source="configured",
            requested_on=True,
        )
        lower = ShedLoadInput(
            "lower",
            "custom_entity",
            [1],
            power_w=230,
            power_source="configured",
            requested_on=False,
        )
        lb._shed_at = {"higher": T0, "lower": T0}
        later = T0 + timedelta(seconds=301)
        status = lb.tick(later, grid(0), fresh(later), [higher, lower])
        assert not status.shed_outputs[0].shed
        assert status.shed_outputs[1].shed
        assert lb._ledger.pending_a(1) == pytest.approx(1)

    def test_overload_bypasses_custom_min_on(self):
        lb = make_lb(resume_delay_s=0)
        load = ShedLoadInput(
            "pump",
            "custom_entity",
            [1],
            power_w=2300,
            power_source="configured",
            min_on_s=300,
            requested_on=True,
        )
        lb.tick(T0, grid(5), fresh(T0), [load])
        t = T0 + timedelta(seconds=5)
        assert not lb.tick(t, grid(5), fresh(t), [load]).shed_outputs[0].shed
        t += timedelta(seconds=5)
        assert lb.tick(t, grid(25), fresh(t), [load]).shed_outputs[0].shed

    def test_phase_return_spends_room_before_other_entries(self):
        lb = make_lb()
        charger = EVBalancerInput(
            "goe", [1], 6, 16, 6, 16, measured_a=6, return_to_phases=[1, 2, 3]
        )
        status = lb.tick(T0, grid(6, 5, 5), fresh(T0), [battery(6000, 3000), charger])
        assert status.ev_outputs[0].return_3p_requested
        assert status.ev_outputs[0].target_a == 6
        assert lb._ledger.pending_a(2) >= 6
        # The old one-phase measurement cannot settle newly added phases.
        t = T0 + timedelta(seconds=5)
        lb.tick(t, grid(6, 5, 5), fresh(t), [charger])
        assert lb._ledger.pending_a(2) >= 6

    def test_battery_plan_decrease_clears_pending_increase(self):
        lb = make_lb()
        lb.tick(T0, grid(5), fresh(T0), [battery(6000, 3000)])
        assert lb._ledger.pending_a(1) > 0
        t = T0 + timedelta(seconds=5)
        out = lb.tick(t, grid(5), fresh(t), [battery(2000, 3690)])
        assert out.battery_output.cap_w == 2000
        assert lb._ledger.pending_a(1) == 0

    def test_low_pre_cut_measurement_is_not_an_actuator_response(self):
        lb = make_lb()
        first = lb.tick(T0, grid(24), fresh(T0), [battery(6000, 6000, measured_w=1000)])
        cap = first.battery_output.cap_w
        t = T0 + timedelta(seconds=5)
        second = lb.tick(t, grid(24), fresh(t), [battery(6000, cap, measured_w=1000)])
        assert second.battery_output.cap_w == cap

    def test_summary_returns_idle_when_last_ramp_step_reaches_plan(self):
        lb = make_lb()
        out = lb.tick(T0, grid(5), fresh(T0), [battery(3000 + STEP_W, 3000)])
        assert out.battery_output.cap_w == 3000 + STEP_W
        assert out.battery_output.state == "idle"
        assert out.state == "idle"
