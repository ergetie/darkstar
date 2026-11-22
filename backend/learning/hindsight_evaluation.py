"""Offline walk-forward check: would learned efficiencies have predicted the SoC better?

For every archived planner run the learned parameters are estimated from data recorded
before the run started, then the SoC is rolled forward from the recorded start SoC under
(a) the efficiencies the run's own configuration used and (b) the learned effective ones,
and compared with the recorded SoC at 6, 12 and 24 hours.

Both arms use the same AC-side battery flow per slot, derived from the energy balance
(``net = import - export + pv - load - water - ev``, the quantity ``meter_battery_flow``
uses) after subtracting the walk-forward standby power for both arms alike. The DC-side
battery counters are never used here: the planner's efficiencies describe AC-side flows
(design D2a).

Everything is read-only: the archive is read through ``plan_archive.list_records`` and the
files themselves, the database through a read-only sqlite connection.
"""

from __future__ import annotations

import gzip
import json
import logging
import math
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from backend.learning.battery_estimators import (
    KEY_CHARGE_LOSS,
    KEY_RTE,
    Estimate,
    estimate_inverter_loss,
    estimate_round_trip_efficiency,
    loss_slot_eligible,
    slot_bounds,
)
from backend.learning.learned_parameters import (
    ParameterState,
    ResolvedBattery,
    battery_section,
    config_capacity_kwh,
    resolve_battery_parameters,
)
from backend.services import plan_archive

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    import pandas as pd

logger = logging.getLogger("darkstar.learning.hindsight")

SLOT = timedelta(minutes=15)
HORIZONS_HOURS = (6, 12, 24)
GATE_HORIZON_HOURS = 24
# The learned 24 h mean absolute SoC error may exceed the config one by at most this (pp).
MAX_WORSE_PP = 0.25
MIN_EVALUABLE_RUNS = 10
# Learned parameters are estimated once per UTC day from data before that day's start,
# which is before every run of the day (no leakage, and one estimate serves many runs).
DB_LOOKBACK_DAYS = 125


@dataclass(frozen=True)
class ArchivedRun:
    run_id: str
    started_at: datetime
    config: dict[str, Any]
    config_pair: tuple[float, float]  # (charge, discharge) efficiency of the run's own config
    capacity_kwh: float
    record: dict[str, Any] = field(default_factory=lambda: {}, repr=False)


@dataclass
class ArmError:
    abs_error_pp: float
    bias_pp: float


@dataclass
class RunResult:
    run_id: str
    started_at: str
    as_of: str
    config_pair: tuple[float, float]
    learned_pair: tuple[float, float]
    horizons: dict[int, dict[str, ArmError]] = field(default_factory=lambda: {})
    skipped_horizons: dict[int, str] = field(default_factory=lambda: {})
    # The learned effective parameters of the run, for the optional replan replay.
    learned_resolved: ResolvedBattery | None = field(default=None, repr=False)


@dataclass
class EvaluationReport:
    runs: list[RunResult] = field(default_factory=lambda: [])
    skipped_runs: list[dict[str, str]] = field(default_factory=lambda: [])
    aggregate: dict[int, dict[str, float | int | None]] = field(default_factory=lambda: {})
    runs_total: int = 0

    @property
    def evaluable_runs(self) -> int:
        """Runs with a result at the gate horizon (24 h)."""
        return sum(1 for run in self.runs if GATE_HORIZON_HOURS in run.horizons)

    def gate_difference_pp(self) -> float | None:
        gate = self.aggregate.get(GATE_HORIZON_HOURS)
        if not gate or gate.get("n") in (None, 0):
            return None
        return float(cast("float", gate["learned_mae_pp"])) - float(
            cast("float", gate["config_mae_pp"])
        )

    def verdict(self) -> tuple[bool, str]:
        """(passed, reason). Fails with too few evaluable runs or a worse learned 24 h MAE."""
        if self.evaluable_runs < MIN_EVALUABLE_RUNS:
            return False, (
                f"only {self.evaluable_runs} evaluable runs, {MIN_EVALUABLE_RUNS} needed"
            )
        difference = self.gate_difference_pp()
        if difference is not None and difference > MAX_WORSE_PP:
            return False, (
                f"learned 24 h MAE is {difference:.2f} pp worse than config "
                f"(limit {MAX_WORSE_PP} pp)"
            )
        return True, "learned efficiencies predict the SoC at least as well as config"

    def to_dict(self) -> dict[str, Any]:
        passed, reason = self.verdict()
        return {
            "passed": passed,
            "reason": reason,
            "runs_total": self.runs_total,
            "evaluable_runs": self.evaluable_runs,
            "aggregate": {str(h): values for h, values in self.aggregate.items()},
            "runs": [
                {
                    "run_id": run.run_id,
                    "started_at": run.started_at,
                    "as_of": run.as_of,
                    "config_pair": list(run.config_pair),
                    "learned_pair": list(run.learned_pair),
                    "horizons": {
                        str(h): {arm: vars(error) for arm, error in arms.items()}
                        for h, arms in run.horizons.items()
                    },
                    "skipped_horizons": {str(h): why for h, why in run.skipped_horizons.items()},
                }
                for run in self.runs
            ],
            "skipped_runs": self.skipped_runs,
        }


