"""The thermal trigger drives the unchanged ladder, restore gate and ledger."""

from datetime import datetime, timedelta

import pytest

from executor.config import LoadBalancingConfig
from executor.load_balancer import (
    BatteryBalancerInput,
    EVBalancerInput,
    LoadBalancer,
    ShedLoadInput,
)

T0 = datetime(2026, 1, 1)


def tick(lb, seconds, amps, entries, stale=False):
    now = T0 + timedelta(seconds=seconds)
    currents = {1: 5.0, 2: 5.0, 3: amps}
    timestamps = dict.fromkeys((1, 2, 3), now - timedelta(seconds=3600) if stale else now)
    return lb.tick(now, currents, timestamps, entries)


def balancer(**kwargs):
    return LoadBalancer(
        LoadBalancingConfig(enabled=True, main_fuse_a=20, ramp_up_window_s=0, **kwargs),
        interval_seconds=15,
    )


def ev(setpoint=16, **kwargs):
    return EVBalancerInput(
        "car", [1, 2, 3], setpoint, 16, min_current_a=6, max_current_a=16, **kwargs
    )


def battery(cap=10000, measured=None):
    return BatteryBalancerInput(
        planned_w=10000,
        applied_cap_w=cap,
        reducible_w=cap,
        active=True,
        measured_w=measured,
        min_w=0,
        step_w=100,
    )


def test_heat_waits_then_floor_pauses_and_trace_shows_heat():
    lb = balancer()
    for second in (0, 60, 120, 180):
        assert tick(lb, second, 30, [ev(6)]).ev_outputs[0].target_a == 6
    status = tick(lb, 240, 30, [ev(6)])
    assert status.ev_outputs[0].state == "paused"
    assert status.phase_heat_percent[3] == pytest.approx(80)
    assert "safety 80%" in status.reason
    assert lb.trace.snapshot()[-1]["heat_percent"][3] == pytest.approx(80)


def test_hot_floor_requests_eligible_one_phase_without_delay():
    lb = balancer()
    tick(lb, 0, 30, [])
    tick(lb, 120, 30, [])
    status = tick(lb, 240, 30, [ev(6, relief_available=True, goal_at_risk=True, phase_1_line=1)])
    assert status.ev_outputs[0].relief_1p_requested


def test_urgent_cut_and_one_cut_per_fresh_sample():
    lb = balancer()
    out = tick(lb, 0, 60, [ev(6)]).ev_outputs[0]
    assert out.state == "paused"
    assert lb._fuse_model.heat(3) == 0.8
    # Same sensor timestamp: urgent cannot order the lower load to cut again.
    heater = ShedLoadInput("tank", "water_heater", [3], power_w=1000)
    now = T0 + timedelta(seconds=1)
    status = lb.tick(now, {1: 5, 2: 5, 3: 60}, dict.fromkeys((1, 2, 3), T0), [ev(None), heater])
    assert not status.shed_outputs[0].shed


@pytest.mark.parametrize(
    "min_off,room_current,restore", [(0, 5, True), (300, 5, False), (0, 16, False)]
)
def test_water_heater_needs_all_phases_cooled_room_and_off_time(min_off, room_current, restore):
    lb = balancer(resume_delay_s=0)
    tank = ShedLoadInput(
        "tank",
        "water_heater",
        [1, 2, 3],
        power_w=3000,
        power_source="configured",
        min_off_s=min_off,
    )
    for second in (0, 60, 120, 180, 240):
        status = tick(lb, second, 30, [tank])
    assert status.shed_outputs[0].shed
    assert tick(lb, 250, 5, [tank]).shed_outputs[0].shed  # hot L3 blocks all-phase restore
    status = tick(lb, 340, room_current, [tank])
    assert status.shed_outputs[0].shed is not restore
    if restore:
        assert lb._ledger.pending_a(3) > 0


def test_battery_heat_cut_ignores_lagging_measurement_and_raise_waits_for_cooling():
    lb = balancer()
    for second in (0, 60, 120, 180):
        assert tick(lb, second, 30, [battery(measured=100)]).battery_output.cap_w == 10000
    status = tick(lb, 240, 30, [battery(measured=100)])
    cap = status.battery_output.cap_w
    assert cap == pytest.approx(10000 - 13 * 230 * 3)
    assert tick(lb, 250, 5, [battery(cap, measured=cap)]).battery_output.cap_w == cap
    assert tick(lb, 340, 5, [battery(cap, measured=cap)]).battery_output.cap_w > cap


