"""Calibration and accounting for the estimated battery-management comparison.

All energy values use the installation's recorded sensor boundary. This module has
no database, configuration, or async dependencies so its numerical behavior can be
tested independently from the API.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise, product
from typing import TYPE_CHECKING, Any, Literal

from backend.measurement_provenance import (
    ENERGY_SEMANTICS,
    MEASUREMENT_METHODS,
    is_sha256,
    measurement_value_digest,
    metadata_object,
    parse_quality_flags,
    parse_recording,
    soc_metadata,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

METHOD_VERSION = "configured-estimate-verified-v1"
FIT_RESOLUTION = 0.002
FIT_MIN = 0.80
FIT_MAX = 1.00
SLOT = timedelta(minutes=15)


@dataclass(frozen=True)
class RecordedObservation:
    start: datetime
    import_kwh: float | None
    export_kwh: float | None
    import_price: float | None
    export_price: float | None
    pv_kwh: float | None
    load_kwh: float | None
    water_kwh: float | None
    ev_kwh: float | None
    charge_kwh: float | None
    discharge_kwh: float | None
    soc_start_percent: float | None
    soc_end_percent: float | None
    quality_flags: str | dict[str, Any] | None = None

    @property
    def demand_kwh(self) -> float | None:
        values = (self.load_kwh, self.water_kwh, self.ev_kwh)
        if any(value is None for value in values):
            return None
        return sum(float(value) for value in values if value is not None)


@dataclass(frozen=True)
class GridModel:
    eta_out: float
    eta_in: float

    def net_grid(self, pv: float, demand: float, charge: float, discharge: float) -> float:
        bus = pv + discharge - charge
        converted_bus = self.eta_out * bus if bus >= 0 else bus / self.eta_in
        return demand - converted_bus


@dataclass(frozen=True)
class BatteryModel:
    eta_charge: float
    eta_discharge: float

    def stored_delta(self, charge: float, discharge: float) -> float:
        return self.eta_charge * charge - discharge / self.eta_discharge


@dataclass(frozen=True)
class FitDiagnostics:
    grid_model: GridModel
    battery_model: BatteryModel
    grid_training_samples: int
    grid_validation_samples: int
    battery_training_pairs: int
    battery_validation_pairs: int
    training_start: str
    training_end: str
    validation_start: str
    validation_end: str
    grid_rmse_kwh: float
    grid_mean_error_kwh: float
    battery_rmse_kwh: float
    battery_mean_error_kwh: float
    net_cost_error_sek: float
    gross_billing_volume_sek: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "method_version": METHOD_VERSION,
            "eta_out": self.grid_model.eta_out,
            "eta_in": self.grid_model.eta_in,
            "eta_charge": self.battery_model.eta_charge,
            "eta_discharge": self.battery_model.eta_discharge,
            "grid_training_samples": self.grid_training_samples,
            "grid_validation_samples": self.grid_validation_samples,
            "battery_training_pairs": self.battery_training_pairs,
            "battery_validation_pairs": self.battery_validation_pairs,
            "training_start": self.training_start,
            "training_end": self.training_end,
            "validation_start": self.validation_start,
            "validation_end": self.validation_end,
            "grid_rmse_kwh": self.grid_rmse_kwh,
            "grid_mean_error_kwh": self.grid_mean_error_kwh,
            "battery_rmse_kwh": self.battery_rmse_kwh,
            "battery_mean_error_kwh": self.battery_mean_error_kwh,
            "net_cost_error_sek": self.net_cost_error_sek,
            "gross_billing_volume_sek": self.gross_billing_volume_sek,
        }


@dataclass(frozen=True)
class CalibrationResult:
    status: str
    reason: str
    diagnostics: FitDiagnostics | None = None
    history: dict[str, Any] | None = None


@dataclass(frozen=True)
class ComparisonSlot:
    observation: RecordedObservation
    bucket: str


@dataclass(frozen=True)
class ComparisonSide:
    grid_cost_sek: float
    wear_cost_sek: float
    stored_energy_change_kwh: float
    stored_energy_value_sek: float
    comparison_cost_sek: float

    def rounded(self) -> dict[str, float]:
        return {
            "grid_cost_sek": round(self.grid_cost_sek, 3),
            "wear_cost_sek": round(self.wear_cost_sek, 3),
            "stored_energy_change_kwh": round(self.stored_energy_change_kwh, 3),
            "stored_energy_value_sek": round(self.stored_energy_value_sek, 3),
            "comparison_cost_sek": round(self.comparison_cost_sek, 3),
        }


@dataclass(frozen=True)
class SimulationFlow:
    grid_net_kwh: float
    charge_kwh: float
    discharge_kwh: float
    stored_kwh: float


@dataclass(frozen=True)
class ComparisonBattery:
    capacity_kwh: float
    min_soc_percent: float
    max_soc_percent: float
    max_charge_w: float
    max_discharge_w: float


def simulate_self_use(
    row: RecordedObservation,
    stored_kwh: float,
    battery: ComparisonBattery,
    grid: GridModel,
    storage: BatteryModel,
) -> SimulationFlow:
    """Simulate one completed slot at the common recorded sensor boundary."""
    assert row.pv_kwh is not None and row.demand_kwh is not None
    min_kwh = battery.capacity_kwh * battery.min_soc_percent / 100
    max_kwh = battery.capacity_kwh * battery.max_soc_percent / 100
    charge_limit = battery.max_charge_w / 1000 * SLOT.total_seconds() / 3600
    discharge_limit = battery.max_discharge_w / 1000 * SLOT.total_seconds() / 3600
    surplus = grid.eta_out * row.pv_kwh - row.demand_kwh
    charge = discharge = 0.0
    if surplus >= 0:
        charge = min(
            surplus / grid.eta_out,
            charge_limit,
            max(0.0, max_kwh - stored_kwh) / storage.eta_charge,
        )
        next_stored = stored_kwh + charge * storage.eta_charge
    else:
        usable = max(0.0, stored_kwh - min_kwh)
        # PV supplies household/water demand first and may then supply the EV.
        # Storage serves only the remaining non-EV demand; EV energy stays in
        # total grid demand and cannot be supplied by battery discharge.
        assert row.load_kwh is not None and row.water_kwh is not None
        non_ev_deficit = max(0.0, row.load_kwh + row.water_kwh - grid.eta_out * row.pv_kwh)
        discharge = min(
            non_ev_deficit / grid.eta_out, discharge_limit, usable * storage.eta_discharge
        )
        next_stored = stored_kwh - discharge / storage.eta_discharge
    net = grid.net_grid(float(row.pv_kwh), float(row.demand_kwh), charge, discharge)
    return SimulationFlow(net, charge, discharge, next_stored)


def _net_flows(net: float) -> tuple[float, float]:
    return max(net, 0.0), max(-net, 0.0)


def build_comparison(
    rows: Sequence[RecordedObservation],
    prior_soc_percent: float | None,
    battery: ComparisonBattery,
    diagnostics: FitDiagnostics,
    cycle_cost_kwh: float,
    bucket_for: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    """Build amounts only after strict calibrated selected-period validation."""
    return _build_comparison_amounts(
        rows,
        prior_soc_percent,
        battery,
        diagnostics.grid_model,
        diagnostics.battery_model,
        cycle_cost_kwh,
        bucket_for,
        period_policy="calibrated",
        calibration=diagnostics.as_dict(),
    )


def build_estimated_comparison(
    rows: Sequence[RecordedObservation],
    prior_soc_percent: float | None,
    battery: ComparisonBattery,
    grid: GridModel,
    storage: BatteryModel,
    cycle_cost_kwh: float,
    bucket_for: Any,
    expected_boundary: str | None = None,
    assumed_boundaries: frozenset[str] = frozenset(),
) -> tuple[dict[str, Any] | None, str | None]:
    """Build an explicitly assumed estimate without claiming calibration validation."""
    if any(not estimate_row_eligible(row, expected_boundary, assumed_boundaries) for row in rows):
        return None, "unsupported_period_measurements"
    return _build_comparison_amounts(
        rows,
        prior_soc_percent,
        battery,
        grid,
        storage,
        cycle_cost_kwh,
        bucket_for,
        period_policy="configured_estimate",
        calibration=None,
    )


def _build_comparison_amounts(
    rows: Sequence[RecordedObservation],
    prior_soc_percent: float | None,
    battery: ComparisonBattery,
    grid: GridModel,
    storage: BatteryModel,
    cycle_cost_kwh: float,
    bucket_for: Any,
    *,
    period_policy: Literal["calibrated", "configured_estimate"],
    calibration: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Shared economics with explicit strict-validation or estimate policy."""
    if period_policy not in {"calibrated", "configured_estimate"}:
        return None, "invalid_policy"
    numeric_configuration = (
        battery.capacity_kwh,
        battery.min_soc_percent,
        battery.max_soc_percent,
        battery.max_charge_w,
        battery.max_discharge_w,
        grid.eta_out,
        grid.eta_in,
        storage.eta_charge,
        storage.eta_discharge,
        cycle_cost_kwh,
    )
    if (
        not all(math.isfinite(value) for value in numeric_configuration)
        or battery.capacity_kwh <= 0
        or not 0 <= battery.min_soc_percent < battery.max_soc_percent <= 100
        or battery.max_charge_w < 0
        or battery.max_discharge_w < 0
        or not 0 < grid.eta_out <= 1
        or not 0 < grid.eta_in <= 1
        or not 0 < storage.eta_charge <= 1
        or not 0 < storage.eta_discharge <= 1
        or cycle_cost_kwh < 0
    ):
        return None, "invalid_configuration"
    if not rows:
        return None, "no_data"
    ordered = sorted(rows, key=lambda row: row.start.astimezone(UTC))
    for left, right in pairwise(ordered):
        if right.start.astimezone(UTC) - left.start.astimezone(UTC) != SLOT:
            return None, "missing_completed_slot"
    for row in ordered:
        flags = _flags(row.quality_flags)
        essential_energies = (
            row.import_kwh,
            row.export_kwh,
            row.pv_kwh,
            row.load_kwh,
            row.water_kwh,
            row.ev_kwh,
            row.charge_kwh,
            row.discharge_kwh,
        )
        if (
            flags.get("exclude") is True
            or flags.get("source") == "backfill"
            or not all(_finite_nonnegative(value) for value in essential_energies)
            or not _valid_soc(row.soc_end_percent)
            or row.start.tzinfo is None
        ):
            return None, "invalid_observation"
        if not _finite_price(row.import_price) or not _finite_price(row.export_price):
            return None, "missing_price"
        if row.demand_kwh is None or not _finite_nonnegative(row.pv_kwh):
            return None, "missing_energy"
        if row.charge_kwh is None or row.discharge_kwh is None:
            return None, "missing_battery_flow"
    start_soc = (
        ordered[0].soc_start_percent
        if _valid_soc(ordered[0].soc_start_percent)
        and (
            trusted_soc_endpoint(ordered[0], "start")
            or (period_policy == "configured_estimate" and _legacy_estimate_row(ordered[0]))
        )
        else prior_soc_percent
    )
    if not _valid_soc(start_soc):
        return None, "missing_start_soc"
    if not _valid_soc(ordered[-1].soc_end_percent):
        return None, "missing_end_soc"

    modeled_nets: list[float] = []
    actual_nets: list[float] = []
    for observation in ordered:
        assert (
            observation.pv_kwh is not None
            and observation.demand_kwh is not None
            and observation.charge_kwh is not None
            and observation.discharge_kwh is not None
            and observation.import_kwh is not None
            and observation.export_kwh is not None
        )
        modeled_nets.append(
            grid.net_grid(
                observation.pv_kwh,
                observation.demand_kwh,
                observation.charge_kwh,
                observation.discharge_kwh,
            )
        )
        actual_nets.append(observation.import_kwh - observation.export_kwh)
    rmse, mean_error = _errors(actual_nets, modeled_nets)
    cost_error = gross = 0.0
    for row, predicted in zip(ordered, modeled_nets, strict=True):
        assert row.import_price is not None and row.export_price is not None
        assert row.import_kwh is not None and row.export_kwh is not None
        actual_import, actual_export = _net_flows(row.import_kwh - row.export_kwh)
        actual_cost = actual_import * row.import_price - actual_export * row.export_price
        import_kwh, export_kwh = _net_flows(predicted)
        modeled_cost = import_kwh * row.import_price - export_kwh * row.export_price
        cost_error += modeled_cost - actual_cost
        gross += abs(row.import_price) * float(row.import_kwh) + abs(row.export_price) * float(
            row.export_kwh
        )
    if period_policy == "calibrated" and (
        rmse > 0.25 or abs(mean_error) > 0.03 or abs(cost_error) > max(1.0, 0.05 * gross)
    ):
        return None, "period_validation_failed"

    assert start_soc is not None and ordered[-1].soc_end_percent is not None
    common_start = start_soc * battery.capacity_kwh / 100
    simulated_stored = common_start
    real_grid_cost = self_grid_cost = real_wear = self_wear = 0.0
    simulated_points: dict[str, list[float]] = {}
    bucket_end_states: dict[str, tuple[float, float]] = {}
    real_end_stored = ordered[-1].soc_end_percent * battery.capacity_kwh / 100
    for row, real_net in zip(ordered, modeled_nets, strict=True):
        assert row.import_price is not None and row.export_price is not None
        assert (
            row.import_kwh is not None
            and row.export_kwh is not None
            and row.charge_kwh is not None
            and row.discharge_kwh is not None
        )
        imp, exp = _net_flows(real_net)
        real_grid_cost += imp * row.import_price - exp * row.export_price
        assert row.pv_kwh is not None and row.demand_kwh is not None
        flow = simulate_self_use(row, simulated_stored, battery, grid, storage)
        simulated_stored = flow.stored_kwh
        sim_imp, sim_exp = _net_flows(flow.grid_net_kwh)
        self_grid_cost += sim_imp * row.import_price - sim_exp * row.export_price
        real_wear += (row.charge_kwh + row.discharge_kwh) * cycle_cost_kwh * 0.5
        self_wear += (flow.charge_kwh + flow.discharge_kwh) * cycle_cost_kwh * 0.5
        key = bucket_for(row.start)
        accum = simulated_points.setdefault(key, [0.0, 0.0, 0.0, 0.0])
        accum[0] += imp * row.import_price - exp * row.export_price
        accum[1] += sim_imp * row.import_price - sim_exp * row.export_price
        accum[2] += (row.charge_kwh + row.discharge_kwh) * cycle_cost_kwh * 0.5
        accum[3] += (flow.charge_kwh + flow.discharge_kwh) * cycle_cost_kwh * 0.5
        if not _valid_soc(row.soc_end_percent):
            return None, "missing_bucket_soc"
        assert row.soc_end_percent is not None
        bucket_end_states[key] = (
            row.soc_end_percent * battery.capacity_kwh / 100,
            simulated_stored,
        )
    assert all(row.import_price is not None for row in ordered)
    reference = (
        sum(r.import_price for r in ordered if r.import_price is not None)
        / len(ordered)
        * grid.eta_out
        * storage.eta_discharge
    )
    real_change, self_change = real_end_stored - common_start, simulated_stored - common_start
    real_value, self_value = real_change * reference, self_change * reference
    darkstar = ComparisonSide(
        real_grid_cost, real_wear, real_change, real_value, real_grid_cost + real_wear - real_value
    )
    self_use = ComparisonSide(
        self_grid_cost, self_wear, self_change, self_value, self_grid_cost + self_wear - self_value
    )
    saving = self_use.comparison_cost_sek - darkstar.comparison_cost_sek
    real_cumulative = self_cumulative = 0.0
    points: list[dict[str, str | float]] = []
    for key in sorted(
        simulated_points, key=lambda value: datetime.fromisoformat(value).astimezone(UTC)
    ):
        values = simulated_points[key]
        real_cumulative += values[0] + values[2]
        self_cumulative += values[1] + values[3]
        # Include the stored-energy adjustment at each measured boundary, valued at the
        # one period reference price so both endpoint values reconcile with summaries.
        real_stored, simulated_end = bucket_end_states[key]
        real_cum_cost = real_cumulative - (real_stored - common_start) * reference
        self_cum_cost = self_cumulative - (simulated_end - common_start) * reference
        points.append(
            {
                "start": key,
                "darkstar_cumulative_comparison_cost_sek": round(real_cum_cost, 3),
                "self_use_cumulative_comparison_cost_sek": round(self_cum_cost, 3),
            }
        )
    # Force endpoint consistency after rounding through the exact summary arithmetic.
    if points:
        points[-1]["darkstar_cumulative_comparison_cost_sek"] = round(
            darkstar.comparison_cost_sek, 3
        )
        points[-1]["self_use_cumulative_comparison_cost_sek"] = round(
            self_use.comparison_cost_sek, 3
        )
    result: dict[str, Any] = {
        "status": "available" if period_policy == "calibrated" else "estimated",
        "reason": "validated" if period_policy == "calibrated" else "configured_losses",
        "basis": "calibrated" if period_policy == "calibrated" else "configured_losses",
        "label": "Verified"
        if period_policy == "calibrated"
        else "Estimate based on configured losses",
        "method_version": METHOD_VERSION,
        "through": (ordered[-1].start.astimezone(UTC) + SLOT).isoformat(),
        "darkstar": darkstar.rounded(),
        "self_use": self_use.rounded(),
        "saving_sek": round(saving, 3),
        "reference_price_sek_kwh": round(reference, 6),
        "points": points,
    }
    if calibration is not None:
        result["calibration"] = calibration
    return result, None


