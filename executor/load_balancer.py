"""
Real-time per-phase load balancing (main fuse protection).

Pure decision logic — no HA calls here. The executor tick gathers SystemState,
calls into this module, and dispatches whatever setpoints/commands come back
via the existing ActionDispatcher paths (executor/actions.py).
"""

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from backend.core.ev_power import DEFAULT_NOMINAL_VOLTAGE_V

from .config import LoadBalancingConfig

_CURRENT_UNITS = {"a", "amp", "amps", "ampere", "amperes"}
_POWER_W_UNITS = {"w", "watt", "watts"}
_POWER_KW_UNITS = {"kw", "kilowatt", "kilowatts"}


def classify_phase_sensor_unit(unit: str | None, device_class: str | None = None) -> str:
    """Classify a phase grid sensor's reading as current or power.

    Primary signal is `unit_of_measurement` (ground truth for what the entity
    actually reports); `device_class` is only consulted when the unit itself
    is missing or unrecognized. Returns one of "current", "power_w",
    "power_kw", or "unrecognized" — callers must treat "unrecognized" as a
    hard validation error, never a silent guess (fuse-protection input).
    """
    normalized_unit = (unit or "").strip().lower()
    if normalized_unit in _CURRENT_UNITS:
        return "current"
    if normalized_unit in _POWER_W_UNITS:
        return "power_w"
    if normalized_unit in _POWER_KW_UNITS:
        return "power_kw"

    normalized_class = (device_class or "").strip().lower()
    if normalized_class == "current":
        return "current"
    if normalized_class == "power":
        return "power_w"

    return "unrecognized"


def power_to_current_a(power_w: float, voltage_v: float) -> float:
    """Convert a power reading (W) to current (A) assuming ~unity power factor."""
    if voltage_v <= 0:
        return 0.0
    return power_w / voltage_v


# Tolerance for float noise when rounding planned kW up to whole amps.
_AMPS_EPSILON = 1e-6

# Quick re-fit anti-flap back-off (load-balancer-graceful-degradation D17).
# A pause within REFIT_FLAP_WINDOW_S of a re-fit lengthens the next confirm
# window one step (resume_confirm_s -> 30 s -> 120 s, never shorter than
# resume_confirm_s); a pause after a longer stable run starts over at step 0.
REFIT_BACKOFF_STEPS_S: tuple[int, ...] = (0, 30, 120)
REFIT_FLAP_WINDOW_S = 600


def planned_kw_to_amps(
    planned_kw: float,
    active_phase_count: int,
    min_current_a: int,
    max_current_a: int,
    voltage_v: float = DEFAULT_NOMINAL_VOLTAGE_V,
) -> int | None:
    """Translate a planned charging power (kW) into an ampere setpoint.

    amps = ceil(planned_kw * 1000 / (voltage_v * active_phase_count)), clamped to
    max_current_a, so the commanded power is never below the planned power. A
    small epsilon keeps exact multiples (e.g. 4.14 kW on 3 phases = 6 A) from
    rounding up. Returns None when the result would be below min_current_a —
    the caller should pause charging rather than command a setpoint below the
    charger's minimum.
    """
    if active_phase_count <= 0 or planned_kw <= 0 or voltage_v <= 0:
        return None

    amps = math.ceil(planned_kw * 1000 / (voltage_v * active_phase_count) - _AMPS_EPSILON)
    amps = min(amps, max_current_a)

    if amps < min_current_a:
        return None

    return amps


@dataclass
class EVBalancerInput:
    """Per-tick balancer input for one type="current" EV charger.

    Give-way position is the entry's index in the ordered list passed to
    `tick()` (built from load_balancing.give_way_order — top gives way first).
    """

    charger_id: str
    phases: list[int]
    current_setpoint_a: int | None  # None = not currently charging
    planner_target_a: int | None  # None = plan does not want this charger charging
    min_current_a: int
    max_current_a: int
    # Effective baseline (settled measured draw, see ev-measured-draw) that
    # reductions, holds and relief accounting start from. None = use
    # current_setpoint_a.
    effective_draw_a: int | None = None
    # Grid phase the charger uses in 1-phase mode (ev_chargers[].phase_1_line).
    phase_1_line: int = 1
    # The engine's verdict that a 1-phase relief switch could be executed this
    # tick: phase switching enabled with an entity, controller not failed,
    # currently 3-phase, and phase_switch_min_dwell_s elapsed since the last
    # switch. False for chargers without phase switching (ladder unchanged).
    # Also gates the quick re-fit's switch to 1-phase (on [phase_1_line])
    # while paused (D17).
    relief_available: bool = False

    def __post_init__(self) -> None:
        if self.effective_draw_a is None:
            self.effective_draw_a = self.current_setpoint_a


