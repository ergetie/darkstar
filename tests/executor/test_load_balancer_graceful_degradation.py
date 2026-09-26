"""load-balancer-graceful-degradation: target margin, averaged ramp-up, pause
debounce, severe overload, 1-phase relief, and a replay of the prod
2026-09-25 afternoon phase history."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from executor.config import EVChargerDeviceConfig, LoadBalancingConfig
from executor.engine import PHASE_SWITCH_SETTLE_S, EVChargerState, ExecutorEngine
from executor.ev_surplus import PhaseModeController
from executor.load_balancer import EVBalancerInput, LoadBalancer, ShedLoadInput

BASE = datetime(2026, 9, 25, 16, 0, 0)
TICK_S = 5
FIXTURE = Path(__file__).parent / "fixtures" / "prod_2026_09_25_phase_history.json"


def make_lb(**overrides) -> LoadBalancer:
    """16 A fuse with the shipped graceful-degradation defaults."""
    cfg = LoadBalancingConfig(enabled=True, main_fuse_a=16)
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return LoadBalancer(cfg)


def fresh(at: datetime) -> dict[int, datetime]:
    return {1: at, 2: at, 3: at}


def ev(setpoint, target=10, phases=(1, 2, 3), relief=False, line=1, draw=None) -> EVBalancerInput:
    return EVBalancerInput(
        "goe",
        list(phases),
        setpoint,
        target,
        min_current_a=6,
        max_current_a=16,
        effective_draw_a=draw,
        phase_1_line=line,
        relief_available=relief,
    )


def warm_up(lb: LoadBalancer, grid: dict[int, float], entry=None, seconds=60) -> datetime:
    """Feed identical fresh readings for a full averaging window."""
    now = BASE
    for i in range(seconds // TICK_S + 1):
        now = BASE + timedelta(seconds=i * TICK_S)
        lb.tick(now, grid, fresh(now), [entry] if entry else [])
    return now


# --- 2.3 Averaged sensing ---------------------------------------------------


class TestAveragedSensing:
    def test_spike_moves_average_only_by_its_share(self):
        lb = make_lb()
        now = warm_up(lb, {1: 9.0, 2: 9.0, 3: 9.0})
        now += timedelta(seconds=TICK_S)
        lb.tick(now, {1: 9.0, 2: 15.0, 3: 9.0}, fresh(now), [])
        avg = lb.averaged_current_a(2, now)
        assert avg is not None
        # 13 samples in the 60 s window, one of them the 15 A spike
        assert avg == pytest.approx(9.0 + 6.0 / 13, abs=0.01)

    def test_increases_blocked_after_startup_until_window_fills(self):
        lb = make_lb()
        grid = {1: 2.0, 2: 2.0, 3: 2.0}
        setpoint = 6
        for i in range(12):  # 0..55 s: window not yet full
            now = BASE + timedelta(seconds=i * TICK_S)
            out = lb.tick(now, grid, fresh(now), [ev(setpoint)]).ev_outputs[0]
            assert out.target_a == 6
        now = BASE + timedelta(seconds=60)
        out = lb.tick(now, grid, fresh(now), [ev(setpoint)]).ev_outputs[0]
        assert out.target_a == 7

    def test_stale_episode_resets_the_window(self):
        lb = make_lb()
        grid = {1: 2.0, 2: 2.0, 3: 2.0}
        now = warm_up(lb, grid)
        assert lb.averaged_current_a(1, now) is not None
        # L1 stops reporting for longer than sensor_stale_after_s
        stale_at = now
        now += timedelta(seconds=35)
        lb.tick(now, grid, {1: stale_at, 2: now, 3: now}, [])
        assert lb.averaged_current_a(1, now) is None
        # Fresh again: increases stay blocked until a full window has passed
        recovered = now + timedelta(seconds=TICK_S)
        out = lb.tick(recovered, grid, fresh(recovered), [ev(6)]).ev_outputs[0]
        assert out.target_a == 6
        for i in range(1, 13):
            t = recovered + timedelta(seconds=i * TICK_S)
            out = lb.tick(t, grid, fresh(t), [ev(6)]).ev_outputs[0]
        assert out.target_a == 7

    def test_own_ramp_is_not_hidden_by_averaging_lag(self):
        """The chargers count at their latest draw, so an averaged ramp cannot
        overshoot the target by the window's lag."""
        lb = make_lb()
        house = 1.0
        setpoint = 6
        now = BASE
        for i in range(200):
            now = BASE + timedelta(seconds=i * TICK_S)
            grid = {1: house + setpoint, 2: house + setpoint, 3: house + setpoint}
            out = lb.tick(now, grid, fresh(now), [ev(setpoint, target=16)]).ev_outputs[0]
            setpoint = out.target_a
            assert house + setpoint <= 16 * 0.85 + 1e-9
        assert setpoint == 12  # 1 A house + 12 A = 13 A <= 13.6 A; 14 A would exceed


