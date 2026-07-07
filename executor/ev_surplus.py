"""
EV excess-PV surplus tracking and commanded phase-mode switching.

Pure decision logic, mirroring executor/load_balancer.py's style — no HA calls
here; the executor tick gathers SystemState, calls into this module, and
dispatches whatever setpoints/mode commands come back via executor/actions.py.
"""

import math
from dataclasses import dataclass
from datetime import datetime


def one_phase_min_kw(min_current_a: int) -> float:
    """Minimum charging power in 1-phase mode (~1.38 kW at 6A)."""
    return min_current_a * 230.0 / 1000.0


def three_phase_min_kw(min_current_a: int) -> float:
    """Minimum charging power in 3-phase mode (~4.14 kW at 6A)."""
    return min_current_a * 3 * 230.0 / 1000.0


@dataclass
class PhaseModeDecision:
    """Phase-mode controller decision for one tick."""

    commanded_mode: int | None  # 1, 3, or None ("unknown"/inactive)
    should_switch: bool  # True if the caller should write a new mode now
    reason: str


class PhaseModeController:
    """Threshold state machine for commanded 1<->3 phase switching (design D5).

    Holds per-charger state across ticks: the currently commanded phase mode,
    the last switch time (contactor-protection dwell), and how long the
    target-power condition has held continuously. `failed` is a fail-safe
    latch: once the phase-mode entity is unreadable or a write fails, no
    further switches are attempted until the caller clears it via
    `on_entity_recovered` (once the entity is confirmed readable again).
    """

    def __init__(self) -> None:
        self.commanded_mode: int | None = None
        self.last_switch_time: datetime | None = None
        self.failed: bool = False
        self._below_since: datetime | None = None
        self._above_since: datetime | None = None

    def decide(
        self,
        now: datetime,
        target_power_kw: float,
        three_phase_min_kw_value: float,
        hysteresis_kw: float,
        min_dwell_s: int,
        enabled: bool,
        entity_configured: bool,
        is_binary: bool,
    ) -> PhaseModeDecision:
        if is_binary or not enabled or not entity_configured or self.failed:
            self._below_since = None
            self._above_since = None
            return PhaseModeDecision(self.commanded_mode, False, "phase switching inactive")

        threshold = three_phase_min_kw_value + hysteresis_kw
        if target_power_kw < threshold:
            self._above_since = None
            self._below_since = self._below_since or now
            condition_elapsed = (now - self._below_since).total_seconds()
            desired = 1
        else:
            self._below_since = None
            self._above_since = self._above_since or now
            condition_elapsed = (now - self._above_since).total_seconds()
            desired = 3

        if self.commanded_mode == desired:
            return PhaseModeDecision(self.commanded_mode, False, "already at desired phase mode")

        if condition_elapsed < min_dwell_s:
            return PhaseModeDecision(
                self.commanded_mode,
                False,
                f"target power held {condition_elapsed:.0f}s < {min_dwell_s}s dwell window",
            )

        if self.last_switch_time is not None:
            since_switch = (now - self.last_switch_time).total_seconds()
            if since_switch < min_dwell_s:
                return PhaseModeDecision(
                    self.commanded_mode,
                    False,
                    f"last switch {since_switch:.0f}s ago < {min_dwell_s}s dwell window",
                )

        return PhaseModeDecision(desired, True, f"switching to {desired}-phase mode")

    def on_switch_success(self, mode: int, now: datetime) -> None:
        self.commanded_mode = mode
        self.last_switch_time = now
        self.failed = False

    def on_entity_unavailable(self) -> None:
        self.commanded_mode = None
        self.failed = True

    def on_entity_recovered(self) -> None:
        self.failed = False


@dataclass
class SurplusFeedbackResult:
    """Result of one tick of the EV surplus feedback controller."""

    target_a: int | None  # None = pause
    state: str  # "charging" | "paused" | "holding_for_phase_switch"
    reason: str