def test_ev_ramp_waits_for_cooling_then_obeys_room_and_step_limit():
    lb = balancer()
    charging = EVBalancerInput("car", [1, 2, 3], 24, 32, min_current_a=6, max_current_a=32)
    for second in (0, 60, 120, 180):
        tick(lb, second, 30, [charging])
    cut = tick(lb, 240, 30, [charging]).ev_outputs[0]
    assert cut.target_a == 11
    charging.current_setpoint_a = 11
    assert tick(lb, 250, 5, [charging]).ev_outputs[0].target_a == 11
    # Cooling alone cannot grant a step while the momentary target has no room.
    assert tick(lb, 340, 17, [charging]).ev_outputs[0].target_a == 11
    assert lb._fuse_model.cooled([1, 2, 3])
    raised = tick(lb, 350, 5, [charging]).ev_outputs[0]
    assert raised.target_a == 11 + lb.config.increase_step_a


def test_stale_fail_safes_freeze_heat_and_reset_on_runtime_config_change():
    lb = balancer(resume_delay_s=120)
    tick(lb, 0, 30, [])
    tick(lb, 60, 30, [])
    heat = lb._fuse_model.heat(3)
    status = tick(lb, 70, 30, [ev(), battery()], stale=True)
    assert status.ev_outputs[0].target_a == 6
    assert status.battery_output.cap_w == 0
    status = tick(lb, 190, 30, [ev(6), battery(0)], stale=True)
    assert status.ev_outputs[0].state == "paused"
    assert status.battery_output.state == "paused"
    assert lb._fuse_model.heat(3) == heat
    lb.configure(LoadBalancingConfig(enabled=True, main_fuse_a=16), 5)
    assert lb._fuse_model.heat(3) == 0
    assert lb._fuse_model.interval_seconds == 5


def test_paused_ev_refits_while_heat_is_still_above_half():
    lb = balancer()
    for second in (0, 60, 120, 180, 240):
        status = tick(lb, second, 30, [ev(6)])
    assert status.ev_outputs[0].state == "paused"
    tick(lb, 250, 5, [ev(None)])
    status = tick(lb, 260, 5, [ev(None)])
    assert status.ev_outputs[0].target_a >= 6
    assert not lb._fuse_model.cooled([3])


def test_paused_battery_refits_at_minimum_while_hot():
    lb = balancer()
    charging = battery(1000)
    charging.min_w = 1000
    for second in (0, 60, 120, 180, 240):
        status = tick(lb, second, 30, [charging])
    assert status.battery_output.state == "paused"
    paused = battery(0)
    paused.min_w = 1000
    tick(lb, 250, 5, [paused])
    status = tick(lb, 260, 5, [paused])
    assert status.battery_output.cap_w == 1000
    assert not lb._fuse_model.cooled([3])


def test_heat_state_and_evaluation_time_follow_model_into_status_and_trace():
    lb = balancer()
    status = tick(lb, 0, 30, [])
    assert status.phase_heat_state == {1: "cold", 2: "cold", 3: "cold"}
    status = tick(lb, 60, 30, [])
    assert status.phase_heat_state[3] == "heating"
    assert status.heat_sampled_at == (T0 + timedelta(seconds=60)).isoformat()
    trace = lb.trace.snapshot()[-1]
    assert trace["heat_state"] == status.phase_heat_state
    assert trace["heat_sampled_at"] == status.heat_sampled_at
    status = tick(lb, 70, 5, [], stale=True)
    assert status.phase_heat_state == {1: "stale", 2: "stale", 3: "stale"}


@pytest.mark.parametrize("min_off,show_heat_reason", [(0, True), (300, False)])
def test_shed_restore_explains_heat_hold_only_after_off_timer(min_off, show_heat_reason):
    lb = balancer(resume_delay_s=0)
    tank = ShedLoadInput(
        "tank", "water_heater", [3], power_w=1000, power_source="configured", min_off_s=min_off
    )
    for second in (0, 60, 120, 180, 240):
        tick(lb, second, 30, [tank])
    status = tick(lb, 250, 5, [tank])
    assert status.shed_outputs[0].shed
    assert ("heat must cool below 50%" in status.shed_outputs[0].reason) is show_heat_reason
    if show_heat_reason:
        status = tick(lb, 340, 5, [tank])
        assert not status.shed_outputs[0].shed
        assert "heat must cool below 50%" not in status.shed_outputs[0].reason