# --- 3.3 Margin, debounce and severe pause ----------------------------------


class TestTargetMarginAndPause:
    def test_quiet_night_ramps_to_full_planned_current(self):
        lb = make_lb()
        house = 2.0
        setpoint = 6
        for i in range(120):
            now = BASE + timedelta(seconds=i * TICK_S)
            grid = {p: house + setpoint for p in (1, 2, 3)}
            out = lb.tick(now, grid, fresh(now), [ev(setpoint, target=10)]).ev_outputs[0]
            setpoint = out.target_a
        assert setpoint == 10  # projected 12 A <= 13.6 A

    def test_ramp_stops_at_target_without_reducing(self):
        lb = make_lb()
        grid = {1: 13.0, 2: 8.0, 3: 8.0}  # L1 13 A with the charger at 8 A
        now = warm_up(lb, grid, ev(8))
        now += timedelta(seconds=TICK_S)
        out = lb.tick(now, grid, fresh(now), [ev(8)]).ev_outputs[0]
        assert out.target_a == 8  # 9 A would project 14 A > 13.6 A; no reduction below fuse

    def test_load_hovering_at_95_percent_blocks_increase(self):
        lb = make_lb()
        grid = {1: 15.2, 2: 8.0, 3: 8.0}
        now = warm_up(lb, grid, ev(8))
        now += timedelta(seconds=TICK_S)
        out = lb.tick(now, grid, fresh(now), [ev(8)]).ev_outputs[0]
        assert out.target_a == 8

    def test_one_second_spike_does_not_pause(self):
        lb = make_lb()
        now = warm_up(lb, {1: 10.0, 2: 10.0, 3: 10.0}, ev(6))
        now += timedelta(seconds=1)
        out = lb.tick(now, {1: 10.0, 2: 10.0, 3: 19.0}, fresh(now), [ev(6)]).ev_outputs[0]
        assert out.target_a == 6 and out.state == "throttling"
        now += timedelta(seconds=1)
        out = lb.tick(now, {1: 10.0, 2: 10.0, 3: 11.0}, fresh(now), [ev(6)]).ev_outputs[0]
        assert out.target_a is not None and out.target_a >= 6
        assert out.state != "paused"

    def test_overload_lasting_the_debounce_pauses(self):
        lb = make_lb()
        now = warm_up(lb, {1: 10.0, 2: 10.0, 3: 10.0}, ev(6))
        overloaded = {1: 10.0, 2: 10.0, 3: 19.0}
        now += timedelta(seconds=TICK_S)
        assert lb.tick(now, overloaded, fresh(now), [ev(6)]).ev_outputs[0].target_a == 6
        now += timedelta(seconds=TICK_S)
        out = lb.tick(now, overloaded, fresh(now), [ev(6)]).ev_outputs[0]
        assert out.target_a is None and out.state == "paused"

    def test_zero_debounce_pauses_immediately(self):
        lb = make_lb(pause_debounce_s=0)
        now = BASE
        out = lb.tick(now, {1: 10.0, 2: 10.0, 3: 19.0}, fresh(now), [ev(6)]).ev_outputs[0]
        assert out.state == "paused"

    def test_severe_overload_pauses_in_the_same_tick(self):
        lb = make_lb()
        now = BASE
        # 21 A on a 16 A fuse = 131 % > 125 %
        out = lb.tick(now, {1: 10.0, 2: 10.0, 3: 21.0}, fresh(now), [ev(6, relief=True)])
        assert out.ev_outputs[0].state == "paused"
        assert not out.ev_outputs[0].relief_1p_requested

    def test_decrease_uses_the_momentary_reading(self):
        lb = make_lb()
        now = warm_up(lb, {1: 12.0, 2: 8.0, 3: 8.0}, ev(10))
        now += timedelta(seconds=TICK_S)
        out = lb.tick(now, {1: 19.0, 2: 8.0, 3: 8.0}, fresh(now), [ev(10)]).ev_outputs[0]
        assert out.target_a is not None and out.target_a <= 7

    def test_reduction_above_floor_is_immediate_not_debounced(self):
        lb = make_lb()
        now = BASE
        out = lb.tick(now, {1: 20.0, 2: 8.0, 3: 8.0}, fresh(now), [ev(12)]).ev_outputs[0]
        assert out.target_a == 8

    def test_resume_blocked_while_momentary_reading_exceeds_target(self):
        lb = make_lb()
        now = BASE
        lb.tick(now, {1: 10.0, 2: 10.0, 3: 22.0}, fresh(now), [ev(6)])
        # L3 reads 9 A: 9 + 6 = 15 A > 13.6 A, although headroom to the fuse is 7 A
        t = now
        for _ in range(60):
            t += timedelta(seconds=TICK_S)
            out = lb.tick(t, {1: 1.0, 2: 1.0, 3: 9.0}, fresh(t), [ev(None)]).ev_outputs[0]
            assert out.target_a is None

    def test_shed_restore_waits_for_averaged_margin(self):
        lb = make_lb(resume_delay_s=10)
        wh = ShedLoadInput("wh", "water_heater", [2])
        now = BASE
        lb.tick(now, {1: 5.0, 2: 17.0, 3: 5.0}, fresh(now), [wh])
        t = now
        for _ in range(30):
            t += timedelta(seconds=TICK_S)
            status = lb.tick(t, {1: 5.0, 2: 14.0, 3: 5.0}, fresh(t), [wh])
            assert status.shed_outputs[0].shed  # 14 A > 13.6 A target
        for _ in range(14):
            t += timedelta(seconds=TICK_S)
            status = lb.tick(t, {1: 5.0, 2: 6.0, 3: 5.0}, fresh(t), [wh])
        assert not status.shed_outputs[0].shed