# --- Loading ------------------------------------------------------------------------------


def _config_pair(record: Mapping[str, Any], config: Mapping[str, Any]) -> tuple[float, float]:
    """The configuration efficiencies of a run (never the learned ones it may have used)."""
    parameters = record.get("battery_parameters")
    if isinstance(parameters, dict):
        stored = cast("dict[str, Any]", parameters)
        charge = stored.get("config_charge_efficiency")
        discharge = stored.get("config_discharge_efficiency")
        if isinstance(charge, int | float) and isinstance(discharge, int | float):
            return float(charge), float(discharge)
    battery = battery_section(config)
    return (
        float(battery.get("charge_efficiency", 0.95)),
        float(battery.get("discharge_efficiency", 0.95)),
    )


def load_archive_runs(archive_dir: Path, days: int | None = None) -> list[ArchivedRun]:
    """Archived ``ok`` runs, oldest first. Unreadable or incomplete files are skipped."""
    runs: list[ArchivedRun] = []
    for entry in plan_archive.list_records(days=days, directory=archive_dir):
        if entry["outcome"] != "ok":
            continue
        try:
            with gzip.open(archive_dir / entry["name"], "rt", encoding="utf-8") as handle:
                record = cast("dict[str, Any]", json.load(handle))
            started = datetime.fromisoformat(str(record["started_at"]))
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            config = cast("dict[str, Any]", record.get("config") or {})
            runs.append(
                ArchivedRun(
                    run_id=str(record.get("run_id") or entry["name"]),
                    started_at=started,
                    config=config,
                    config_pair=_config_pair(record, config),
                    capacity_kwh=config_capacity_kwh(config),
                    record=record,
                )
            )
        except Exception as exc:
            logger.warning("Plan archive record %s skipped: %s", entry["name"], exc)
    return runs