def _legacy_estimate_row(row: RecordedObservation) -> bool:
    """Whether metadata absence is a legacy unknown eligible only for estimates."""
    flags = _flags(row.quality_flags)
    return (
        flags.get("source") == "recorder"
        and "recording" not in flags
        and "comparison_history" not in flags
        and flags.get("exclude") is not True
    )


def estimate_row_eligible(
    row: RecordedObservation,
    expected_boundary: str | None = None,
    assumed_boundaries: frozenset[str] = frozenset(),
) -> bool:
    """Accept supported observed provenance or explicitly assumed legacy recorder rows."""
    flags = _flags(row.quality_flags)
    if (
        row.start.tzinfo is None
        or flags.get("exclude") is True
        or flags.get("source") == "backfill"
    ):
        return False
    # Only explicitly registered earlier encodings may be assumed. Other
    # changed boundaries and unsupported modern methods remain rejected.
    if (
        not _legacy_estimate_row(row)
        and trusted_row_provenance(row, expected_boundary) is None
        and not any(
            trusted_row_provenance(row, boundary) is not None for boundary in assumed_boundaries
        )
    ):
        return False
    recording = parse_recording(flags)
    if recording is not None:
        for endpoint in ("start", "end"):
            soc = soc_metadata(recording, endpoint)
            if soc.get("source") == "cached" or soc.get("owner") == "backfill":
                return False
    return _valid_soc(row.soc_end_percent)