class TestSafetyInvariants:
    """Fuse-protection invariants of the graceful-degradation changes."""

    def test_increase_capped_by_momentary_headroom(self):
        """A low average must never let a raise push this tick's reading past
        the fuse: with 0.5 A momentary headroom no 1 A step is taken."""
        lb = make_lb()
        now = warm_up(lb, {1: 6.0, 2: 6.0, 3: 6.0}, ev(6))
        now += timedelta(seconds=TICK_S)
        out = lb.tick(now, {1: 6.0, 2: 15.5, 3: 6.0}, fresh(now), [ev(6)]).ev_outputs[0]
        assert out.target_a == 6

    def test_increase_step_limited_to_whole_momentary_headroom(self):
        lb = make_lb(increase_step_a=4)
        now = warm_up(lb, {1: 6.0, 2: 6.0, 3: 6.0}, ev(6))
        now += timedelta(seconds=TICK_S)
        # Average leaves room for +4 A, momentary L2 headroom only 2.5 A.
        out = lb.tick(now, {1: 6.0, 2: 13.5, 3: 6.0}, fresh(now), [ev(6)]).ev_outputs[0]
        assert out.target_a == 8

    def test_debounce_hold_never_above_prior_setpoint(self):
        """A setpoint below the floor cannot be 'held' at the floor during an
        overload (that would be a raise) — it pauses instead."""
        lb = make_lb()
        now = BASE
        entry = EVBalancerInput("goe", [1, 2, 3], 5, 10, min_current_a=6, max_current_a=16)
        out = lb.tick(now, {1: 10.0, 2: 10.0, 3: 18.0}, fresh(now), [entry]).ev_outputs[0]
        assert out.target_a is None and out.state == "paused"

    def test_debounce_hold_is_exactly_the_floor(self):
        lb = make_lb()
        now = BASE
        out = lb.tick(now, {1: 10.0, 2: 10.0, 3: 19.0}, fresh(now), [ev(8, draw=7)]).ev_outputs[0]
        assert out.target_a == 6 and out.state == "throttling"

    def test_shed_relief_hold_never_below_floor(self):
        """Holding for unmeasured shed relief uses the measured draw, but never
        commands a sub-floor setpoint."""
        lb = make_lb()
        wh = ShedLoadInput("wh", "water_heater", [3])
        now = BASE
        status = lb.tick(now, {1: 8.0, 2: 8.0, 3: 18.0}, fresh(now), [wh, ev(10, draw=4)])
        assert status.shed_outputs[0].shed
        out = status.ev_outputs[0]
        assert out.target_a is not None and 6 <= out.target_a <= 10

    def test_severe_overload_during_debounce_pauses_at_once(self):
        lb = make_lb(pause_debounce_s=30)
        now = BASE
        out = lb.tick(now, {1: 10.0, 2: 10.0, 3: 18.0}, fresh(now), [ev(6)]).ev_outputs[0]
        assert out.target_a == 6
        now += timedelta(seconds=TICK_S)
        out = lb.tick(now, {1: 10.0, 2: 10.0, 3: 20.5}, fresh(now), [ev(6)]).ev_outputs[0]
        assert out.target_a is None and out.state == "paused"

    def test_debounce_timer_resets_on_recovery(self):
        lb = make_lb(pause_debounce_s=10)
        overloaded = {1: 10.0, 2: 10.0, 3: 18.0}
        t = BASE
        lb.tick(t, overloaded, fresh(t), [ev(6)])
        t += timedelta(seconds=TICK_S)
        lb.tick(t, {1: 10.0, 2: 10.0, 3: 12.0}, fresh(t), [ev(6)])  # headroom >= 0
        t += timedelta(seconds=TICK_S)
        out = lb.tick(t, overloaded, fresh(t), [ev(6)]).ev_outputs[0]
        assert out.target_a == 6 and out.state == "throttling"  # timer restarted

    def test_stale_sensor_forces_floor_then_pauses_after_resume_delay(self):
        lb = make_lb()
        t = BASE
        stale_ts = {1: t, 2: t, 3: t - timedelta(seconds=3600)}
        out = lb.tick(t, {1: 10.0, 2: 10.0, 3: 10.0}, stale_ts, [ev(10)]).ev_outputs[0]
        assert out.target_a == 6 and out.state == "stale_fallback"
        t += timedelta(seconds=lb.config.resume_delay_s)
        stale_ts = {1: t, 2: t, 3: t - timedelta(seconds=3600)}
        out = lb.tick(t, {1: 10.0, 2: 10.0, 3: 10.0}, stale_ts, [ev(6)]).ev_outputs[0]
        assert out.target_a is None and out.state == "paused"


