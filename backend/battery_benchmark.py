"""Daily battery hindsight benchmark (pure logic, no I/O).

One local day is compared with the best battery plan possible in hindsight:
the same recorded load, PV and prices, solved by Kepler in benchmark mode and
ending at the same modelled stored energy as reality. Actual, hindsight and
no-battery schedules are priced with the same per-slot net-grid model.
"""

from __future__ import annotations

import math
import time
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytz

from backend.measurement_provenance import parse_quality_flags, parse_recording, soc_metadata
from planner.errors import PlannerError
from planner.solver.kepler import KeplerSolver
from planner.solver.types import KeplerBenchmark, KeplerConfig, KeplerInput, KeplerInputSlot

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

BENCHMARK_VERSION = 1
SLOT_MINUTES = 15
CLEAN_METHODS = frozenset({"power_history", "derived_history", "disabled_zero"})
MAX_SNAPSHOT_SLOTS = 2
CAPACITY_HISTORY_DAYS = 6
CAPACITY_TOLERANCE = 0.15
CAPACITY_MIN_MOVEMENT_PP = 20.0
CAPACITY_MIN_SLOT_DELTA_PP = 1.0
MIN_IDEAL_VALUE_SEK = 1.0
EV_ACTIVE_KWH = 1e-6
REQUIRED_FIELDS = (
    "import_kwh",
    "export_kwh",
    "pv_kwh",
    "load_kwh",
    "water_kwh",
    "ev_charging_kwh",
    "soc_end_percent",
    "import_price_sek_kwh",
    "export_price_sek_kwh",
)


def state_key(day: date) -> str:
    return f"battery_benchmark:{day.isoformat()}"


def slot_bill(net_grid_kwh: float, import_price: float, export_price: float) -> float:
    """Net-grid cost of one slot: import paid at import price, export earned at export price."""
    return max(net_grid_kwh, 0.0) * import_price - max(-net_grid_kwh, 0.0) * export_price


def meter_battery_flow(row: Mapping[str, Any]) -> tuple[float, float]:
    """(charge, discharge) kWh implied by the meter balance of one slot."""
    net = (
        row["import_kwh"]
        - row["export_kwh"]
        + row["pv_kwh"]
        - row["load_kwh"]
        - row["water_kwh"]
        - row["ev_charging_kwh"]
    )
    return max(net, 0.0), max(-net, 0.0)


def slot_recording(row: Mapping[str, Any]) -> str | None:
    """'clean', 'snapshot' or None (not usable) from per-value recording provenance."""
    recording = parse_recording(parse_quality_flags(row.get("quality_flags")))
    if recording is None or not recording["components"]:
        return None
    if soc_metadata(recording, "end").get("source") != "live":
        return None
    methods = {c["method"] for c in recording["components"].values()}
    if methods <= CLEAN_METHODS:
        return "clean"
    if methods <= CLEAN_METHODS | {"snapshot"}:
        return "snapshot"
    return None


def schedule_cost(
    rows: Sequence[Mapping[str, Any]],
    flows: list[tuple[float, float]],
    wear_cost_sek_per_kwh: float,
) -> float:
    """Cost of a battery schedule on recorded demand, PV and prices (Kepler's wear split)."""
    total = 0.0
    for row, (charge, discharge) in zip(rows, flows, strict=True):
        demand = row["load_kwh"] + row["water_kwh"] + row["ev_charging_kwh"]
        net = demand - row["pv_kwh"] + charge - discharge
        total += slot_bill(net, row["import_price_sek_kwh"], row["export_price_sek_kwh"])
        total += (charge + discharge) * wear_cost_sek_per_kwh * 0.5
    return total


def rows_by_local_day(rows: list[dict[str, Any]], tz: Any) -> dict[date, list[dict[str, Any]]]:
    """Group slot rows by local date, each day sorted by real time (DST-safe)."""
    grouped: dict[date, list[dict[str, Any]]] = {}
    for row in sorted(rows, key=lambda r: datetime.fromisoformat(r["slot_start"])):
        local_day = datetime.fromisoformat(row["slot_start"]).astimezone(tz).date()
        grouped.setdefault(local_day, []).append(row)
    return grouped