class EVSurplusController:
    """Real-time measured-surplus feedback loop for one EV charger (design D3/D4).

    Deadband + asymmetric ramp: increases are limited to `increase_step_a` per
    tick (reusing universal-load-balancing's shared ramp step); decreases
    apply immediately — clouds must never cause grid import. Sustained-
    shortfall pause/resume reuses the same resume-delay + resume-margin shape
    as the fuse balancer, applied to the charger's 1-phase minimum instead of
    the main fuse.
    """

    def __init__(self) -> None:
        self.paused_at: datetime | None = None
        self._resume_surplus_since: datetime | None = None

    def tick(
        self,
        now: datetime,
        surplus_kw: float,
        deadband_kw: float,
        current_setpoint_a: int | None,
        min_current_a: int,
        max_current_a: int,
        active_phase_count: int,
        increase_step_a: int,
        resume_delay_s: int,
        resume_margin_percent: float,
        phase_switch_can_lower_floor: bool,
    ) -> SurplusFeedbackResult:
        if current_setpoint_a is None:
            # Not currently charging: mirror the fuse balancer's own "resume at
            # floor" convention (no 0 -> floor ramp) — either enough surplus
            # exists to start at the floor, or it doesn't and we wait/pause.
            # A charger that was never paused may start the instant surplus
            # suffices; one that *is* paused must still clear the resume
            # delay + margin gate below — sufficiency alone must not bypass it.
            if surplus_kw > deadband_kw:
                raw_a = math.floor(surplus_kw * 1000 / (230 * max(1, active_phase_count)))
            else:
                raw_a = 0
            raw_a = max(0, min(raw_a, max_current_a))

            if self.paused_at is None:
                if raw_a >= min_current_a:
                    self._resume_surplus_since = None
                    return SurplusFeedbackResult(
                        min_current_a, "charging", "Starting at floor — surplus supports it"
                    )

                if phase_switch_can_lower_floor:
                    self._resume_surplus_since = None
                    return SurplusFeedbackResult(
                        None,
                        "holding_for_phase_switch",
                        "Insufficient surplus at current phase mode — holding while phase switch may help",
                    )

            return self._pause_or_wait_for_resume(
                now, surplus_kw, min_current_a, resume_delay_s, resume_margin_percent
            )

        # Currently charging: deadband + asymmetric ramp (increases ramped,
        # decreases immediate — clouds must never cause grid import).
        baseline_a = current_setpoint_a
        if surplus_kw > deadband_kw or surplus_kw < -deadband_kw:
            delta_a = math.floor(surplus_kw * 1000 / (230 * max(1, active_phase_count)))
            desired_a = baseline_a + delta_a
        else:
            desired_a = baseline_a  # within deadband: hold

        desired_a = max(0, min(desired_a, max_current_a))

        if desired_a > baseline_a:
            # Increase-slow ramp (shared with universal-load-balancing)
            target_a = min(desired_a, baseline_a + max(1, increase_step_a))
        else:
            # Decrease immediately — never draw from the grid
            target_a = desired_a

        if target_a >= min_current_a:
            self.paused_at = None
            self._resume_surplus_since = None
            return SurplusFeedbackResult(target_a, "charging", "Surplus feedback within floor")

        # Setpoint would fall below the floor.
        if phase_switch_can_lower_floor:
            # Give the phase-mode controller time to switch to 1-phase, which
            # lowers the floor's kW equivalent; hold at the floor meanwhile
            # rather than pausing.
            self.paused_at = None
            self._resume_surplus_since = None
            return SurplusFeedbackResult(
                min_current_a,
                "holding_for_phase_switch",
                "Below floor at current phase mode — holding while phase switch may help",
            )

        return self._pause_or_wait_for_resume(
            now, surplus_kw, min_current_a, resume_delay_s, resume_margin_percent
        )

    def _pause_or_wait_for_resume(
        self,
        now: datetime,
        surplus_kw: float,
        min_current_a: int,
        resume_delay_s: int,
        resume_margin_percent: float,
    ) -> SurplusFeedbackResult:
        one_phase_floor_kw = one_phase_min_kw(min_current_a)
        resume_threshold_kw = one_phase_floor_kw * (1 + resume_margin_percent / 100.0)

        if self.paused_at is None:
            self.paused_at = now
            self._resume_surplus_since = None
            return SurplusFeedbackResult(
                None,
                "paused",
                f"Surplus insufficient to sustain {min_current_a}A floor — pausing",
            )

        if surplus_kw >= resume_threshold_kw:
            self._resume_surplus_since = self._resume_surplus_since or now
            elapsed = (now - self._resume_surplus_since).total_seconds()
            if elapsed >= resume_delay_s:
                self.paused_at = None
                self._resume_surplus_since = None
                return SurplusFeedbackResult(
                    min_current_a, "charging", "Surplus recovered — resuming at floor"
                )
            return SurplusFeedbackResult(
                None,
                "paused",
                f"Surplus recovering ({elapsed:.0f}s / {resume_delay_s}s to resume)",
            )

        self._resume_surplus_since = None
        paused_elapsed = (now - self.paused_at).total_seconds()
        return SurplusFeedbackResult(
            None, "paused", f"Waiting for surplus to recover (paused {paused_elapsed:.0f}s ago)"
        )
