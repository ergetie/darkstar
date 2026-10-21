"""
Real-time per-phase load balancing (main fuse protection).

Pure decision logic — no HA calls here. The executor tick gathers SystemState,
calls into this module, and dispatches whatever setpoints/commands come back
via the existing ActionDispatcher paths (executor/actions.py).
"""

import logging
import math
import statistics
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from backend.core.ev_power import DEFAULT_NOMINAL_VOLTAGE_V

from .config import LoadBalancingConfig

logger = logging.getLogger(__name__)

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


# Fresh-sample tracking (coordinated-ramping D6): how many sensor update gaps
# are kept to estimate the cadence, the plausible gap range, and the cap on the
# actuator response timeout (two detected sensor intervals, at most this long).
CADENCE_HISTORY = 8
CADENCE_MAX_GAP_S = 120.0
RESPONSE_TIMEOUT_MAX_S = 15.0
# Fallback cadence when no sensor interval has been observed yet: one tick.
DEFAULT_TICK_S = 5.0

# Flap back-off key of the battery (charger ids are user-defined strings).
BATTERY_FLAP_KEY = "__battery__"

# Bounded decision trace (coordinated-ramping D14).
BALANCER_TRACE_TICKS = 600


@dataclass(frozen=True)
class Relief:
    """Relief one phase needs this tick: amperes to shed and whether the
    reduction must not wait (severe overload)."""

    amount_a: float = 0.0
    urgent: bool = False


def relief_needed(momentary_a: float, main_fuse_a: float, severe_percent: float) -> Relief:
    """Default overload trigger (coordinated-ramping D15): instant threshold.

    A phase needs relief as soon as its momentary reading exceeds the fuse
    rating; it is urgent above severe_overload_percent. This is the only
    place overload is detected — a proportional timing model can replace it
    (see `LoadBalancer(relief_trigger=...)`) without touching the ledger, the
    room gate or the give-way ladder.
    """
    excess = momentary_a - main_fuse_a
    if excess <= 0:
        return Relief()
    return Relief(excess, momentary_a > main_fuse_a * severe_percent / 100.0)


ReliefTrigger = Callable[[float, float, float], Relief]


@dataclass
class _PendingItem:
    amps: dict[int, float]
    value: float
    tolerance: float
    at: datetime


class PendingLedger:
    """Cross-tick ledger of granted-but-not-yet-measured increases (D1).

    One item per entry key holds the amperes granted per phase, the granted
    value (in the entry's own unit) and when. Every room check subtracts the
    ledger so a lagging average cannot hide a granted step. An item expires
    when the measured value has caught up with the granted value (within
    `tolerance`) or after `timeout_s`; a reduction of the entry clears it.
    """

    def __init__(self) -> None:
        self._items: dict[str, _PendingItem] = {}

    def grant(
        self,
        key: str,
        amps_per_phase: dict[int, float],
        value: float,
        tolerance: float,
        now: datetime,
    ) -> None:
        item = self._items.get(key)
        if item is None:
            self._items[key] = _PendingItem(dict(amps_per_phase), value, tolerance, now)
            return
        for phase, amps in amps_per_phase.items():
            item.amps[phase] = item.amps.get(phase, 0.0) + amps
        item.value = value
        item.tolerance = tolerance
        item.at = now

    def clear(self, key: str) -> None:
        self._items.pop(key, None)

    def expire(self, now: datetime, timeout_s: float, measured: dict[str, float | None]) -> None:
        for key, item in list(self._items.items()):
            value = measured.get(key)
            if (value is not None and value >= item.value - item.tolerance) or (
                now - item.at
            ).total_seconds() >= timeout_s:
                del self._items[key]

    def pending_a(self, phase: int, exclude: str | None = None) -> float:
        return sum(item.amps.get(phase, 0.0) for key, item in self._items.items() if key != exclude)

    def age_s(self, key: str, now: datetime) -> float | None:
        item = self._items.get(key)
        return None if item is None else (now - item.at).total_seconds()

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {
            key: {"amps": {str(p): round(a, 2) for p, a in item.amps.items()}, "value": item.value}
            for key, item in self._items.items()
        }


class BalancerTrace:
    """Bounded in-memory ring buffer of per-tick balancer snapshots (D14)."""

    def __init__(self, size: int = BALANCER_TRACE_TICKS) -> None:
        self._ticks: deque[dict[str, Any]] = deque(maxlen=size)

    def add(self, snapshot: dict[str, Any]) -> None:
        self._ticks.append(snapshot)

    def note_written(self, key: str, value: Any) -> None:
        """Record the value finally dispatched for an entry on the latest tick."""
        if self._ticks:
            self._ticks[-1].setdefault("written", {})[key] = value

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self._ticks)

    def __len__(self) -> int:
        return len(self._ticks)


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
    # The engine's goal-risk verdict before the tick (ev-charging-losses D7):
    # slow 1-phase relief is lossy, so it is offered only when pausing would
    # put the EV goal at risk. Evaluation fails open (True).
    goal_at_risk: bool = False
    # The current plan slot is solar-surplus charging for this charger: pausing
    # would export that power, so lossy 1-phase still beats it. Unreadable → False.
    surplus_slot: bool = False
    # Raw measured draw (A), no settle fallback: used only to detect that a
    # granted step has shown up (pending ledger). None = unmeasured.
    measured_a: float | None = None
    return_to_phases: list[int] | None = None

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
    return_3p_requested: bool = False


@dataclass
class ShedLoadInput:
    """A configured on/off balanced load (water heater, custom entity, or a
    binary-type EV charger declared in load_balancing.loads). Give-way position
    is the entry's index in the ordered list passed to `tick()`."""

    load_id: str
    device_type: str
    phases: list[int]
    # Restore power (W) resolved by the engine from the live sensor, the
    # configured power, else None (worst case: a full main fuse on its
    # phases), and where it came from: "sensor" | "configured" | "worst_case".
    power_w: float | None = None
    power_source: str = "worst_case"
    # Minimum seconds a shed load stays off before it may be restored.
    min_off_s: int = 0
    min_on_s: int = 0
    requested_on: bool | None = None
    current_on: bool | None = None


@dataclass
class ShedLoadOutput:
    """Balancer decision for one on/off load: shed=True means actuate its off state."""

    load_id: str
    device_type: str
    shed: bool
    reason: str = ""
    power_w: float | None = None
    power_source: str = "worst_case"


# The house battery's inverter is assumed to be 3-phase (battery-load-balancing D2).
BATTERY_PHASES: tuple[int, ...] = (1, 2, 3)


@dataclass
class BatteryBalancerInput:
    """Per-tick balancer input for the house battery's planned grid charging
    (give_way_order entry kind="battery"). Powers are AC watts.

    The battery draws evenly on all three phases (3-phase inverter, D2). Only
    the grid-sourced part of the charge can be reduced (D4): the engine
    passes it as reducible_w (min of the applied cap and grid import — a
    measured charge that lags the cap must not block a cut; it is passed
    separately as measured_w).
    """

    planned_w: float  # Charge power the controller decided this tick
    applied_cap_w: float  # Cap dispatched last tick (planned_w when none)
    reducible_w: float  # Grid-sourced charge that a cut can actually relieve
    active: bool  # mode intent is "charge" (planned grid charging)
    min_w: float  # Profile minimum charge value, in watts
    phases: list[int] = field(default_factory=lambda: list(BATTERY_PHASES))
    # Measured charge power (W), None when unmeasured. Detects the response to
    # a cut / settling of a granted step; never blocks a cut.
    measured_w: float | None = None
    # Profile round step (W): tolerance for "the granted step has settled".
    step_w: float = 0.0


