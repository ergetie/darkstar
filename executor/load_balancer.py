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
    """Per-tick balancer input for one type="current" EV charger."""

    charger_id: str
    phases: list[int]
    current_setpoint_a: int | None  # None = not currently charging
    planner_target_a: int | None  # None = plan does not want this charger charging
    min_current_a: int
    max_current_a: int
    # Lower number gives way first when multiple dynamically-throttled
    # chargers share an overloaded phase. Resolved by the caller from
    # load_balancing.charger_priority (default: position in ev_chargers[]).
    priority: int = 0


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
    binary-type EV charger declared in load_balancing.loads)."""

    load_id: str
    device_type: str
    phases: list[int]
    priority: int


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

    Holds anti-flap state (pause timestamps, stale timers, shed order) between
    ticks. `tick()` is pure — it takes a snapshot of measured phase currents
    plus the intended EV/load state and returns capped setpoints and shed
    decisions; it never calls Home Assistant itself. Multiple EV chargers
    sharing a phase are resolved by priority-ordered sequential allocation
    (see `_resolve_ev`): the lowest-priority-number charger is evaluated
    first against the raw headroom, and its resulting draw change is folded
    into a running headroom pool before the next-priority charger is
    evaluated — so a charger further down the priority order only gives way
    for whatever deficit remains after every charger ahead of it is already
    at its floor or paused. A single-charger setup sees no observable change
    (there is no "next" charger to consult the pool).
    """

    def __init__(self, config: LoadBalancingConfig):
        self.config = config
        self._ev_paused_at: dict[str, datetime] = {}
        self._ev_stale_since: dict[str, datetime] = {}
        # Shed stack: append on shed, pop from the end to restore (LIFO — most
        # recently shed load is restored first, per the reverse-order spec).
        self._shed_stack: list[str] = []
        self._shed_at: dict[str, datetime] = {}

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
    ) -> tuple[EVBalancerOutput, bool, bool, bool]:
        """Resolve one EV charger's decision against the current headroom pool.

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
                    and margin_ok(binding_phases)
                    and binding_headroom >= ev.min_current_a
                )
                if not resume_ok:
                    return (
                        EVBalancerOutput(
                            ev.charger_id,
                            None,
                            "paused",
                            f"Waiting to resume (headroom {binding_headroom:.1f}A, "
                            f"paused {int(elapsed)}s ago)",
                        ),
                        False,
                        True,
                        False,
                    )
                self._ev_paused_at.pop(ev.charger_id, None)
            elif binding_headroom < ev.min_current_a:
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
        ev_inputs: list[EVBalancerInput],
        loads: list[ShedLoadInput],
    ) -> LoadBalancerStatus:
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
        # resolved in priority order (see class docstring); kept separate
        # from `headroom` (raw, used for shedding below) so single-charger
        # behavior is unaffected by this bookkeeping.
        pool_headroom = dict(headroom)
        margin_threshold = main_fuse_a * self.config.resume_margin_percent / 100.0
        min_current_by_id = {ev.charger_id: ev.min_current_a for ev in ev_inputs}

        def margin_ok(phases: list[int]) -> bool:
            return all(phase_current.get(p, main_fuse_a) < margin_threshold for p in phases)

        outputs_by_id: dict[str, EVBalancerOutput] = {}
        any_stale_fallback = False
        any_paused = False
        any_throttling = False

        ordered_evs = sorted(ev_inputs, key=lambda ev: (ev.priority, ev.charger_id))
        for ev in ordered_evs:
            binding_phases = ev.phases or [1, 2, 3]
            output, is_stale, is_paused, is_throttling = self._resolve_ev(
                ev,
                binding_phases,
                now,
                phase_current,
                updated_at,
                pool_headroom,
                main_fuse_a,
                margin_ok,
            )
            any_stale_fallback = any_stale_fallback or is_stale
            any_paused = any_paused or is_paused
            any_throttling = any_throttling or is_throttling
            outputs_by_id[ev.charger_id] = output

            # Fold this charger's resulting draw change into the pool so the
            # next-priority charger sees the deficit that actually remains.
            previous_draw = ev.current_setpoint_a or 0
            new_draw = output.target_a or 0
            delta = previous_draw - new_draw
            if delta:
                for p in binding_phases:
                    pool_headroom[p] = pool_headroom.get(p, main_fuse_a) + delta

        # Preserve caller's input order for the status surface — priority only
        # governs allocation order, not display/reporting order.
        ev_outputs = [outputs_by_id[ev.charger_id] for ev in ev_inputs]

        # Shedding: only when every EV is already at its floor, paused, or
        # stale-limited (simplified single-pool gate — see class docstring).
        ev_at_floor_or_paused = all(
            out.target_a is None or out.target_a <= min_current_by_id.get(out.charger_id, 0)
            for out in ev_outputs
        )

        if ev_at_floor_or_paused:
            shed_ids = set(self._shed_stack)
            candidates = sorted(
                (ld for ld in loads if ld.load_id not in shed_ids),
                key=lambda ld: ld.priority,
            )
            for ld in candidates:
                if any(headroom.get(p, main_fuse_a) < 0 for p in ld.phases):
                    self._shed_stack.append(ld.load_id)
                    self._shed_at[ld.load_id] = now
                    break  # one shed action per tick

        if self._shed_stack:
            top_id = self._shed_stack[-1]
            top_load = next((ld for ld in loads if ld.load_id == top_id), None)
            shed_at = self._shed_at.get(top_id)
            if top_load is not None and shed_at is not None:
                elapsed = (now - shed_at).total_seconds()
                healthy = all(headroom.get(p, main_fuse_a) >= 0 for p in top_load.phases)
                if elapsed >= self.config.resume_delay_s and healthy and margin_ok(top_load.phases):
                    self._shed_stack.pop()
                    self._shed_at.pop(top_id, None)

        shed_id_set = set(self._shed_stack)
        shed_outputs = [
            ShedLoadOutput(
                ld.load_id,
                ld.device_type,
                ld.load_id in shed_id_set,
                reason=("Shed: phase overloaded, EV at floor" if ld.load_id in shed_id_set else ""),
            )
            for ld in loads
        ]

        if any_paused:
            state = "paused"
        elif self._shed_stack:
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