def comparison_row_usable(
    row: RecordedObservation,
    expected_boundary: str | None = None,
    assumed_boundaries: frozenset[str] = frozenset(),
) -> bool:
    """Whether one slot may enter a simulated run.

    Combines the estimate eligibility rules with the per-row measurement checks the
    simulation applies, so a slot failing them is excluded instead of failing the
    whole period.
    """
    if not estimate_row_eligible(row, expected_boundary, assumed_boundaries):
        return False
    essential_energies = (
        row.import_kwh,
        row.export_kwh,
        row.pv_kwh,
        row.load_kwh,
        row.water_kwh,
        row.ev_kwh,
        row.charge_kwh,
        row.discharge_kwh,
    )
    return (
        all(_finite_nonnegative(value) for value in essential_energies)
        and _finite_price(row.import_price)
        and _finite_price(row.export_price)
    )


def split_comparison_runs(
    expected_starts: Sequence[datetime],
    rows_by_start: dict[datetime, RecordedObservation],
    usable: Callable[[RecordedObservation], bool],
) -> list[list[RecordedObservation]]:
    """Split a period into maximal runs of consecutive usable slots.

    ``expected_starts`` and the ``rows_by_start`` keys are UTC slot starts, so adjacency
    is elapsed 15-minute time and stays correct across DST changes. Missing or unusable
    slots break runs and are excluded.
    """
    runs: list[list[RecordedObservation]] = []
    current: list[RecordedObservation] = []
    for start in sorted(expected_starts):
        row = rows_by_start.get(start)
        if row is not None and usable(row):
            current.append(row)
            continue
        if current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