# --- 4.x 1-phase relief -----------------------------------------------------


class TestReliefLadder:
    def _sustain(self, lb, grid, entry, ticks=2):
        now = BASE
        out = None
        for i in range(ticks):
            now = BASE + timedelta(seconds=i * TICK_S)
            out = lb.tick(now, grid, fresh(now), [entry]).ev_outputs[0]
        return out

    def test_l3_overload_requests_1_phase_on_l1(self):
        lb = make_lb()
        # L3 headroom -4 A at the floor, L1 has room
        out = self._sustain(lb, {1: 8.0, 2: 8.0, 3: 20.0}, ev(6, relief=True))
        assert out.relief_1p_requested
        assert out.target_a == 6 and out.state == "throttling"
        assert "L1" in out.reason and "L3" in out.reason

    def test_relief_waits_for_the_debounce(self):
        lb = make_lb()
        out = self._sustain(lb, {1: 8.0, 2: 8.0, 3: 20.0}, ev(6, relief=True), ticks=1)
        assert not out.relief_1p_requested and out.target_a == 6

    def test_overload_on_the_1_phase_line_pauses(self):
        lb = make_lb()
        out = self._sustain(lb, {1: 20.0, 2: 8.0, 3: 8.0}, ev(6, relief=True))
        assert not out.relief_1p_requested
        assert out.state == "paused"

    def test_dwell_not_elapsed_pauses(self):
        lb = make_lb()
        out = self._sustain(lb, {1: 8.0, 2: 8.0, 3: 20.0}, ev(6, relief=False))
        assert not out.relief_1p_requested
        assert out.state == "paused"

    def test_charger_wired_to_l2_is_not_relief_for_l2(self):
        lb = make_lb()
        out = self._sustain(lb, {1: 8.0, 2: 20.0, 3: 8.0}, ev(6, relief=True, line=2))
        assert not out.relief_1p_requested and out.state == "paused"

    def test_charger_without_phase_switching_is_throttle_then_pause(self):
        lb = make_lb()
        first = self._sustain(lb, {1: 8.0, 2: 8.0, 3: 24.0 - 5}, ev(12), ticks=1)
        assert first.target_a == 9  # immediate throttle by the deficit
        lb2 = make_lb()
        out = self._sustain(lb2, {1: 8.0, 2: 8.0, 3: 20.0}, ev(6))
        assert out.state == "paused" and not out.relief_1p_requested

    def test_1_phase_charger_is_never_asked_for_relief(self):
        lb = make_lb()
        out = self._sustain(lb, {1: 20.0, 2: 8.0, 3: 8.0}, ev(6, phases=(1,), relief=True))
        assert out.state == "paused" and not out.relief_1p_requested

    def test_phase_set_expansion_restarts_at_floor(self):
        lb = make_lb()
        now = warm_up(lb, {1: 13.0, 2: 1.0, 3: 1.0}, ev(12, target=16, phases=(1,)))
        now += timedelta(seconds=TICK_S)
        out = lb.tick(now, {1: 13.0, 2: 1.0, 3: 1.0}, fresh(now), [ev(12, target=8)])
        assert out.ev_outputs[0].target_a == 6


