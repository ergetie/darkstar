"""excess-pv-priority-dispatch 5.2: end-to-end dry run (shadow/simulated HA).

Feeds a synthetic SystemState sequence (export ramp, cloud dip, sustained
shortfall) through the pure EVSurplusController and PhaseModeController and
asserts the dispatched amp / phase-mode sequence, tick by tick — the same
decision logic executor/engine.py wires to real HA calls each tick.
"""

from datetime import datetime, timedelta

from executor.ev_surplus import EVSurplusController, PhaseModeController

NOW = datetime(2025, 6, 1, 12, 0, 0)


def _tick(seconds: float) -> datetime:
    return NOW + timedelta(seconds=seconds)


class TestSurplusAmpSequence:
    """Ramp up on export -> immediate drop on cloud dip -> pause on sustained
    shortfall -> delayed resume once surplus recovers."""

    def test_full_sequence(self):
        ctrl = EVSurplusController()
        min_current_a, max_current_a, phases = 6, 16, 3
        increase_step_a, resume_delay_s, resume_margin_percent = 1, 120, 90.0
        deadband_kw = 0.2
        setpoint: int | None = None
        dispatched: list[
            tuple[float, float, str, int | None]
        ] = []  # (t, surplus_kw, state, target_a)

        def tick(t_s: float, surplus_kw: float) -> None:
            nonlocal setpoint
            result = ctrl.tick(
                now=_tick(t_s),
                surplus_kw=surplus_kw,
                deadband_kw=deadband_kw,
                current_setpoint_a=setpoint,
                min_current_a=min_current_a,
                max_current_a=max_current_a,
                active_phase_count=phases,
                increase_step_a=increase_step_a,
                resume_delay_s=resume_delay_s,
                resume_margin_percent=resume_margin_percent,
                phase_switch_can_lower_floor=False,
            )
            setpoint = result.target_a
            dispatched.append((t_s, surplus_kw, result.state, result.target_a))

        # --- Phase 1: export ramps up from nothing to a healthy surplus.
        # 6kW/3-phase clears the 6A floor immediately (no 0->floor ramp).
        tick(0, 6.0)
        assert dispatched[-1][2] == "charging"
        assert dispatched[-1][3] == 6

        # Further export growth ramps by +1A/tick (shared ramp step), not in
        # one jump, even though the surplus alone would justify much more.
        tick(5, 10.0)
        assert dispatched[-1][3] == 7
        tick(10, 10.0)
        assert dispatched[-1][3] == 8
        tick(15, 10.0)
        assert dispatched[-1][3] == 9

        # --- Phase 2: a mild cloud passes — import ticks up slightly.
        # Setpoint drops immediately, no ramp limit (never draw from the grid),
        # but surplus still sustains the floor so charging continues.
        tick(20, -1.0)
        assert dispatched[-1][2] == "charging"
        assert dispatched[-1][3] == 7  # 9 - floor(1000/690)=2 -> 7, applied immediately

        # --- Phase 3: sustained shortfall — a heavier/longer dip drops the
        # feedback-computed setpoint below the 6A floor -> pause.
        tick(25, -5.0)
        assert dispatched[-1][2] == "paused"
        assert dispatched[-1][3] is None
        paused_since = dispatched[-1][0]

        # --- Phase 4: surplus recovers, but resume is delayed (never before
        # resume_delay_s of continuously-good surplus).
        tick(paused_since + 10, 5.0)
        assert dispatched[-1][2] == "paused", "must not resume before the delay elapses"

        tick(paused_since + 60, 5.0)
        assert dispatched[-1][2] == "paused", "still within the delay window"

        tick(paused_since + 130, 5.0)
        assert dispatched[-1][2] == "charging", "resumes once surplus has held for the full delay"
        assert dispatched[-1][3] == min_current_a


class TestPhaseModeSwitchSequence:
    """Phase-mode switches down when target power drops, respecting dwell,
    and never fires again before the dwell window from the last switch."""

    def test_switch_sequence_respects_dwell(self):
        ctrl = PhaseModeController()
        ctrl.commanded_mode = 3  # starts 3-phase
        three_phase_min_kw = 4.14
        hysteresis_kw = 0.5
        min_dwell_s = 600

        # Power drops below (3ph_min + hysteresis) — condition starts, but no
        # switch until it's held for the full dwell window.
        d = ctrl.decide(
            now=_tick(0),
            target_power_kw=1.0,
            three_phase_min_kw_value=three_phase_min_kw,
            hysteresis_kw=hysteresis_kw,
            min_dwell_s=min_dwell_s,
            enabled=True,
            entity_configured=True,
            is_binary=False,
        )
        assert not d.should_switch

        d = ctrl.decide(
            now=_tick(300),
            target_power_kw=1.0,
            three_phase_min_kw_value=three_phase_min_kw,
            hysteresis_kw=hysteresis_kw,
            min_dwell_s=min_dwell_s,
            enabled=True,
            entity_configured=True,
            is_binary=False,
        )
        assert not d.should_switch, "only 300s of 600s dwell elapsed"

        d = ctrl.decide(
            now=_tick(600),
            target_power_kw=1.0,
            three_phase_min_kw_value=three_phase_min_kw,
            hysteresis_kw=hysteresis_kw,
            min_dwell_s=min_dwell_s,
            enabled=True,
            entity_configured=True,
            is_binary=False,
        )
        assert d.should_switch and d.commanded_mode == 1
        ctrl.on_switch_success(1, _tick(600))

        # Power immediately recovers above threshold, but the dwell lockout
        # (measured from the last switch) blocks an immediate re-switch.
        d = ctrl.decide(
            now=_tick(650),
            target_power_kw=10.0,
            three_phase_min_kw_value=three_phase_min_kw,
            hysteresis_kw=hysteresis_kw,
            min_dwell_s=min_dwell_s,
            enabled=True,
            entity_configured=True,
            is_binary=False,
        )
        assert not d.should_switch, "within the post-switch dwell lockout"

        # Once both the condition has held AND the post-switch dwell has
        # elapsed, the switch back up is allowed.
        d = ctrl.decide(
            now=_tick(1250),
            target_power_kw=10.0,
            three_phase_min_kw_value=three_phase_min_kw,
            hysteresis_kw=hysteresis_kw,
            min_dwell_s=min_dwell_s,
            enabled=True,
            entity_configured=True,
            is_binary=False,
        )
        assert d.should_switch and d.commanded_mode == 3
