from datetime import datetime, timedelta

from executor.config import LoadBalancingConfig
from executor.load_balancer import (
    EVBalancerInput,
    LoadBalancer,
    ShedLoadInput,
    classify_phase_sensor_unit,
    planned_kw_to_amps,
    power_to_current_a,
)


class TestClassifyPhaseSensorUnit:
    """load-balancing-power-sensors 2.2: unit -> current/power classification."""

    def test_amps_is_current(self):
        assert classify_phase_sensor_unit("A") == "current"
        assert classify_phase_sensor_unit("a") == "current"
        assert classify_phase_sensor_unit("amps") == "current"

    def test_watts_is_power_w(self):
        assert classify_phase_sensor_unit("W") == "power_w"
        assert classify_phase_sensor_unit("watt") == "power_w"

    def test_kilowatts_is_power_kw(self):
        assert classify_phase_sensor_unit("kW") == "power_kw"
        assert classify_phase_sensor_unit("kilowatts") == "power_kw"

    def test_unrecognized_unit_falls_back_to_device_class(self):
        assert classify_phase_sensor_unit("", "current") == "current"
        assert classify_phase_sensor_unit(None, "power") == "power_w"

    def test_truly_unrecognized_is_unrecognized(self):
        assert classify_phase_sensor_unit("lux", "illuminance") == "unrecognized"
        assert classify_phase_sensor_unit(None, None) == "unrecognized"


class TestPowerToCurrentA:
    """load-balancing-power-sensors 2.4: I = P / V conversion."""

    def test_basic_conversion(self):
        assert power_to_current_a(2760, 230) == 12.0

    def test_nominal_fallback_voltage(self):
        assert round(power_to_current_a(1610, 220), 1) == 7.3

    def test_zero_voltage_does_not_divide_by_zero(self):
        assert power_to_current_a(1000, 0) == 0.0


class TestPlannedKwToAmps:
    """universal-load-balancing 3.2: kW -> A translation."""

    def test_11kw_three_phase_yields_15a(self):
        assert planned_kw_to_amps(11.0, 3, min_current_a=6, max_current_a=16) == 15

    def test_3_6kw_single_phase_yields_15a(self):
        assert planned_kw_to_amps(3.6, 1, min_current_a=6, max_current_a=16) == 15

    def test_below_floor_returns_none(self):
        assert planned_kw_to_amps(1.0, 3, min_current_a=6, max_current_a=16) is None

    def test_clamped_to_max_current(self):
        assert planned_kw_to_amps(20.0, 1, min_current_a=6, max_current_a=16) == 16

    def test_zero_kw_returns_none(self):
        assert planned_kw_to_amps(0.0, 3, min_current_a=6, max_current_a=16) is None

    def test_zero_active_phases_returns_none(self):
        assert planned_kw_to_amps(11.0, 0, min_current_a=6, max_current_a=16) is None

    def test_exact_floor_is_not_paused(self):
        # 6A * 230V * 3 phases = 4.14kW -> exactly 6A
        assert planned_kw_to_amps(4.14, 3, min_current_a=6, max_current_a=16) == 6


BASE = datetime(2026, 1, 1, 12, 0, 0)