class TestPhaseModeControllerRelief:
    def test_relief_overrides_power_threshold(self):
        ctrl = PhaseModeController()
        ctrl.commanded_mode = 3
        decision = ctrl.decide_relief(BASE, 600, True, True, False)
        assert decision.should_switch and decision.commanded_mode == 1

    def test_relief_respects_dwell(self):
        ctrl = PhaseModeController()
        ctrl.on_switch_success(3, BASE)
        decision = ctrl.decide_relief(BASE + timedelta(seconds=200), 600, True, True, False)
        assert not decision.should_switch
        assert not ctrl.relief_available(BASE + timedelta(seconds=200), 600)
        assert ctrl.relief_available(BASE + timedelta(seconds=600), 600)

    def test_relief_refused_when_failed(self):
        ctrl = PhaseModeController()
        ctrl.on_entity_unavailable()
        assert not ctrl.decide_relief(BASE, 600, True, True, False).should_switch
        assert not ctrl.relief_available(BASE, 600)

    def test_relief_held_1_phase_does_not_bounce_back_on_power_alone(self):
        ctrl = PhaseModeController()
        ctrl.on_switch_success(1, BASE, relief=True)
        assert ctrl.relief_hold
        for s in range(0, 1300, 5):
            decision = ctrl.decide(
                BASE + timedelta(seconds=s), 6.9, 4.14, 0.5, 600, True, True, False,
                three_phase_fits=False,
            )
            assert not decision.should_switch

    def test_return_to_3_phase_after_load_ends(self):
        ctrl = PhaseModeController()
        ctrl.on_switch_success(1, BASE, relief=True)
        decision = None
        for s in range(0, 700, 5):
            decision = ctrl.decide(
                BASE + timedelta(seconds=s), 6.9, 4.14, 0.5, 600, True, True, False,
                three_phase_fits=True,
            )
            if decision.should_switch:
                break
        assert decision is not None and decision.should_switch and decision.commanded_mode == 3
        ctrl.on_switch_success(3, BASE + timedelta(seconds=700))
        assert not ctrl.relief_hold

    def test_low_target_power_takes_back_ownership(self):
        ctrl = PhaseModeController()
        ctrl.on_switch_success(1, BASE, relief=True)
        ctrl.decide(BASE + timedelta(seconds=5), 2.0, 4.14, 0.5, 600, True, True, False)
        assert not ctrl.relief_hold

    def test_three_phase_fits_uses_averaged_room_for_min_current(self):
        lb = make_lb()
        # Charger at 10 A on L1 in 1-phase; L3 house averages 9 A -> 9 + 6 > 13.6
        now = warm_up(lb, {1: 11.0, 2: 1.0, 3: 9.0}, ev(10, phases=(1,)))
        assert not lb.three_phase_fits([1, 2, 3], [1], 10, 6, now)
        lb2 = make_lb()
        now = warm_up(lb2, {1: 11.0, 2: 1.0, 3: 1.0}, ev(10, phases=(1,)))
        assert lb2.three_phase_fits([1, 2, 3], [1], 10, 6, now)

    def test_three_phase_fits_needs_a_full_window(self):
        lb = make_lb()
        lb.tick(BASE, {1: 1.0, 2: 1.0, 3: 1.0}, fresh(BASE), [])
        assert not lb.three_phase_fits([1, 2, 3], [1], 6, 6, BASE)


class TestBalancerPhaseAttribution:
    """4.4: a 1-phase charger's draw is attributed to phase_1_line only."""

    @staticmethod
    def _cfg(line=2) -> EVChargerDeviceConfig:
        return EVChargerDeviceConfig(
            id="goe",
            type="current",
            phases=[1, 2, 3],
            phase_switching_enabled=True,
            phase_mode_entity="select.goe_psm",
            phase_1_line=line,
        )

    def test_commanded_1_phase_uses_phase_1_line(self):
        ctrl = PhaseModeController()
        ctrl.on_switch_success(1, BASE - timedelta(hours=1), relief=True)
        phases = ExecutorEngine._balancer_phases(self._cfg(), EVChargerState(), ctrl, BASE)
        assert phases == [2]

    def test_3_phase_uses_configured_phases(self):
        ctrl = PhaseModeController()
        ctrl.on_switch_success(3, BASE - timedelta(hours=1))
        assert ExecutorEngine._balancer_phases(self._cfg(), None, ctrl, BASE) == [1, 2, 3]

    def test_measured_phases_override(self):
        ctrl = PhaseModeController()
        ctrl.on_switch_success(1, BASE - timedelta(hours=1), relief=True)
        state = EVChargerState()
        state.active_phases = [1]
        assert ExecutorEngine._balancer_phases(self._cfg(), state, ctrl, BASE) == [1]

    def test_union_while_measurement_settles_after_switch(self):
        ctrl = PhaseModeController()
        ctrl.on_switch_success(3, BASE)
        state = EVChargerState()
        state.active_phases = [2]  # still the old 1-phase measurement
        t = BASE + timedelta(seconds=PHASE_SWITCH_SETTLE_S - 1)
        assert ExecutorEngine._balancer_phases(self._cfg(), state, ctrl, t) == [1, 2, 3]


