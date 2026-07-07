"""excess-pv-priority-dispatch 3.9: EV surplus feedback + phase-mode state machine."""

from datetime import datetime, timedelta

from executor.ev_surplus import (
    EVSurplusController,
    PhaseModeController,
    one_phase_min_kw,
    three_phase_min_kw,
)

NOW = datetime(2025, 6, 1, 12, 0, 0)


def _tick(now: datetime, seconds: float) -> datetime:
    return now + timedelta(seconds=seconds)


class TestEVSurplusControllerFeedback:
    def test_raises_within_ramp_limit_on_export(self):
        ctrl = EVSurplusController()
        result = ctrl.tick(
            now=NOW,
            surplus_kw=3.0,  # would want a big jump
            deadband_kw=0.2,
            current_setpoint_a=6,
            min_current_a=6,
            max_current_a=16,
            active_phase_count=3,
            increase_step_a=1,
            resume_delay_s=120,
            resume_margin_percent=90.0,
            phase_switch_can_lower_floor=False,
        )
        assert result.state == "charging"
        assert result.target_a == 7  # limited to +1A/tick despite a much bigger raw increase

    def test_lowers_immediately_on_import_no_ramp_limit(self):
        ctrl = EVSurplusController()
        result = ctrl.tick(
            now=NOW,
            surplus_kw=-3.0,  # importing heavily
            deadband_kw=0.2,
            current_setpoint_a=16,
            min_current_a=6,
            max_current_a=16,
            active_phase_count=3,
            increase_step_a=1,
            resume_delay_s=120,
            resume_margin_percent=90.0,
            phase_switch_can_lower_floor=False,
        )
        # delta = floor(-3000/(230*3)) = floor(-4.35) = -5 -> 16-5=11, applied fully (no ramp cap)
        assert result.target_a == 11
        assert result.state == "charging"

    def test_holds_within_deadband(self):
        ctrl = EVSurplusController()
        result = ctrl.tick(
            now=NOW,
            surplus_kw=0.1,  # within +-0.2 deadband
            deadband_kw=0.2,
            current_setpoint_a=10,
            min_current_a=6,
            max_current_a=16,
            active_phase_count=3,
            increase_step_a=1,
            resume_delay_s=120,
            resume_margin_percent=90.0,
            phase_switch_can_lower_floor=False,
        )
        assert result.target_a == 10
        assert result.state == "charging"

    def test_pause_on_sustained_shortfall(self):
        ctrl = EVSurplusController()
        result = ctrl.tick(
            now=NOW,
            surplus_kw=0.05,  # tiny surplus, well below the 1-phase floor
            deadband_kw=0.2,
            current_setpoint_a=None,
            min_current_a=6,
            max_current_a=16,
            active_phase_count=3,
            increase_step_a=1,
            resume_delay_s=120,
            resume_margin_percent=90.0,
            phase_switch_can_lower_floor=False,
        )
        assert result.target_a is None
        assert result.state == "paused"
        assert ctrl.paused_at == NOW

    def test_no_resume_before_delay_even_with_good_surplus(self):
        ctrl = EVSurplusController()
        ctrl.tick(
            now=NOW,
            surplus_kw=0.0,
            deadband_kw=0.2,
            current_setpoint_a=None,
            min_current_a=6,
            max_current_a=16,
            active_phase_count=3,
            increase_step_a=1,
            resume_delay_s=120,
            resume_margin_percent=90.0,
            phase_switch_can_lower_floor=False,
        )
        assert ctrl.paused_at is not None

        # Strong surplus recovers, but only 30s in — before the 120s resume delay
        result = ctrl.tick(
            now=_tick(NOW, 30),
            surplus_kw=5.0,
            deadband_kw=0.2,
            current_setpoint_a=None,
            min_current_a=6,
            max_current_a=16,
            active_phase_count=3,
            increase_step_a=1,
            resume_delay_s=120,
            resume_margin_percent=90.0,
            phase_switch_can_lower_floor=False,
        )
        assert result.target_a is None
        assert result.state == "paused"

    def test_resume_after_stable_surplus_for_full_delay(self):
        ctrl = EVSurplusController()
        ctrl.tick(
            now=NOW,
            surplus_kw=0.0,
            deadband_kw=0.2,
            current_setpoint_a=None,
            min_current_a=6,
            max_current_a=16,
            active_phase_count=3,
            increase_step_a=1,
            resume_delay_s=120,
            resume_margin_percent=90.0,
            phase_switch_can_lower_floor=False,
        )

        t = NOW
        result = None
        for elapsed in range(0, 130, 10):
            t = _tick(NOW, elapsed)
            result = ctrl.tick(
                now=t,
                surplus_kw=5.0,  # comfortably above resume threshold throughout
                deadband_kw=0.2,
                current_setpoint_a=None,
                min_current_a=6,
                max_current_a=16,
                active_phase_count=3,
                increase_step_a=1,
                resume_delay_s=120,
                resume_margin_percent=90.0,
                phase_switch_can_lower_floor=False,
            )
        assert result is not None
        assert result.target_a == 6
        assert result.state == "charging"

    def test_resume_clock_resets_if_surplus_drops_below_threshold(self):
        ctrl = EVSurplusController()
        ctrl.tick(
            now=NOW,
            surplus_kw=0.0,
            deadband_kw=0.2,
            current_setpoint_a=None,
            min_current_a=6,
            max_current_a=16,
            active_phase_count=3,
            increase_step_a=1,
            resume_delay_s=120,
            resume_margin_percent=90.0,
            phase_switch_can_lower_floor=False,
        )
        # 100s of good surplus...
        ctrl.tick(
            now=_tick(NOW, 100),
            surplus_kw=5.0,
            deadband_kw=0.2,
            current_setpoint_a=None,
            min_current_a=6,
            max_current_a=16,
            active_phase_count=3,
            increase_step_a=1,
            resume_delay_s=120,
            resume_margin_percent=90.0,
            phase_switch_can_lower_floor=False,
        )
        # ...then a dip below threshold resets the resume clock
        ctrl.tick(
            now=_tick(NOW, 110),
            surplus_kw=0.0,
            deadband_kw=0.2,
            current_setpoint_a=None,
            min_current_a=6,
            max_current_a=16,
            active_phase_count=3,
            increase_step_a=1,
            resume_delay_s=120,
            resume_margin_percent=90.0,
            phase_switch_can_lower_floor=False,
        )
        # Even though 130s have elapsed since the original pause, surplus was
        # only good again for a few seconds -> must not resume yet.
        result = ctrl.tick(
            now=_tick(NOW, 130),
            surplus_kw=5.0,
            deadband_kw=0.2,
            current_setpoint_a=None,
            min_current_a=6,
            max_current_a=16,
            active_phase_count=3,
            increase_step_a=1,
            resume_delay_s=120,
            resume_margin_percent=90.0,
            phase_switch_can_lower_floor=False,
        )
        assert result.state == "paused"

    def test_holds_for_phase_switch_instead_of_pausing_when_it_can_help(self):
        ctrl = EVSurplusController()
        result = ctrl.tick(
            now=NOW,
            surplus_kw=-0.3,  # below -deadband -> decrease below the 3-phase floor
            deadband_kw=0.2,
            current_setpoint_a=6,
            min_current_a=6,
            max_current_a=16,
            active_phase_count=3,
            increase_step_a=1,
            resume_delay_s=120,
            resume_margin_percent=90.0,
            phase_switch_can_lower_floor=True,
        )
        assert result.state == "holding_for_phase_switch"
        assert result.target_a == 6
        assert ctrl.paused_at is None