def _local_day_bounds(day: date, tz: Any) -> tuple[datetime, datetime]:
    start = tz.localize(datetime.combine(day, datetime.min.time()))
    end = tz.localize(datetime.combine(day + timedelta(days=1), datetime.min.time()))
    return start, end


def _finite(row: Mapping[str, Any]) -> bool:
    return all(
        isinstance(row.get(k), int | float) and math.isfinite(row[k]) for k in REQUIRED_FIELDS
    )


def _recording_reason(
    day: date, rows_by_day: Mapping[date, list[dict[str, Any]]], tz: Any, now: datetime
) -> tuple[str | None, int]:
    """First failing data reason (or None) and the snapshot-slot count."""
    rows = rows_by_day.get(day, [])
    start, end = _local_day_bounds(day, tz)
    if end > now:
        return "not_finished", 0
    expected = int((end - start).total_seconds() // (SLOT_MINUTES * 60))
    times = [
        (datetime.fromisoformat(r["slot_start"]), datetime.fromisoformat(r["slot_end"]))
        for r in rows
    ]
    if (
        len(rows) != expected
        or times[0][0] != start
        or times[-1][1] != end
        or any(times[i - 1][1] != times[i][0] for i in range(1, len(times)))
    ):
        return "incomplete_day", 0
    previous = rows_by_day.get(day - timedelta(days=1), [])
    if not previous or datetime.fromisoformat(previous[-1]["slot_end"]) != start:
        return "incomplete_day", 0
    states = [slot_recording(r) for r in [previous[-1], *rows]]
    snapshots = states.count("snapshot")
    if None in states or snapshots > MAX_SNAPSHOT_SLOTS:
        return "not_clean_recording", snapshots
    if not all(_finite(r) for r in [previous[-1], *rows]):
        return "missing_values", snapshots
    return None, snapshots


def implied_capacity(
    days: list[list[dict[str, Any]]], prev_rows: list[dict[str, Any]], config: KeplerConfig
) -> tuple[float | None, float]:
    """Capacity implied by meter flows vs SoC change, and total SoC movement in pp."""
    energy = movement = 0.0
    for prev, rows in zip(prev_rows, days, strict=True):
        soc_before = prev["soc_end_percent"]
        for row in rows:
            delta = row["soc_end_percent"] - soc_before
            soc_before = row["soc_end_percent"]
            charge, discharge = meter_battery_flow(row)
            stored = charge * config.charge_efficiency - discharge / config.discharge_efficiency
            if abs(delta) >= CAPACITY_MIN_SLOT_DELTA_PP and stored * delta > 0:
                energy += abs(stored)
                movement += abs(delta)
    return (energy / movement * 100.0 if movement > 0 else None), movement


def base_record(day: date, config: KeplerConfig) -> dict[str, Any]:
    return {
        "version": BENCHMARK_VERSION,
        "date": day.isoformat(),
        "status": "excluded",
        "reason": None,
        "capacity_kwh": config.capacity_kwh,
        "implied_capacity_kwh": None,
        "snapshot_slots": 0,
        "actual_cost_sek": None,
        "ideal_cost_sek": None,
        "no_battery_cost_sek": None,
        "missed_sek": None,
        "value_actual_sek": None,
        "value_ideal_sek": None,
        "score": None,
        "solver_status": None,
        "solve_seconds": None,
    }


def benchmark_day(
    day: date,
    rows_by_day: Mapping[date, list[dict[str, Any]]],
    config: KeplerConfig,
    now: datetime,
) -> dict[str, Any]:
    """Score one local day. rows_by_day holds slot rows sorted by time, keyed by local date,
    covering the day and the days before it (start SoC and capacity history)."""
    tz = pytz.timezone(config.timezone_name)
    record = base_record(day, config)
    reason, record["snapshot_slots"] = _recording_reason(day, rows_by_day, tz, now)
    if reason is not None:
        record["reason"] = reason
        return record

    rows = rows_by_day[day]
    history = [day]
    cursor = day - timedelta(days=1)
    while len(history) <= CAPACITY_HISTORY_DAYS and cursor in rows_by_day:
        if _recording_reason(cursor, rows_by_day, tz, now)[0] is None:
            history.append(cursor)
        cursor -= timedelta(days=1)
    implied, movement = implied_capacity(
        [rows_by_day[d] for d in history],
        [rows_by_day[d - timedelta(days=1)][-1] for d in history],
        config,
    )
    record["implied_capacity_kwh"] = implied
    if (
        implied is not None
        and movement >= CAPACITY_MIN_MOVEMENT_PP
        and abs(implied - config.capacity_kwh) / config.capacity_kwh > CAPACITY_TOLERANCE
    ):
        record["reason"] = "capacity_mismatch"
        return record

    flows = [meter_battery_flow(r) for r in rows]
    initial = (
        rows_by_day[day - timedelta(days=1)][-1]["soc_end_percent"] * config.capacity_kwh / 100
    )
    terminal = initial + sum(
        c * config.charge_efficiency - d / config.discharge_efficiency for c, d in flows
    )
    if not (0 <= initial <= config.capacity_kwh and 0 <= terminal <= config.capacity_kwh):
        record["reason"] = "stock_out_of_range"
        return record

    slots = [
        KeplerInputSlot(
            start_time=datetime.fromisoformat(r["slot_start"]),
            end_time=datetime.fromisoformat(r["slot_end"]),
            load_kwh=r["load_kwh"] + r["water_kwh"] + r["ev_charging_kwh"],
            pv_kwh=r["pv_kwh"],
            import_price_sek_kwh=r["import_price_sek_kwh"],
            export_price_sek_kwh=r["export_price_sek_kwh"],
        )
        for r in rows
    ]
    bench = KeplerBenchmark(
        terminal_soc_kwh=terminal,
        no_discharge_slots=[r["ev_charging_kwh"] > EV_ACTIVE_KWH for r in rows],
    )
    started = time.monotonic()
    try:
        result = KeplerSolver().solve(KeplerInput(slots, initial, benchmark=bench), config)
        status = "time_limit" if result.time_limit_hit else result.status_msg
        optimal = result.is_optimal and not result.time_limit_hit
    except PlannerError as exc:
        status, optimal, result = (
            str(exc.details.get("solver_status") or exc.code.value),
            False,
            None,
        )
    record["solve_seconds"] = round(time.monotonic() - started, 3)
    record["solver_status"] = status
    if not optimal or result is None:
        record["status"] = "failed"
        record["reason"] = "solver_not_optimal"
        return record

    wear = config.wear_cost_sek_per_kwh
    actual = schedule_cost(rows, flows, wear)
    ideal = schedule_cost(rows, [(s.charge_kwh, s.discharge_kwh) for s in result.slots], wear)
    no_battery = schedule_cost(rows, [(0.0, 0.0)] * len(rows), wear)
    value_ideal = no_battery - ideal
    record.update(
        status="scored",
        actual_cost_sek=actual,
        ideal_cost_sek=ideal,
        no_battery_cost_sek=no_battery,
        missed_sek=actual - ideal,
        value_actual_sek=no_battery - actual,
        value_ideal_sek=value_ideal,
        score=(no_battery - actual) / value_ideal if value_ideal >= MIN_IDEAL_VALUE_SEK else None,
    )
    return record


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals over scored days plus counts by status and reason."""
    scored = [r for r in records if r.get("status") == "scored"]
    value_actual = sum(r["value_actual_sek"] for r in scored)
    value_ideal = sum(r["value_ideal_sek"] for r in scored)
    by_status: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    for r in records:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        if r.get("reason"):
            by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1
    return {
        "missed_sek": sum(r["missed_sek"] for r in scored),
        "value_actual_sek": value_actual,
        "value_ideal_sek": value_ideal,
        "score": value_actual / value_ideal if value_ideal >= MIN_IDEAL_VALUE_SEK else None,
        "days_scored": len(scored),
        "days_total": len(records),
        "by_status": by_status,
        "by_reason": by_reason,
    }
