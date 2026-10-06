"""Calibration and accounting for the estimated battery-management comparison.

All energy values use the installation's recorded sensor boundary. This module has
no database, configuration, or async dependencies so its numerical behavior can be
tested independently from the API.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise, product
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

METHOD_VERSION = "recorded-boundary-v1"
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
    """Return comparison amounts and status reason after validating the selected period."""
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
        else prior_soc_percent
    )
    if not _valid_soc(start_soc):
        return None, "missing_start_soc"
    if not _valid_soc(ordered[-1].soc_end_percent):
        return None, "missing_end_soc"

    grid, storage = diagnostics.grid_model, diagnostics.battery_model
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
    if rmse > 0.25 or abs(mean_error) > 0.03 or abs(cost_error) > max(1.0, 0.05 * gross):
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
    return {
        "status": "available",
        "reason": "validated",
        "method_version": METHOD_VERSION,
        "through": (ordered[-1].start.astimezone(UTC) + SLOT).isoformat(),
        "calibration": diagnostics.as_dict(),
        "darkstar": darkstar.rounded(),
        "self_use": self_use.rounded(),
        "saving_sek": round(saving, 3),
        "reference_price_sek_kwh": round(reference, 6),
        "points": points,
    }, None


def _finite_nonnegative(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and value >= 0


def _finite_price(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def _valid_soc(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and 0 <= value <= 100


def _flags(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
            return cast("dict[str, Any]", decoded) if isinstance(decoded, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def calibration_eligible(row: RecordedObservation) -> bool:
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
    observations: Iterable[RecordedObservation], capacity_kwh: float, comparison_end: datetime
) -> CalibrationResult:
    """Fit and validate model on a UTC chronological 80/20 split."""
    end_utc = comparison_end.astimezone(UTC)
    start_utc = end_utc - timedelta(days=30)
    rows = sorted(
        (
            r
            for r in observations
            if calibration_eligible(r)
            and start_utc <= r.start.astimezone(UTC)
            and r.start.astimezone(UTC) + SLOT <= end_utc
        ),
        key=lambda r: r.start.astimezone(UTC),
    )
    if len(rows) < 1000:
        return CalibrationResult("insufficient_data", "too_few_grid_observations")
    pairs = _battery_pairs(rows, capacity_kwh)
    if len(pairs) < 200:
        return CalibrationResult("insufficient_data", "too_few_battery_pairs")
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
        return CalibrationResult("insufficient_data", "unidentifiable_flow_direction")
    # Predict directly from observed PV and battery actions, preserving within-slot
    # coexistence at the installation's recorded sensor boundary.
    hold_rows = rows[grid_cut:]
    if len(hold_rows) != len(grid_hold):
        return CalibrationResult("insufficient_data", "inconsistent_grid_observations")
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
        return CalibrationResult("unreliable_model", "holdout_validation_failed", diagnostics)
    return CalibrationResult("available", "validated", diagnostics)