_SIDE_KEYS = (
    "grid_cost_sek",
    "wear_cost_sek",
    "stored_energy_change_kwh",
    "stored_energy_value_sek",
    "comparison_cost_sek",
)


def combine_run_comparisons(runs: Sequence[tuple[dict[str, Any], int]]) -> dict[str, Any]:
    """Merge independently simulated runs into one period result.

    ``runs`` holds ``(result, slot_count)`` in chronological order. Totals and the saving
    are sums of the per-run values (each run values its own stored-energy change at its
    own reference price). The reference price reported is the slot-weighted mean. Point
    series are made cumulative across runs by offsetting each run with the final values
    of the runs before it.
    """
    if len(runs) == 1:
        return dict(runs[0][0])
    combined: dict[str, Any] = {k: v for k, v in runs[0][0].items() if k != "points"}
    for side in ("darkstar", "self_use"):
        combined[side] = {
            key: round(sum(float(result[side][key]) for result, _ in runs), 3) for key in _SIDE_KEYS
        }
    combined["saving_sek"] = round(sum(float(result["saving_sek"]) for result, _ in runs), 3)
    total_slots = sum(count for _, count in runs)
    combined["reference_price_sek_kwh"] = round(
        sum(float(result["reference_price_sek_kwh"]) * count for result, count in runs)
        / total_slots,
        6,
    )
    combined["through"] = runs[-1][0]["through"]
    points: list[dict[str, Any]] = []
    dark_offset = self_offset = 0.0
    for result, _ in runs:
        run_points: list[dict[str, Any]] = result.get("points") or []
        for point in run_points:
            shifted: dict[str, Any] = {
                "start": point["start"],
                "darkstar_cumulative_comparison_cost_sek": round(
                    dark_offset + float(point["darkstar_cumulative_comparison_cost_sek"]), 3
                ),
                "self_use_cumulative_comparison_cost_sek": round(
                    self_offset + float(point["self_use_cumulative_comparison_cost_sek"]), 3
                ),
            }
            if points and points[-1]["start"] == shifted["start"]:
                # A bucket shared by two runs reports the later cumulative value.
                points[-1] = shifted
            else:
                points.append(shifted)
        dark_offset += float(result["darkstar"]["comparison_cost_sek"])
        self_offset += float(result["self_use"]["comparison_cost_sek"])
    if points:
        points[-1]["darkstar_cumulative_comparison_cost_sek"] = combined["darkstar"][
            "comparison_cost_sek"
        ]
        points[-1]["self_use_cumulative_comparison_cost_sek"] = combined["self_use"][
            "comparison_cost_sek"
        ]
    combined["points"] = points
    return combined


