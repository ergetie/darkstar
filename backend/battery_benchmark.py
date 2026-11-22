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

from backend.measurement_provenance import (
    SUPPORTED_METHODS,
    base_load_demand_affected,
    device_component_methods,
    parse_quality_flags,
    parse_recording,
    soc_metadata,
)
from planner.errors import PlannerError
from planner.solver.kepler import KeplerSolver
from planner.solver.types import (
    KeplerBenchmark,
    KeplerBenchmarkRelaxation,
    KeplerConfig,
    KeplerInput,
    KeplerInputSlot,
    KeplerResult,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

BENCHMARK_VERSION = 3
SLOT_MINUTES = 15
CLEAN_METHODS = frozenset({"power_history", "derived_history", "disabled_zero"})
MAX_UNVERIFIED_SLOTS = 4
CAPACITY_HISTORY_DAYS = 6
CAPACITY_TOLERANCE = 0.20
CAPACITY_MIN_SOC_RANGE_PP = 20.0
MIN_IDEAL_VALUE_SEK = 1.0
EV_CHARGING_MIN_KW = 0.02
ENERGY_FIELDS = (
    "import_kwh",
    "export_kwh",
    "pv_kwh",
    "load_kwh",
    "water_kwh",
    "ev_charging_kwh",
)
PRICE_FIELDS = ("import_price_sek_kwh", "export_price_sek_kwh")
# Tolerance (kWh) when deciding that a recorded flow exceeded a configured limit.
LIMIT_TOLERANCE_KWH = 1e-9
# Margin (kWh) added to relaxed caps so solver tolerances cannot cut off the recorded point.
RELAXED_CAP_MARGIN_KWH = 1e-6


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
    """'clean', 'snapshot', 'partial' or None (not usable) from per-value recording provenance.

    'partial': a device component is unknown but the load was derived from history, so it
    still contains that device's energy and the recorded demand (load + water + ev) is
    exact. Unknown load, grid, pv or battery methods are not usable, nor is a slot whose
    base-load flag says the demand itself is untrusted (clamp, understated load).
    """
    flags = parse_quality_flags(row.get("quality_flags"))
    if base_load_demand_affected(flags):
        return None
    recording = parse_recording(flags, SUPPORTED_METHODS)
    if recording is None or not recording["components"]:
        return None
    if soc_metadata(recording, "end").get("source") != "live":
        return None
    components = recording["components"]
    devices = device_component_methods(components)
    unknown_devices = {name for name, method in devices.items() if method == "unknown"}
    if unknown_devices and components.get("load", {}).get("method") != "derived_history":
        return None
    methods = {c["method"] for name, c in components.items() if name not in unknown_devices}
    if not methods <= CLEAN_METHODS | {"snapshot"}:
        return None
    if unknown_devices:
        return "partial"
    return "clean" if methods <= CLEAN_METHODS else "snapshot"


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


def _finite_value(row: Mapping[str, Any], key: str) -> bool:
    value = row.get(key)
    return isinstance(value, int | float) and math.isfinite(value)


def _has_gap(row: Mapping[str, Any]) -> bool:
    """Whether a slot is missing recorded energy or SoC (nothing was recorded for it)."""
    return not all(_finite_value(row, k) for k in (*ENERGY_FIELDS, "soc_end_percent"))


def _gap_filled(row: dict[str, Any]) -> dict[str, Any]:
    """Row with missing energy values as 0 kWh (no recorded flow) and missing SoC as None,
    so actual and hindsight see identical inputs and the capacity fit skips the SoC."""
    if not _has_gap(row):
        return row
    filled = dict(row)
    for key in ENERGY_FIELDS:
        if not _finite_value(row, key):
            filled[key] = 0.0
    if not _finite_value(row, "soc_end_percent"):
        filled["soc_end_percent"] = None
    return filled


def _recording_reason(
    day: date, rows_by_day: Mapping[date, list[dict[str, Any]]], tz: Any, now: datetime
) -> tuple[str | None, int, int, int]:
    """First failing data reason (or None), the snapshot-slot count, the unverified-slot
    count (snapshot or unusable provenance, including the start-SoC slot) and the
    partial-slot count (unmeasured device inside a derived load)."""
    rows = rows_by_day.get(day, [])
    start, end = _local_day_bounds(day, tz)
    if end > now:
        return "not_finished", 0, 0, 0
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
        return "incomplete_day", 0, 0, 0
    previous = rows_by_day.get(day - timedelta(days=1), [])
    if not previous or datetime.fromisoformat(previous[-1]["slot_end"]) != start:
        return "incomplete_day", 0, 0, 0
    states = [slot_recording(r) for r in [previous[-1], *rows]]
    snapshots = states.count("snapshot")
    partials = states.count("partial")
    # A day slot missing energy or SoC (prices present) is a recording gap: unverified.
    # A partial slot (unmeasured device inside a derived load) has exact demand and
    # counts as verified; it is reported through ``partial_slots`` instead.
    unverified = sum(
        state not in {"clean", "partial"} or (i > 0 and _has_gap(row))
        for i, (state, row) in enumerate(zip(states, [previous[-1], *rows], strict=True))
    )
    if unverified > MAX_UNVERIFIED_SLOTS:
        return "not_clean_recording", snapshots, unverified, partials
    # Cost needs every price; the start stock needs the start-SoC slot's SoC.
    if not all(_finite_value(r, k) for r in rows for k in PRICE_FIELDS) or not _finite_value(
        previous[-1], "soc_end_percent"
    ):
        return "missing_values", snapshots, unverified, partials
    return None, snapshots, unverified, partials


def _ev_charging(row: Mapping[str, Any]) -> bool:
    """Whether the slot's average EV power shows real charging, not sensor idle noise."""
    hours = (
        datetime.fromisoformat(row["slot_end"]) - datetime.fromisoformat(row["slot_start"])
    ).total_seconds() / 3600
    return hours > 0 and row["ev_charging_kwh"] / hours > EV_CHARGING_MIN_KW


def implied_capacity(
    days: list[list[dict[str, Any]]], prev_rows: list[dict[str, Any]], config: KeplerConfig
) -> tuple[float | None, float]:
    """Capacity implied by meter flows vs SoC over a window, and the window SoC range in pp.

    Cumulative stored energy is fitted against SoC % by least squares over every slot, so
    quantised or jittering SoC averages out instead of biasing the estimate. Days are given
    with the last row of their previous day; consecutive days form one continuous segment
    (stock carries across midnight), and each segment gets its own intercept so gaps between
    eligible days do not break the fit. Capacity = slope * 100.
    """
    ordered = sorted(
        zip(prev_rows, days, strict=True),
        key=lambda pair: datetime.fromisoformat(pair[0]["slot_end"]),
    )
    segments: list[list[tuple[float, float]]] = []
    last_end: str | None = None
    stock = 0.0
    for prev, rows in ordered:
        if last_end is None or prev["slot_end"] != last_end:
            stock = 0.0
            segments.append([(prev["soc_end_percent"], stock)])
        for row in rows:
            charge, discharge = meter_battery_flow(row)
            stock += charge * config.charge_efficiency - discharge / config.discharge_efficiency
            if row["soc_end_percent"] is not None:
                segments[-1].append((row["soc_end_percent"], stock))
        last_end = rows[-1]["slot_end"] if rows else prev["slot_end"]

    socs = [soc for segment in segments for soc, _ in segment]
    soc_range = max(socs) - min(socs) if socs else 0.0
    sxx = sxy = 0.0
    for segment in segments:
        mean_soc = sum(soc for soc, _ in segment) / len(segment)
        mean_stock = sum(e for _, e in segment) / len(segment)
        for soc, e in segment:
            sxx += (soc - mean_soc) ** 2
            sxy += (soc - mean_soc) * (e - mean_stock)
    if sxx <= 0:
        return None, soc_range
    return sxy / sxx * 100.0, soc_range


def base_record(day: date, config: KeplerConfig) -> dict[str, Any]:
    return {
        "version": BENCHMARK_VERSION,
        "date": day.isoformat(),
        "status": "excluded",
        "reason": None,
        "capacity_kwh": config.capacity_kwh,
        "implied_capacity_kwh": None,
        "warnings": [],
        "relaxed_limits": [],
        "snapshot_slots": 0,
        "partial_slots": 0,
        "unverified_slots": 0,
        "day_slots": 0,
        "stored_change_kwh": None,
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


def _slot_hours(row: Mapping[str, Any]) -> float:
    return (
        datetime.fromisoformat(row["slot_end"]) - datetime.fromisoformat(row["slot_start"])
    ).total_seconds() / 3600


def recorded_limit_relaxation(
    rows: Sequence[Mapping[str, Any]],
    flows: Sequence[tuple[float, float]],
    initial: float,
    config: KeplerConfig,
) -> tuple[KeplerBenchmarkRelaxation, list[str]]:
    """Per-slot grid-side limits implied by what was recorded, and the limits that were
    actually exceeded in at least one slot (sorted names).

    The recorded schedule is a feasible point of the relaxed model: grid caps use the
    recorded meter flows, the inverter cap uses the inverter flow the recorded battery
    flows imply (PV is routed to the battery first, as cheaply as the model allows), and
    the export-disabled and export-floor constraints are lifted in slots that exported
    while they were violated (export disabled, or modelled stock below the floor).
    """
    floor_kwh: float | None = None
    if config.enable_export and config.export_floor_soc_percent is not None:
        floor_kwh = config.capacity_kwh * config.export_floor_soc_percent / 100.0
    relaxed: set[str] = set()
    import_kwh: list[float] = []
    export_kwh: list[float] = []
    inverter_ac_kwh: list[float] = []
    export_limits_off: list[bool] = []
    stock = initial
    for row, (charge, discharge) in zip(rows, flows, strict=True):
        hours = _slot_hours(row)
        stock += charge * config.charge_efficiency - discharge / config.discharge_efficiency
        grid_import, grid_export = row["import_kwh"], row["export_kwh"]
        import_kwh.append(grid_import + RELAXED_CAP_MARGIN_KWH)
        export_kwh.append(grid_export + RELAXED_CAP_MARGIN_KWH)
        if (
            config.max_import_power_kw is not None
            and grid_import > config.max_import_power_kw * hours + LIMIT_TOLERANCE_KWH
        ):
            relaxed.add("grid_import")
        if (
            config.max_export_power_kw is not None
            and grid_export > config.max_export_power_kw * hours + LIMIT_TOLERANCE_KWH
        ):
            relaxed.add("grid_export")

        pv_to_battery = min(charge, row["pv_kwh"])
        pv_to_ac = row["pv_kwh"] - pv_to_battery
        if config.inverter_topology == "ac_coupled":
            ac_flow = pv_to_ac + charge + discharge
        else:
            ac_flow = pv_to_ac + discharge + (charge - pv_to_battery)
        inverter_ac_kwh.append(ac_flow + RELAXED_CAP_MARGIN_KWH)
        if (
            config.max_inverter_ac_kw is not None
            and ac_flow > config.max_inverter_ac_kw * hours + LIMIT_TOLERANCE_KWH
        ):
            relaxed.add("inverter_ac")

        lift = False
        if grid_export > LIMIT_TOLERANCE_KWH:
            if not config.enable_export:
                lift = True
                relaxed.add("grid_export")
            elif floor_kwh is not None and stock < floor_kwh - LIMIT_TOLERANCE_KWH:
                lift = True
                relaxed.add("export_floor")
        export_limits_off.append(lift)
    relaxation = KeplerBenchmarkRelaxation(
        import_kwh=import_kwh,
        export_kwh=export_kwh,
        inverter_ac_kwh=inverter_ac_kwh,
        export_limits_off=export_limits_off,
    )
    return relaxation, sorted(relaxed)


def _solve_benchmark(
    slots: list[KeplerInputSlot],
    initial: float,
    bench: KeplerBenchmark,
    config: KeplerConfig,
) -> tuple[KeplerResult | None, str, bool, bool]:
    """One hindsight solve: (result, solver status, optimal, time limit hit)."""
    try:
        result = KeplerSolver().solve(KeplerInput(slots, initial, benchmark=bench), config)
    except PlannerError as exc:
        return None, str(exc.details.get("solver_status") or exc.code.value), False, False
    status = "time_limit" if result.time_limit_hit else result.status_msg
    return result, status, result.is_optimal and not result.time_limit_hit, result.time_limit_hit


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
    (
        reason,
        record["snapshot_slots"],
        record["unverified_slots"],
        record["partial_slots"],
    ) = _recording_reason(day, rows_by_day, tz, now)
    if reason is not None:
        record["reason"] = reason
        return record

    raw_rows_by_day = rows_by_day
    rows_by_day = {d: [_gap_filled(r) for r in day_rows] for d, day_rows in rows_by_day.items()}
    rows = rows_by_day[day]
    record["day_slots"] = len(rows)
    if record["unverified_slots"] > 0:
        # A few slots without verified provenance (start-SoC slot included) are tolerated.
        record["warnings"].append("unverified_slots")
    if record["partial_slots"] > 0:
        # Demand is exact (load is derived from history) but a device sensor was missing.
        record["warnings"].append("partial_slots")
    history = [day]
    cursor = day - timedelta(days=1)
    while len(history) <= CAPACITY_HISTORY_DAYS and cursor in rows_by_day:
        if _recording_reason(cursor, raw_rows_by_day, tz, now)[0] is None:
            history.append(cursor)
        cursor -= timedelta(days=1)
    implied, soc_range = implied_capacity(
        [rows_by_day[d] for d in history],
        [rows_by_day[d - timedelta(days=1)][-1] for d in history],
        config,
    )
    record["implied_capacity_kwh"] = implied
    if (
        implied is not None
        and soc_range >= CAPACITY_MIN_SOC_RANGE_PP
        and abs(implied - config.capacity_kwh) / config.capacity_kwh > CAPACITY_TOLERANCE
    ):
        # Advisory only: the estimate is too uncertain to justify dropping the day.
        record["warnings"].append("capacity_mismatch")

    flows = [meter_battery_flow(r) for r in rows]
    initial = (
        rows_by_day[day - timedelta(days=1)][-1]["soc_end_percent"] * config.capacity_kwh / 100
    )
    terminal = initial + sum(
        c * config.charge_efficiency - d / config.discharge_efficiency for c, d in flows
    )
    if not (0 <= initial <= config.capacity_kwh and 0 <= terminal <= config.capacity_kwh):
        # Flow drift or capacity config; clamped ends stay inside Kepler's SoC bounds.
        initial = min(max(initial, 0.0), config.capacity_kwh)
        terminal = min(max(terminal, 0.0), config.capacity_kwh)
        record["warnings"].append("stock_clamped")
    record["stored_change_kwh"] = terminal - initial

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
        no_discharge_slots=[_ev_charging(r) for r in rows],
    )
    started = time.monotonic()
    result, status, optimal, time_limit_hit = _solve_benchmark(slots, initial, bench, config)
    if not optimal:
        # Reality may have exceeded limits the strict solve enforces (EV charging above the
        # import limit, PV surplus above the export limit): retry once with them lifted to
        # what was recorded, but only when that actually changes the model.
        relaxation, relaxed_limits = recorded_limit_relaxation(rows, flows, initial, config)
        if relaxed_limits:
            bench.relaxation = relaxation
            result, status, optimal, time_limit_hit = _solve_benchmark(
                slots, initial, bench, config
            )
            if optimal:
                record["warnings"].append("limits_relaxed")
                record["relaxed_limits"] = relaxed_limits
    record["solve_seconds"] = round(time.monotonic() - started, 3)
    record["solver_status"] = status
    if not optimal or result is None:
        record["status"] = "failed"
        record["reason"] = (
            "solver_time_limit" if time_limit_hit else "infeasible_with_recorded_limits"
        )
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
    """Totals over scored days plus counts by status, reason and warning."""
    scored = [r for r in records if r.get("status") == "scored"]
    value_actual = sum(r["value_actual_sek"] for r in scored)
    value_ideal = sum(r["value_ideal_sek"] for r in scored)
    by_status: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    by_warning: dict[str, int] = {}
    for r in records:
        warnings: list[str] = r.get("warnings") or []
        for warning in warnings:
            by_warning[warning] = by_warning.get(warning, 0) + 1
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
        "by_warning": by_warning,
        "stored_change_kwh": sum(r.get("stored_change_kwh") or 0.0 for r in scored),
    }