# --- 7.1 Prod replay --------------------------------------------------------


def _replay():
    """Closed-loop replay of the prod 2026-09-25 16:00-16:30 (local) window.

    The house load per phase is the recorded grid current minus the charger's
    recorded contribution, estimated from L1 (the charger was 3-phase and L1
    read about -0.8 A while it was paused). The simulated charger draws the
    balancer's setpoint on its current phases, planned at 8 A like prod.
    """
    fixture = json.loads(FIXTURE.read_text())
    voltage = fixture["voltage_v"]
    start = datetime.fromisoformat(fixture["start_utc"])
    lb = make_lb()
    ctrl = PhaseModeController()
    ctrl.commanded_mode = 3
    setpoint: int | None = 8
    phases = [1, 2, 3]
    events: list[tuple[datetime, str]] = []
    over_fuse_since: datetime | None = None
    longest_over_fuse_s = 0.0
    for offset, w1, w2, w3 in fixture["rows"]:
        now = start + timedelta(seconds=offset)
        recorded = [w1 / voltage, w2 / voltage, w3 / voltage]
        recorded_charger = max(0.0, recorded[0] + 0.8)
        house = {p: recorded[p - 1] - recorded_charger for p in (1, 2, 3)}
        grid = {p: house[p] + (setpoint if setpoint and p in phases else 0) for p in (1, 2, 3)}

        if max(grid.values()) > 16:
            over_fuse_since = over_fuse_since or now
            longest_over_fuse_s = max(longest_over_fuse_s, (now - over_fuse_since).total_seconds())
        else:
            over_fuse_since = None

        fits = lb.three_phase_fits([1, 2, 3], phases, setpoint or 0, 6, now)
        decision = ctrl.decide(now, 5.5, 4.14, 0.5, 600, True, True, False, three_phase_fits=fits)
        if decision.should_switch and decision.commanded_mode is not None:
            ctrl.on_switch_success(decision.commanded_mode, now)
            phases = [1, 2, 3] if decision.commanded_mode == 3 else [1]
            events.append((now, f"switch_{decision.commanded_mode}"))

        one_phase = phases == [1]
        entry = EVBalancerInput(
            "goe",
            phases,
            setpoint,
            24 if one_phase else 8,
            min_current_a=6,
            max_current_a=16 if one_phase else 10,
            phase_1_line=1,
            relief_available=len(phases) > 1 and ctrl.relief_available(now, 600),
        )
        out = lb.tick(now, grid, fresh(now), [entry]).ev_outputs[0]
        if out.relief_1p_requested and ctrl.decide_relief(now, 600, True, True, False).should_switch:
            ctrl.on_switch_success(1, now, relief=True)
            phases = [1]
            events.append((now, "relief"))
        if out.state == "paused":
            events.append((now, "pause"))
        setpoint = out.target_a
    return events, longest_over_fuse_s


def test_prod_replay_relieves_instead_of_pausing():
    events, longest_over_fuse_s = _replay()
    kinds = [kind for _, kind in events]
    # Prod paused three times in this window; the ladder moves the car to L1 instead.
    assert "pause" not in kinds
    assert kinds.count("relief") == 1
    relief_at = next(t for t, kind in events if kind == "relief")
    # The first sustained L3 overload starts at 16:15:21 local (14:15:21 UTC).
    assert relief_at.strftime("%H:%M") == "14:15"
    # Overloads never outlast the pause debounce plus one tick.
    assert longest_over_fuse_s <= 5 + TICK_S
    # After the floor heating on L3 stops and the dwell expires, the car returns to 3-phase.
    assert "switch_3" in kinds
    switch_back = next(t for t, kind in events if kind == "switch_3")
    assert (switch_back - relief_at).total_seconds() >= 600


# --- 8.11 Quick re-fit while paused (D17) -------------------------------------


def _pause(lb: LoadBalancer, now: datetime, relief: bool = False) -> None:
    """Severe L3 overload pauses the charger immediately."""
    out = lb.tick(now, {1: 10.0, 2: 10.0, 3: 22.0}, fresh(now), [ev(6, relief=relief)])
    assert out.ev_outputs[0].state == "paused"