@dataclass
class EVBalancerOutput:
    """Balancer decision for one EV charger. `target_a=None` means stop/paused."""

    charger_id: str
    target_a: int | None
    state: str  # "idle" | "throttling" | "paused" | "stale_fallback"
    reason: str = ""
    # Degradation-ladder step 2: at the floor, overloaded only on phases the
    # 1-phase line does not use — the engine should switch to 1-phase this
    # tick (the charger is held at min_current_a meanwhile).
    relief_1p_requested: bool = False
    # Quick re-fit from a pause (D17): the charger resumes at target_a only
    # if the 1-phase switch in relief_1p_requested is actually applied this
    # tick; otherwise the engine must keep it paused (see abort_refit).
    refit_from_pause: bool = False


@dataclass
class ShedLoadInput:
    """A configured on/off balanced load (water heater, custom entity, or a
    binary-type EV charger declared in load_balancing.loads). Give-way position
    is the entry's index in the ordered list passed to `tick()`."""

    load_id: str
    device_type: str
    phases: list[int]


@dataclass
class ShedLoadOutput:
    """Balancer decision for one on/off load: shed=True means actuate its off state."""

    load_id: str
    device_type: str
    shed: bool
    reason: str = ""


@dataclass
class LoadBalancerStatus:
    """Full per-tick balancer result, suitable for logging/status surfaces."""

    enabled: bool
    state: str  # "disabled" | "idle" | "throttling" | "shedding" | "paused" | "stale_fallback"
    reason: str
    main_fuse_a: int | None
    phase_current_a: dict[int, float]
    phase_headroom_a: dict[int, float]
    ev_outputs: list[EVBalancerOutput] = field(default_factory=lambda: [])
    shed_outputs: list[ShedLoadOutput] = field(default_factory=lambda: [])