def load_slot_rows(db_path: Path | str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """``slot_observations`` rows of a window through a read-only connection."""
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
    try:
        connection.row_factory = sqlite3.Row
        cursor = connection.execute(
            "SELECT * FROM slot_observations WHERE slot_start >= ? AND slot_start < ? "
            "ORDER BY slot_start",
            (start.isoformat(), end.isoformat()),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        connection.close()


# --- Walk-forward -------------------------------------------------------------------------


@dataclass(frozen=True)
class _Slot:
    end: datetime
    hours: float
    net_kwh: float  # AC-side import - export + pv - load - water - ev
    eligible: bool
    soc_end: float | None


def _index_slots(rows: Sequence[Mapping[str, Any]]) -> dict[datetime, _Slot]:
    bounds = [slot_bounds(row) for row in rows]
    data_end = max((b[1] for b in bounds if b is not None), default=None)
    slots: dict[datetime, _Slot] = {}
    if data_end is None:
        return slots
    for row, bound in zip(rows, bounds, strict=True):
        if bound is None:
            continue
        start, end = bound
        eligible = loss_slot_eligible(row, data_end)
        net = 0.0
        if eligible:
            net = (
                float(row["import_kwh"])
                - float(row["export_kwh"])
                + float(row["pv_kwh"])
                - float(row["load_kwh"])
                - float(row["water_kwh"])
                - float(row["ev_charging_kwh"])
            )
        soc = row.get("soc_end_percent")
        slots[start] = _Slot(
            end=end,
            hours=(end - start).total_seconds() / 3600.0,
            net_kwh=net,
            eligible=eligible,
            soc_end=float(soc) if isinstance(soc, int | float) and math.isfinite(soc) else None,
        )
    return slots


def _estimates_as_pair(
    config: Mapping[str, Any],
    rte: Estimate,
    charge_loss: Estimate,
    standby: Estimate,
    as_of: datetime,
) -> tuple[ResolvedBattery, float] | str:
    """The learned effective pair (through the shared resolution seam) and standby watts."""
    for estimate in (rte, charge_loss):
        if not estimate.accepted:
            return f"learned parameters unavailable: {estimate.rejected_reason}"
    states = {
        key: ParameterState(
            key=key,
            learned_value=estimate.value,
            applied_value=estimate.value,
            estimated_at=as_of,
            applied_at=as_of,
        )
        for key, estimate in ((KEY_RTE, rte), (KEY_CHARGE_LOSS, charge_loss))
    }
    resolved = resolve_battery_parameters(config, states, as_of)
    return resolved, standby.value if standby.accepted and standby.value is not None else 0.0


def _roll(
    slots: Mapping[datetime, _Slot],
    first: datetime,
    count: int,
    start_soc_percent: float,
    capacity_kwh: float,
    standby_kw: float,
    pairs: Mapping[str, tuple[float, float]],
) -> tuple[dict[str, list[float]], int, str | None]:
    """Predicted SoC % after each slot for each arm, up to the first unusable slot.

    Returns (per-arm predictions, number of usable slots, reason the roll stopped early).
    """
    stored = dict.fromkeys(pairs, start_soc_percent / 100.0 * capacity_kwh)
    predictions: dict[str, list[float]] = {arm: [] for arm in pairs}
    cursor = first
    for index in range(count):
        slot = slots.get(cursor)
        if slot is None:
            return predictions, index, f"slot {cursor.isoformat()} is missing"
        if not slot.eligible:
            return (
                predictions,
                index,
                f"slot {cursor.isoformat()} is not eligible "
                "(unreliable base load, unclean recording or a missing value)",
            )
        net = slot.net_kwh - standby_kw * slot.hours
        charge, discharge = max(net, 0.0), max(-net, 0.0)
        for arm, (charge_eff, discharge_eff) in pairs.items():
            stored[arm] += charge * charge_eff - discharge / discharge_eff
            stored[arm] = min(max(stored[arm], 0.0), capacity_kwh)
            predictions[arm].append(stored[arm] / capacity_kwh * 100.0)
        cursor = slot.end
    return predictions, count, None


def evaluate_runs(
    runs: Sequence[ArchivedRun],
    rows: Sequence[Mapping[str, Any]],
    *,
    learned_override: tuple[float, float] | None = None,
    standby_override_w: float = 0.0,
) -> EvaluationReport:
    """Compare config and learned efficiencies on every run (see the module docstring).

    ``learned_override`` replaces the walk-forward estimate with an explicit
    ``(charge, discharge)`` pair, for tests of the comparison itself.
    """
    report = EvaluationReport(runs_total=len(runs))
    slots = _index_slots(rows)
    estimates: dict[datetime, tuple[ResolvedBattery, float] | str] = {}
    max_slots = max(HORIZONS_HOURS) * 4

    for run in runs:

        def skip(reason: str, run: ArchivedRun = run) -> None:
            report.skipped_runs.append({"run_id": run.run_id, "reason": reason})

        if run.capacity_kwh <= 0:
            skip("battery capacity is not configured")
            continue
        started = run.started_at.astimezone(UTC)
        as_of = started.replace(hour=0, minute=0, second=0, microsecond=0)
        if learned_override is not None:
            learned_pair = learned_override
            standby_w = standby_override_w
            learned_resolved = _override_resolved(run.config, learned_override, as_of)
        else:
            if as_of not in estimates:
                lookback = as_of - timedelta(days=DB_LOOKBACK_DAYS)
                visible = [r for r in rows if _before(r, as_of, lookback)]
                loss = estimate_inverter_loss(visible, None, run.capacity_kwh, as_of)
                estimates[as_of] = _estimates_as_pair(
                    run.config,
                    estimate_round_trip_efficiency(visible, run.capacity_kwh, as_of),
                    loss.charge_loss,
                    loss.standby_w,
                    as_of,
                )
            outcome = estimates[as_of]
            if isinstance(outcome, str):
                skip(outcome)
                continue
            resolved, standby_w = outcome
            learned_pair = (resolved.charge_efficiency, resolved.discharge_efficiency)
            learned_resolved = resolved

        first = started.replace(
            minute=started.minute - started.minute % 15, second=0, microsecond=0
        )
        anchor = slots.get(first - SLOT)
        if anchor is None or anchor.end != first or anchor.soc_end is None:
            skip("no recorded start SoC before the run")
            continue
        predictions, usable, stop_reason = _roll(
            slots,
            first,
            max_slots,
            anchor.soc_end,
            run.capacity_kwh,
            standby_w / 1000.0,
            {"config": run.config_pair, "learned": learned_pair},
        )
        result = RunResult(
            run_id=run.run_id,
            started_at=started.isoformat(),
            as_of=as_of.isoformat(),
            config_pair=run.config_pair,
            learned_pair=learned_pair,
            learned_resolved=learned_resolved,
        )
        for hours in HORIZONS_HOURS:
            count = hours * 4
            if usable < count:
                result.skipped_horizons[hours] = stop_reason or "horizon not recorded"
                continue
            last = _slot_at(slots, first, count - 1)
            if last is None or last.soc_end is None:
                result.skipped_horizons[hours] = "no recorded SoC at the end of the horizon"
                continue
            result.horizons[hours] = {
                arm: ArmError(
                    abs_error_pp=abs(predictions[arm][count - 1] - last.soc_end),
                    bias_pp=predictions[arm][count - 1] - last.soc_end,
                )
                for arm in ("config", "learned")
            }
        if result.horizons:
            report.runs.append(result)
        else:
            skip(next(iter(result.skipped_horizons.values()), "nothing evaluable"))

    for hours in HORIZONS_HOURS:
        errors = [run.horizons[hours] for run in report.runs if hours in run.horizons]
        if not errors:
            report.aggregate[hours] = {"n": 0}
            continue
        count = len(errors)
        report.aggregate[hours] = {
            "n": count,
            "config_mae_pp": sum(e["config"].abs_error_pp for e in errors) / count,
            "learned_mae_pp": sum(e["learned"].abs_error_pp for e in errors) / count,
            "config_bias_pp": sum(e["config"].bias_pp for e in errors) / count,
            "learned_bias_pp": sum(e["learned"].bias_pp for e in errors) / count,
        }
    return report


def _override_resolved(
    config: Mapping[str, Any], pair: tuple[float, float], as_of: datetime
) -> ResolvedBattery:
    """A learned-basis ``ResolvedBattery`` carrying an explicit efficiency pair."""
    base = resolve_battery_parameters(config, {}, as_of)
    return replace(base, charge_efficiency=pair[0], discharge_efficiency=pair[1], learned=True)


def _slot_at(slots: Mapping[datetime, _Slot], first: datetime, offset: int) -> _Slot | None:
    return slots.get(first + SLOT * offset)


def _before(row: Mapping[str, Any], as_of: datetime, lookback: datetime) -> bool:
    bounds = slot_bounds(row)
    return bounds is not None and lookback <= bounds[0] and bounds[1] <= as_of


def format_report(report: EvaluationReport) -> str:
    """Plain-text summary of the report."""
    passed, reason = report.verdict()
    lines = [
        f"Archived runs: {report.runs_total}, evaluable at 24 h: {report.evaluable_runs}, "
        f"skipped: {len(report.skipped_runs)}",
        f"Result: {'PASS' if passed else 'FAIL'} - {reason}",
        "",
        "Horizon  runs  config MAE  learned MAE  config bias  learned bias  (percentage points)",
    ]
    for hours, values in report.aggregate.items():
        if not values.get("n"):
            lines.append(f"{hours:>5} h     0  -")
            continue
        lines.append(
            f"{hours:>5} h {values['n']:>5}  {values['config_mae_pp']:>10.2f}  "
            f"{values['learned_mae_pp']:>11.2f}  {values['config_bias_pp']:>11.2f}  "
            f"{values['learned_bias_pp']:>12.2f}"
        )
    reasons: dict[str, int] = {}
    for skipped in report.skipped_runs:
        reasons[skipped["reason"]] = reasons.get(skipped["reason"], 0) + 1
    for run in report.runs:
        for why in run.skipped_horizons.values():
            reasons[why] = reasons.get(why, 0) + 1
    if reasons:
        lines += ["", "Skipped (runs or horizons) and why:"]
        lines += [
            f"  {count} x {why}" for why, count in sorted(reasons.items(), key=lambda i: -i[1])[:10]
        ]
    return "\n".join(lines)


# --- Optional plan-sensitivity replay -----------------------------------------------------


def _replay_config(config: Mapping[str, Any], db_path: Path | str) -> dict[str, Any]:
    """The run's config made safe for an offline replay.

    Telemetry writes are off, forecast reads point at the given (read-only) database, and
    everything that would reach the network is removed: without a site location the
    temperature forecast makes no request, and EV SoC sensors trigger no Home Assistant
    history read.
    """
    replay: dict[str, Any] = json.loads(json.dumps(config))
    learning = replay.setdefault("learning", {})
    learning["enable"] = False
    learning["sqlite_path"] = str(db_path)
    system = replay.get("system")
    if isinstance(system, dict):
        cast("dict[str, Any]", system).pop("location", None)
    chargers: list[Any] = replay.get("ev_chargers") or []
    for charger in chargers:
        if isinstance(charger, dict):
            cast("dict[str, Any]", charger).pop("soc_sensor", None)
    return replay


async def _replan_run(
    run: ArchivedRun, learned: ResolvedBattery, db_path: Path | str
) -> dict[str, Any]:
    import pytz

    from planner.pipeline import PlannerPipeline

    config = _replay_config(run.config, db_path)
    inputs = cast("dict[str, Any]", run.record.get("inputs") or {})
    now = run.started_at.astimezone(pytz.timezone(str(config.get("timezone", "UTC"))))
    frames: dict[str, pd.DataFrame] = {}
    for arm, parameters in (
        ("config", resolve_battery_parameters(config, {}, run.started_at)),
        ("learned", learned),
    ):
        pipeline = PlannerPipeline(config)
        frames[arm] = await pipeline.generate_schedule(
            copy_inputs(inputs),
            mode="full",
            save_to_file=False,
            publish_state=False,
            now_override=now,
            battery_parameters=parameters,
        )
    config_frame, learned_frame = frames["config"], frames["learned"]
    differing = int(sum(config_frame["action"] != learned_frame["action"]))
    charge_delta = float(
        sum(learned_frame["kepler_charge_kwh"]) - sum(config_frame["kepler_charge_kwh"])
    )
    return {
        "run_id": run.run_id,
        "differing_action_slots": differing,
        "planned_charge_delta_kwh": round(charge_delta, 3),
    }


def copy_inputs(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Independent copy of archived planner inputs (the pipeline may mutate them)."""
    return cast("dict[str, Any]", json.loads(json.dumps(inputs)))


def replan_report(
    report: EvaluationReport, runs: Sequence[ArchivedRun], db_path: Path | str, workdir: Path
) -> list[dict[str, Any]]:
    """Re-solve each evaluated run under the config and learned efficiencies.

    Informational only. Runs in ``workdir`` (the pipeline writes relative paths such as
    ``data/strategy_history.json``) so no project file is touched; a failing run is
    reported with its error and never aborts the rest.
    """
    import asyncio
    import contextlib

    by_id = {run.run_id: run for run in runs}
    results: list[dict[str, Any]] = []
    workdir.mkdir(parents=True, exist_ok=True)
    with contextlib.chdir(workdir):
        for result in report.runs:
            run = by_id[result.run_id]
            if result.learned_resolved is None:
                continue
            try:
                results.append(asyncio.run(_replan_run(run, result.learned_resolved, db_path)))
            except Exception as exc:
                results.append({"run_id": run.run_id, "error": f"{type(exc).__name__}: {exc}"})
    return results