def make_lb(**overrides) -> LoadBalancer:
    cfg = LoadBalancingConfig(
        enabled=True,
        main_fuse_a=20,
        resume_delay_s=120,
        resume_margin_percent=90,
        increase_step_a=1,
        sensor_stale_after_s=30,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return LoadBalancer(cfg)


def fresh_ts(*phases, at=BASE) -> dict:
    return {p: at for p in phases}


class TestHeadroomComputation:
    """4.1: per-phase headroom, binding headroom = min over a load's phases."""

    def test_unbalanced_load_scenario(self):
        lb = make_lb()
        grid = {1: 18.0, 2: 5.0, 3: 5.0}
        status = lb.tick(BASE, grid, fresh_ts(1, 2, 3), [])

        assert status.phase_headroom_a == {1: 2.0, 2: 15.0, 3: 15.0}
        binding_headroom = min(status.phase_headroom_a[p] for p in (1, 2, 3))
        assert binding_headroom == 2.0

    def test_one_phase_over_fuse_throttles_despite_low_total_power(self):
        """4.8: total power fine, but L1 alone over fuse -> still throttles."""
        lb = make_lb()
        ev = EVBalancerInput("goe", [1, 2, 3], 10, 10, min_current_a=6, max_current_a=16)
        grid = {1: 22.0, 2: 2.0, 3: 2.0}  # modest total, but L1 > 20A fuse
        status = lb.tick(BASE, grid, fresh_ts(1, 2, 3), [ev])

        out = status.ev_outputs[0]
        assert out.target_a is not None
        assert out.target_a < 10


class TestEVDecreaseSide:
    """4.2: decreases apply immediately, unbounded, floored at min_current_a."""

    def test_stove_spike_reduces_to_10a_or_lower(self):
        lb = make_lb()
        ev = EVBalancerInput("goe", [1, 2, 3], 16, 16, min_current_a=6, max_current_a=16)
        grid = {1: 26.0, 2: 5.0, 3: 5.0}  # headroom on L1 = 20-26 = -6
        status = lb.tick(BASE, grid, fresh_ts(1, 2, 3), [ev])

        out = status.ev_outputs[0]
        assert out.target_a is not None
        assert out.target_a <= 10
        assert out.state == "throttling"

    def test_reduction_floors_at_min_current_and_pauses(self):
        lb = make_lb()
        ev = EVBalancerInput("goe", [1], 10, 16, min_current_a=6, max_current_a=16)
        grid = {1: 27.0, 2: 5.0, 3: 5.0}  # headroom = -7 -> 10-7=3 < floor(6) -> pause
        status = lb.tick(BASE, grid, fresh_ts(1, 2, 3), [ev])

        out = status.ev_outputs[0]
        assert out.target_a is None
        assert out.state == "paused"


class TestEVIncreaseSide:
    """4.3: rate-limited increases, gated on resume margin."""

    def test_increase_blocked_near_margin(self):
        lb = make_lb()  # margin 90% of 20A = 18A
        ev = EVBalancerInput("goe", [1], 10, 16, min_current_a=6, max_current_a=16)
        grid = {1: 19.0, 2: 5.0, 3: 5.0}  # 95% of fuse
        status = lb.tick(BASE, grid, fresh_ts(1, 2, 3), [ev])

        out = status.ev_outputs[0]
        assert out.target_a == 10  # unchanged

    def test_step_limited_ramp_toward_target(self):
        lb = make_lb()
        ev = EVBalancerInput("goe", [1], 10, 16, min_current_a=6, max_current_a=16)
        grid = {1: 5.0, 2: 5.0, 3: 5.0}
        status = lb.tick(BASE, grid, fresh_ts(1, 2, 3), [ev])

        out = status.ev_outputs[0]
        assert out.target_a == 11  # +1A step

    def test_never_exceeds_planner_target(self):
        lb = make_lb()
        ev = EVBalancerInput("goe", [1], 10, 10, min_current_a=6, max_current_a=16)
        grid = {1: 2.0, 2: 2.0, 3: 2.0}
        status = lb.tick(BASE, grid, fresh_ts(1, 2, 3), [ev])

        out = status.ev_outputs[0]
        assert out.target_a == 10


class TestPauseResumeAntiFlap:
    """4.4: pause below floor, resume only after delay + margin."""

    def test_brief_dip_does_not_resume_before_delay(self):
        lb = make_lb()
        ev_charging = EVBalancerInput("goe", [1], 10, 16, min_current_a=6, max_current_a=16)

        status0 = lb.tick(BASE, {1: 27.0, 2: 5.0, 3: 5.0}, fresh_ts(1, 2, 3), [ev_charging])
        assert status0.ev_outputs[0].target_a is None
        assert status0.state == "paused"

        # Stopped charger now reports current_setpoint_a=None (as the engine would)
        ev_stopped = EVBalancerInput("goe", [1], None, 16, min_current_a=6, max_current_a=16)

        t_dip = BASE + timedelta(seconds=30)
        status1 = lb.tick(t_dip, {1: 5.0, 2: 5.0, 3: 5.0}, fresh_ts(1, 2, 3, at=t_dip), [ev_stopped])
        assert status1.ev_outputs[0].target_a is None  # still paused, only 30s elapsed

        t_resume = BASE + timedelta(seconds=130)
        status2 = lb.tick(
            t_resume, {1: 5.0, 2: 5.0, 3: 5.0}, fresh_ts(1, 2, 3, at=t_resume), [ev_stopped]
        )
        assert status2.ev_outputs[0].target_a == 6  # resumes at floor after 120s + margin


class TestShedding:
    """4.5: shed in list order (top first), restore in exact reverse order."""

    def test_shed_then_restore_reverse_order(self):
        lb = make_lb()
        wh = ShedLoadInput("wh", "water_heater", [1])
        pump = ShedLoadInput("pump", "custom_entity", [1])
        entries = [wh, pump]  # wh listed first -> gives way first

        grid_over = {1: 25.0, 2: 5.0, 3: 5.0}
        t0 = BASE
        status0 = lb.tick(t0, grid_over, fresh_ts(1, 2, 3, at=t0), entries)
        assert {o.load_id for o in status0.shed_outputs if o.shed} == {"wh"}

        t1 = t0 + timedelta(seconds=5)
        status1 = lb.tick(t1, grid_over, fresh_ts(1, 2, 3, at=t1), entries)
        assert {o.load_id for o in status1.shed_outputs if o.shed} == {"wh", "pump"}

        grid_ok = {1: 5.0, 2: 5.0, 3: 5.0}
        t2 = t1 + timedelta(seconds=125)
        status2 = lb.tick(t2, grid_ok, fresh_ts(1, 2, 3, at=t2), entries)
        assert {o.load_id for o in status2.shed_outputs if o.shed} == {"wh"}  # pump restored first

        t3 = t2 + timedelta(seconds=125)
        status3 = lb.tick(t3, grid_ok, fresh_ts(1, 2, 3, at=t3), entries)
        assert {o.load_id for o in status3.shed_outputs if o.shed} == set()  # wh restored too


class TestStaleSensorFailSafe:
    """4.6: stale data forces the EV to the floor, then pauses if still stale."""

    def test_two_stage_fallback(self):
        lb = make_lb()
        ev = EVBalancerInput("goe", [1], 16, 16, min_current_a=6, max_current_a=16)

        t0 = BASE
        stale_ts = {1: t0 - timedelta(seconds=40)}  # older than sensor_stale_after_s=30
        status0 = lb.tick(t0, {1: 10.0}, stale_ts, [ev])
        out0 = status0.ev_outputs[0]
        assert out0.target_a == 6
        assert out0.state == "stale_fallback"

        t1 = t0 + timedelta(seconds=125)  # >= resume_delay_s since staleness first observed
        status1 = lb.tick(t1, {1: 10.0}, stale_ts, [ev])
        out1 = status1.ev_outputs[0]
        assert out1.target_a is None
        assert out1.state == "paused"

    def test_missing_phase_reading_is_treated_as_stale(self):
        lb = make_lb()
        ev = EVBalancerInput("goe", [1], 16, 16, min_current_a=6, max_current_a=16)
        status = lb.tick(BASE, {}, {}, [ev])
        assert status.ev_outputs[0].target_a == 6
        assert status.ev_outputs[0].state == "stale_fallback"

    def test_escalated_stale_pause_honors_resume_delay_after_recovery(self):
        """9.3: once stale_fallback escalates to a full pause, a flapping
        sensor that comes back fresh must not resume charging immediately —
        it has to wait out resume_delay_s (with margin/headroom ok), exactly
        like an overload-induced pause.
        """
        lb = make_lb()
        ev = EVBalancerInput("goe", [1], 16, 16, min_current_a=6, max_current_a=16)

        t0 = BASE
        stale_ts = {1: t0 - timedelta(seconds=40)}  # older than sensor_stale_after_s=30
        status0 = lb.tick(t0, {1: 10.0}, stale_ts, [ev])
        assert status0.ev_outputs[0].state == "stale_fallback"

        # Sensor stays stale past resume_delay_s -> escalates to a full pause.
        t1 = t0 + timedelta(seconds=125)
        status1 = lb.tick(t1, {1: 10.0}, stale_ts, [ev])
        out1 = status1.ev_outputs[0]
        assert out1.state == "paused"
        assert out1.target_a is None

        # The sensor flaps back to fresh right away and the charger has
        # already stopped (current_setpoint_a=None) — but the plan still
        # wants it charging.
        ev_stopped = EVBalancerInput("goe", [1], None, 16, min_current_a=6, max_current_a=16)
        t2 = t1 + timedelta(seconds=1)
        status2 = lb.tick(t2, {1: 5.0}, fresh_ts(1, at=t2), [ev_stopped])
        out2 = status2.ev_outputs[0]
        assert out2.state == "paused"
        assert out2.target_a is None

        # Just short of resume_delay_s since the pause began: still paused.
        t3 = t1 + timedelta(seconds=119)
        status3 = lb.tick(t3, {1: 5.0}, fresh_ts(1, at=t3), [ev_stopped])
        assert status3.ev_outputs[0].state == "paused"

        # Once resume_delay_s has elapsed since the pause began (and
        # margin/headroom are fine), charging resumes at the floor.
        t4 = t1 + timedelta(seconds=121)
        status4 = lb.tick(t4, {1: 5.0}, fresh_ts(1, at=t4), [ev_stopped])
        out4 = status4.ev_outputs[0]
        assert out4.state == "throttling"
        assert out4.target_a == 6


class TestFeatureGating:
    """4.7 precondition: disabled/unconfigured balancer is a pure no-op."""

    def test_disabled_returns_disabled_state(self):
        cfg = LoadBalancingConfig(enabled=False)
        lb = LoadBalancer(cfg)
        ev = EVBalancerInput("goe", [1], 16, 16, min_current_a=6, max_current_a=16)
        status = lb.tick(BASE, {1: 100.0}, fresh_ts(1), [ev])

        assert status.state == "disabled"
        assert status.ev_outputs == []


class TestPositionOrderedAllocation:
    """load-balancing-completion 3.1: give-way-order sequential allocation
    across dynamically-throttled chargers sharing a phase — list position
    (top first) decides, not a numeric priority."""

    def test_single_charger_is_unaffected_by_ordering(self):
        """Spec scenario: a single charger behaves byte-identically to the
        pre-ordering behavior regardless of its position."""
        lb = make_lb()
        ev = EVBalancerInput("goe", [1, 2, 3], 16, 16, min_current_a=6, max_current_a=16)
        grid = {1: 26.0, 2: 5.0, 3: 5.0}
        status = lb.tick(BASE, grid, fresh_ts(1, 2, 3), [ev])

        out = status.ev_outputs[0]
        assert out.target_a == 10
        assert out.state == "throttling"

    def test_higher_listed_charger_gives_way_first_and_fully_resolves_deficit(self):
        lb = make_lb()
        # Both chargers draw on L1 only; L1 headroom = 20-30 = -10.
        charger_a = EVBalancerInput("a", [1], 16, 16, min_current_a=6, max_current_a=16)
        charger_b = EVBalancerInput("b", [1], 16, 16, min_current_a=6, max_current_a=16)
        grid = {1: 30.0, 2: 5.0, 3: 5.0}
        status = lb.tick(BASE, grid, fresh_ts(1, 2, 3), [charger_a, charger_b])

        out_a = next(o for o in status.ev_outputs if o.charger_id == "a")
        out_b = next(o for o in status.ev_outputs if o.charger_id == "b")
        # A (listed first) absorbs the full -10A deficit (16-10=6, exactly its floor).
        assert out_a.target_a == 6
        assert out_a.state == "throttling"
        # A's reduction (10A) fully cancels the deficit -> B is untouched.
        assert out_b.target_a == 16
        assert out_b.state == "idle"

    def test_higher_listed_alone_insufficient_shares_remainder_with_next(self):
        lb = make_lb()
        # L1 headroom = 20-44 = -24; even A pausing fully (max possible 16A
        # relief) leaves -8A, which B must then absorb.
        charger_a = EVBalancerInput("a", [1], 16, 16, min_current_a=6, max_current_a=16)
        charger_b = EVBalancerInput("b", [1], 16, 16, min_current_a=6, max_current_a=16)
        grid = {1: 44.0, 2: 5.0, 3: 5.0}
        status = lb.tick(BASE, grid, fresh_ts(1, 2, 3), [charger_a, charger_b])

        out_a = next(o for o in status.ev_outputs if o.charger_id == "a")
        out_b = next(o for o in status.ev_outputs if o.charger_id == "b")
        # A pauses entirely: -24 + 16 = -8 < floor 6.
        assert out_a.target_a is None
        assert out_a.state == "paused"
        # Remaining -8A deficit (after A's full 16A relief) is absorbed by B.
        assert out_b.target_a == 8
        assert out_b.state == "throttling"

    def test_list_order_reversal_swaps_who_gives_way(self):
        """Multi-charger ordering follows list position: with B listed first,
        B gives way and A is untouched (mirror of the test above)."""
        lb = make_lb()
        charger_a = EVBalancerInput("a", [1], 16, 16, min_current_a=6, max_current_a=16)
        charger_b = EVBalancerInput("b", [1], 16, 16, min_current_a=6, max_current_a=16)
        grid = {1: 30.0, 2: 5.0, 3: 5.0}
        status = lb.tick(BASE, grid, fresh_ts(1, 2, 3), [charger_b, charger_a])

        out_a = next(o for o in status.ev_outputs if o.charger_id == "a")
        out_b = next(o for o in status.ev_outputs if o.charger_id == "b")
        assert out_b.target_a == 6
        assert out_b.state == "throttling"
        assert out_a.target_a == 16
        assert out_a.state == "idle"

    def test_missing_main_fuse_a_returns_disabled(self):
        cfg = LoadBalancingConfig(enabled=True, main_fuse_a=None)
        lb = LoadBalancer(cfg)
        status = lb.tick(BASE, {}, {}, [])
        assert status.state == "disabled"


class TestInterleavedGiveWayOrder:
    """load-balancing-completion 3.1/3.2: shed loads and chargers interleave
    in one user-ordered list — top gives way first, restore in exact reverse
    order, pausing is position-aware."""

    def test_shed_above_charger_gives_way_before_charger_slows(self):
        """Spec scenario: water heater listed above the charger on the same
        phase is shed first; the charger is only reduced if the deficit
        persists after the shed."""
        lb = make_lb()
        wh = ShedLoadInput("wh", "water_heater", [2])
        ev = EVBalancerInput("goe", [1, 2, 3], 16, 16, min_current_a=6, max_current_a=16)

        grid = {1: 5.0, 2: 26.0, 3: 5.0}  # L2 headroom = -6
        status = lb.tick(BASE, grid, fresh_ts(1, 2, 3), [wh, ev])

        # The water heater sheds; the charger holds its setpoint this tick.
        assert [o.load_id for o in status.shed_outputs if o.shed] == ["wh"]
        out = status.ev_outputs[0]
        assert out.target_a == 16

        # Next tick the shed relieved L2 fully -> charger still untouched.
        t1 = BASE + timedelta(seconds=5)
        grid_ok = {1: 5.0, 2: 10.0, 3: 5.0}
        status1 = lb.tick(t1, grid_ok, fresh_ts(1, 2, 3, at=t1), [wh, ev])
        assert status1.ev_outputs[0].target_a == 16

    def test_charger_reduces_when_deficit_persists_after_shed(self):
        lb = make_lb()
        wh = ShedLoadInput("wh", "water_heater", [2])
        ev = EVBalancerInput("goe", [1, 2, 3], 16, 16, min_current_a=6, max_current_a=16)

        grid = {1: 5.0, 2: 30.0, 3: 5.0}  # L2 headroom = -10
        lb.tick(BASE, grid, fresh_ts(1, 2, 3), [wh, ev])  # wh sheds, ev holds

        # Shed only relieved 4A -> deficit persists; wh is exhausted, so the
        # charger now gives way.
        t1 = BASE + timedelta(seconds=5)
        grid1 = {1: 5.0, 2: 26.0, 3: 5.0}  # still -6
        status1 = lb.tick(t1, grid1, fresh_ts(1, 2, 3, at=t1), [wh, ev])
        out = status1.ev_outputs[0]
        assert out.target_a == 10  # 16 + (-6)
        assert out.state == "throttling"

    def test_charger_not_paused_while_higher_listed_shed_can_give_way(self):
        """Spec scenario: charger at its floor, phase overloaded, unshed load
        listed above it -> the load sheds, the charger is NOT paused."""
        lb = make_lb()
        wh = ShedLoadInput("wh", "water_heater", [1])
        ev = EVBalancerInput("goe", [1], 6, 16, min_current_a=6, max_current_a=16)

        grid = {1: 24.0, 2: 5.0, 3: 5.0}  # -4: at floor, would pause without wh
        status = lb.tick(BASE, grid, fresh_ts(1, 2, 3), [wh, ev])

        assert [o.load_id for o in status.shed_outputs if o.shed] == ["wh"]
        out = status.ev_outputs[0]
        assert out.target_a == 6  # held at floor, not paused
        assert out.state != "paused"

    def test_charger_pauses_once_higher_listed_shed_is_exhausted(self):
        lb = make_lb()
        wh = ShedLoadInput("wh", "water_heater", [1])
        ev = EVBalancerInput("goe", [1], 6, 16, min_current_a=6, max_current_a=16)

        grid = {1: 24.0, 2: 5.0, 3: 5.0}
        lb.tick(BASE, grid, fresh_ts(1, 2, 3), [wh, ev])  # wh sheds

        # Deficit persists next tick; wh exhausted -> charger pauses now.
        t1 = BASE + timedelta(seconds=5)
        status1 = lb.tick(t1, grid, fresh_ts(1, 2, 3, at=t1), [wh, ev])
        out = status1.ev_outputs[0]
        assert out.target_a is None
        assert out.state == "paused"

    def test_restore_is_exact_reverse_order_across_kinds(self):
        """The charger (below the shed load, gave way last) resumes first;
        the shed load above it only restores afterwards."""
        lb = make_lb()
        wh = ShedLoadInput("wh", "water_heater", [1])
        ev_charging = EVBalancerInput("goe", [1], 6, 16, min_current_a=6, max_current_a=16)

        grid = {1: 24.0, 2: 5.0, 3: 5.0}
        t0 = BASE
        lb.tick(t0, grid, fresh_ts(1, 2, 3, at=t0), [wh, ev_charging])  # wh sheds
        t1 = t0 + timedelta(seconds=5)
        lb.tick(t1, grid, fresh_ts(1, 2, 3, at=t1), [wh, ev_charging])  # ev pauses

        # Recovery, past resume_delay_s for both.
        ev_stopped = EVBalancerInput("goe", [1], None, 16, min_current_a=6, max_current_a=16)
        grid_ok = {1: 5.0, 2: 5.0, 3: 5.0}
        t2 = t1 + timedelta(seconds=125)
        status2 = lb.tick(t2, grid_ok, fresh_ts(1, 2, 3, at=t2), [wh, ev_stopped])
        # Charger (gave way last) resumes first; wh stays shed this tick.
        assert status2.ev_outputs[0].target_a == 6
        assert [o.load_id for o in status2.shed_outputs if o.shed] == ["wh"]

        # Next tick the wh (nothing below it still given way) restores.
        ev_resumed = EVBalancerInput("goe", [1], 6, 16, min_current_a=6, max_current_a=16)
        t3 = t2 + timedelta(seconds=5)
        status3 = lb.tick(t3, grid_ok, fresh_ts(1, 2, 3, at=t3), [wh, ev_resumed])
        assert not any(o.shed for o in status3.shed_outputs)

    def test_shed_restore_blocked_while_lower_listed_charger_paused(self):
        """A paused charger below the shed load blocks its restore (reverse
        order), even when the shed load's own conditions are satisfied."""
        lb = make_lb()
        wh = ShedLoadInput("wh", "water_heater", [1])
        ev_charging = EVBalancerInput("goe", [1], 6, 16, min_current_a=6, max_current_a=16)

        grid = {1: 24.0, 2: 5.0, 3: 5.0}
        t0 = BASE
        lb.tick(t0, grid, fresh_ts(1, 2, 3, at=t0), [wh, ev_charging])  # wh sheds
        t1 = t0 + timedelta(seconds=5)
        lb.tick(t1, grid, fresh_ts(1, 2, 3, at=t1), [wh, ev_charging])  # ev pauses

        # Healthy again but only 60s since the charger paused: charger still
        # waiting out its resume delay -> wh must NOT restore before it.
        ev_stopped = EVBalancerInput("goe", [1], None, 16, min_current_a=6, max_current_a=16)
        grid_ok = {1: 5.0, 2: 5.0, 3: 5.0}
        t2 = t1 + timedelta(seconds=60)
        status2 = lb.tick(t2, grid_ok, fresh_ts(1, 2, 3, at=t2), [wh, ev_stopped])
        assert status2.ev_outputs[0].target_a is None
        assert [o.load_id for o in status2.shed_outputs if o.shed] == ["wh"]

    def test_default_order_reproduces_two_tier_behavior(self):
        """Migrated default (all chargers before all shed loads): charger
        throttles to floor and pauses, shed activates only then — tick-for-
        tick like the old two-tier gate."""
        lb = make_lb()
        ev = EVBalancerInput("goe", [1, 2, 3], 16, 16, min_current_a=6, max_current_a=16)
        wh = ShedLoadInput("wh", "water_heater", [2])

        # Tick 1: modest L2 overload -> charger throttles, wh untouched.
        grid = {1: 5.0, 2: 26.0, 3: 5.0}
        status0 = lb.tick(BASE, grid, fresh_ts(1, 2, 3), [ev, wh])
        assert status0.ev_outputs[0].target_a == 10
        assert not any(o.shed for o in status0.shed_outputs)

        # Tick 2: deep overload -> charger pauses AND wh sheds the same tick
        # (charger relief alone cannot cover the deficit).
        ev_10 = EVBalancerInput("goe", [1, 2, 3], 10, 16, min_current_a=6, max_current_a=16)
        t1 = BASE + timedelta(seconds=5)
        grid_deep = {1: 5.0, 2: 40.0, 3: 5.0}
        status1 = lb.tick(t1, grid_deep, fresh_ts(1, 2, 3, at=t1), [ev_10, wh])
        assert status1.ev_outputs[0].target_a is None
        assert [o.load_id for o in status1.shed_outputs if o.shed] == ["wh"]