class TestPhaseModeController:
    def test_switches_down_after_dwell_below_threshold(self):
        ctrl = PhaseModeController()
        ctrl.commanded_mode = 3

        # First tick below threshold: condition just started, no switch yet
        d = ctrl.decide(
            now=NOW,
            target_power_kw=1.0,
            three_phase_min_kw_value=4.14,
            hysteresis_kw=0.5,
            min_dwell_s=600,
            enabled=True,
            entity_configured=True,
            is_binary=False,
        )
        assert d.should_switch is False

        d = ctrl.decide(
            now=_tick(NOW, 600),
            target_power_kw=1.0,
            three_phase_min_kw_value=4.14,
            hysteresis_kw=0.5,
            min_dwell_s=600,
            enabled=True,
            entity_configured=True,
            is_binary=False,
        )
        assert d.should_switch is True
        assert d.commanded_mode == 1

    def test_switches_up_after_dwell_above_threshold(self):
        ctrl = PhaseModeController()
        ctrl.commanded_mode = 1

        ctrl.decide(
            now=NOW,
            target_power_kw=6.0,
            three_phase_min_kw_value=4.14,
            hysteresis_kw=0.5,
            min_dwell_s=600,
            enabled=True,
            entity_configured=True,
            is_binary=False,
        )
        d = ctrl.decide(
            now=_tick(NOW, 601),
            target_power_kw=6.0,
            three_phase_min_kw_value=4.14,
            hysteresis_kw=0.5,
            min_dwell_s=600,
            enabled=True,
            entity_configured=True,
            is_binary=False,
        )
        assert d.should_switch is True
        assert d.commanded_mode == 3

    def test_hysteresis_hold_between_thresholds(self):
        ctrl = PhaseModeController()
        ctrl.commanded_mode = 3

        # Power between 3ph_min (4.14) and 3ph_min+hysteresis (4.64) -> stays 3-phase
        d = ctrl.decide(
            now=_tick(NOW, 1000),
            target_power_kw=4.3,
            three_phase_min_kw_value=4.14,
            hysteresis_kw=0.5,
            min_dwell_s=600,
            enabled=True,
            entity_configured=True,
            is_binary=False,
        )
        assert d.should_switch is False
        assert d.commanded_mode == 3

    def test_dwell_lockout_prevents_immediate_re_switch(self):
        ctrl = PhaseModeController()
        ctrl.commanded_mode = 3

        ctrl.decide(
            now=NOW,
            target_power_kw=1.0,
            three_phase_min_kw_value=4.14,
            hysteresis_kw=0.5,
            min_dwell_s=600,
            enabled=True,
            entity_configured=True,
            is_binary=False,
        )
        d1 = ctrl.decide(
            now=_tick(NOW, 600),
            target_power_kw=1.0,
            three_phase_min_kw_value=4.14,
            hysteresis_kw=0.5,
            min_dwell_s=600,
            enabled=True,
            entity_configured=True,
            is_binary=False,
        )
        assert d1.should_switch is True
        ctrl.on_switch_success(1, _tick(NOW, 600))

        # Power immediately swings high, but we just switched — dwell lockout applies
        d2 = ctrl.decide(
            now=_tick(NOW, 610),
            target_power_kw=10.0,
            three_phase_min_kw_value=4.14,
            hysteresis_kw=0.5,
            min_dwell_s=600,
            enabled=True,
            entity_configured=True,
            is_binary=False,
        )
        assert d2.should_switch is False

        # After the dwell window has passed since the last switch, it's allowed
        d3 = ctrl.decide(
            now=_tick(NOW, 1210),
            target_power_kw=10.0,
            three_phase_min_kw_value=4.14,
            hysteresis_kw=0.5,
            min_dwell_s=600,
            enabled=True,
            entity_configured=True,
            is_binary=False,
        )
        assert d3.should_switch is True
        assert d3.commanded_mode == 3

    def test_unavailable_entity_fail_safe(self):
        ctrl = PhaseModeController()
        ctrl.commanded_mode = 3
        ctrl.on_entity_unavailable()

        d = ctrl.decide(
            now=_tick(NOW, 1000),
            target_power_kw=1.0,
            three_phase_min_kw_value=4.14,
            hysteresis_kw=0.5,
            min_dwell_s=600,
            enabled=True,
            entity_configured=True,
            is_binary=False,
        )
        assert d.should_switch is False
        assert d.commanded_mode is None
        assert ctrl.commanded_mode is None

    def test_disabled_flag_prevents_switching(self):
        ctrl = PhaseModeController()
        ctrl.commanded_mode = 3

        d = ctrl.decide(
            now=_tick(NOW, 1000),
            target_power_kw=1.0,
            three_phase_min_kw_value=4.14,
            hysteresis_kw=0.5,
            min_dwell_s=600,
            enabled=False,
            entity_configured=True,
            is_binary=False,
        )
        assert d.should_switch is False
        assert d.commanded_mode == 3  # unchanged, not reset to unknown

    def test_binary_charger_never_switches(self):
        ctrl = PhaseModeController()
        d = ctrl.decide(
            now=_tick(NOW, 1000),
            target_power_kw=1.0,
            three_phase_min_kw_value=4.14,
            hysteresis_kw=0.5,
            min_dwell_s=600,
            enabled=True,
            entity_configured=True,
            is_binary=True,
        )
        assert d.should_switch is False


class TestPhaseMinHelpers:
    def test_one_phase_min_kw(self):
        assert one_phase_min_kw(6) == 6 * 230.0 / 1000.0

    def test_three_phase_min_kw(self):
        assert three_phase_min_kw(6) == 6 * 3 * 230.0 / 1000.0
