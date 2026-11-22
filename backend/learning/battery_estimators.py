"""Pure estimators for battery round-trip efficiency and inverter charge-path loss.

Every function works on plain row dicts (``slot_observations`` columns) and an ``as_of``
time, never touches a database and never looks at rows that end after ``as_of``. The same
code therefore serves the daily service, the offline walk-forward evaluator and the tests.

Sides of the inverter (design D2a). Recorded ``batt_charge_kwh`` / ``batt_discharge_kwh``
are battery-terminal (DC) energies; the planner's charge and discharge are AC-side. The
round-trip efficiency is estimated from DC counters only. The loss fit regresses the
energy-balance residual on the DC charge counter (``k`` per DC kWh) and the result is
converted to the AC basis ``ell = k / (1 + k)`` before it is returned.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from itertools import pairwise
from typing import TYPE_CHECKING, Any, cast

import numpy as np

from backend.measurement_provenance import (
    SUPPORTED_METHODS,
    base_load_unreliable,
    parse_quality_flags,
    parse_recording,
    soc_metadata,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

# --- Parameter keys ---------------------------------------------------------------------
KEY_RTE = "battery_round_trip_efficiency"
KEY_CHARGE_LOSS = "inverter_charge_loss"
KEY_STANDBY_W = "inverter_standby_w"
KEY_DISCHARGE_EFFICIENCY = "inverter_discharge_efficiency"

# --- Physical bounds (estimates outside are rejected, never clamped) ---------------------
RTE_BOUNDS = (0.80, 0.995)
CHARGE_LOSS_BOUNDS = (0.0, 0.15)
STANDBY_W_BOUNDS = (0.0, 300.0)
DISCHARGE_EFFICIENCY_BOUNDS = (0.85, 1.0)

# --- Round-trip efficiency ---------------------------------------------------------------
RTE_LOOKBACK_DAYS = 120
RTE_MIN_RUN_DAYS = 1.0
RTE_CHUNK_DAYS = 7.0
RTE_MAX_SOC_CORRECTION_SHARE = 0.10
RTE_MIN_POOLED_DAYS = 28
RTE_MIN_DISCHARGE_CAPACITIES = 5.0
RTE_CONFIDENCE_TOLERANCE = 0.03
RTE_CONFIDENCE_FULL_DAYS = 42

# --- Inverter loss -----------------------------------------------------------------------
LOSS_LOOKBACK_DAYS = 120
LOSS_MIN_SLOTS = 1000
LOSS_MIN_SPAN_DAYS = 14
LOSS_MIN_CHARGE_CAPACITIES = 2.0
LOSS_CONFIDENCE_TOLERANCE = 0.03
LOSS_CONFIDENCE_FULL_SLOTS = 2000
HUBER_ITERATIONS = 20
HUBER_TUNING = 1.345
MAD_TO_SIGMA = 1.4826
MIN_FIT_SCALE_KWH = 1e-6

# --- Acceptance --------------------------------------------------------------------------
MIN_CONFIDENCE = 0.5

SLOT_SECONDS_DEFAULT = 900.0


@dataclass(frozen=True)
class Estimate:
    """Result of one estimator run. ``rejected_reason`` is None when the value is usable."""

    value: float | None
    confidence: float
    evidence: dict[str, Any] = field(default_factory=lambda: {})
    rejected_reason: str | None = None

    @property
    def accepted(self) -> bool:
        return self.rejected_reason is None and self.value is not None


@dataclass(frozen=True)
class InverterLossEstimates:
    """Both outputs of the inverter-loss fit (AC-basis charge loss, standby watts)."""

    charge_loss: Estimate
    standby_w: Estimate


def _rejected(reason: str, evidence: dict[str, Any], value: float | None = None) -> Estimate:
    return Estimate(
        value=value, confidence=0.0, evidence={**evidence, "reason": reason}, rejected_reason=reason
    )


# --- Row helpers -------------------------------------------------------------------------


def _number(row: Mapping[str, Any], key: str) -> float | None:
    """A finite float or None; a missing or null value is never zero."""
    value = row.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def slot_bounds(row: Mapping[str, Any]) -> tuple[datetime, datetime] | None:
    """Timezone-aware (start, end) of a slot; end defaults to start + 15 min when absent."""
    start = _parse_time(row.get("slot_start"))
    if start is None:
        return None
    end = _parse_time(row.get("slot_end"))
    if end is None:
        end = start + timedelta(seconds=SLOT_SECONDS_DEFAULT)
    return (start, end) if end > start else None


def _is_past(row: Mapping[str, Any], as_of: datetime) -> bool:
    bounds = slot_bounds(row)
    return bounds is not None and bounds[1] <= as_of


def _excluded(flags: dict[str, Any]) -> bool:
    return flags.get("exclude") is True


def rte_slot_eligible(row: Mapping[str, Any], as_of: datetime) -> bool:
    """Whether a slot may enter the round-trip efficiency windows.

    Battery charge, discharge and end SoC must be present and recorded from power history
    and a live SoC reading, the slot must not be excluded and must lie in the past.
    """
    if not _is_past(row, as_of):
        return False
    if any(
        _number(row, key) is None
        for key in ("batt_charge_kwh", "batt_discharge_kwh", "soc_end_percent")
    ):
        return False
    flags = parse_quality_flags(row.get("quality_flags"))
    if _excluded(flags):
        return False
    recording = parse_recording(flags, SUPPORTED_METHODS)
    if recording is None:
        return False
    components = cast("dict[str, Any]", recording["components"])
    for name in ("battery_charge", "battery_discharge"):
        component: Any = components.get(name)
        if (
            not isinstance(component, dict)
            or cast("dict[str, Any]", component).get("method") != "power_history"
        ):
            return False
    return soc_metadata(recording, "end").get("source") == "live"


_BALANCE_FIELDS = (
    "import_kwh",
    "export_kwh",
    "pv_kwh",
    "load_kwh",
    "water_kwh",
    "ev_charging_kwh",
    "batt_charge_kwh",
    "batt_discharge_kwh",
)


def loss_slot_eligible(row: Mapping[str, Any], as_of: datetime) -> bool:
    """Whether a slot's energy-balance residual is a trustworthy inverter loss.

    Clean recording (every component measured, no unknown device), not excluded, base load
    not flagged unreliable, every balance value present, in the past.
    """
    # Imported here: backend.battery_benchmark pulls in the planner package, which imports
    # this module's parameter store (planner.pipeline), so a top-level import would cycle.
    from backend.battery_benchmark import slot_recording

    if not _is_past(row, as_of):
        return False
    if any(_number(row, key) is None for key in _BALANCE_FIELDS):
        return False
    flags = parse_quality_flags(row.get("quality_flags"))
    if _excluded(flags) or base_load_unreliable(flags):
        return False
    return slot_recording(row) == "clean"


def balance_residual_kwh(row: Mapping[str, Any]) -> float:
    """``(pv + import + discharge) - (load + ev + water + export + charge)`` of one slot."""
    values = {key: float(row[key]) for key in _BALANCE_FIELDS}
    return (values["pv_kwh"] + values["import_kwh"] + values["batt_discharge_kwh"]) - (
        values["load_kwh"]
        + values["ev_charging_kwh"]
        + values["water_kwh"]
        + values["export_kwh"]
        + values["batt_charge_kwh"]
    )


# --- Confidence ---------------------------------------------------------------------------


def split_half_confidence(
    first: float | None, second: float | None, size: float, full_size: float, tolerance: float
) -> float:
    """``min(1, size / full) x max(0, 1 - |a - b| / tolerance)``; 0 when a half is missing."""
    if first is None or second is None or full_size <= 0 or tolerance <= 0:
        return 0.0
    return min(1.0, size / full_size) * max(0.0, 1.0 - abs(first - second) / tolerance)


def _bounded(value: float, bounds: tuple[float, float]) -> bool:
    return bounds[0] <= value <= bounds[1]


def _finish(
    value: float,
    confidence: float,
    evidence: dict[str, Any],
    bounds: tuple[float, float],
    label: str,
) -> Estimate:
    """Apply the bounds and confidence rules; rejected estimates keep their value as evidence."""
    evidence = {**evidence, "value": value, "confidence": confidence}
    if not _bounded(value, bounds):
        return _rejected(
            f"{label} {value:.4f} is outside the plausible range {bounds[0]} to {bounds[1]}",
            evidence,
            value,
        )
    if round(confidence, 9) < MIN_CONFIDENCE:
        reason = f"confidence {confidence:.2f} is below {MIN_CONFIDENCE}"
        return Estimate(
            value=value,
            confidence=confidence,
            evidence={**evidence, "reason": reason},
            rejected_reason=reason,
        )
    return Estimate(value=value, confidence=confidence, evidence=evidence)


# --- Round-trip efficiency ----------------------------------------------------------------


@dataclass(frozen=True)
class _Chunk:
    """Flows of one stretch of contiguous eligible slots and the SoC change across it."""

    run: int
    first_day: date
    last_day: date
    days: float
    charge_kwh: float
    discharge_kwh: float
    d_soc_pp: float


def _prepare(
    rows: Iterable[Mapping[str, Any]], cutoff: datetime
) -> list[tuple[Mapping[str, Any], datetime, datetime]]:
    prepared: dict[datetime, tuple[Mapping[str, Any], datetime, datetime]] = {}
    for row in rows:
        bounds = slot_bounds(row)
        if bounds is None or bounds[0] < cutoff:
            continue
        prepared[bounds[0]] = (row, bounds[0], bounds[1])
    return [prepared[key] for key in sorted(prepared)]


def _eligible_runs(
    rows: Iterable[Mapping[str, Any]], as_of: datetime
) -> list[list[tuple[Mapping[str, Any], datetime, datetime]]]:
    """Maximal runs of back-to-back eligible slots; any gap or unusable slot ends a run."""
    cutoff = as_of - timedelta(days=RTE_LOOKBACK_DAYS)
    runs: list[list[tuple[Mapping[str, Any], datetime, datetime]]] = []
    current: list[tuple[Mapping[str, Any], datetime, datetime]] = []
    for item in _prepare(rows, cutoff):
        if not rte_slot_eligible(item[0], as_of):
            current = []
            continue
        if not current or current[-1][2] != item[1]:
            current = []
            runs.append(current)
        current.append(item)
    return runs


def _chunks(rows: Sequence[Mapping[str, Any]], as_of: datetime) -> list[_Chunk]:
    """Cut every run into chunks of about a week, each with its own start and end SoC.

    The SoC is recorded in every slot, so a run can be cut anywhere: the first slot of a run
    only supplies the starting SoC (its flows are not counted) and each chunk starts at the
    end SoC of the slot before it. Neighbouring chunks share their boundary SoC, so the
    SoC change of a whole run telescopes to its first and last reading.
    """
    chunks: list[_Chunk] = []
    for run_index, run in enumerate(_eligible_runs(rows, as_of)):
        slots = run[1:]
        if not slots:
            continue
        start_index = 0
        total = (slots[-1][2] - slots[0][1]).total_seconds() / 86400.0
        if total < RTE_MIN_RUN_DAYS:
            continue
        cut_points: list[int] = []
        for index, (_, start, _) in enumerate(slots):
            elapsed = (start - slots[start_index][1]).total_seconds() / 86400.0
            remaining = (slots[-1][2] - start).total_seconds() / 86400.0
            if elapsed >= RTE_CHUNK_DAYS and remaining >= RTE_MIN_RUN_DAYS:
                cut_points.append(index)
                start_index = index
        bounds = [0, *cut_points, len(slots)]
        for first, last in pairwise(bounds):
            part = slots[first:last]
            before = run[first]  # run[0] precedes slots[0], so run[first] precedes slots[first]
            chunks.append(
                _Chunk(
                    run=run_index,
                    first_day=part[0][1].date(),
                    last_day=part[-1][1].date(),
                    days=(part[-1][2] - part[0][1]).total_seconds() / 86400.0,
                    charge_kwh=sum(float(row["batt_charge_kwh"]) for row, _, _ in part),
                    discharge_kwh=sum(float(row["batt_discharge_kwh"]) for row, _, _ in part),
                    d_soc_pp=float(part[-1][0]["soc_end_percent"])
                    - float(before[0]["soc_end_percent"]),
                )
            )
    return chunks


def _rte_value(charge: float, discharge: float, stored_change: float) -> float | None:
    """Round-trip efficiency ``R`` from ``charge x sqrt(R) - discharge / sqrt(R) = change``.

    This is the symmetric-split stored-energy balance used by the design (each way is
    ``sqrt(R)``); ``change`` is the energy the battery gained over the period. It reduces to
    ``discharge / charge`` when the battery ended where it started.
    """
    if charge <= 0 or discharge < 0:
        return None
    root = (stored_change + math.sqrt(stored_change**2 + 4.0 * charge * discharge)) / (2.0 * charge)
    return root * root


def _chunks_rte(chunks: Sequence[_Chunk], capacity_kwh: float) -> float | None:
    return _rte_value(
        sum(c.charge_kwh for c in chunks),
        sum(c.discharge_kwh for c in chunks),
        sum(c.d_soc_pp for c in chunks) / 100.0 * capacity_kwh,
    )


def estimate_round_trip_efficiency(
    rows: Sequence[Mapping[str, Any]], config_capacity_kwh: float, as_of: datetime
) -> Estimate:
    """Battery round-trip efficiency (DC out / DC in) over runs of contiguous eligible slots.

    Flows are pooled over every run of back-to-back eligible slots (at least a day long) and
    corrected for the net SoC change of the pool (``change = dSoC x configured capacity``).
    Over a long pool that change is small next to the throughput, so the unidentifiable
    capacity matters little; a pool where the correction exceeds
    ``RTE_MAX_SOC_CORRECTION_SHARE`` of the charge energy is rejected.
    """
    if config_capacity_kwh <= 0:
        return _rejected("battery capacity is not configured", {})
    chunks = _chunks(rows, as_of)
    days = sum(c.days for c in chunks)
    discharge = sum(c.discharge_kwh for c in chunks)
    charge = sum(c.charge_kwh for c in chunks)
    stored_change = sum(c.d_soc_pp for c in chunks) / 100.0 * config_capacity_kwh
    correction_share = abs(stored_change) / charge if charge > 0 else 0.0
    evidence: dict[str, Any] = {
        "days": round(days, 2),
        "runs": len({c.run for c in chunks}),
        "discharge_kwh": round(discharge, 3),
        "charge_kwh": round(charge, 3),
        "soc_correction_kwh": round(stored_change, 3),
        "soc_correction_share": round(correction_share, 4),
        "window_start": chunks[0].first_day.isoformat() if chunks else None,
        "window_end": chunks[-1].last_day.isoformat() if chunks else None,
    }
    needed_discharge = RTE_MIN_DISCHARGE_CAPACITIES * config_capacity_kwh
    if days < RTE_MIN_POOLED_DAYS:
        return _rejected(
            f"{days:.0f} usable days, {RTE_MIN_POOLED_DAYS} needed (continuous recorded data)",
            evidence,
        )
    if discharge < needed_discharge:
        return _rejected(
            f"{discharge:.0f} kWh discharged, {needed_discharge:.0f} kWh needed", evidence
        )
    if correction_share > RTE_MAX_SOC_CORRECTION_SHARE:
        return _rejected(
            f"the battery's net charge change is {correction_share:.0%} of the energy charged "
            f"(at most {RTE_MAX_SOC_CORRECTION_SHARE:.0%} allowed)",
            evidence,
        )
    value = _chunks_rte(chunks, config_capacity_kwh)
    if value is None:
        return _rejected("no battery charge energy recorded", evidence)
    odd, even = chunks[0::2], chunks[1::2]
    confidence = split_half_confidence(
        _chunks_rte(odd, config_capacity_kwh) if odd else None,
        _chunks_rte(even, config_capacity_kwh) if even else None,
        days,
        RTE_CONFIDENCE_FULL_DAYS,
        RTE_CONFIDENCE_TOLERANCE,
    )
    return _finish(value, confidence, evidence, RTE_BOUNDS, "round-trip efficiency")


# --- Inverter loss ------------------------------------------------------------------------


def _huber_fit(design: np.ndarray, target: np.ndarray) -> np.ndarray | None:
    """Huber-weighted iteratively reweighted least squares; None when the design is singular."""
    if design.shape[0] < design.shape[1] or np.linalg.matrix_rank(design) < design.shape[1]:
        return None
    weights = np.ones(design.shape[0])
    coefficients = np.zeros(design.shape[1])
    for _ in range(HUBER_ITERATIONS):
        root = np.sqrt(weights)
        coefficients = np.linalg.lstsq(design * root[:, None], target * root, rcond=None)[0]
        residuals = target - design @ coefficients
        scale = max(
            MAD_TO_SIGMA * float(np.median(np.abs(residuals - np.median(residuals)))),
            MIN_FIT_SCALE_KWH,
        )
        limit = HUBER_TUNING * scale
        magnitude = np.maximum(np.abs(residuals), 1e-12)
        weights = np.where(magnitude <= limit, 1.0, limit / magnitude)
    return coefficients


@dataclass(frozen=True)
class _LossSlot:
    start: datetime
    hours: float
    charge_kwh: float
    loss_kwh: float
    from_sensor: bool


def _loss_slots(
    rows: Sequence[Mapping[str, Any]], loss_sensor_values: Mapping[str, float], as_of: datetime
) -> list[_LossSlot]:
    cutoff = as_of - timedelta(days=LOSS_LOOKBACK_DAYS)
    slots: list[_LossSlot] = []
    for row, start, end in _prepare(rows, cutoff):
        if not loss_slot_eligible(row, as_of):
            continue
        sensor = loss_sensor_values.get(str(row["slot_start"]))
        sensor_ok = sensor is not None and math.isfinite(sensor)
        slots.append(
            _LossSlot(
                start=start,
                hours=(end - start).total_seconds() / 3600.0,
                charge_kwh=float(row["batt_charge_kwh"]),
                loss_kwh=float(sensor)
                if sensor_ok and sensor is not None
                else balance_residual_kwh(row),
                from_sensor=sensor_ok,
            )
        )
    return slots


def _fit_slots(slots: Sequence[_LossSlot]) -> tuple[float, float] | None:
    """(standby_kw, k) from a Huber fit of ``loss = standby x hours + k x charge``."""
    design = np.array([[s.hours, s.charge_kwh] for s in slots], dtype=float)
    target = np.array([s.loss_kwh for s in slots], dtype=float)
    coefficients = _huber_fit(design, target)
    if coefficients is None:
        return None
    return float(coefficients[0]), float(coefficients[1])


def _ac_charge_loss(k: float) -> float:
    """AC-basis charge loss from the per-DC-kWh coefficient (design D2a)."""
    return k / (1.0 + k)


def estimate_inverter_loss(
    rows: Sequence[Mapping[str, Any]],
    loss_sensor_values: Mapping[str, float] | None,
    config_capacity_kwh: float,
    as_of: datetime,
) -> InverterLossEstimates:
    """Robust fit of standby power and AC-side charge loss from eligible slots."""
    slots = _loss_slots(rows, loss_sensor_values or {}, as_of)
    charge_total = sum(s.charge_kwh for s in slots)
    span_days = (slots[-1].start - slots[0].start).total_seconds() / 86400.0 if slots else 0.0
    evidence: dict[str, Any] = {
        "slots": len(slots),
        "sensor_slots": sum(1 for s in slots if s.from_sensor),
        "span_days": round(span_days, 2),
        "charge_kwh": round(charge_total, 3),
        "window_start": slots[0].start.date().isoformat() if slots else None,
        "window_end": slots[-1].start.date().isoformat() if slots else None,
    }

    def both(reason: str, **extra: Any) -> InverterLossEstimates:
        rejected = _rejected(reason, {**evidence, **extra})
        return InverterLossEstimates(charge_loss=rejected, standby_w=rejected)

    if config_capacity_kwh <= 0:
        return both("battery capacity is not configured")
    if len(slots) < LOSS_MIN_SLOTS or span_days < LOSS_MIN_SPAN_DAYS:
        return both(
            f"{len(slots)} reliable slots over {span_days:.0f} days, "
            f"{LOSS_MIN_SLOTS} slots over {LOSS_MIN_SPAN_DAYS} days needed"
        )
    needed_charge = LOSS_MIN_CHARGE_CAPACITIES * config_capacity_kwh
    if charge_total < needed_charge:
        return both(f"{charge_total:.0f} kWh charged, {needed_charge:.0f} kWh needed")
    fit = _fit_slots(slots)
    if fit is None:
        return both("charge energy does not vary enough to fit the loss")
    standby_kw, k = fit
    half = len(slots) // 2
    first, second = _fit_slots(slots[:half]), _fit_slots(slots[half:])
    confidence = split_half_confidence(
        _ac_charge_loss(first[1]) if first else None,
        _ac_charge_loss(second[1]) if second else None,
        len(slots),
        LOSS_CONFIDENCE_FULL_SLOTS,
        LOSS_CONFIDENCE_TOLERANCE,
    )
    evidence = {**evidence, "k_per_dc_charge": round(k, 5)}
    return InverterLossEstimates(
        charge_loss=_finish(
            _ac_charge_loss(k), confidence, evidence, CHARGE_LOSS_BOUNDS, "inverter charge loss"
        ),
        standby_w=_finish(
            standby_kw * 1000.0, confidence, evidence, STANDBY_W_BOUNDS, "inverter standby power"
        ),
    )
