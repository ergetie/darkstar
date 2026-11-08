"""Pure accounting for a measured DS versus grid-only electricity bill."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, TypedDict, cast

if TYPE_CHECKING:
    from collections.abc import Iterable

METHOD_VERSION = "grid-only-bill-v1"
SLOT = timedelta(minutes=15)


@dataclass(frozen=True)
class GridOnlyObservation:
    start: datetime
    import_kwh: object
    export_kwh: object
    import_price_sek_kwh: object
    export_price_sek_kwh: object
    load_kwh: object
    water_kwh: object
    ev_charging_kwh: object
    batt_charge_kwh: object = None
    batt_discharge_kwh: object = None
    quality_flags: object = None


@dataclass(frozen=True)
class _SlotCosts:
    start_utc: datetime
    import_cost: float
    export_revenue: float
    ds_electricity_cost: float
    ds_wear_cost: float
    ds_cost: float
    grid_only_cost: float
    water_unmeasured: bool = False


# One reason per excluded slot: (machine code, component or None). The first failing
# check wins, in the order the checks are evaluated (see the grid-only-comparison spec).
_Exclusion = tuple[str, str | None]


class _BucketTotals(TypedDict):
    end: datetime
    import_cost: float
    export_revenue: float
    ds_electricity_cost: float
    ds_wear_cost: float
    ds_cost: float
    grid_only_cost: float


def _finite_number(value: Any, *, nonnegative: bool) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or (nonnegative and number < 0):
        return None
    return number


def _quality_flags(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return cast("dict[str, Any]", value)
    if isinstance(value, str):
        try:
            decoded: Any = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
        return cast("dict[str, Any]", decoded) if isinstance(decoded, dict) else {}
    return {}


def _component_method(flags: dict[str, Any], name: str) -> object:
    recording: Any = flags.get("recording")
    if not isinstance(recording, dict):
        return None
    components: Any = cast("dict[str, Any]", recording).get("components")
    if not isinstance(components, dict):
        return None
    component: Any = cast("dict[str, Any]", components).get(name)
    if not isinstance(component, dict):
        return None
    return cast("dict[str, Any]", component).get("method")


def _recording_exclusion(
    flags: dict[str, Any], *, battery_present: bool, allow_unmeasured_water: bool = False
) -> _Exclusion | None:
    """First failing provenance check, or ``None`` when the recording allows the slot.

    ``allow_unmeasured_water`` accepts a water component with method ``unknown`` only
    when the load was derived from history (so it still contains the unmeasured water)
    and every other relevant component is eligible.
    """
    if flags.get("source") != "recorder":
        return "not_recorder", None
    if flags.get("placeholder") is True or flags.get("is_placeholder") is True:
        return "not_recorder", None
    if flags.get("backfill") is True:
        return "not_recorder", None
    if flags.get("exclude") is True:
        return "user_excluded", None
    comparison_history: Any = flags.get("comparison_history")
    if isinstance(comparison_history, dict):
        history_map = cast("dict[str, Any]", comparison_history)
        if history_map.get("disposition") == "exclude_from_comparison":
            return "user_excluded", None

    recording_value: Any = flags.get("recording")
    if recording_value is None:
        # Pre-provenance recorder rows remain valid when their relevant numbers exist.
        return None
    if not isinstance(recording_value, dict):
        return "unsupported_provenance", None
    recording_map = cast("dict[str, Any]", recording_value)
    if recording_map.get("schema_version") != 1:
        return "unsupported_provenance", None
    if recording_map.get("semantics") != "slot-energy-v1":
        return "unsupported_provenance", None

    components: Any = recording_map.get("components")
    if not isinstance(components, dict):
        return "unsupported_provenance", None
    component_map = cast("dict[str, Any]", components)
    relevant_components = ["import", "export", "load", "water", "ev"]
    if battery_present:
        relevant_components.extend(("battery_charge", "battery_discharge"))
    for name in relevant_components:
        component = component_map.get(name)
        if not isinstance(component, dict):
            # Missing provenance for a relevant component is unknown provenance.
            return "unknown_component", name
        component_metadata = cast("dict[str, Any]", component)
        method = component_metadata.get("method")
        owner = component_metadata.get("owner")
        if (
            name == "water"
            and method == "unknown"
            and owner == "recorder"
            and allow_unmeasured_water
            and _component_method(flags, "load") == "derived_history"
        ):
            continue
        if method == "unconfigured_zero":
            return "unconfigured_sensor", name
        if method in {"snapshot", "mixed"}:
            return "estimated_component", name
        if owner != "recorder" or method == "unknown":
            return "unknown_component", name
        if (
            battery_present
            and name in {"battery_charge", "battery_discharge"}
            and method == "disabled_zero"
        ):
            return "battery_disabled_zero", name
        if method not in {"power_history", "derived_history", "disabled_zero"}:
            return "unknown_component", name
    return None


def _valid_slot_start(start: datetime) -> datetime | None:
    if start.tzinfo is None or start.utcoffset() is None:
        return None
    if start.minute % 15 or start.second or start.microsecond:
        return None
    return start.astimezone(UTC)


def _slot_costs(
    row: GridOnlyObservation,
    *,
    battery_present: bool,
    cycle_cost_kwh: float,
) -> _SlotCosts | _Exclusion:
    """Slot amounts, or the first failing check as ``(reason, component)``."""
    if battery_present and not math.isfinite(cycle_cost_kwh):
        return "battery_cost_invalid", None
    start_utc = _valid_slot_start(row.start)
    if start_utc is None:
        return "missing_slot", None
    flags = _quality_flags(row.quality_flags)
    exclusion = _recording_exclusion(
        flags, battery_present=battery_present, allow_unmeasured_water=True
    )
    if exclusion is not None:
        return exclusion
    water_unmeasured = _component_method(flags, "water") == "unknown"

    # Unmeasured water (null or zero) is not a filled value: derived load still contains it.
    water_value = _finite_number(row.water_kwh, nonnegative=True)
    if water_unmeasured and water_value is None and row.water_kwh is None:
        water_value = 0.0
    energy_inputs = {
        "import": _finite_number(row.import_kwh, nonnegative=True),
        "export": _finite_number(row.export_kwh, nonnegative=True),
        "load": _finite_number(row.load_kwh, nonnegative=True),
        "water": water_value,
        "ev": _finite_number(row.ev_charging_kwh, nonnegative=True),
    }
    if battery_present:
        energy_inputs["battery_charge"] = _finite_number(row.batt_charge_kwh, nonnegative=True)
        energy_inputs["battery_discharge"] = _finite_number(
            row.batt_discharge_kwh, nonnegative=True
        )
    prices = (
        _finite_number(row.import_price_sek_kwh, nonnegative=False),
        _finite_number(row.export_price_sek_kwh, nonnegative=False),
    )
    if any(value is None for value in prices):
        return "missing_price", None
    for name, value in energy_inputs.items():
        if value is None:
            return "missing_energy_value", name
    energies = (
        energy_inputs["import"],
        energy_inputs["export"],
        energy_inputs["load"],
        energy_inputs["water"],
        energy_inputs["ev"],
    )
    battery_flows = (
        (energy_inputs["battery_charge"], energy_inputs["battery_discharge"])
        if battery_present
        else (0.0, 0.0)
    )

    recording: Any = flags.get("recording")
    components: dict[str, Any] = {}
    if isinstance(recording, dict):
        recording_map = cast("dict[str, Any]", recording)
        raw_components: Any = recording_map.get("components", {})
        if isinstance(raw_components, dict):
            components = cast("dict[str, Any]", raw_components)
    import_kwh, export_kwh, load_kwh, water_kwh, ev_kwh = energies
    import_price, export_price = prices
    charge_kwh, discharge_kwh = battery_flows
    assert import_kwh is not None and export_kwh is not None
    assert load_kwh is not None and water_kwh is not None and ev_kwh is not None
    assert import_price is not None and export_price is not None
    assert charge_kwh is not None and discharge_kwh is not None
    if water_unmeasured and ev_kwh > 0 and load_kwh == 0:
        # The base-load clamp (ev + water > total) may have hidden real demand.
        return "clamp_hidden_demand", None
    values_by_component = {
        "import": import_kwh,
        "export": export_kwh,
        "load": load_kwh,
        "water": water_kwh,
        "ev": ev_kwh,
        "battery_charge": charge_kwh,
        "battery_discharge": discharge_kwh,
    }
    for name, component in components.items():
        if name not in values_by_component or not isinstance(component, dict):
            continue
        component_map = cast("dict[str, Any]", component)
        if component_map.get("method") == "disabled_zero" and values_by_component[name] != 0:
            return "disabled_nonzero", name

    import_cost = import_kwh * import_price
    export_revenue = export_kwh * export_price
    grid_only_cost = (load_kwh + water_kwh + ev_kwh) * import_price
    ds_electricity_cost = import_cost - export_revenue
    ds_wear_cost = (charge_kwh + discharge_kwh) * cycle_cost_kwh * 0.5
    ds_cost = ds_electricity_cost + ds_wear_cost
    if not all(
        math.isfinite(value)
        for value in (
            import_cost,
            export_revenue,
            grid_only_cost,
            ds_electricity_cost,
            ds_wear_cost,
            ds_cost,
        )
    ):
        # Overflow to a non-finite amount: the energy values cannot be priced.
        return "missing_energy_value", None
    return _SlotCosts(
        start_utc,
        import_cost,
        export_revenue,
        ds_electricity_cost,
        ds_wear_cost,
        ds_cost,
        grid_only_cost,
        water_unmeasured,
    )


def _local_iso(value: datetime, timezone: Any) -> str:
    return value.astimezone(timezone).isoformat()


def _round(value: float) -> float:
    return round(value, 3)


def _bucket_bounds(start_utc: datetime, timezone: Any, hourly: bool) -> tuple[datetime, datetime]:
    local = start_utc.astimezone(timezone)
    if hourly:
        start = local.replace(minute=0, second=0, microsecond=0)
        start_utc = start.astimezone(UTC)
        return start_utc, start_utc + timedelta(hours=1)
    local_start = timezone.localize(datetime.combine(local.date(), datetime.min.time()))
    next_date = local.date() + timedelta(days=1)
    local_end = timezone.localize(datetime.combine(next_date, datetime.min.time()))
    return local_start.astimezone(UTC), local_end.astimezone(UTC)


def _excluded_spans(
    excluded: list[tuple[datetime, _Exclusion]], timezone: Any
) -> list[dict[str, Any]]:
    """Maximal runs of elapsed-UTC contiguous slots sharing one reason and component.

    Contiguity is measured in UTC so a DST change cannot split or merge a run; the
    offset-qualified local ISO ``end`` is exclusive.
    """
    spans: list[dict[str, Any]] = []
    run_start: datetime | None = None
    run_end: datetime | None = None
    run_key: _Exclusion | None = None
    run_slots = 0

    def close_run() -> None:
        if run_start is None or run_end is None or run_key is None:
            return
        spans.append(
            {
                "start": _local_iso(run_start, timezone),
                "end": _local_iso(run_end, timezone),
                "slots": run_slots,
                "reason": run_key[0],
                "component": run_key[1],
            }
        )

    for start_utc, key in excluded:
        if run_key == key and run_end == start_utc:
            run_end = start_utc + SLOT
            run_slots += 1
            continue
        close_run()
        run_start, run_end, run_key, run_slots = start_utc, start_utc + SLOT, key, 1
    close_run()
    return spans


def build_grid_only_comparison(
    observations: Iterable[GridOnlyObservation],
    expected_starts: Iterable[datetime],
    *,
    timezone: Any,
    hourly: bool,
    axis_start: datetime,
    axis_end: datetime,
    has_completed_observations: bool,
    battery_present: bool = False,
    cycle_cost_kwh: float = 0.0,
) -> dict[str, Any]:
    """Aggregate the same eligible completed slots into bills, buckets and gap-safe runs.

    ``expected_starts`` are the requested period's elapsed-UTC 15-minute boundaries.
    The boolean distinguishes an empty observation table from present-but-invalid rows.
    """
    expected: set[datetime] = set()
    for start in expected_starts:
        start_utc = _valid_slot_start(start)
        if start_utc is not None:
            expected.add(start_utc)
    by_start: dict[datetime, list[GridOnlyObservation]] = defaultdict(list)
    for observation in observations:
        start_utc = _valid_slot_start(observation.start)
        if start_utc is not None and start_utc in expected:
            by_start[start_utc].append(observation)

    eligible: list[_SlotCosts] = []
    excluded_slots_by_start: list[tuple[datetime, _Exclusion]] = []
    for start_utc in sorted(expected):
        candidates = by_start.get(start_utc, [])
        if not candidates:
            excluded_slots_by_start.append((start_utc, ("missing_slot", None)))
            continue
        # Duplicate local ISO representations of one instant are ambiguous; exclude them.
        if len(candidates) != 1:
            excluded_slots_by_start.append((start_utc, ("ambiguous_rows", None)))
            continue
        costs = _slot_costs(
            candidates[0], battery_present=battery_present, cycle_cost_kwh=cycle_cost_kwh
        )
        if isinstance(costs, _SlotCosts):
            eligible.append(costs)
        else:
            excluded_slots_by_start.append((start_utc, costs))

    covered = len(eligible)
    total = len(expected)
    excluded = total - covered
    water_unmeasured_slots = sum(1 for slot in eligible if slot.water_unmeasured)
    excluded_by_reason: dict[str, int] = {}
    for _, (reason_code, _component) in excluded_slots_by_start:
        excluded_by_reason[reason_code] = excluded_by_reason.get(reason_code, 0) + 1
    if not has_completed_observations:
        status, reason = "no_data", "no_completed_observations"
    elif covered == 0:
        status, reason = "unavailable", "no_usable_observations"
    elif excluded:
        status, reason = "partial", "partial_coverage"
    else:
        status, reason = "available", "complete_coverage"

    result: dict[str, Any] = {
        "status": status,
        "reason": reason,
        "method_version": METHOD_VERSION,
        "coverage": {
            "covered_slots": covered,
            "total_slots": total,
            "excluded_slots": excluded,
            "water_unmeasured_slots": water_unmeasured_slots,
            "water_unmeasured_hours": water_unmeasured_slots * 0.25,
            "excluded_by_reason": excluded_by_reason,
        },
        "time_axis": {
            "timezone": getattr(timezone, "zone", str(timezone)),
            "start": _local_iso(axis_start, timezone),
            "end": _local_iso(axis_end, timezone),
        },
        "excluded_spans": _excluded_spans(excluded_slots_by_start, timezone),
    }
    if not covered:
        return result

    grid_only_total = sum(slot.grid_only_cost for slot in eligible)
    ds_total = sum(slot.ds_cost for slot in eligible)
    ds_electricity_total = sum(slot.ds_electricity_cost for slot in eligible)
    ds_wear_total = sum(slot.ds_wear_cost for slot in eligible)
    result.update(
        {
            "through": _local_iso(eligible[-1].start_utc + SLOT, timezone),
            "grid_only_cost_sek": _round(grid_only_total),
            "grid_only_wear_cost_sek": 0.0,
            "ds_electricity_cost_sek": _round(ds_electricity_total),
            "ds_wear_cost_sek": _round(ds_wear_total),
            "ds_cost_sek": _round(ds_total),
            "saving_sek": _round(grid_only_total - ds_total),
        }
    )

    bucket_totals: dict[datetime, _BucketTotals] = {}
    for slot in eligible:
        bucket_start, bucket_end = _bucket_bounds(slot.start_utc, timezone, hourly)
        bucket = bucket_totals.setdefault(
            bucket_start,
            _BucketTotals(
                end=bucket_end,
                import_cost=0.0,
                export_revenue=0.0,
                ds_electricity_cost=0.0,
                ds_wear_cost=0.0,
                ds_cost=0.0,
                grid_only_cost=0.0,
            ),
        )
        bucket["import_cost"] += slot.import_cost
        bucket["export_revenue"] += slot.export_revenue
        bucket["ds_electricity_cost"] += slot.ds_electricity_cost
        bucket["ds_wear_cost"] += slot.ds_wear_cost
        bucket["ds_cost"] += slot.ds_cost
        bucket["grid_only_cost"] += slot.grid_only_cost

    bucket_points: list[dict[str, Any]] = []
    cumulative_ds = cumulative_grid_only = 0.0
    for bucket_start in sorted(bucket_totals):
        bucket = bucket_totals[bucket_start]
        cumulative_ds += bucket["ds_cost"]
        cumulative_grid_only += bucket["grid_only_cost"]
        bucket_points.append(
            {
                "start": _local_iso(bucket_start, timezone),
                "end": _local_iso(bucket["end"], timezone),
                "import_cost_sek": _round(bucket["import_cost"]),
                "export_revenue_sek": _round(bucket["export_revenue"]),
                "ds_electricity_cost_sek": _round(bucket["ds_electricity_cost"]),
                "ds_wear_cost_sek": _round(bucket["ds_wear_cost"]),
                "grid_only_wear_cost_sek": 0.0,
                "ds_cost_sek": _round(bucket["ds_cost"]),
                "grid_only_cost_sek": _round(bucket["grid_only_cost"]),
                "cumulative_ds_cost_sek": _round(cumulative_ds),
                "cumulative_grid_only_cost_sek": _round(cumulative_grid_only),
            }
        )
    result["points"] = bucket_points

    segments: list[dict[str, Any]] = []
    segment_slots: list[_SlotCosts] = []
    cumulative_ds = cumulative_grid_only = 0.0

    def close_segment() -> None:
        nonlocal cumulative_ds, cumulative_grid_only, segment_slots
        if not segment_slots:
            return
        start_utc = segment_slots[0].start_utc
        end_utc = segment_slots[-1].start_utc + SLOT
        points = [
            {
                "at": _local_iso(start_utc, timezone),
                "cumulative_ds_cost_sek": _round(cumulative_ds),
                "cumulative_grid_only_cost_sek": _round(cumulative_grid_only),
            }
        ]
        for slot in segment_slots:
            cumulative_ds += slot.ds_cost
            cumulative_grid_only += slot.grid_only_cost
            points.append(
                {
                    "at": _local_iso(slot.start_utc + SLOT, timezone),
                    "cumulative_ds_cost_sek": _round(cumulative_ds),
                    "cumulative_grid_only_cost_sek": _round(cumulative_grid_only),
                }
            )
        segments.append(
            {
                "start": _local_iso(start_utc, timezone),
                "end": _local_iso(end_utc, timezone),
                "points": points,
            }
        )
        segment_slots = []

    for slot in eligible:
        if segment_slots and slot.start_utc != segment_slots[-1].start_utc + SLOT:
            close_segment()
        segment_slots.append(slot)
    close_segment()
    result["segments"] = segments
    return result