def _finite_nonnegative(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and value >= 0


def _finite_price(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def _valid_soc(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and 0 <= value <= 100


def _flags(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    return parse_quality_flags(raw)


def calibration_eligible(row: RecordedObservation) -> bool:
    flags = _flags(row.quality_flags)
    if flags.get("exclude") is True or flags.get("source") == "backfill":
        return False
    if trusted_row_provenance(row) is None:
        return False
    energies = (
        row.import_kwh,
        row.export_kwh,
        row.pv_kwh,
        row.load_kwh,
        row.water_kwh,
        row.ev_kwh,
        row.charge_kwh,
        row.discharge_kwh,
    )
    if not all(_finite_nonnegative(v) for v in energies) or not (
        _finite_price(row.import_price) and _finite_price(row.export_price)
    ):
        return False
    # Historical recorder rows commonly lack slot-start SoC; contiguous end-SoC
    # pairs still identify battery factors. Validate start SoC when it exists.
    if (
        row.soc_start_percent is not None and not _valid_soc(row.soc_start_percent)
    ) or not _valid_soc(row.soc_end_percent):
        return False
    return row.start.tzinfo is not None


_REQUIRED_COMPONENTS = (
    "import",
    "export",
    "pv",
    "load",
    "water",
    "ev",
    "battery_charge",
    "battery_discharge",
)
_LEGACY_METHODS = {"cumulative_meter_energy", "power_history_energy"}
_ENERGY_COMPATIBILITY_REGISTRY = {
    "observed_algorithm": {
        # Recorder integration is zero-order hold over each 15-minute slot.
        "power-history-step-zoh-v1": "full-slot-measured-energy-v1",
    },
    "legacy_method": {
        # These are accepted only when a reviewed interval attestation also
        # establishes the same boundary, slot semantics, and live-SoC history.
        "cumulative_meter_energy": "full-slot-measured-energy-v1",
        "power_history_energy": "full-slot-measured-energy-v1",
    },
}
_OBSERVED_ALGORITHMS = _ENERGY_COMPATIBILITY_REGISTRY["observed_algorithm"]
_LEGACY_COMPATIBILITY = _ENERGY_COMPATIBILITY_REGISTRY["legacy_method"]


def _measured_energy_cohort(boundary: str, semantics: str) -> str:
    """Identity for the single explicitly registered full-slot compatibility class."""
    compatibility_class = "full-slot-measured-energy-v1"
    return f"measured:{boundary}:{semantics}:{compatibility_class}:compat-v1"


def trusted_row_provenance(
    row: RecordedObservation, expected_boundary: str | None = None
) -> tuple[str, str, str] | None:
    """Return (cohort id, boundary, source class) only for explicit trusted evidence."""
    flags = _flags(row.quality_flags)
    if flags.get("exclude") is True or flags.get("source") == "backfill":
        return None
    comparison_history = metadata_object(flags.get("comparison_history"))
    if comparison_history.get("disposition") == "exclude_from_comparison":
        return None
    recording = parse_recording(flags)
    if recording is not None:
        boundary = str(recording["boundary_fingerprint"])
        if boundary == "mixed" or (expected_boundary and boundary != expected_boundary):
            return None
        components = recording["components"]
        for component in _REQUIRED_COMPONENTS:
            item = metadata_object(components.get(component))
            if item.get("owner") != "recorder":
                return None
            if item.get("schema_version", recording["schema_version"]) != 1:
                return None
            if item.get("method") not in MEASUREMENT_METHODS:
                return None
            if item.get("boundary_fingerprint", boundary) != boundary:
                return None
            if item.get("semantics", ENERGY_SEMANTICS) != ENERGY_SEMANTICS:
                return None
            if (
                not isinstance(item.get("algorithm", recording.get("algorithm")), str)
                or item.get("algorithm", recording.get("algorithm")) not in _OBSERVED_ALGORITHMS
            ):
                return None
            if item.get("method") in {"snapshot", "mixed", "unconfigured_zero", "unknown"}:
                return None
        soc = soc_metadata(recording, "end")
        if soc.get("owner") != "recorder" or soc.get("source") != "live":
            return None
        if (
            soc.get("schema_version", recording["schema_version"]) != 1
            or soc.get("boundary_fingerprint", boundary) != boundary
            or soc.get("semantics", ENERGY_SEMANTICS) != ENERGY_SEMANTICS
            or not isinstance(soc.get("algorithm", recording.get("algorithm")), str)
            or soc.get("algorithm", recording.get("algorithm")) not in _OBSERVED_ALGORITHMS
        ):
            return None
        algorithm = str(recording.get("algorithm", ""))
        if algorithm not in _OBSERVED_ALGORITHMS or recording.get("semantics") != ENERGY_SEMANTICS:
            return None
        return _measured_energy_cohort(boundary, recording["semantics"]), boundary, "observed"

    # A malformed or unsupported observed-provenance object is never downgraded
    # into legacy history by attaching a separate attestation.
    if "recording" in flags:
        return None

    attestation = metadata_object(flags.get("legacy_attestation"))
    if type(attestation.get("schema_version")) is not int or attestation.get("schema_version") != 1:
        return None
    if attestation.get("disposition") != "verified_measured_energy":
        return None
    if (
        comparison_history.get("schema_version") != 1
        or comparison_history.get("disposition") != "verified_measured_energy"
        or comparison_history.get("evidence_digest") != attestation.get("evidence_digest")
    ):
        return None
    if attestation.get("semantics") != ENERGY_SEMANTICS:
        return None
    boundary = attestation.get("boundary_fingerprint")
    evidence = attestation.get("evidence_digest")
    methods = metadata_object(attestation.get("methods"))
    soc_method = attestation.get("soc_method")
    if not isinstance(boundary, str) or not is_sha256(boundary) or not is_sha256(evidence):
        return None
    if expected_boundary and boundary != expected_boundary:
        return None
    if set(methods) != set(_REQUIRED_COMPONENTS) or any(
        not isinstance(methods.get(name), str) or methods.get(name) not in _LEGACY_METHODS
        for name in _REQUIRED_COMPONENTS
    ):
        return None
    if soc_method != "live_soc_history":
        return None
    compatibility_classes = {_LEGACY_COMPATIBILITY.get(method) for method in methods.values()}
    if compatibility_classes != {"full-slot-measured-energy-v1"}:
        return None
    try:
        value_digest = observation_value_digest(row)
    except (ValueError, TypeError):
        return None
    if attestation.get("affected_measurement_digest") != value_digest:
        return None
    cohort = _measured_energy_cohort(boundary, attestation["semantics"])
    return cohort, boundary, "attested"


def _cohort_selection(
    observations: Iterable[RecordedObservation],
    start_utc: datetime,
    end_utc: datetime,
    expected_boundary: str | None,
) -> tuple[list[RecordedObservation], dict[str, Any]]:
    considered = [
        row
        for row in observations
        if row.start.tzinfo is not None
        and start_utc <= row.start.astimezone(UTC)
        and row.start.astimezone(UTC) + SLOT <= end_utc
    ]
    exclusions = dict.fromkeys(
        (
            "explicitly_excluded",
            "backfill",
            "snapshot_or_mixed",
            "cached_soc",
            "unknown_provenance",
            "boundary_mismatch",
            "invalid_measurements",
            "incompatible_cohort",
        ),
        0,
    )
    candidates: list[tuple[RecordedObservation, tuple[str, str, str]]] = []
    latest_signature: str | None = None
    latest_signature_start: datetime | None = None
    for row in considered:
        flags = _flags(row.quality_flags)
        if flags.get("exclude") is True:
            exclusions["explicitly_excluded"] += 1
            continue
        comparison_history = metadata_object(flags.get("comparison_history"))
        if comparison_history.get("disposition") == "exclude_from_comparison":
            exclusions["explicitly_excluded"] += 1
            continue
        if flags.get("source") == "backfill":
            exclusions["backfill"] += 1
            continue
        rec = parse_recording(flags)
        raw_rec = metadata_object(flags.get("recording"))
        if raw_rec:
            boundary = raw_rec.get("boundary_fingerprint")
            if (
                isinstance(boundary, str)
                and is_sha256(boundary)
                and (expected_boundary is None or boundary == expected_boundary)
            ):
                if (
                    raw_rec.get("schema_version") == 1
                    and isinstance(raw_rec.get("algorithm"), str)
                    and raw_rec.get("algorithm") in _OBSERVED_ALGORITHMS
                    and raw_rec.get("semantics") == ENERGY_SEMANTICS
                ):
                    signature = _measured_energy_cohort(boundary, ENERGY_SEMANTICS)
                else:
                    signature = (
                        f"unsupported:{boundary}:"
                        + hashlib.sha256(
                            json.dumps(raw_rec, sort_keys=True, default=str).encode()
                        ).hexdigest()
                    )
                if (
                    latest_signature_start is None
                    or row.start.astimezone(UTC) > latest_signature_start
                ):
                    latest_signature, latest_signature_start = signature, row.start.astimezone(UTC)
        attestation = metadata_object(flags.get("legacy_attestation"))
        trusted_attestation = (
            trusted_row_provenance(row, expected_boundary) if attestation and not raw_rec else None
        )
        if trusted_attestation is not None and (
            latest_signature_start is None or row.start.astimezone(UTC) > latest_signature_start
        ):
            latest_signature, latest_signature_start = (
                trusted_attestation[0],
                row.start.astimezone(UTC),
            )
        if rec is not None:
            components = rec.get("components", {})
            if (
                any(
                    isinstance(components.get(name), dict)
                    and components[name].get("owner") == "backfill"
                    for name in _REQUIRED_COMPONENTS
                )
                or soc_metadata(rec, "end").get("owner") == "backfill"
            ):
                exclusions["backfill"] += 1
                continue
            methods = [components.get(name, {}).get("method") for name in _REQUIRED_COMPONENTS]
            if any(
                method in {"snapshot", "mixed", "unconfigured_zero", "unknown"}
                for method in methods
            ):
                exclusions["snapshot_or_mixed"] += 1
                continue
            if soc_metadata(rec, "end").get("source") == "cached":
                exclusions["cached_soc"] += 1
                continue
        provenance = trusted_row_provenance(row, expected_boundary)
        if provenance is None:
            if (
                rec is not None
                and expected_boundary
                and rec.get("boundary_fingerprint") != expected_boundary
            ):
                exclusions["boundary_mismatch"] += 1
            else:
                exclusions["unknown_provenance"] += 1
            continue
        if not calibration_eligible_without_provenance(row):
            exclusions["invalid_measurements"] += 1
            continue
        candidates.append((row, provenance))
    all_candidates = candidates
    if latest_signature is not None:
        candidates = [item for item in candidates if item[1][0] == latest_signature]
        exclusions["incompatible_cohort"] += len(all_candidates) - len(candidates)
    if not candidates:
        return [], {
            "considered_count": len(considered),
            "eligible_count": 0,
            "exclusions": exclusions,
            "cohort_id": latest_signature,
            "cohort_start": (
                None if latest_signature_start is None else latest_signature_start.isoformat()
            ),
        }
    by_cohort: dict[str, list[tuple[RecordedObservation, tuple[str, str, str]]]] = {}
    for item in candidates:
        by_cohort.setdefault(item[1][0], []).append(item)
    if latest_signature is not None:
        chosen_id = latest_signature
        chosen = by_cohort.get(chosen_id, [])
    else:
        chosen_id, chosen = max(
            by_cohort.items(), key=lambda pair: max(row.start.astimezone(UTC) for row, _ in pair[1])
        )
    selected = sorted((row for row, _ in chosen), key=lambda row: row.start.astimezone(UTC))
    return selected, {
        "considered_count": len(considered),
        "eligible_count": len(selected),
        "exclusions": exclusions,
        "cohort_id": chosen_id,
        "cohort_start": selected[0].start.astimezone(UTC).isoformat(),
    }


def calibration_eligible_without_provenance(row: RecordedObservation) -> bool:
    """Numeric checks shared by selection after provenance has been validated."""
    flags = _flags(row.quality_flags)
    if flags.get("exclude") is True or flags.get("source") == "backfill":
        return False
    energies = (
        row.import_kwh,
        row.export_kwh,
        row.pv_kwh,
        row.load_kwh,
        row.water_kwh,
        row.ev_kwh,
        row.charge_kwh,
        row.discharge_kwh,
    )
    return (
        all(_finite_nonnegative(value) for value in energies)
        and _finite_price(row.import_price)
        and _finite_price(row.export_price)
        and (row.soc_start_percent is None or _valid_soc(row.soc_start_percent))
        and _valid_soc(row.soc_end_percent)
        and row.start.tzinfo is not None
    )


def _grid_sample(row: RecordedObservation) -> tuple[float, float, float, float] | None:
    demand = row.demand_kwh
    if demand is None or row.pv_kwh is None or row.charge_kwh is None or row.discharge_kwh is None:
        return None
    bus = row.pv_kwh + row.discharge_kwh - row.charge_kwh
    observed_net = float(row.import_kwh or 0) - float(row.export_kwh or 0)
    return bus, demand, observed_net, float(row.import_price or 0.0)


def _battery_pairs(
    rows: Sequence[RecordedObservation], capacity_kwh: float
) -> list[tuple[datetime, float, float, float]]:
    ordered = sorted(rows, key=lambda row: row.start.astimezone(UTC))
    pairs: list[tuple[datetime, float, float, float]] = []
    for left, right in pairwise(ordered):
        if right.start.astimezone(UTC) - left.start.astimezone(UTC) != SLOT:
            continue
        vals = (right.charge_kwh, right.discharge_kwh, left.soc_end_percent, right.soc_end_percent)
        if any(value is None or not math.isfinite(value) for value in vals):
            continue
        assert left.soc_end_percent is not None and right.soc_end_percent is not None
        if not (10 < left.soc_end_percent < 95 and 10 < right.soc_end_percent < 95):
            continue
        charge = float(right.charge_kwh or 0.0)
        discharge = float(right.discharge_kwh or 0.0)
        if charge + discharge < 0.05:
            continue
        delta = (right.soc_end_percent - left.soc_end_percent) * capacity_kwh / 100.0
        pairs.append((right.start, charge, discharge, delta))
    return pairs


def _factor_grid() -> tuple[float, ...]:
    return tuple(round(FIT_MIN + i * FIT_RESOLUTION, 3) for i in range(101))


def _fit_grid(samples: Sequence[tuple[float, float, float, float]]) -> GridModel | None:
    pos: list[tuple[float, float, float]] = [
        (bus, demand, observed) for bus, demand, observed, _ in samples if bus > 1e-9
    ]
    neg: list[tuple[float, float, float]] = [
        (bus, demand, observed) for bus, demand, observed, _ in samples if bus < -1e-9
    ]
    if len(pos) < 30 or len(neg) < 30 or sum(x[0] for x in pos) < 3 or sum(-x[0] for x in neg) < 3:
        return None
    factors = _factor_grid()
    # The two directions are independent scalar least-squares fits.
    out_candidates: list[tuple[float, float]] = []
    for eta in factors:
        err = sum((demand - eta * bus - observed) ** 2 for bus, demand, observed in pos)
        out_candidates.append((err, eta))
    in_candidates: list[tuple[float, float]] = []
    for eta in factors:
        err = sum((demand - bus / eta - observed) ** 2 for bus, demand, observed in neg)
        in_candidates.append((err, eta))
    return GridModel(min(out_candidates)[1], min(in_candidates)[1])


def _fit_battery(samples: Sequence[tuple[datetime, float, float, float]]) -> BatteryModel | None:
    charge = [row for row in samples if row[1] > 1e-9]
    discharge = [row for row in samples if row[2] > 1e-9]
    if (
        len(charge) < 30
        or len(discharge) < 30
        or sum(r[1] for r in charge) < 3
        or sum(r[2] for r in discharge) < 3
    ):
        return None
    factors = _factor_grid()
    # The factors are independent only when the two observed flow columns have
    # full rank. Simultaneous proportional flows identify only their net effect.
    cc = sum(c * c for _, c, _, _ in samples)
    dd = sum(d * d for _, _, d, _ in samples)
    cd = sum(c * d for _, c, d, _ in samples)
    if cc * dd - cd * cd <= 1e-10 * cc * dd:
        return None
    cy = sum(c * delta for _, c, _, delta in samples)
    dy = sum(d * delta for _, _, d, delta in samples)
    yy = sum(delta * delta for _, _, _, delta in samples)
    best: tuple[float, float, float] | None = None
    for eta_charge, eta_discharge in product(factors, repeat=2):
        inverse_discharge = 1 / eta_discharge
        error = (
            eta_charge * eta_charge * cc
            + inverse_discharge * inverse_discharge * dd
            - 2 * eta_charge * inverse_discharge * cd
            - 2 * eta_charge * cy
            + 2 * inverse_discharge * dy
            + yy
        )
        candidate = (error, eta_charge, eta_discharge)
        if best is None or candidate < best:
            best = candidate
    return None if best is None else BatteryModel(best[1], best[2])


def _errors(actual: Sequence[float], predicted: Sequence[float]) -> tuple[float, float]:
    errors = [got - want for got, want in zip(predicted, actual, strict=True)]
    return math.sqrt(sum(e * e for e in errors) / len(errors)), sum(errors) / len(errors)


def fit_calibration(
    observations: Iterable[RecordedObservation],
    capacity_kwh: float,
    comparison_end: datetime,
    expected_boundary: str | None = None,
) -> CalibrationResult:
    """Fit and validate model on a UTC chronological 80/20 split."""
    end_utc = comparison_end.astimezone(UTC)
    start_utc = end_utc - timedelta(days=30)
    rows, history = _cohort_selection(observations, start_utc, end_utc, expected_boundary)
    if len(rows) < 1000:
        reason = (
            "insufficient_compatible_history" if history["eligible_count"] else "unverified_history"
        )
        return CalibrationResult("insufficient_data", reason, history=history)
    pairs = _battery_pairs(rows, capacity_kwh)
    if len(pairs) < 200:
        return CalibrationResult("insufficient_data", "too_few_battery_pairs", history=history)
    grid_samples = [_grid_sample(row) for row in rows]
    grid: list[tuple[float, float, float, float]] = [
        sample for sample in grid_samples if sample is not None
    ]
    grid_cut = int(len(grid) * 0.8)
    pair_cut = int(len(pairs) * 0.8)
    grid_train, grid_hold = grid[:grid_cut], grid[grid_cut:]
    pair_train, pair_hold = pairs[:pair_cut], pairs[pair_cut:]
    gm = _fit_grid(grid_train)
    bm = _fit_battery(pair_train)
    if gm is None or bm is None:
        return CalibrationResult(
            "insufficient_data", "unidentifiable_flow_direction", history=history
        )
    # Predict directly from observed PV and battery actions, preserving within-slot
    # coexistence at the installation's recorded sensor boundary.
    hold_rows = rows[grid_cut:]
    if len(hold_rows) != len(grid_hold):
        return CalibrationResult(
            "insufficient_data", "inconsistent_grid_observations", history=history
        )
    grid_pred: list[float] = []
    grid_actual: list[float] = []
    for row in hold_rows:
        assert (
            row.pv_kwh is not None
            and row.demand_kwh is not None
            and row.charge_kwh is not None
            and row.discharge_kwh is not None
            and row.import_kwh is not None
            and row.export_kwh is not None
        )
        grid_pred.append(gm.net_grid(row.pv_kwh, row.demand_kwh, row.charge_kwh, row.discharge_kwh))
        grid_actual.append(row.import_kwh - row.export_kwh)
    grmse, gmean = _errors(grid_actual, grid_pred)
    battery_actual = [s[3] for s in pair_hold]
    battery_pred = [bm.stored_delta(s[1], s[2]) for s in pair_hold]
    brmse, bmean = _errors(battery_actual, battery_pred)
    cost_error = 0.0
    gross = 0.0
    for row, prediction in zip(hold_rows, grid_pred, strict=True):
        assert row.import_price is not None and row.export_price is not None
        observed_import, observed_export = _net_flows(
            float(row.import_kwh or 0) - float(row.export_kwh or 0)
        )
        actual = observed_import * row.import_price - observed_export * row.export_price
        predicted = max(prediction, 0) * row.import_price - max(-prediction, 0) * row.export_price
        cost_error += predicted - actual
        gross += abs(row.import_price) * float(row.import_kwh or 0) + abs(row.export_price) * float(
            row.export_kwh or 0
        )
    diagnostics = FitDiagnostics(
        gm,
        bm,
        len(grid_train),
        len(grid_hold),
        len(pair_train),
        len(pair_hold),
        rows[0].start.astimezone(UTC).isoformat(),
        rows[grid_cut - 1].start.astimezone(UTC).isoformat(),
        rows[grid_cut].start.astimezone(UTC).isoformat(),
        rows[-1].start.astimezone(UTC).isoformat(),
        grmse,
        gmean,
        brmse,
        bmean,
        cost_error,
        gross,
    )
    if (
        grmse > 0.25
        or abs(gmean) > 0.03
        or brmse > 0.25
        or abs(bmean) > 0.03
        or abs(cost_error) > max(1.0, 0.05 * gross)
    ):
        return CalibrationResult(
            "unreliable_model", "holdout_validation_failed", diagnostics, history
        )
    return CalibrationResult("available", "validated", diagnostics, history)


def observation_value_digest(row: RecordedObservation) -> str:
    return measurement_value_digest(
        (
            row.start,
            row.import_kwh,
            row.export_kwh,
            row.pv_kwh,
            row.load_kwh,
            row.water_kwh,
            row.ev_kwh,
            row.charge_kwh,
            row.discharge_kwh,
            row.soc_start_percent,
            row.soc_end_percent,
            row.import_price,
            row.export_price,
        )
    )


def trusted_soc_provenance(
    row: RecordedObservation, endpoint: str, expected_boundary: str | None = None
) -> tuple[str, str, str] | None:
    """Validate the used SoC endpoint independently of unused energy/start values."""
    if endpoint not in {"start", "end"} or row.start.tzinfo is None:
        return None
    value = row.soc_start_percent if endpoint == "start" else row.soc_end_percent
    if not _valid_soc(value):
        return None
    flags = _flags(row.quality_flags)
    if (
        flags.get("exclude") is True
        or flags.get("source") == "backfill"
        or metadata_object(flags.get("comparison_history")).get("disposition")
        == "exclude_from_comparison"
    ):
        return None
    recording = parse_recording(flags)
    if recording is None:
        # Legacy evidence binds the complete measurement preimage; it remains
        # the only way to establish a strict historical SoC endpoint.
        return trusted_row_provenance(row, expected_boundary)
    boundary = recording["boundary_fingerprint"]
    if (
        (expected_boundary is not None and boundary != expected_boundary)
        or not isinstance(recording.get("algorithm"), str)
        or recording["algorithm"] not in _OBSERVED_ALGORITHMS
    ):
        return None
    soc = soc_metadata(recording, endpoint)
    if not (
        soc.get("source") == "live"
        and soc.get("owner") == "recorder"
        and soc.get("schema_version", recording["schema_version"]) == 1
        and soc.get("boundary_fingerprint", boundary) == boundary
        and soc.get("semantics", ENERGY_SEMANTICS) == ENERGY_SEMANTICS
        and isinstance(soc.get("algorithm", recording.get("algorithm")), str)
        and soc.get("algorithm", recording.get("algorithm")) in _OBSERVED_ALGORITHMS
    ):
        return None
    return _measured_energy_cohort(boundary, ENERGY_SEMANTICS), boundary, "observed"


def trusted_soc_endpoint(row: RecordedObservation, endpoint: str) -> bool:
    return trusted_soc_provenance(row, endpoint) is not None


def estimate_soc_endpoint_eligible(
    row: RecordedObservation,
    endpoint: str,
    expected_boundary: str,
    assumed_boundaries: frozenset[str] = frozenset(),
) -> bool:
    """Trust/assume only the independent state used as an estimate anchor."""
    value = row.soc_start_percent if endpoint == "start" else row.soc_end_percent
    if endpoint not in {"start", "end"} or row.start.tzinfo is None or not _valid_soc(value):
        return False
    if _legacy_estimate_row(row):
        return True
    return trusted_soc_provenance(row, endpoint, expected_boundary) is not None or any(
        trusted_soc_provenance(row, endpoint, boundary) is not None
        for boundary in assumed_boundaries
    )


def history_coverage(
    observations: Iterable[RecordedObservation],
    comparison_end: datetime,
    expected_boundary: str | None = None,
) -> dict[str, Any]:
    """Report the exact candidate/cohort classification without numerical fitting."""
    end_utc = comparison_end.astimezone(UTC)
    return _cohort_selection(
        observations, end_utc - timedelta(days=30), end_utc, expected_boundary
    )[1]