def _paused_ticks(lb, start, grid, entry, seconds):
    """Tick every TICK_S for `seconds` after `start`; return (time, output) pairs."""
    outs = []
    for i in range(1, seconds // TICK_S + 1):
        t = start + timedelta(seconds=i * TICK_S)
        outs.append((t, lb.tick(t, grid, fresh(t), [entry]).ev_outputs[0]))
    return outs


class TestQuickRefit:
    QUIET = {1: 2.0, 2: 2.0, 3: 2.0}

    def test_refits_after_confirm_window_not_resume_delay(self):
        lb = make_lb()
        _pause(lb, BASE)
        outs = _paused_ticks(lb, BASE, self.QUIET, ev(None), 15)
        assert [o.target_a is None for _, o in outs] == [True, True, False]
        t, out = outs[-1]
        # Fitting since BASE+5 s; resumed at BASE+15 s, far below resume_delay_s.
        assert (t - BASE).total_seconds() == 15 < lb.config.resume_delay_s
        assert out.state == "throttling" and not out.relief_1p_requested

    def test_resumes_at_largest_fitting_amps_capped_by_plan(self):
        lb = make_lb()
        _pause(lb, BASE)
        # 13.6 A target - 2 A house = 11.6 A -> 11 A, under a 16 A plan
        out = _paused_ticks(lb, BASE, self.QUIET, ev(None, target=16), 15)[-1][1]
        assert out.target_a == 11
        lb2 = make_lb()
        _pause(lb2, BASE)
        out = _paused_ticks(lb2, BASE, self.QUIET, ev(None, target=8), 15)[-1][1]
        assert out.target_a == 8

    def test_resume_amps_fit_the_tightest_phase(self):
        lb = make_lb()
        _pause(lb, BASE)
        grid = {1: 2.0, 2: 6.0, 3: 2.0}  # L2: 13.6 - 6 = 7.6 A -> 7 A
        out = _paused_ticks(lb, BASE, grid, ev(None, target=16), 15)[-1][1]
        assert out.target_a == 7
        assert 6.0 + out.target_a <= 16 * 0.85

    def test_picks_1_phase_when_only_the_1_phase_line_fits(self):
        lb = make_lb()
        _pause(lb, BASE, relief=True)
        grid = {1: 2.0, 2: 2.0, 3: 12.0}  # L3: 13.6 - 12 = 1.6 A < 6 A
        outs = _paused_ticks(lb, BASE, grid, ev(None, target=10, relief=True), 15)
        assert all(o.target_a is None for _, o in outs[:-1])
        out = outs[-1][1]
        assert out.relief_1p_requested and out.refit_from_pause
        assert out.target_a == 10  # L1 fits 11 A, capped by the 10 A plan
        assert "1-phase on L1" in out.reason

    def test_prefers_current_mode_when_it_fits(self):
        lb = make_lb()
        _pause(lb, BASE, relief=True)
        out = _paused_ticks(lb, BASE, self.QUIET, ev(None, relief=True), 15)[-1][1]
        assert out.target_a is not None and not out.relief_1p_requested

    def test_stays_paused_when_dwell_not_elapsed_and_current_mode_does_not_fit(self):
        lb = make_lb()
        _pause(lb, BASE)
        grid = {1: 2.0, 2: 2.0, 3: 12.0}
        # relief_available=False: dwell since the last switch not elapsed
        outs = _paused_ticks(lb, BASE, grid, ev(None, relief=False), 300)
        assert all(o.target_a is None and o.state == "paused" for _, o in outs)
        # Once the dwell elapses (relief available), the 1-phase re-fit follows.
        start = outs[-1][0]
        outs = _paused_ticks(lb, start, grid, ev(None, relief=True), 15)
        assert outs[-1][1].relief_1p_requested and outs[-1][1].target_a is not None

    def test_1_phase_line_overloaded_stays_paused(self):
        lb = make_lb()
        _pause(lb, BASE, relief=True)
        grid = {1: 12.0, 2: 2.0, 3: 2.0}
        outs = _paused_ticks(lb, BASE, grid, ev(None, relief=True), 120)
        assert all(o.target_a is None for _, o in outs)

    def test_stale_reading_restarts_the_confirm_window(self):
        lb = make_lb()
        _pause(lb, BASE)
        t = BASE + timedelta(seconds=5)
        lb.tick(t, self.QUIET, fresh(t), [ev(None)])  # fits
        t += timedelta(seconds=TICK_S)
        stale = {1: t, 2: t, 3: t - timedelta(seconds=60)}
        # Stale-sensor behaviour is unchanged (floor fallback); it breaks the
        # unbroken run of fresh fitting readings the re-fit needs.
        assert lb.tick(t, self.QUIET, stale, [ev(None)]).ev_outputs[0].state == "stale_fallback"
        outs = _paused_ticks(lb, t, self.QUIET, ev(None), 10)
        assert [o.target_a is None for _, o in outs] == [True, True]
        outs = _paused_ticks(lb, outs[-1][0], self.QUIET, ev(None), 5)
        assert outs[-1][1].target_a is not None

    def test_refit_never_exceeds_target_margin_or_fuse(self):
        """Fuse invariant: whatever the resume amps, projected phase current
        stays within the target margin (and hence below main_fuse_a)."""
        for house in (0.0, 1.5, 3.3, 5.0, 7.6):
            lb = make_lb()
            _pause(lb, BASE)
            grid = {1: house, 2: house, 3: house}
            out = _paused_ticks(lb, BASE, grid, ev(None, target=16), 15)[-1][1]
            assert out.target_a is not None
            assert house + out.target_a <= 16 * 0.85 + 1e-9

    def _refit_then_pause(self, lb, start, confirm_s):
        """Wait out the confirm window on quiet readings, re-fit, then pause
        again with a severe spike shortly after. Returns the pause time."""
        outs = _paused_ticks(lb, start, self.QUIET, ev(None), confirm_s + TICK_S)
        resumed = [t for t, o in outs if o.target_a is not None]
        assert resumed, f"no re-fit within {confirm_s + TICK_S}s"
        # The first fitting tick is start+5 s, so the re-fit lands confirm_s later.
        assert (resumed[0] - start).total_seconds() == confirm_s + TICK_S
        pause_at = resumed[0] + timedelta(seconds=60)
        _pause(lb, pause_at)
        return pause_at

    def test_backoff_grows_on_repeated_pauses_and_resets(self):
        lb = make_lb()
        _pause(lb, BASE)
        assert lb.refit_confirm_s("goe") == 10
        t = self._refit_then_pause(lb, BASE, 10)
        assert lb.refit_confirm_s("goe") == 30
        t = self._refit_then_pause(lb, t, 30)
        assert lb.refit_confirm_s("goe") == 120
        t = self._refit_then_pause(lb, t, 120)
        assert lb.refit_confirm_s("goe") == 120  # capped at the last step
        # Re-fit, then charge stably for longer than the flap window.
        outs = _paused_ticks(lb, t, self.QUIET, ev(None), 125)
        resumed_at = next(tt for tt, o in outs if o.target_a is not None)
        pause_at = resumed_at + timedelta(seconds=601)
        _pause(lb, pause_at)
        assert lb.refit_confirm_s("goe") == 10
        # The 10 s window is effective again.
        outs = _paused_ticks(lb, pause_at, self.QUIET, ev(None), 15)
        assert outs[-1][1].target_a is not None

    def test_two_paused_chargers_refit_in_reverse_give_way_order(self):
        """The lower-listed charger re-fits first; the higher-listed one
        waits (timers kept) and then re-fits into what is left, never
        spending the room the first one took."""

        def charger(cid, setpoint, target):
            e = ev(setpoint, target=target)
            e.charger_id = cid
            return e

        lb = make_lb()
        severe = {1: 10.0, 2: 10.0, 3: 30.0}
        out = lb.tick(BASE, severe, fresh(BASE), [charger("a", 6, 6), charger("b", 6, 6)])
        assert [o.state for o in out.ev_outputs] == ["paused", "paused"]

        a_set = b_set = None
        house = 0.0
        resumed = {}
        for i in range(1, 7):
            t = BASE + timedelta(seconds=i * TICK_S)
            own = (a_set or 0) + (b_set or 0)
            grid = {p: house + own for p in (1, 2, 3)}
            out = lb.tick(t, grid, fresh(t), [charger("a", a_set, 6), charger("b", b_set, 6)])
            a_out, b_out = out.ev_outputs
            if a_set is None and a_out.target_a is not None:
                resumed["a"] = i
            if b_set is None and b_out.target_a is not None:
                resumed["b"] = i
            a_set, b_set = a_out.target_a, b_out.target_a
            # Fuse invariant across both chargers.
            assert house + (a_set or 0) + (b_set or 0) <= 16 * 0.85 + 1e-9
        assert resumed["b"] < resumed["a"]
        assert a_set == 6 and b_set == 6

    def test_backoff_never_shorter_than_configured_confirm(self):
        lb = make_lb(resume_confirm_s=60)
        _pause(lb, BASE)
        assert lb.refit_confirm_s("goe") == 60
        self._refit_then_pause(lb, BASE, 60)
        assert lb.refit_confirm_s("goe") == 60  # max(60, 30)
        lb._ev_refit_level["goe"] = 2
        assert lb.refit_confirm_s("goe") == 120


def test_prod_replay_has_no_long_over_fuse_and_no_pause_with_quick_refit():
    """D17 must not change the prod replay: zero pauses, no phase over the
    fuse for more than 10 s."""
    events, longest_over_fuse_s = _replay()
    assert not [e for e in events if e[1] == "pause"]
    assert longest_over_fuse_s <= 10
