"""
Real-time per-phase load balancing (main fuse protection).

Pure decision logic — no HA calls here. The executor tick gathers SystemState,
calls into this module, and dispatches whatever setpoints/commands come back
via the existing ActionDispatcher paths (executor/actions.py).
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

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


def planned_kw_to_amps(
    planned_kw: float,
    active_phase_count: int,
    min_current_a: int,
    max_current_a: int,
) -> int | None:
    """Translate a planned charging power (kW) into an ampere setpoint.

    amps = floor(planned_kw * 1000 / (230 * active_phase_count)), clamped to
    max_current_a. Returns None when the result would be below min_current_a —
    the caller should pause charging rather than command a setpoint below the
    charger's minimum.
    """
    if active_phase_count <= 0 or planned_kw <= 0:
        return None

    amps = math.floor(planned_kw * 1000 / (230 * active_phase_count))
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


@dataclass
class EVBalancerOutput:
    """Balancer decision for one EV charger. `target_a=None` means stop/paused."""

    charger_id: str
    target_a: int | None
    state: str  # "idle" | "throttling" | "paused" | "stale_fallback"
    reason: str = ""


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
    restored first), gated per entry by the unchanged resume delay + margin
    rules; at most one shed load is reconnected per tick so each restore's
    load is measured before the next.
    """

    def __init__(self, config: LoadBalancingConfig):
        self.config = config
        self._ev_paused_at: dict[str, datetime] = {}
        self._ev_stale_since: dict[str, datetime] = {}
        # Currently-shed loads: load_id -> shed timestamp (+ human reason).
        # Restore order comes from reverse list position, not insertion order.
        self._shed_at: dict[str, datetime] = {}
        self._shed_reason: dict[str, str] = {}

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
        margin_ok: Callable[[list[int]], bool],
        resume_blocked: bool = False,
        hold_for_relief: bool = False,
    ) -> tuple[EVBalancerOutput, bool, bool, bool]:
        """Resolve one EV charger's decision against the current headroom pool.

        resume_blocked: a give-way entry below this charger is still paused or
        shed — restore happens in exact reverse list order, so this charger
        may not resume yet. hold_for_relief: a shed entry above this charger
        gave way this tick on a shared phase; its relief is unmeasured, so
        hold the current setpoint instead of reducing or pausing.

        Returns (output, is_stale, is_paused, is_throttling) — the three
        flags feed the tick-level `any_*` aggregates that drive the overall
        balancer state.
        """
        stale_phases = [
            p for p in binding_phases if self._is_stale(p, phase_current, updated_at, now)
        ]

        if stale_phases:
            stale_since = self._ev_stale_since.setdefault(ev.charger_id, now)
            stale_elapsed = (now - stale_since).total_seconds()
            if stale_elapsed >= self.config.resume_delay_s:
                # Escalating stale_fallback -> a full pause: record the pause
                # start (if not already paused) so that once the sensor comes
                # back fresh, recovery falls through to the same
                # resume-delay + margin gate as an overload pause, instead of
                # resuming immediately (setdefault: don't reset an
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

        if ev.current_setpoint_a is None:
            if ev.planner_target_a is None:
                self._ev_paused_at.pop(ev.charger_id, None)
                return EVBalancerOutput(ev.charger_id, None, "idle"), False, False, False

            paused_at = self._ev_paused_at.get(ev.charger_id)
            if paused_at is not None:
                elapsed = (now - paused_at).total_seconds()
                resume_ok = (
                    elapsed >= self.config.resume_delay_s
                    and not resume_blocked
                    and margin_ok(binding_phases)
                    and binding_headroom >= ev.min_current_a
                )
                if not resume_ok:
                    reason = (
                        "Waiting to resume — a lower-listed give-way entry must restore first"
                        if resume_blocked and elapsed >= self.config.resume_delay_s
                        else f"Waiting to resume (headroom {binding_headroom:.1f}A, "
                        f"paused {int(elapsed)}s ago)"
                    )
                    return (
                        EVBalancerOutput(ev.charger_id, None, "paused", reason),
                        False,
                        True,
                        False,
                    )
                self._ev_paused_at.pop(ev.charger_id, None)
            elif binding_headroom < ev.min_current_a:
                if hold_for_relief:
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
            if hold_for_relief:
                # A higher-listed shed entry gave way this tick on a shared
                # phase — hold the setpoint until its relief is measured
                # instead of reducing (or pausing) below it. Still never
                # above the planned charging level.
                hold_ceiling = (
                    min(ev.max_current_a, ev.planner_target_a)
                    if ev.planner_target_a is not None
                    else setpoint
                )
                hold_target = min(setpoint, hold_ceiling)
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
            new_target = math.floor(setpoint + binding_headroom)
            if new_target < ev.min_current_a:
                self._ev_paused_at[ev.charger_id] = now
                return (
                    EVBalancerOutput(
                        ev.charger_id,
                        None,
                        "paused",
                        f"Headroom {binding_headroom:.1f}A insufficient to sustain "
                        f"{ev.min_current_a}A floor — pausing",
                    ),
                    False,
                    True,
                    False,
                )
            return (
                EVBalancerOutput(
                    ev.charger_id,
                    new_target,
                    "throttling",
                    f"Reduced {setpoint}A -> {new_target}A (headroom {binding_headroom:.1f}A)",
                ),
                False,
                False,
                True,
            )

        if ev.planner_target_a is None:
            self._ev_paused_at.pop(ev.charger_id, None)
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

        if margin_ok(binding_phases):
            new_target = min(setpoint + self.config.increase_step_a, ceiling)
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
                f"Holding {setpoint}A — phase near margin, waiting to ramp "
                f"toward {ev.planner_target_a}A",
            ),
            False,
            False,
            True,
        )

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
        margin_threshold = main_fuse_a * self.config.resume_margin_percent / 100.0

        def margin_ok(phases: list[int]) -> bool:
            return all(phase_current.get(p, main_fuse_a) < margin_threshold for p in phases)

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
                # Charger resume is decided in the give-way pass (per-charger
                # delay + margin gating); until it resumes it blocks restores
                # of entries above it.
                break
            if shed_restore_done:
                break
            shed_at = self._shed_at[entry.load_id]
            elapsed = (now - shed_at).total_seconds()
            healthy = all(headroom.get(p, main_fuse_a) >= 0 for p in entry.phases)
            if elapsed >= self.config.resume_delay_s and healthy and margin_ok(entry.phases):
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
                    margin_ok,
                    resume_blocked=resume_blocked,
                    hold_for_relief=hold_for_relief,
                )
                any_stale_fallback = any_stale_fallback or is_stale
                any_paused = any_paused or is_paused
                any_throttling = any_throttling or is_throttling
                outputs_by_id[entry.charger_id] = output

                # Fold this charger's resulting draw change into the pool so
                # the next entry sees the deficit that actually remains.
                previous_draw = entry.current_setpoint_a or 0
                new_draw = output.target_a or 0
                delta = previous_draw - new_draw
                if delta:
                    for p in binding_phases:
                        pool_headroom[p] = pool_headroom.get(p, main_fuse_a) + delta
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
