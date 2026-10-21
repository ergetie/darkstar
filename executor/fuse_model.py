"""In-memory, per-phase time-current fuse approximation (no I/O).

Hager SE_TECHAPP_28-04-2015_31_DVB.pdf (Typ C, fastest band edge)
and SE_TECHAPP_28-04-2015_21_SMAELTSAEKRINGAR.pdf (Diazed gG).
Points read from graphs, approximately +/-30%; these are not certified curves.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from typing import Literal

from .config import LoadBalancingConfig

# Assumptions: 1.13x exactly one hour (graph: no trip for >=1 h), and
# 5x exactly 0.1 s to interpolate the instantaneous region.
TYP_C_POINTS = (
    (1.13, 3600.0),
    (1.2, 3600.0),
    (1.3, 1200.0),
    (1.5, 300.0),
    (2.0, 30.0),
    (3.0, 4.0),
    (5.0, 0.1),
)
# Assumptions: 1.25x exactly four hours (graph: never); extrapolate above
# 4x using the last log-log segment. Custom curves use the same extension.
DIAZED_GG_POINTS = ((1.25, 14400.0), (1.6, 3600.0), (1.8, 900.0), (2.5, 100.0), (4.0, 10.0))


FuseHeatState = Literal["heating", "cooling", "holding", "cold", "stale", "unavailable"]


@dataclass(frozen=True)
class Relief:
    """Amperes to give way; urgent bypasses the hold for unmeasured relief."""

    amount_a: float = 0.0
    urgent: bool = False


def trip_time_s(
    multiple: float,
    points: tuple[tuple[float, float], ...] = TYP_C_POINTS,
    *,
    instantaneous: bool = True,
) -> float:
    """Log-log interpolation, no timed heating below the first anchor."""
    for anchor, seconds in points:
        if multiple == anchor:
            return seconds
    if multiple < points[0][0]:
        return math.inf
    if instantaneous and multiple >= points[-1][0]:
        return points[-1][1]
    lo, hi = points[-2:]
    for left, right in pairwise(points):
        if multiple <= right[0]:
            lo, hi = left, right
            break
    slope = math.log(hi[1] / lo[1]) / math.log(hi[0] / lo[0])
    return lo[1] * (multiple / lo[0]) ** slope


class FuseHeatModel:
    """Heat is a trip-time fraction, integrated once per phase per tick."""

    def __init__(self, config: LoadBalancingConfig, interval_seconds: float = 300):
        self._signature: tuple[object, ...] | None = None
        self.reset()
        self.configure(config, interval_seconds)

    def reset(self) -> None:
        self._heat: dict[int, float] = {}
        self._rate: dict[int, float] = {}
        self._at: dict[int, datetime] = {}
        self._stale: set[int] = set()
        self._heat_state: dict[int, FuseHeatState] = {}

    def configure(self, config: LoadBalancingConfig, interval_seconds: float) -> None:
        custom = tuple((p.overload_percent / 100, p.time_s) for p in config.fuse_custom_points)
        signature = (
            config.fuse_preset,
            config.main_fuse_a,
            custom if config.fuse_preset == "custom" else None,
        )
        if signature != self._signature:
            self.reset()
            self._signature = signature
        self.config = config
        self.interval_seconds = interval_seconds
        self.points = (
            custom
            if config.fuse_preset == "custom"
            else DIAZED_GG_POINTS
            if config.fuse_preset == "diazed_gg"
            else TYP_C_POINTS
        )

    @property
    def safety_percent(self) -> float:
        explicit = self.config.fuse_safety_percent
        return (
            explicit
            if explicit is not None
            else (65 if self.config.fuse_preset == "diazed_gg" else 80)
        )

    def heat(self, phase: int) -> float:
        return self._heat.get(phase, 0.0)

    def heat_state(self, phase: int) -> FuseHeatState:
        """State of the last model evaluation; never infer movement from current."""
        return self._heat_state.get(phase, "unavailable")

    def cooled(self, phases: Iterable[int]) -> bool:
        return all(self.heat(p) < 0.5 for p in phases)

    def relief_needed(self, phase: int, momentary_a: float, now: datetime, stale: bool) -> Relief:
        if stale or not math.isfinite(momentary_a):
            self._stale.add(phase)
            self._heat_state[phase] = "stale" if stale else "unavailable"
            return Relief()
        previous = self._at.get(phase)
        dt = (
            0.0
            if previous is None or phase in self._stale
            else max(0.0, (now - previous).total_seconds())
        )
        self._at[phase] = now
        self._stale.discard(phase)
        if dt > max(120.0, 2 * self.interval_seconds):
            dt = 0.0
        rating = self.config.main_fuse_a
        if rating is None or rating <= 0:
            self._heat_state[phase] = "unavailable"
            return Relief()
        multiple = momentary_a / rating
        trip = trip_time_s(multiple, self.points, instantaneous=self.config.fuse_preset == "typ_c")
        previous_heat = self.heat(phase)
        heat = previous_heat
        if math.isfinite(trip):
            rate = 1.0 / trip
            self._rate[phase] = rate
            heat += dt * rate
        elif multiple < 1.0:
            heat = max(0.0, heat - dt * self._rate.get(phase, 0.0))
        self._heat[phase] = heat
        safety = self.safety_percent / 100
        urgent = trip * safety < self.interval_seconds
        amount = max(0.0, momentary_a - rating * self.config.target_margin_percent / 100)
        if amount > 0 and (heat + 1e-12 >= safety or urgent):
            self._heat[phase] = max(heat, safety)
            relief = Relief(amount, urgent)
        else:
            relief = Relief()
        current_heat = self.heat(phase)
        self._heat_state[phase] = (
            "heating"
            if current_heat > previous_heat
            else "cooling"
            if current_heat < previous_heat
            else "cold"
            if current_heat == 0
            else "holding"
        )
        return relief