class LoadBalancer:
    """Real-time per-phase fuse protection guard.

    Holds anti-flap state (pause timestamps, stale timers, shed times) between
    ticks. `tick()` is pure — it takes a snapshot of measured phase currents
    plus an ordered list of give-way entries (built from
    load_balancing.give_way_order — top gives way first) and returns capped
    setpoints and shed decisions; it never calls Home Assistant itself.

    Give-way resolution is a single top-down pass: each entry drawing on an
    overloaded phase gives way fully before the next entry is touched. A
    charger entry gives way by immediate setpoint reduction toward its floor
    (its draw change is folded into a running headroom pool, so an entry
    further down only gives way for whatever deficit remains), then pauses —
    pausing is position-aware: it only happens once no entry above the charger
    on that phase can still give way. A shed entry gives way by switching off;
    its relief is measured on subsequent ticks, so entries below it on the
    same phase(s) hold for one tick rather than over-reacting.

    Restore runs in exact reverse list order (the last entry to give way is
    restored first): a shed load after resume_delay_s + margin, a paused
    charger through the quick re-fit (confirm window + back-off, D17); at
    most one shed load is reconnected per tick so each restore's load is
    measured before the next.
    """

    def __init__(self, config: LoadBalancingConfig):
        self.config = config
        self._ev_paused_at: dict[str, datetime] = {}
        self._ev_stale_since: dict[str, datetime] = {}
        # Currently-shed loads: load_id -> shed timestamp (+ human reason).
        # Restore order comes from reverse list position, not insertion order.
        self._shed_at: dict[str, datetime] = {}
        self._shed_reason: dict[str, str] = {}
        # Charger at its floor with negative headroom since (pause debounce).
        self._ev_overload_since: dict[str, datetime] = {}
        # Phases each charger drew on last tick (detects a phase-set expansion,
        # e.g. the return from 1-phase to 3-phase).
        self._ev_last_phases: dict[str, frozenset[int]] = {}
        # Per-phase rolling (timestamp, grid amps, own chargers' draw amps)
        # samples over ramp_up_window_s, and when the current unbroken run of
        # fresh samples started.
        self._samples: dict[int, deque[tuple[datetime, float, float]]] = {}
        self._fresh_since: dict[int, datetime] = {}
        # Quick re-fit (D17): since when the paused charger's current mode /
        # 1-phase alternative has continuously fitted, when it last re-fitted,
        # and its back-off step.
        self._ev_fit_since: dict[str, datetime] = {}
        self._ev_fit_1p_since: dict[str, datetime] = {}
        self._ev_last_refit_at: dict[str, datetime] = {}
        self._ev_refit_level: dict[str, int] = {}

    # --- Quick re-fit (D17) -----------------------------------------------

    def refit_confirm_s(self, charger_id: str) -> int:
        """Confirm window currently required before a paused charger re-fits."""
        level = min(self._ev_refit_level.get(charger_id, 0), len(REFIT_BACKOFF_STEPS_S) - 1)
        return max(self.config.resume_confirm_s, REFIT_BACKOFF_STEPS_S[level])

    def abort_refit(self, charger_id: str, now: datetime) -> None:
        """The engine could not apply a re-fit's 1-phase switch: the charger
        stays paused and the confirm window starts over (no back-off step)."""
        self._ev_paused_at[charger_id] = now
        self._ev_last_refit_at.pop(charger_id, None)
        self._ev_fit_since.pop(charger_id, None)
        self._ev_fit_1p_since.pop(charger_id, None)

    def _clear_fit_timers(self, charger_id: str) -> None:
        self._ev_fit_since.pop(charger_id, None)
        self._ev_fit_1p_since.pop(charger_id, None)

    # --- Averaged sensing (ramp-up path) ---------------------------------

    def _update_samples(
        self,
        now: datetime,
        phase_current: dict[int, float],
        updated_at: dict[int, datetime],
        own_draw: dict[int, float],
    ) -> None:
        """Feed this tick's readings into the per-phase rolling buffers.

        own_draw is the balancer's own chargers' draw per phase this tick; it
        is stored with the grid reading so the averaged path can average the
        rest of the house while counting the chargers at their current draw
        (a ramp is never hidden by the averaging lag).

        A stale or missing phase drops its buffer: increases on it stay
        blocked until a full window of fresh samples has accumulated again.
        """
        window = self.config.ramp_up_window_s
        for phase in (1, 2, 3):
            if self._is_stale(phase, phase_current, updated_at, now):
                self._samples.pop(phase, None)
                self._fresh_since.pop(phase, None)
                continue
            buf = self._samples.setdefault(phase, deque())
            self._fresh_since.setdefault(phase, now)
            buf.append((now, abs(phase_current[phase]), own_draw.get(phase, 0.0)))
            while buf and (now - buf[0][0]).total_seconds() > window:
                buf.popleft()

    def averaged_current_a(self, phase: int, now: datetime) -> float | None:
        """Averaged phase current for the ramp-up path.

        The rest of the house (grid minus the balancer's own chargers) is
        averaged over ramp_up_window_s; the chargers count at their latest
        draw. A one-tick house spike therefore only moves this value by its
        share of the window, while the chargers' own ramp is seen at once.

        None until the phase has an unbroken run of fresh samples spanning
        the full window (after startup or a stale-sensor episode).
        """
        since = self._fresh_since.get(phase)
        buf = self._samples.get(phase)
        if since is None or not buf:
            return None
        if (now - since).total_seconds() < self.config.ramp_up_window_s:
            return None
        house_avg = sum(grid - own for _, grid, own in buf) / len(buf)
        return house_avg + buf[-1][2]

    def _target_threshold_a(self) -> float:
        fuse = self.config.main_fuse_a or 0
        return fuse * self.config.target_margin_percent / 100.0

    def three_phase_fits(
        self,
        three_phase_lines: list[int],
        current_lines: list[int],
        current_draw_a: float,
        min_current_a: int,
        now: datetime,
    ) -> bool:
        """Whether a charger held in 1-phase may return to 3-phase.

        Every line the charger would use in 3-phase mode must have a full
        averaging window and room for the charger at min_current_a (where it
        restarts after the switch) within the target margin. On the lines it
        already draws on, its current draw is swapped for min_current_a.
        """
        if not self.config.enabled or self.config.main_fuse_a is None:
            return True
        threshold = self._target_threshold_a()
        for line in three_phase_lines:
            avg = self.averaged_current_a(line, now)
            if avg is None:
                return False
            own = current_draw_a if line in current_lines else 0.0
            if avg - own + min_current_a > threshold + _AMPS_EPSILON:
                return False
        return True

    def _is_stale(
        self,
        phase: int,
        phase_current_a: dict[int, float],
        grid_current_updated_at: dict[int, datetime],
        now: datetime,
    ) -> bool:
        if phase not in phase_current_a:
            return True
        updated_at = grid_current_updated_at.get(phase)
        if updated_at is None:
            return True
        return (now - updated_at).total_seconds() > self.config.sensor_stale_after_s

    def _resolve_ev(
        self,
        ev: EVBalancerInput,
        binding_phases: list[int],
        now: datetime,
        phase_current: dict[int, float],
        updated_at: dict[int, datetime],
        pool_headroom: dict[int, float],
        main_fuse_a: int,
        avg_ok: Callable[[list[int], float], bool],
        resume_blocked: bool = False,
        hold_for_relief: bool = False,
    ) -> tuple[EVBalancerOutput, bool, bool, bool]:
        """Resolve one EV charger's decision against the current headroom pool.

        resume_blocked: a give-way entry below this charger is still paused or
        shed — restore happens in exact reverse list order, so this charger
        may not resume yet. hold_for_relief: a shed entry above this charger
        gave way this tick on a shared phase; its relief is unmeasured, so
        hold the current setpoint instead of reducing or pausing — unless a
        binding phase is above severe_overload_percent, which always pauses
        immediately (D16).

        Returns (output, is_stale, is_paused, is_throttling) — the three
        flags feed the tick-level `any_*` aggregates that drive the overall
        balancer state.
        """
        stale_phases = [
            p for p in binding_phases if self._is_stale(p, phase_current, updated_at, now)
        ]

        if stale_phases:
            self._ev_overload_since.pop(ev.charger_id, None)
            # A re-fit needs an unbroken run of fresh readings (D17).
            self._clear_fit_timers(ev.charger_id)
            stale_since = self._ev_stale_since.setdefault(ev.charger_id, now)
            stale_elapsed = (now - stale_since).total_seconds()
            if stale_elapsed >= self.config.resume_delay_s:
                # Escalating stale_fallback -> a full pause: record the pause
                # start (if not already paused) so that once the sensor comes
                # back fresh, recovery goes through the same quick re-fit
                # (confirm window within the target margin) as an overload
                # pause, instead of resuming immediately. Not counted as a
                # flap for the re-fit back-off (setdefault: don't reset an
                # already-running pause clock on every stale tick).
                self._ev_paused_at.setdefault(ev.charger_id, now)
                return (
                    EVBalancerOutput(
                        ev.charger_id,
                        None,
                        "paused",
                        f"Phase sensor(s) {stale_phases} stale for "
                        f"{int(stale_elapsed)}s — charging paused",
                    ),
                    True,
                    True,
                    False,
                )
            return (
                EVBalancerOutput(
                    ev.charger_id,
                    ev.min_current_a,
                    "stale_fallback",
                    f"Phase sensor(s) {stale_phases} stale — forcing {ev.min_current_a}A",
                ),
                True,
                False,
                False,
            )

        self._ev_stale_since.pop(ev.charger_id, None)
        binding_headroom = min(pool_headroom.get(p, main_fuse_a) for p in binding_phases)

        if ev.current_setpoint_a is None or binding_headroom >= 0:
            # Not drawing, or no longer overloaded: the pause debounce resets.
            self._ev_overload_since.pop(ev.charger_id, None)

        if ev.current_setpoint_a is None:
            if ev.planner_target_a is None:
                self._ev_paused_at.pop(ev.charger_id, None)
                self._clear_fit_timers(ev.charger_id)
                return EVBalancerOutput(ev.charger_id, None, "idle"), False, False, False

            paused_at = self._ev_paused_at.get(ev.charger_id)
            if paused_at is not None:
                return self._refit_paused(
                    ev, binding_phases, now, pool_headroom, main_fuse_a, paused_at, resume_blocked
                )
            self._clear_fit_timers(ev.charger_id)
            if binding_headroom < ev.min_current_a:
                if hold_for_relief and not self._severe_phases(
                    binding_phases, phase_current, main_fuse_a
                ):
                    # A higher-listed shed entry gave way this tick; don't
                    # start the pause clock before its relief is measured.
                    return (
                        EVBalancerOutput(
                            ev.charger_id,
                            None,
                            "paused",
                            "Waiting for shed relief before starting to charge",
                        ),
                        False,
                        True,
                        False,
                    )
                self._ev_paused_at[ev.charger_id] = now
                return (
                    EVBalancerOutput(
                        ev.charger_id,
                        None,
                        "paused",
                        f"Insufficient headroom to start charging "
                        f"({binding_headroom:.1f}A < {ev.min_current_a}A floor)",
                    ),
                    False,
                    True,
                    False,
                )

            return (
                EVBalancerOutput(
                    ev.charger_id, ev.min_current_a, "throttling", "Resuming at floor"
                ),
                False,
                False,
                True,
            )

        # Currently charging at ev.current_setpoint_a
        setpoint = ev.current_setpoint_a
        if binding_headroom < 0:
            # Reduce/hold from what the car actually draws, never above the
            # commanded setpoint.
            draw = min(
                setpoint, ev.effective_draw_a if ev.effective_draw_a is not None else setpoint
            )
            severe = (
                self._severe_phases(binding_phases, phase_current, main_fuse_a)
                if hold_for_relief
                else []
            )
            if severe:
                # A severe overload outranks the hold for unmeasured shed
                # relief: pause at once (D16). Without a hold, the normal
                # reduce/degrade ladder below applies unchanged.
                return self._pause_charging(
                    ev,
                    now,
                    f"Phase(s) {severe} above {self.config.severe_overload_percent:g}% of the "
                    f"{main_fuse_a}A fuse — pausing immediately",
                )
            if hold_for_relief and setpoint >= ev.min_current_a:
                # A higher-listed shed entry gave way this tick on a shared
                # phase — hold the setpoint until its relief is measured
                # instead of reducing (or pausing) below it. Never above the
                # planned charging level or the prior setpoint, never below
                # min_current_a.
                hold_ceiling = (
                    min(ev.max_current_a, ev.planner_target_a)
                    if ev.planner_target_a is not None
                    else draw
                )
                hold_target = min(setpoint, max(ev.min_current_a, min(draw, hold_ceiling)))
                return (
                    EVBalancerOutput(
                        ev.charger_id,
                        hold_target,
                        "throttling",
                        f"Holding {hold_target}A — waiting for shed relief on overloaded phase(s)",
                    ),
                    False,
                    False,
                    True,
                )
            new_target = math.floor(draw + binding_headroom)
            if new_target < ev.min_current_a:
                return self._degrade_at_floor(
                    ev, binding_phases, now, phase_current, pool_headroom, main_fuse_a
                )
            # Still above the floor: not a floor overload, no debounce running.
            self._ev_overload_since.pop(ev.charger_id, None)
            return (
                EVBalancerOutput(
                    ev.charger_id,
                    new_target,
                    "throttling",
                    f"Reduced {setpoint}A -> {new_target}A (headroom {binding_headroom:.1f}A)"
                    + (f", drawing {draw}A" if draw != setpoint else ""),
                ),
                False,
                False,
                True,
            )

        if ev.planner_target_a is None:
            self._ev_paused_at.pop(ev.charger_id, None)
            self._clear_fit_timers(ev.charger_id)
            return (
                EVBalancerOutput(ev.charger_id, None, "idle", "Plan ended"),
                False,
                False,
                False,
            )

        ceiling = min(ev.max_current_a, ev.planner_target_a)
        if setpoint >= ceiling:
            return (
                EVBalancerOutput(ev.charger_id, ceiling, "idle", "At target"),
                False,
                False,
                False,
            )

        # An increase must fit both paths: the averaged target gate below and
        # the momentary headroom against main_fuse_a, so a raise can never
        # itself push a phase over the fuse on this tick's reading.
        step = min(self.config.increase_step_a, math.floor(binding_headroom + _AMPS_EPSILON))
        new_target = min(setpoint + step, ceiling)
        if new_target > setpoint and avg_ok(binding_phases, new_target - setpoint):
            at_target = new_target >= ceiling
            return (
                EVBalancerOutput(
                    ev.charger_id,
                    new_target,
                    "idle" if at_target else "throttling",
                    f"Ramping {setpoint}A -> {new_target}A toward {ev.planner_target_a}A",
                ),
                False,
                False,
                not at_target,
            )

        return (
            EVBalancerOutput(
                ev.charger_id,
                setpoint,
                "throttling",
                f"Holding {setpoint}A — averaged phase current near the "
                f"{self.config.target_margin_percent:g}% target, waiting to ramp "
                f"toward {ev.planner_target_a}A",
            ),
            False,
            False,
            True,
        )

    def _fit_amps(self, lines: list[int], pool_headroom: dict[int, float], main_fuse_a: int) -> int:
        """Whole amps a charger could start at on `lines` right now: the
        momentary headroom (after this tick's other give-way decisions) kept
        within target_margin_percent of the fuse, on the tightest line."""
        margin_reserve = main_fuse_a - self._target_threshold_a()
        room = min(pool_headroom.get(p, main_fuse_a) - margin_reserve for p in lines)
        return math.floor(room + _AMPS_EPSILON)

    def _refit_paused(
        self,
        ev: EVBalancerInput,
        binding_phases: list[int],
        now: datetime,
        pool_headroom: dict[int, float],
        main_fuse_a: int,
        paused_at: datetime,
        resume_blocked: bool,
    ) -> tuple[EVBalancerOutput, bool, bool, bool]:
        """Quick re-fit of a balancer-paused charger (D17).

        Each tick checks, on the momentary reading within the target margin,
        whether the current phase mode has room for min_current_a on every
        binding phase and whether the 1-phase alternative (phase_1_line only,
        offered while relief_available) has. Once one of them has fitted
        continuously for the confirm window, the charger resumes — in its
        current mode when that fits, else switched to 1-phase — at the
        largest whole amps that fit, capped by the planner target. It then
        ramps through the normal averaged gate.
        """
        floor = ev.min_current_a
        cid = ev.charger_id
        paused_for = int((now - paused_at).total_seconds())
        confirm_s = self.refit_confirm_s(cid)

        current_amps = self._fit_amps(binding_phases, pool_headroom, main_fuse_a)
        if current_amps >= floor:
            self._ev_fit_since.setdefault(cid, now)
        else:
            self._ev_fit_since.pop(cid, None)
        one_phase_offered = (
            ev.relief_available and len(binding_phases) > 1 and ev.phase_1_line in binding_phases
        )
        one_phase_amps = (
            self._fit_amps([ev.phase_1_line], pool_headroom, main_fuse_a)
            if one_phase_offered
            else 0
        )
        if one_phase_offered and one_phase_amps >= floor:
            self._ev_fit_1p_since.setdefault(cid, now)
        else:
            self._ev_fit_1p_since.pop(cid, None)

        def confirmed(since: datetime | None) -> bool:
            return since is not None and (now - since).total_seconds() >= confirm_s

        use_current = confirmed(self._ev_fit_since.get(cid))
        use_1p = not use_current and confirmed(self._ev_fit_1p_since.get(cid))
        if not (use_current or use_1p) or resume_blocked:
            if resume_blocked and (use_current or use_1p):
                reason = "Waiting to resume — a lower-listed give-way entry must restore first"
            elif self._ev_fit_since.get(cid) or self._ev_fit_1p_since.get(cid):
                since = self._ev_fit_since.get(cid) or self._ev_fit_1p_since[cid]
                reason = (
                    f"Waiting to resume — room for {floor}A for "
                    f"{int((now - since).total_seconds())}s of {confirm_s}s "
                    f"(paused {paused_for}s ago)"
                )
            else:
                reason = (
                    f"Waiting to resume — no room for {floor}A within the "
                    f"{self.config.target_margin_percent:g}% target (paused {paused_for}s ago)"
                )
            return EVBalancerOutput(cid, None, "paused", reason), False, True, False

        ceiling = min(ev.max_current_a, ev.planner_target_a or floor)
        amps = max(floor, min(current_amps if use_current else one_phase_amps, ceiling))
        self._ev_paused_at.pop(cid, None)
        self._clear_fit_timers(cid)
        self._ev_last_refit_at[cid] = now
        if use_current:
            reason = f"Resuming at {amps}A after {confirm_s}s within limits (paused {paused_for}s)"
            return EVBalancerOutput(cid, amps, "throttling", reason), False, False, True
        reason = (
            f"Resuming 1-phase on L{ev.phase_1_line} at {amps}A — "
            f"{'/'.join(f'L{p}' for p in binding_phases if p != ev.phase_1_line)} "
            f"still without room for {floor}A (paused {paused_for}s)"
        )
        return (
            EVBalancerOutput(
                cid,
                amps,
                "throttling",
                reason,
                relief_1p_requested=True,
                refit_from_pause=True,
            ),
            False,
            False,
            True,
        )

    def _degrade_at_floor(
        self,
        ev: EVBalancerInput,
        binding_phases: list[int],
        now: datetime,
        phase_current: dict[int, float],
        pool_headroom: dict[int, float],
        main_fuse_a: int,
    ) -> tuple[EVBalancerOutput, bool, bool, bool]:
        """The overload cannot be absorbed above min_current_a.

        Ladder: severe overload pauses at once; otherwise hold the floor for
        pause_debounce_s; then request 1-phase relief where it helps and is
        available; otherwise pause.
        """
        floor = ev.min_current_a
        severe = self._severe_phases(binding_phases, phase_current, main_fuse_a)
        if severe:
            return self._pause_charging(
                ev,
                now,
                f"Phase(s) {severe} above {self.config.severe_overload_percent:g}% of the "
                f"{main_fuse_a}A fuse — pausing immediately",
            )

        if ev.current_setpoint_a is not None and ev.current_setpoint_a < floor:
            # Holding the floor would raise the setpoint during an overload.
            return self._pause_charging(
                ev,
                now,
                f"Overload with setpoint {ev.current_setpoint_a}A below the {floor}A floor — pausing",
            )

        overload_since = self._ev_overload_since.setdefault(ev.charger_id, now)
        elapsed = (now - overload_since).total_seconds()
        if elapsed < self.config.pause_debounce_s:
            return (
                EVBalancerOutput(
                    ev.charger_id,
                    floor,
                    "throttling",
                    f"Holding {floor}A floor — overload for {elapsed:.0f}s, pausing after "
                    f"{self.config.pause_debounce_s}s",
                ),
                False,
                False,
                True,
            )

        overloaded = [p for p in binding_phases if pool_headroom.get(p, main_fuse_a) < 0]
        if (
            ev.relief_available
            and len(binding_phases) > 1
            and ev.phase_1_line in binding_phases
            and overloaded
            and ev.phase_1_line not in overloaded
        ):
            return (
                EVBalancerOutput(
                    ev.charger_id,
                    floor,
                    "throttling",
                    f"1-phase on L{ev.phase_1_line} — relieving "
                    + ", ".join(f"L{p}" for p in overloaded),
                    relief_1p_requested=True,
                ),
                False,
                False,
                True,
            )

        return self._pause_charging(
            ev,
            now,
            f"Overload on {', '.join(f'L{p}' for p in overloaded) or 'charger phases'} "
            f"lasted {elapsed:.0f}s at the {floor}A floor — pausing",
        )

    def _severe_phases(
        self, binding_phases: list[int], phase_current: dict[int, float], main_fuse_a: int
    ) -> list[int]:
        """Phases whose momentary reading exceeds severe_overload_percent of the fuse."""
        threshold = main_fuse_a * self.config.severe_overload_percent / 100.0
        return [p for p in binding_phases if abs(phase_current.get(p, 0.0)) > threshold]

    def _pause_charging(
        self, ev: EVBalancerInput, now: datetime, reason: str
    ) -> tuple[EVBalancerOutput, bool, bool, bool]:
        cid = ev.charger_id
        self._ev_overload_since.pop(cid, None)
        self._ev_paused_at[cid] = now
        self._clear_fit_timers(cid)
        # Anti-flap back-off (D17): pausing again soon after a re-fit makes
        # the next confirm window longer; after a stable run it starts over.
        last_refit = self._ev_last_refit_at.pop(cid, None)
        if last_refit is not None and (now - last_refit).total_seconds() < REFIT_FLAP_WINDOW_S:
            self._ev_refit_level[cid] = min(
                self._ev_refit_level.get(cid, 0) + 1, len(REFIT_BACKOFF_STEPS_S) - 1
            )
        else:
            self._ev_refit_level.pop(cid, None)
        if self._ev_refit_level.get(cid):
            reason += f" (next resume after {self.refit_confirm_s(cid)}s within limits)"
        return EVBalancerOutput(ev.charger_id, None, "paused", reason), False, True, False

    def tick(
        self,
        now: datetime,
        grid_current_a: dict[int, float] | None,
        grid_current_updated_at: dict[int, datetime] | None,
        entries: list[EVBalancerInput | ShedLoadInput],
    ) -> LoadBalancerStatus:
        """Run one balancer tick over the ordered give-way entries (top first)."""
        main_fuse_a = self.config.main_fuse_a
        if not self.config.enabled or main_fuse_a is None:
            return LoadBalancerStatus(
                enabled=False,
                state="disabled",
                reason="Load balancing disabled or unconfigured",
                main_fuse_a=main_fuse_a,
                phase_current_a={},
                phase_headroom_a={},
            )

        phase_current = grid_current_a or {}
        updated_at = grid_current_updated_at or {}
        headroom = {p: main_fuse_a - phase_current[p] for p in phase_current}
        # Running headroom pool consumed/replenished as each charger is
        # resolved top-down (see class docstring); kept separate from
        # `headroom` (raw, used for restore checks) so single-charger
        # behavior is unaffected by this bookkeeping.
        pool_headroom = dict(headroom)
        own_draw: dict[int, float] = {}
        for entry in entries:
            if isinstance(entry, EVBalancerInput) and entry.current_setpoint_a is not None:
                draw = min(
                    entry.current_setpoint_a,
                    entry.effective_draw_a
                    if entry.effective_draw_a is not None
                    else entry.current_setpoint_a,
                )
                for p in entry.phases or [1, 2, 3]:
                    own_draw[p] = own_draw.get(p, 0.0) + draw
        self._update_samples(now, phase_current, updated_at, own_draw)
        target_threshold = self._target_threshold_a()
        # Averaged-path increases already granted this tick, per phase, so two
        # entries cannot both spend the same room below the target.
        granted_increase: dict[int, float] = {}

        def avg_ok(phases: list[int], add_a: float) -> bool:
            """Projected averaged current stays within the target margin."""
            for p in phases:
                avg = self.averaged_current_a(p, now)
                if avg is None:
                    return False
                if avg + granted_increase.get(p, 0.0) + add_a > target_threshold + _AMPS_EPSILON:
                    return False
            return True

        # Drop shed state for loads no longer configured (order self-heals at
        # config load; a dangling id here would block restores forever).
        valid_shed_ids = {e.load_id for e in entries if isinstance(e, ShedLoadInput)}
        for shed_id in list(self._shed_at):
            if shed_id not in valid_shed_ids:
                self._shed_at.pop(shed_id, None)
                self._shed_reason.pop(shed_id, None)

        def has_given_way(entry: EVBalancerInput | ShedLoadInput) -> bool:
            if isinstance(entry, EVBalancerInput):
                return entry.charger_id in self._ev_paused_at
            return entry.load_id in self._shed_at

        # --- Restore pass: exact reverse list order — the last entry to give
        # way restores first. Runs before the give-way pass so a charger can
        # resume in the same tick its lower-listed shed load reconnects. At
        # most one shed load reconnects per tick (each restore's real draw is
        # measured before the next); a still-given-way entry blocks every
        # restore above it.
        shed_restore_done = False
        for entry in reversed(entries):
            if not has_given_way(entry):
                continue
            if isinstance(entry, EVBalancerInput):
                # Charger resume is decided in the give-way pass (quick
                # re-fit, D17); until it resumes it blocks restores
                # of entries above it.
                break
            if shed_restore_done:
                break
            shed_at = self._shed_at[entry.load_id]
            elapsed = (now - shed_at).total_seconds()
            healthy = all(headroom.get(p, main_fuse_a) >= 0 for p in entry.phases)
            if elapsed >= self.config.resume_delay_s and healthy and avg_ok(entry.phases, 0.0):
                self._shed_at.pop(entry.load_id, None)
                self._shed_reason.pop(entry.load_id, None)
                shed_restore_done = True
            else:
                break

        # --- Give-way pass: top-down; each entry gives way fully before the
        # next is touched. Chargers fold their draw change into the pool
        # (known relief); a shed action marks its phases pending so entries
        # below hold one tick while its relief is measured.
        outputs_by_id: dict[str, EVBalancerOutput] = {}
        pending_relief_phases: set[int] = set()
        any_stale_fallback = False
        any_paused = False
        any_throttling = False

        for idx, entry in enumerate(entries):
            if isinstance(entry, EVBalancerInput):
                binding_phases = entry.phases or [1, 2, 3]
                resume_blocked = any(has_given_way(e) for e in entries[idx + 1 :])
                hold_for_relief = bool(set(binding_phases) & pending_relief_phases)
                output, is_stale, is_paused, is_throttling = self._resolve_ev(
                    entry,
                    binding_phases,
                    now,
                    phase_current,
                    updated_at,
                    pool_headroom,
                    main_fuse_a,
                    avg_ok,
                    resume_blocked=resume_blocked,
                    hold_for_relief=hold_for_relief,
                )
                # A charger whose phase set grew (e.g. back from 1-phase to
                # 3-phase) restarts at its floor on the new phases; ramping
                # from there goes through the averaged target gate.
                last_phases = self._ev_last_phases.get(entry.charger_id)
                self._ev_last_phases[entry.charger_id] = frozenset(binding_phases)
                if (
                    last_phases
                    and entry.current_setpoint_a is not None
                    and set(binding_phases) - last_phases
                    and output.target_a is not None
                    and output.target_a > entry.min_current_a
                ):
                    output = EVBalancerOutput(
                        entry.charger_id,
                        entry.min_current_a,
                        "throttling",
                        f"Now drawing on phases {sorted(binding_phases)} — restarting at "
                        f"{entry.min_current_a}A floor",
                    )
                    is_throttling = True
                any_stale_fallback = any_stale_fallback or is_stale
                any_paused = any_paused or is_paused
                any_throttling = any_throttling or is_throttling
                outputs_by_id[entry.charger_id] = output

                # Fold this charger's resulting draw change into the pool so
                # the next entry sees the deficit that actually remains.
                # A reduction relieves only what the car actually drew
                # (effective baseline); a hold or raise keeps the setpoint-
                # based accounting.
                setpoint = entry.current_setpoint_a or 0
                previous_draw = (
                    entry.effective_draw_a if entry.effective_draw_a is not None else setpoint
                )
                new_draw = output.target_a or 0
                if new_draw >= setpoint:
                    delta = setpoint - new_draw
                else:
                    delta = max(0, previous_draw - new_draw)
                if delta:
                    for p in binding_phases:
                        pool_headroom[p] = pool_headroom.get(p, main_fuse_a) + delta
                raised_by = new_draw - setpoint
                if raised_by > 0:
                    for p in binding_phases:
                        granted_increase[p] = granted_increase.get(p, 0.0) + raised_by
                continue

            # Shed entry
            if entry.load_id in self._shed_at or not entry.phases:
                continue  # already given way (exhausted) / not actionable
            overloaded = [p for p in entry.phases if pool_headroom.get(p, main_fuse_a) < 0]
            if overloaded and not (set(entry.phases) & pending_relief_phases):
                self._shed_at[entry.load_id] = now
                self._shed_reason[entry.load_id] = (
                    f"Shed: phase(s) {overloaded} overloaded, every higher give-way entry exhausted"
                )
                pending_relief_phases |= set(entry.phases)

        ev_inputs = [e for e in entries if isinstance(e, EVBalancerInput)]
        ev_outputs = [outputs_by_id[e.charger_id] for e in ev_inputs]
        shed_outputs = [
            ShedLoadOutput(
                e.load_id,
                e.device_type,
                e.load_id in self._shed_at,
                reason=self._shed_reason.get(e.load_id, ""),
            )
            for e in entries
            if isinstance(e, ShedLoadInput)
        ]

        if any_paused:
            state = "paused"
        elif self._shed_at:
            state = "shedding"
        elif any_stale_fallback:
            state = "stale_fallback"
        elif any_throttling:
            state = "throttling"
        else:
            state = "idle"

        return LoadBalancerStatus(
            enabled=True,
            state=state,
            reason="; ".join(o.reason for o in ev_outputs if o.reason) or "Within limits",
            main_fuse_a=main_fuse_a,
            phase_current_a=dict(phase_current),
            phase_headroom_a=headroom,
            ev_outputs=ev_outputs,
            shed_outputs=shed_outputs,
        )