@dataclass
class BatteryBalancerOutput:
    """Balancer decision for battery grid charging. cap_w is never above
    planned_w; state "paused" means grid charging is held off this tick."""

    planned_w: float
    cap_w: float
    state: str  # "idle" | "throttling" | "paused"
    reason: str = ""
    phases: list[int] = field(default_factory=lambda: list(BATTERY_PHASES))
    # A cut was ordered this tick (the write layer bypasses pacing/deadband).
    urgent: bool = False


BalancerEntry = EVBalancerInput | ShedLoadInput | BatteryBalancerInput


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
    battery_output: BatteryBalancerOutput | None = None


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
    restored first): a shed load after resume_delay_s and its minimum off
    time once the shared room fits its power, a paused charger through the
    quick re-fit (confirm window + back-off, D17); at most one shed load is
    reconnected per tick so each restore's load is measured before the next.

    Coordinated ramping: every increase (EV ramp, battery ramp and plan
    step-up, resumes, restores, return to 3-phase) goes through one room
    gate that subtracts a cross-tick ledger of granted-but-unmeasured steps,
    and ramp steps are granted rearmost entry first. Reductions act once per
    fresh sensor sample and then wait for the actuator's response (see
    `_response_timeout_s`); overload detection is the pluggable
    `relief_needed` trigger.
    """

    def __init__(self, config: LoadBalancingConfig, relief_trigger: ReliefTrigger | None = None):
        self.config = config
        # The single place overload is detected (D15); see relief_needed().
        self._relief_trigger: ReliefTrigger = relief_trigger or relief_needed
        self._ev_paused_at: dict[str, datetime] = {}
        self._ev_stale_since: dict[str, datetime] = {}
        # Currently-shed loads: load_id -> shed timestamp (+ human reason).
        # Restore order comes from reverse list position, not insertion order.
        self._shed_at: dict[str, datetime] = {}
        self._shed_reason: dict[str, str] = {}
        self._switch_on_at: dict[str, datetime] = {}
        self._plan_switch_seen: set[str] = set()
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
        # Ramp-up hold-off: when each charger's setpoint was last reduced
        # (throttle, floor degrade, 1-phase relief). No raise for
        # ramp_up_window_s after it, so the averaged window first flushes
        # the pre-reduction samples. Cleared on plan end and pause.
        self._ev_reduced_at: dict[str, datetime] = {}
        # Battery grid charging (battery-load-balancing): when the cap was
        # last cut (ramp-up hold-off), when grid charging was paused, and
        # since when its phases have fitted the minimum charge (resume).
        self._battery_reduced_at: datetime | None = None
        self._battery_paused_at: datetime | None = None
        self._battery_fit_since: datetime | None = None
        self._battery_stale_since: datetime | None = None
        # Coordinated ramping: ledger of granted increases, per-phase fresh
        # sample tracking (D6), decision trace and the last logged decisions.
        self._ledger = PendingLedger()
        self.trace = BalancerTrace()
        self._last_sample_ts: dict[int, datetime] = {}
        self._last_sample_value: dict[int, float] = {}
        self._sample_gaps: dict[int, deque[float]] = {}
        self._fresh_phases: set[int] = set()
        # Phase -> when a cut was ordered on it and its response is awaited.
        self._awaiting: dict[int, datetime] = {}
        self._awaiting_targets: dict[int, dict[str, float]] = {}
        self._awaiting_baseline: dict[int, dict[str, float | None]] = {}
        self._blocked_cut_phases: set[int] = set()
        self._last_tick_at: datetime | None = None
        self._tick_s = DEFAULT_TICK_S
        self._last_decisions: dict[str, tuple[str, str]] = {}
        # Tick-scoped state (reset every tick): this tick's relief per phase,
        # the headroom pool, deferred ramp requests, charger debounce phases,
        # measured phase voltage.
        self._relief: dict[int, Relief] = {}
        self._pool: dict[int, float] = {}
        self._ramp_requests: dict[str, Callable[[], None]] = {}
        self._debounce_phases: set[int] = set()
        self._voltage: dict[int, float] = {}

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

    def _note_pause(self, key: str, now: datetime) -> None:
        """Anti-flap back-off (D17, shared with the battery): pausing again soon
        after a re-fit lengthens the next confirm window one step; after a
        stable run it starts over."""
        last_refit = self._ev_last_refit_at.pop(key, None)
        if last_refit is not None and (now - last_refit).total_seconds() < REFIT_FLAP_WINDOW_S:
            self._ev_refit_level[key] = min(
                self._ev_refit_level.get(key, 0) + 1, len(REFIT_BACKOFF_STEPS_S) - 1
            )
        else:
            self._ev_refit_level.pop(key, None)

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
        self._fresh_phases = set()
        for phase in (1, 2, 3):
            if self._is_stale(phase, phase_current, updated_at, now):
                self._samples.pop(phase, None)
                self._fresh_since.pop(phase, None)
                self._last_sample_ts.pop(phase, None)
                continue
            self._track_sample(phase, updated_at[phase], phase_current[phase])
            buf = self._samples.setdefault(phase, deque())
            self._fresh_since.setdefault(phase, now)
            buf.append((now, phase_current[phase], own_draw.get(phase, 0.0)))
            while buf and (now - buf[0][0]).total_seconds() > window:
                buf.popleft()

    def _track_sample(self, phase: int, sample_ts: datetime, value: float) -> None:
        """Note whether this tick brought a new sensor sample for `phase` (D6)
        and learn the sensor's update cadence from the gaps between samples."""
        last = self._last_sample_ts.get(phase)
        if last is not None and sample_ts == last and self._last_sample_value.get(phase) == value:
            return
        self._fresh_phases.add(phase)
        self._last_sample_ts[phase] = sample_ts
        self._last_sample_value[phase] = value
        if last is not None:
            gap = (sample_ts - last).total_seconds()
            if 0 < gap <= CADENCE_MAX_GAP_S:
                self._sample_gaps.setdefault(phase, deque(maxlen=CADENCE_HISTORY)).append(gap)

    def _response_timeout_s(self, phase: int) -> float:
        """How long to wait for a cut to show in the measurement: two detected
        sensor intervals (one tick when unknown), at most 15 s."""
        gaps = self._sample_gaps.get(phase)
        cadence = statistics.median(gaps) if gaps else self._tick_s
        return min(RESPONSE_TIMEOUT_MAX_S, 2 * cadence)

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

    # --- Shared room gate (D2) ---------------------------------------------

    def _volts(self, phase: int) -> float:
        """Measured phase voltage when fresh, else the nominal voltage (D11)."""
        return self._voltage.get(phase) or self.config.nominal_voltage_v

    def _w_per_a(self, phases: list[int]) -> float:
        """Watts per ampere drawn evenly on every one of `phases`."""
        return sum(self._volts(p) for p in phases)

    def _room_a(self, phases: list[int], now: datetime, whole_phase: bool = False) -> float | None:
        """Room for a new increase on the tightest of `phases`.

        Averaged current plus every pending (granted, unmeasured) increase
        must stay within the target margin, and the momentary headroom after
        this tick's cuts minus the pending increases must stay non-negative.
        Everything granted earlier this tick is already in the ledger, so the
        budget is shared by all increase paths. `whole_phase` measures against
        the full fuse rating instead (unknown-power load: the phase must be
        free). None while a phase lacks a full window of fresh samples.
        """
        fuse = self.config.main_fuse_a or 0
        ceiling = float(fuse) if whole_phase else self._target_threshold_a()
        room = math.inf
        for p in phases:
            avg = self.averaged_current_a(p, now)
            if avg is None:
                return None
            pending = self._ledger.pending_a(p)
            room = min(
                room,
                ceiling - avg - pending,
                self._pool.get(p, float(fuse)) - pending,
            )
        return room

    def _pacing_ok(self, key: str, now: datetime) -> bool:
        """Adaptive step pacing (D10): the next increase of an actuator waits
        until its previous step settled in the measurement (the ledger item is
        gone) or `max_step_interval_s` has passed."""
        age = self._ledger.age_s(key, now)
        return age is None or age >= self.config.max_step_interval_s

    def _grant_a(
        self, key: str, phases: list[int], wanted_a: float, now: datetime, whole: bool
    ) -> float:
        """Amperes per phase an increase of `key` may take now (0 = none).

        whole=True grants whole amperes (partial steps allowed, EV current);
        otherwise the step is granted entirely or not at all. The caller
        records the grant in the ledger.
        """
        if wanted_a <= _AMPS_EPSILON or not self._pacing_ok(key, now):
            return 0.0
        room = self._room_a(phases, now)
        if room is None:
            return 0.0
        if whole:
            return float(max(0, math.floor(min(wanted_a, room) + _AMPS_EPSILON)))
        return wanted_a if room + _AMPS_EPSILON >= wanted_a else 0.0

    def _urgent_phases(self, phases: list[int]) -> list[int]:
        """Phases where the trigger demands an immediate, undebounced reduction."""
        return [p for p in phases if (r := self._relief.get(p)) is not None and r.urgent]

    def three_phase_fits(
        self,
        three_phase_lines: list[int],
        current_lines: list[int],
        current_draw_a: float,
        min_current_a: int,
        now: datetime,
        charger_id: str | None = None,
    ) -> bool:
        """Whether a charger held in 1-phase may return to 3-phase.

        Every line the charger would use in 3-phase mode must have a full
        averaging window and room for the charger at min_current_a (where it
        restarts after the switch) within the target margin. On the lines it
        already draws on, its current draw is swapped for min_current_a.
        """
        if not self.config.enabled or self.config.main_fuse_a is None:
            return True
        key = f"charger:{charger_id}" if charger_id is not None else None
        if key is not None and not self._pacing_ok(key, now):
            return False
        for line in three_phase_lines:
            wanted = max(0.0, min_current_a - (current_draw_a if line in current_lines else 0.0))
            room = self._room_a([line], now)
            if room is None or room + _AMPS_EPSILON < wanted:
                return False
        if charger_id is not None:
            # The return is a granted increase: count it until it is measured.
            self._ledger.grant(
                f"phase_return:{charger_id}",
                {p: float(min_current_a) for p in three_phase_lines if p not in current_lines},
                float(min_current_a),
                0.5,
                now,
            )
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

    def _describe_stale_phases(
        self,
        stale_phases: list[int],
        phase_current_a: dict[int, float],
        grid_current_updated_at: dict[int, datetime],
        now: datetime,
    ) -> str:
        """Name each stale phase as L1..L3 with "no reading" or the real reading age."""
        parts: list[str] = []
        for phase in stale_phases:
            updated_at = grid_current_updated_at.get(phase)
            if phase not in phase_current_a or updated_at is None:
                parts.append(f"L{phase} no reading")
            else:
                parts.append(f"L{phase} age {int((now - updated_at).total_seconds())}s")
        return ", ".join(parts)

    def _resolve_ev(
        self,
        ev: EVBalancerInput,
        binding_phases: list[int],
        now: datetime,
        phase_current: dict[int, float],
        updated_at: dict[int, datetime],
        pool_headroom: dict[int, float],
        main_fuse_a: int,
        resume_blocked: bool = False,
        hold_for_relief: bool = False,
    ) -> tuple[EVBalancerOutput, bool, bool, bool]:
        """Resolve one EV charger's decision and maintain its ramp-up
        hold-off timestamp (see _resolve_ev_decision for the decision)."""
        result = self._resolve_ev_decision(
            ev,
            binding_phases,
            now,
            phase_current,
            updated_at,
            pool_headroom,
            main_fuse_a,
            resume_blocked,
            hold_for_relief,
        )
        output = result[0]
        if output.target_a is None or (
            ev.current_setpoint_a is not None and output.target_a < ev.current_setpoint_a
        ):
            # A reduction clears the charger's pending (granted) increase.
            self._ledger.clear(f"charger:{ev.charger_id}")
            self._ledger.clear(f"phase_return:{ev.charger_id}")
        if output.target_a is None:
            # Paused, idle or plan ended: the hold-off does not carry over.
            self._ev_reduced_at.pop(ev.charger_id, None)
        elif (
            output.state == "throttling"
            and ev.current_setpoint_a is not None
            and not output.refit_from_pause
            and (output.target_a < ev.current_setpoint_a or output.relief_1p_requested)
        ):
            self._ev_reduced_at[ev.charger_id] = now
        return result

    def _resolve_ev_decision(
        self,
        ev: EVBalancerInput,
        binding_phases: list[int],
        now: datetime,
        phase_current: dict[int, float],
        updated_at: dict[int, datetime],
        pool_headroom: dict[int, float],
        main_fuse_a: int,
        resume_blocked: bool = False,
        hold_for_relief: bool = False,
    ) -> tuple[EVBalancerOutput, bool, bool, bool]:
        """Resolve one EV charger's decision against the current headroom pool.

        resume_blocked: a give-way entry below this charger is still paused or
        shed — restore happens in exact reverse list order, so this charger
        may not resume yet. hold_for_relief: relief on a shared phase is
        still unmeasured (an entry above gave way this tick, or a cut on the
        phase is awaiting its response / already acted on this sample), so
        hold the current setpoint instead of reducing or pausing — unless the
        trigger flags a binding phase urgent (above severe_overload_percent),
        which always pauses immediately (D16).

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
            stale_desc = self._describe_stale_phases(stale_phases, phase_current, updated_at, now)
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
                        f"Phase sensor(s) stale ({stale_desc}) — "
                        f"charging paused (paused for {int(stale_elapsed)}s)",
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
                    f"Phase sensor(s) stale ({stale_desc}) — forcing {ev.min_current_a}A",
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
            start_headroom = self._room_a(binding_phases, now)
            start_headroom = 0.0 if start_headroom is None else start_headroom
            if start_headroom < ev.min_current_a:
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
                        f"({start_headroom:.1f}A < {ev.min_current_a}A floor)",
                    ),
                    False,
                    True,
                    False,
                )

            self._ledger.grant(
                f"charger:{ev.charger_id}",
                {p: float(ev.min_current_a) for p in binding_phases},
                float(ev.min_current_a),
                0.5,
                now,
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
            if severe and not (set(binding_phases) & self._blocked_cut_phases):
                # A severe overload outranks the hold for unmeasured shed
                # relief: pause at once (D16). Without a hold, the normal
                # reduce/degrade ladder below applies unchanged.
                return self._pause_charging(
                    ev,
                    now,
                    f"Phase(s) {severe} above {self.config.severe_overload_percent:g}% of the "
                    f"{main_fuse_a}A fuse — pausing immediately",
                )
            if (
                hold_for_relief or set(binding_phases) & self._blocked_cut_phases
            ) and setpoint >= ev.min_current_a:
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
                        f"Holding {hold_target}A — waiting for relief to show on overloaded phase(s)",
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

        reduced_at = self._ev_reduced_at.get(ev.charger_id)
        if (
            reduced_at is not None
            and (now - reduced_at).total_seconds() < self.config.ramp_up_window_s
        ):
            # Ramp-up hold-off: the averaged window still holds samples from
            # before the reduction, so it would under-read the new load.
            return (
                EVBalancerOutput(
                    ev.charger_id,
                    setpoint,
                    "throttling",
                    f"Holding {setpoint}A — reduced "
                    f"{(now - reduced_at).total_seconds():.0f}s ago, waiting "
                    f"{self.config.ramp_up_window_s}s before ramping toward "
                    f"{ev.planner_target_a}A",
                ),
                False,
                False,
                True,
            )

        # An increase goes through the shared room gate (ledger, averaged
        # target, momentary headroom). The gate is evaluated after every entry
        # has been resolved, rearmost entry first, so the budget goes to the
        # entry that gives way last; the hold below is replaced if granted.
        hold = EVBalancerOutput(
            ev.charger_id,
            setpoint,
            "throttling",
            f"Holding {setpoint}A — averaged phase current near the "
            f"{self.config.target_margin_percent:g}% target, waiting to ramp "
            f"toward {ev.planner_target_a}A",
        )
        wanted = min(self.config.increase_step_a, ceiling - setpoint)
        key = f"charger:{ev.charger_id}"

        def ramp() -> None:
            granted = int(self._grant_a(key, binding_phases, wanted, now, whole=True))
            if granted <= 0:
                if not self._pacing_ok(key, now):
                    hold.reason = (
                        f"Holding {setpoint}A — previous step still settling, waiting to "
                        f"ramp toward {ev.planner_target_a}A"
                    )
                return
            new_target = setpoint + granted
            self._ledger.grant(
                key,
                {p: float(granted) for p in binding_phases},
                float(new_target),
                min(1.0, granted / 2),
                now,
            )
            hold.target_a = new_target
            hold.state = "idle" if new_target >= ceiling else "throttling"
            hold.reason = f"Ramping {setpoint}A -> {new_target}A toward {ev.planner_target_a}A"

        self._ramp_requests[key] = ramp
        return hold, False, False, True

    def _fit_amps(self, lines: list[int], pool_headroom: dict[int, float], main_fuse_a: int) -> int:
        """Whole amps a charger could start at on `lines` right now: the
        momentary headroom (after this tick's other give-way decisions) kept
        within target_margin_percent of the fuse, on the tightest line."""
        margin_reserve = main_fuse_a - self._target_threshold_a()
        room = min(
            pool_headroom.get(p, main_fuse_a) - margin_reserve - self._ledger.pending_a(p)
            for p in lines
        )
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
        offered while relief_available and the goal is at risk or the slot is
        surplus) has. Once one of them has fitted
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
            ev.relief_available
            and (ev.goal_at_risk or ev.surplus_slot)
            and len(binding_phases) > 1
            and ev.phase_1_line in binding_phases
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
        wanted = max(floor, min(current_amps if use_current else one_phase_amps, ceiling))
        resume_phases = binding_phases if use_current else [ev.phase_1_line]
        amps = int(self._grant_a(f"charger:{cid}", resume_phases, float(wanted), now, whole=True))
        if amps < floor:
            return (
                EVBalancerOutput(cid, None, "paused", "Waiting for shared restore room"),
                False,
                True,
                False,
            )
        self._ev_paused_at.pop(cid, None)
        self._clear_fit_timers(cid)
        self._ev_last_refit_at[cid] = now
        self._ledger.grant(
            f"charger:{cid}",
            {p: float(amps) for p in (binding_phases if use_current else [ev.phase_1_line])},
            float(amps),
            0.5,
            now,
        )
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
        pause_debounce_s; then request 1-phase relief where it helps, is
        available and the EV goal is at risk or the slot is
        solar-surplus charging; otherwise pause.
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
            # Entries below must not give way for this overload before the
            # debounce has run out (D5).
            self._debounce_phases |= set(binding_phases)
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
            and (ev.goal_at_risk or ev.surplus_slot)
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
        """Phases the trigger flags urgent (default: momentary reading above
        severe_overload_percent of the fuse)."""
        return self._urgent_phases(binding_phases)

    def _pause_charging(
        self, ev: EVBalancerInput, now: datetime, reason: str
    ) -> tuple[EVBalancerOutput, bool, bool, bool]:
        cid = ev.charger_id
        self._ev_overload_since.pop(cid, None)
        self._ev_paused_at[cid] = now
        self._clear_fit_timers(cid)
        # Anti-flap back-off (D17): pausing again soon after a re-fit makes
        # the next confirm window longer; after a stable run it starts over.
        self._note_pause(cid, now)
        if self._ev_refit_level.get(cid):
            reason += f" (next resume after {self.refit_confirm_s(cid)}s within limits)"
        return EVBalancerOutput(ev.charger_id, None, "paused", reason), False, True, False

    # --- Battery grid charging (battery-load-balancing) ------------------

    def _reset_battery(self) -> None:
        self._battery_reduced_at = None
        self._battery_paused_at = None
        self._battery_fit_since = None
        self._battery_stale_since = None
        self._ledger.clear("battery")

    def _resolve_battery(
        self,
        battery: BatteryBalancerInput,
        now: datetime,
        phase_current: dict[int, float],
        updated_at: dict[int, datetime],
        pool_headroom: dict[int, float],
        main_fuse_a: int,
        resume_blocked: bool,
        hold_for_relief: bool,
    ) -> tuple[BatteryBalancerOutput, float]:
        """Resolve the battery's grid-charge cap against the headroom pool.

        Returns (output, relief_a): relief_a is the per-phase current the
        decision actually frees on every battery phase.

        Cut (D3/D4, coordinated ramping D7): the remaining deficit on the
        tightest battery phase, spread over the three inverter phases
        (deficit x V x 3, measured voltage when known), limited to the cap
        and the grid import — a measured charge that still lags the cap never
        blocks a cut; it only limits how much relief is credited to the pool.
        Below the profile minimum, grid charging is paused for the tick.
        Raise (D6): no raise for ramp_up_window_s after a cut, then
        increase_step_a per phase through the shared room gate (also toward a
        higher plan), never above the plan. A paused battery resumes at the
        profile minimum once its phases have fitted it for the escalating
        confirm time and nothing below it is still given way. Stale phase
        (D9): minimum charge at once, pause after resume_delay_s.
        """
        phases = battery.phases or list(BATTERY_PHASES)
        planned = max(0.0, battery.planned_w)
        if not battery.active or planned <= 0:
            self._reset_battery()
            return BatteryBalancerOutput(planned, planned, "idle", "", phases), 0.0

        w_per_a = self._w_per_a(phases)
        if planned < battery.applied_cap_w:
            self._ledger.clear("battery")
        cap = max(0.0, min(battery.applied_cap_w, planned))
        if cap < battery.min_w and cap < planned and self._battery_paused_at is None:
            # The dispatched cap fell below the profile minimum (rounding):
            # grid charging was stopped, so treat the battery as paused.
            self._battery_paused_at = now
            self._note_pause(BATTERY_FLAP_KEY, now)
        if self._battery_paused_at is not None:
            cap = 0.0

        def output(new_cap: float, reason: str, urgent: bool = False) -> BatteryBalancerOutput:
            if self._battery_paused_at is not None:
                state = "paused"
            elif new_cap < planned:
                state = "throttling"
            else:
                state = "idle"
            return BatteryBalancerOutput(planned, new_cap, state, reason, phases, urgent)

        stale_phases = [p for p in phases if self._is_stale(p, phase_current, updated_at, now)]
        if stale_phases:
            self._battery_fit_since = None
            desc = self._describe_stale_phases(stale_phases, phase_current, updated_at, now)
            stale_since = self._battery_stale_since or now
            self._battery_stale_since = stale_since
            stale_elapsed = (now - stale_since).total_seconds()
            if stale_elapsed >= self.config.resume_delay_s:
                if self._battery_paused_at is None:
                    # Same recovery as an overload pause: a confirm window
                    # within the margin, not an immediate resume.
                    self._battery_paused_at = now
                self._ledger.clear("battery")
                return (
                    output(
                        0.0,
                        f"Battery: phase sensor(s) stale ({desc}) — grid charging paused "
                        f"(paused for {int(stale_elapsed)}s)",
                    ),
                    0.0,
                )
            if self._battery_paused_at is not None:
                return output(0.0, f"Battery: phase sensor(s) stale ({desc}) — paused"), 0.0
            floor_cap = min(planned, battery.min_w)
            if cap <= floor_cap:
                return output(cap, ""), 0.0
            self._ledger.clear("battery")
            self._battery_reduced_at = now
            return (
                output(
                    floor_cap,
                    f"Battery: phase sensor(s) stale ({desc}) — forcing {floor_cap / 1000:.1f} kW",
                    urgent=True,
                ),
                0.0,
            )
        self._battery_stale_since = None

        binding = min(pool_headroom.get(p, main_fuse_a) for p in phases)
        if binding < 0:
            self._battery_fit_since = None
            if self._battery_paused_at is not None:
                return output(0.0, "Battery: grid charging paused — phases still overloaded"), 0.0
            if set(phases) & self._blocked_cut_phases or (
                hold_for_relief and not self._severe_phases(phases, phase_current, main_fuse_a)
            ):
                return (
                    output(cap, "Battery: holding grid charging — waiting for relief to show"),
                    0.0,
                )
            reducible = max(0.0, min(battery.reducible_w, cap))
            if reducible <= 0:
                # PV covers the battery: cutting would relieve nothing.
                return output(cap, ""), 0.0
            cut = min(-binding * w_per_a, reducible)
            new_cap = cap - cut
            self._battery_reduced_at = now
            self._ledger.clear("battery")
            measured = battery.measured_w
            if new_cap < battery.min_w:
                # Below the profile minimum: stop grid charging for the tick.
                # All of the grid-sourced charge that is really drawn is relieved.
                self._battery_paused_at = now
                self._note_pause(BATTERY_FLAP_KEY, now)
                relieved = reducible if measured is None else min(reducible, measured)
                reason = (
                    f"Battery: grid charging paused — {cap / 1000:.1f} kW cut below the "
                    f"{battery.min_w / 1000:.1f} kW minimum (headroom {binding:.1f}A)"
                )
                if self._ev_refit_level.get(BATTERY_FLAP_KEY):
                    reason += (
                        f" (next resume after "
                        f"{self.refit_confirm_s(BATTERY_FLAP_KEY)}s within limits)"
                    )
                return output(0.0, reason, urgent=True), relieved / w_per_a
            # Credit the pool only with what the battery really draws above
            # the new cap; a lagging measurement must not hide the overload.
            relieved = cut if measured is None else min(cut, max(0.0, measured - new_cap))
            return (
                output(
                    new_cap,
                    f"Battery: grid charge capped {cap / 1000:.1f} -> {new_cap / 1000:.1f} kW "
                    f"(headroom {binding:.1f}A)",
                    urgent=True,
                ),
                relieved / w_per_a,
            )

        if self._battery_paused_at is not None:
            min_a = battery.min_w / w_per_a
            room_a = self._fit_amps(phases, pool_headroom, main_fuse_a)
            if room_a + _AMPS_EPSILON >= min_a and room_a > 0:
                if self._battery_fit_since is None:
                    self._battery_fit_since = now
            else:
                self._battery_fit_since = None
            fit_for = (
                (now - self._battery_fit_since).total_seconds()
                if self._battery_fit_since is not None
                else None
            )
            confirm_s = self.refit_confirm_s(BATTERY_FLAP_KEY)
            if fit_for is None or fit_for < confirm_s:
                reason = (
                    f"Battery: waiting to resume grid charging — room for "
                    f"{battery.min_w / 1000:.1f} kW for {int(fit_for)}s of {confirm_s}s"
                    if fit_for is not None
                    else f"Battery: waiting to resume grid charging — no room for "
                    f"{battery.min_w / 1000:.1f} kW within the "
                    f"{self.config.target_margin_percent:g}% target"
                )
                return output(0.0, reason), 0.0
            if resume_blocked:
                return (
                    output(
                        0.0,
                        "Battery: waiting to resume — a lower-listed give-way entry "
                        "must restore first",
                    ),
                    0.0,
                )
            # Resume at the profile minimum; the rest is reached by gated ramp
            # steps (never the full momentary headroom at once).
            new_cap = min(planned, battery.min_w)
            if self._grant_a("battery", phases, new_cap / w_per_a, now, whole=False) <= 0:
                return output(0.0, "Battery: waiting for shared restore room"), 0.0
            self._battery_paused_at = None
            self._battery_fit_since = None
            self._ev_last_refit_at[BATTERY_FLAP_KEY] = now
            self._ledger.grant(
                "battery",
                dict.fromkeys(phases, new_cap / w_per_a),
                new_cap,
                max(battery.step_w, 0.0),
                now,
            )
            return (
                output(new_cap, f"Battery: resuming grid charging at {new_cap / 1000:.1f} kW"),
                0.0,
            )

        if cap >= planned:
            self._battery_reduced_at = None
            return output(planned, ""), 0.0

        reduced_at = self._battery_reduced_at
        if reduced_at is not None:
            since = (now - reduced_at).total_seconds()
            if since < self.config.ramp_up_window_s:
                return (
                    output(
                        cap,
                        f"Battery: holding {cap / 1000:.1f} kW — capped {since:.0f}s ago, "
                        f"waiting {self.config.ramp_up_window_s}s before ramping toward "
                        f"{planned / 1000:.1f} kW",
                    ),
                    0.0,
                )

        step_a = float(self.config.increase_step_a)
        new_cap = min(cap + step_a * w_per_a, planned)
        raise_a = (new_cap - cap) / w_per_a
        hold = output(
            cap,
            f"Battery: holding {cap / 1000:.1f} kW — averaged phase current near the "
            f"{self.config.target_margin_percent:g}% target",
        )

        def ramp() -> None:
            if self._grant_a("battery", phases, raise_a, now, whole=False) <= 0:
                if not self._pacing_ok("battery", now):
                    hold.reason = (
                        f"Battery: holding {cap / 1000:.1f} kW — previous step still settling"
                    )
                return
            self._ledger.grant(
                "battery",
                dict.fromkeys(phases, raise_a),
                new_cap,
                min(battery.step_w, (new_cap - cap) / 2),
                now,
            )
            if new_cap >= planned:
                self._battery_reduced_at = None
            hold.cap_w = new_cap
            hold.state = "idle" if new_cap >= planned else "throttling"
            hold.reason = (
                f"Battery: ramping {cap / 1000:.1f} -> {new_cap / 1000:.1f} kW toward "
                f"{planned / 1000:.1f} kW"
            )

        if raise_a > 0:
            self._ramp_requests["battery"] = ramp
        return hold, 0.0

    def _restore_need(self, entry: ShedLoadInput) -> tuple[float, bool]:
        """(amperes per phase a restore needs, whole-phase-free rule) (D4).

        The load's power is spread evenly over its phases. Unknown power is
        counted as a full main fuse on its phases: it restores only when the
        whole phase is free.
        """
        if entry.power_w is not None and entry.power_source != "worst_case":
            return max(0.0, entry.power_w) / self._w_per_a(entry.phases), False
        return float(self.config.main_fuse_a or 0), True

    def tick(
        self,
        now: datetime,
        grid_current_a: dict[int, float] | None,
        grid_current_updated_at: dict[int, datetime] | None,
        entries: list[BalancerEntry],
        phase_voltage_v: dict[int, float] | None = None,
    ) -> LoadBalancerStatus:
        """Run one balancer tick over the ordered give-way entries (top first).

        phase_voltage_v: fresh measured grid voltage per phase (battery W/A
        conversion); phases without one use the nominal voltage.
        """
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
        self._voltage = {p: v for p, v in (phase_voltage_v or {}).items() if v and v > 0}
        if self._last_tick_at is not None:
            dt = (now - self._last_tick_at).total_seconds()
            if 0 < dt <= CADENCE_MAX_GAP_S:
                self._tick_s = dt
        self._last_tick_at = now
        self._ramp_requests = {}
        self._debounce_phases = set()

        # Overload detection is isolated in the trigger (D15). A phase needs
        # relief when the trigger says so; the pool is negative exactly then.
        self._relief = {
            p: self._relief_trigger(
                phase_current[p], float(main_fuse_a), self.config.severe_overload_percent
            )
            for p in phase_current
        }
        headroom = {p: main_fuse_a - phase_current[p] for p in phase_current}
        # Running headroom pool consumed/replenished as each charger is
        # resolved top-down (see class docstring); kept separate from
        # `headroom` (raw, used for restore checks) so single-charger
        # behavior is unaffected by this bookkeeping.
        pool_headroom = {
            p: (-r.amount_a if r.amount_a > 0 else max(0.0, headroom[p]))
            for p, r in self._relief.items()
        }
        self._pool = pool_headroom
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
            elif isinstance(entry, BatteryBalancerInput) and entry.active:
                # Like the chargers: counted at its latest draw (measured, else
                # the applied cap) so the averaging lag never hides its ramp.
                battery_phases = entry.phases or list(BATTERY_PHASES)
                w_per_a = self._w_per_a(battery_phases)
                battery_w = (
                    min(entry.applied_cap_w, entry.measured_w)
                    if entry.measured_w is not None
                    else entry.applied_cap_w
                )
                for p in battery_phases:
                    own_draw[p] = own_draw.get(p, 0.0) + max(0.0, battery_w) / w_per_a
        self._update_samples(now, phase_current, updated_at, own_draw)

        # Granted increases expire when measured (or by timeout).
        measured: dict[str, float | None] = {}
        for entry in entries:
            if isinstance(entry, EVBalancerInput):
                measured[f"charger:{entry.charger_id}"] = entry.measured_a
            elif isinstance(entry, BatteryBalancerInput):
                measured["battery"] = entry.measured_w
        self._ledger.expire(now, self.config.pending_timeout_s, measured)

        # Fresh-sample rule (D6): an overloaded phase is acted on once per
        # sensor sample, and a further cut waits for the actuator's response.
        # Gated phases are treated like a shed's unmeasured relief: entries
        # holding their setpoint instead of cutting again (unless urgent).
        overloaded_phases = {p for p, r in self._relief.items() if r.amount_a > 0}
        for p in list(self._awaiting):
            if p not in overloaded_phases:
                del self._awaiting[p]
        pending_relief_phases: set[int] = set()
        for p in overloaded_phases:
            awaiting_since = self._awaiting.get(p)
            targets = self._awaiting_targets.get(p, {})
            responded = bool(targets) and all(
                (value := measured.get(key)) is not None
                and value <= target + _AMPS_EPSILON
                and (
                    (baseline := self._awaiting_baseline.get(p, {}).get(key)) is None
                    or abs(value - baseline) > _AMPS_EPSILON
                )
                for key, target in targets.items()
            )
            if (
                awaiting_since is not None
                and not responded
                and (now - awaiting_since).total_seconds() < self._response_timeout_s(p)
            ):
                pending_relief_phases.add(p)
                continue
            self._awaiting.pop(p, None)
            if p not in self._fresh_phases:
                pending_relief_phases.add(p)
        # Phases waiting only on the response of an earlier tick's cut (not on
        # relief ordered this tick) never hold a shed back when urgent.
        self._blocked_cut_phases = set(pending_relief_phases)
        carried_gate: set[int] = set()

        # Drop shed state for loads no longer configured (order self-heals at
        # config load; a dangling id here would block restores forever).
        valid_shed_ids = {e.load_id for e in entries if isinstance(e, ShedLoadInput)}
        for shed_id in list(self._shed_at):
            if shed_id not in valid_shed_ids:
                self._shed_at.pop(shed_id, None)
                self._shed_reason.pop(shed_id, None)
        restore_notes: dict[str, str] = {}

        if not any(isinstance(e, BatteryBalancerInput) for e in entries):
            self._reset_battery()

        def has_given_way(entry: BalancerEntry) -> bool:
            if isinstance(entry, EVBalancerInput):
                return entry.charger_id in self._ev_paused_at
            if isinstance(entry, BatteryBalancerInput):
                return entry.active and self._battery_paused_at is not None
            # A planned-off entry has no restore demand. It must not hold
            # higher-listed entries hostage to a restore its plan forbids.
            return entry.requested_on is not False and entry.load_id in self._shed_at

        # Plan switching shares the restore gate and the same anti-wear clocks.
        # First managed start is conservatively treated as off; existing draw
        # still appears in the phase samples, so this cannot overbook room.
        for entry in entries:
            if not isinstance(entry, ShedLoadInput) or entry.requested_on is None:
                continue
            if entry.load_id not in self._plan_switch_seen:
                self._plan_switch_seen.add(entry.load_id)
                if entry.current_on is True:
                    self._switch_on_at[entry.load_id] = now
                else:
                    self._shed_at.setdefault(entry.load_id, now)
            if not entry.requested_on and entry.load_id not in self._shed_at:
                on_at = self._switch_on_at.get(entry.load_id, now)
                if (now - on_at).total_seconds() >= entry.min_on_s:
                    self._shed_at[entry.load_id] = now
                    self._shed_reason[entry.load_id] = "Planned off"
                    self._ledger.clear(f"shed:{entry.load_id}")

        shed_restore_done = False

        def restore_shed(entry: ShedLoadInput, index: int) -> None:
            nonlocal shed_restore_done
            if (
                entry.requested_on is False
                or entry.load_id not in self._shed_at
                or shed_restore_done
            ):
                return
            if any(has_given_way(e) for e in entries[index + 1 :]):
                return
            shed_at = self._shed_at[entry.load_id]
            elapsed = (now - shed_at).total_seconds()
            healthy = all(headroom.get(p, main_fuse_a) >= 0 for p in entry.phases)
            if elapsed < max(self.config.resume_delay_s, entry.min_off_s) or not healthy:
                return
            need_a, whole_phase = self._restore_need(entry)
            room = self._room_a(entry.phases, now, whole_phase)
            if room is not None and room + _AMPS_EPSILON >= need_a:
                self._shed_at.pop(entry.load_id, None)
                self._shed_reason.pop(entry.load_id, None)
                self._switch_on_at[entry.load_id] = now
                self._ledger.grant(
                    f"shed:{entry.load_id}",
                    # Unknown power counts as a full fuse rating until it expires.
                    dict.fromkeys(entry.phases, float(main_fuse_a) if whole_phase else need_a),
                    0.0,
                    0.0,
                    now,
                )
                shed_restore_done = True
            else:
                restore_notes[entry.load_id] = (
                    "restore waits for the whole phase to be free (load power unknown)"
                    if whole_phase
                    else f"restore waits for {need_a:.1f}A of room "
                    f"({entry.power_source} power {((entry.power_w or 0) / 1000):.1f} kW)"
                )
                return

        # --- Give-way pass: top-down; each entry gives way fully before the
        # next is touched. Chargers fold their draw change into the pool
        # (known relief); a shed action marks its phases pending so entries
        # below hold while its relief is measured.
        outputs_by_id: dict[str, EVBalancerOutput] = {}
        battery_output: BatteryBalancerOutput | None = None
        cut_phases: set[int] = set()
        any_stale_fallback = False
        any_paused = False
        throttling_keys: set[str] = set()

        # Reductions retain give-way order. Every other decision (including
        # resumes, restores and ramps) spends the shared budget in reverse order.
        indexed = list(enumerate(entries))

        def needs_relief(entry: BalancerEntry) -> bool:
            return any(pool_headroom.get(p, main_fuse_a) < 0 for p in entry.phases)

        reduction_entries = [(i, e) for i, e in indexed if needs_relief(e)]
        increase_entries = [(i, e) for i, e in reversed(indexed) if not needs_relief(e)]
        for idx, entry in reduction_entries + increase_entries:
            if isinstance(entry, BatteryBalancerInput):
                battery_phases = entry.phases or list(BATTERY_PHASES)
                battery_output, relief_a = self._resolve_battery(
                    entry,
                    now,
                    phase_current,
                    updated_at,
                    pool_headroom,
                    main_fuse_a,
                    resume_blocked=any(has_given_way(e) for e in entries[idx + 1 :]),
                    hold_for_relief=bool(set(battery_phases) & pending_relief_phases),
                )
                any_paused = any_paused or battery_output.state == "paused"
                if battery_output.state == "throttling":
                    throttling_keys.add("battery")
                if battery_output.urgent:
                    cut_phases |= set(battery_phases)
                    pending_relief_phases |= set(battery_phases)
                    self._blocked_cut_phases |= set(battery_phases)
                if relief_a > 0:
                    # Fold the relief into the pool (D3) and, since the
                    # inverter reacts with a lag, hold entries below on these
                    # phases until it shows (shed-style, see Risks).
                    for p in battery_phases:
                        pool_headroom[p] = pool_headroom.get(p, main_fuse_a) + relief_a
                    pending_relief_phases |= set(battery_phases)
                    carried_gate -= set(battery_phases)
                ramp = self._ramp_requests.pop("battery", None)
                if ramp is not None:
                    ramp()
                continue
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
                    resume_blocked=resume_blocked,
                    hold_for_relief=hold_for_relief,
                )
                # A charger whose phase set grew (e.g. back from 1-phase to
                # 3-phase) restarts at its floor on the new phases; the
                # return counts as a granted increase until it is measured,
                # and ramping from there goes through the room gate.
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
                    self._ramp_requests.pop(f"charger:{entry.charger_id}", None)
                    if self._ledger.age_s(f"charger:{entry.charger_id}", now) is None:
                        self._ledger.grant(
                            f"charger:{entry.charger_id}",
                            {
                                p: float(entry.min_current_a)
                                for p in set(binding_phases) - last_phases
                            },
                            float(entry.min_current_a),
                            0.5,
                            now,
                        )
                any_stale_fallback = any_stale_fallback or is_stale
                any_paused = any_paused or is_paused
                if is_throttling:
                    throttling_keys.add(f"charger:{entry.charger_id}")
                outputs_by_id[entry.charger_id] = output
                ramp = self._ramp_requests.pop(f"charger:{entry.charger_id}", None)
                if (
                    entry.return_to_phases
                    and output.target_a is not None
                    and output.target_a >= entry.min_current_a
                    and not (set(entry.return_to_phases) & self._blocked_cut_phases)
                    and self.three_phase_fits(
                        entry.return_to_phases,
                        binding_phases,
                        float(output.target_a),
                        entry.min_current_a,
                        now,
                        entry.charger_id,
                    )
                ):
                    output.target_a = entry.min_current_a
                    output.return_3p_requested = True
                    output.state = "throttling"
                    output.reason = (
                        "Returning to three phases at minimum current through shared room gate"
                    )
                elif ramp is not None:
                    ramp()

                # Fold this charger's relief into the pool so the next entry
                # sees the deficit that actually remains: a reduction relieves
                # only what the car actually drew (effective baseline). Raises
                # are not folded — the ledger counts them.
                setpoint = entry.current_setpoint_a or 0
                previous_draw = (
                    entry.effective_draw_a if entry.effective_draw_a is not None else setpoint
                )
                new_draw = output.target_a or 0
                if new_draw < setpoint:
                    delta = max(0, previous_draw - new_draw)
                    for p in binding_phases:
                        pool_headroom[p] = pool_headroom.get(p, main_fuse_a) + delta
                    cut_phases |= set(binding_phases)
                    pending_relief_phases |= set(binding_phases)
                    self._blocked_cut_phases |= set(binding_phases)
                elif output.relief_1p_requested:
                    cut_phases |= set(binding_phases)
                continue

            # Shed entry
            restore_shed(entry, idx)
            if entry.load_id in self._shed_at or not entry.phases:
                continue  # already given way (exhausted) / not actionable
            overloaded = [p for p in entry.phases if pool_headroom.get(p, main_fuse_a) < 0]
            if overloaded and not ((set(entry.phases) & pending_relief_phases) - carried_gate):
                if set(overloaded) & self._debounce_phases and not self._urgent_phases(overloaded):
                    # A charger above is still within its pause debounce on a
                    # shared phase: it gets its chance first (D5).
                    continue
                self._shed_at[entry.load_id] = now
                self._shed_reason[entry.load_id] = (
                    f"Shed: phase(s) {overloaded} overloaded, every higher give-way entry exhausted"
                )
                self._ledger.clear(f"shed:{entry.load_id}")
                pending_relief_phases |= set(entry.phases)
                carried_gate -= set(entry.phases)
                cut_phases |= set(entry.phases)
                self._blocked_cut_phases |= set(entry.phases)

        for p in cut_phases & overloaded_phases:
            self._awaiting[p] = now
            targets: dict[str, float] = {}
            for entry in entries:
                if isinstance(entry, BatteryBalancerInput) and battery_output is not None:
                    if p in entry.phases and battery_output.cap_w < entry.applied_cap_w:
                        targets["battery"] = battery_output.cap_w
                elif isinstance(entry, EVBalancerInput):
                    out = outputs_by_id[entry.charger_id]
                    if p in entry.phases and (out.target_a or 0) < (entry.current_setpoint_a or 0):
                        targets[f"charger:{entry.charger_id}"] = float(out.target_a or 0)
            self._awaiting_targets[p] = targets
            self._awaiting_baseline[p] = {key: measured.get(key) for key in targets}

        ev_inputs = [e for e in entries if isinstance(e, EVBalancerInput)]
        ev_outputs = [outputs_by_id[e.charger_id] for e in ev_inputs]
        shed_outputs = [
            ShedLoadOutput(
                e.load_id,
                e.device_type,
                e.load_id in self._shed_at,
                reason=(
                    "; ".join(
                        x
                        for x in (
                            self._shed_reason.get(e.load_id, ""),
                            restore_notes.get(e.load_id, ""),
                        )
                        if x
                    )
                ),
                power_w=e.power_w,
                power_source=e.power_source,
            )
            for e in entries
            if isinstance(e, ShedLoadInput)
        ]
        # Deferred grants can finish a ramp; derive the summary from the final
        # outputs rather than the pre-grant hold states.
        throttling_keys = {o.charger_id for o in ev_outputs if o.state == "throttling"}
        if battery_output is not None and battery_output.state == "throttling":
            throttling_keys.add("battery")
        reasons = [o.reason for o in ev_outputs if o.reason]
        if battery_output is not None and battery_output.reason:
            reasons.append(battery_output.reason)

        if any_paused:
            state = "paused"
        elif self._shed_at:
            state = "shedding"
        elif any_stale_fallback:
            state = "stale_fallback"
        elif throttling_keys:
            state = "throttling"
        else:
            state = "idle"

        status = LoadBalancerStatus(
            enabled=True,
            state=state,
            reason="; ".join(reasons) or "Within limits",
            main_fuse_a=main_fuse_a,
            phase_current_a=dict(phase_current),
            phase_headroom_a=headroom,
            ev_outputs=ev_outputs,
            shed_outputs=shed_outputs,
            battery_output=battery_output,
        )
        self._record(now, entries, status, phase_current, updated_at, pending_relief_phases)
        return status

    # --- Observability (D14) ------------------------------------------------

    def _record(
        self,
        now: datetime,
        entries: list[BalancerEntry],
        status: LoadBalancerStatus,
        phase_current: dict[int, float],
        updated_at: dict[int, datetime],
        gated: set[int],
    ) -> None:
        """Log decision changes (not unchanged ticks) and trace the tick."""
        ev_by_id = {o.charger_id: o for o in status.ev_outputs}
        shed_by_id = {o.load_id: o for o in status.shed_outputs}
        snapshot_entries: dict[str, dict[str, Any]] = {}
        seen: set[str] = set()

        def note(key: str, state: str, value: str, reason: str, detail: dict[str, Any]) -> None:
            seen.add(key)
            snapshot_entries[key] = {"state": state, "value": value, "reason": reason, **detail}
            previous = self._last_decisions.get(key)
            self._last_decisions[key] = (state, value)
            if previous == (state, value) or (previous is None and state == "idle"):
                return
            old = "-" if previous is None else f"{previous[0]} {previous[1]}"
            logger.info("Load balancer %s: %s -> %s %s (%s)", key, old, state, value, reason or "-")

        for entry in entries:
            if isinstance(entry, EVBalancerInput):
                out = ev_by_id.get(entry.charger_id)
                if out is None:
                    continue
                note(
                    f"charger:{entry.charger_id}",
                    out.state,
                    "paused" if out.target_a is None else f"{out.target_a}A",
                    out.reason,
                    {"setpoint_a": entry.current_setpoint_a, "plan_a": entry.planner_target_a},
                )
            elif isinstance(entry, BatteryBalancerInput):
                bat = status.battery_output
                if bat is None:
                    continue
                note(
                    "battery",
                    bat.state,
                    f"{bat.cap_w:.0f}W",
                    bat.reason,
                    {
                        "plan_w": bat.planned_w,
                        "cap_w": bat.cap_w,
                        "measured_w": entry.measured_w,
                    },
                )
            else:
                shed = shed_by_id.get(entry.load_id)
                if shed is None:
                    continue
                note(
                    f"shed:{entry.load_id}",
                    "shed" if shed.shed else "on",
                    "off" if shed.shed else "on",
                    shed.reason,
                    {"power_source": shed.power_source},
                )
        for key in list(self._last_decisions):
            if key not in seen:
                del self._last_decisions[key]

        self.trace.add(
            {
                "t": now.isoformat(),
                "state": status.state,
                "raw_a": {str(p): round(v, 2) for p, v in phase_current.items()},
                "avg_a": {
                    str(p): None
                    if (avg := self.averaged_current_a(p, now)) is None
                    else round(avg, 2)
                    for p in (1, 2, 3)
                },
                "age_s": {
                    str(p): round((now - ts).total_seconds(), 1) for p, ts in updated_at.items()
                },
                "relief_a": {str(p): round(r.amount_a, 2) for p, r in self._relief.items()},
                "gated_phases": sorted(gated),
                "entries": snapshot_entries,
                "shed": sorted(self._shed_at),
                "ledger": self._ledger.snapshot(),
            }
        )
