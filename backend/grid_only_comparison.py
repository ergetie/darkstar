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


def _recording_is_eligible(flags: dict[str, Any], *, battery_present: bool) -> bool:
    source = flags.get("source")
    if source != "recorder":
        return False

    if flags.get("exclude") is True or flags.get("placeholder") is True:
        return False
    if flags.get("is_placeholder") is True or flags.get("backfill") is True:
        return False
    comparison_history: Any = flags.get("comparison_history")
    if isinstance(comparison_history, dict):
        history_map = cast("dict[str, Any]", comparison_history)
        if history_map.get("disposition") == "exclude_from_comparison":
            return False

    recording_value: Any = flags.get("recording")
    if recording_value is None:
        # Pre-provenance recorder rows remain valid when their relevant numbers exist.
        return True
    if not isinstance(recording_value, dict):
        return False
    recording_map = cast("dict[str, Any]", recording_value)
    if recording_map.get("schema_version") != 1:
        return False
    if recording_map.get("semantics") != "slot-energy-v1":
        return False

    components: Any = recording_map.get("components")
    if not isinstance(components, dict):
        return False
    component_map = cast("dict[str, Any]", components)
    relevant_components = ["import", "export", "load", "water", "ev"]
    if battery_present:
        relevant_components.extend(("battery_charge", "battery_discharge"))
    for name in relevant_components:
        component = component_map.get(name)
        if not isinstance(component, dict):
            return False
        component_metadata = cast("dict[str, Any]", component)
        method = component_metadata.get("method")
        owner = component_metadata.get("owner")
        if owner != "recorder" or method in {"snapshot", "mixed", "unconfigured_zero", "unknown"}:
            return False
        if (
            battery_present
            and name in {"battery_charge", "battery_discharge"}
            and method == "disabled_zero"
        ):
            return False
        if method not in {"power_history", "derived_history", "disabled_zero"}:
            return False
    return True


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
) -> _SlotCosts | None:
    if battery_present and not math.isfinite(cycle_cost_kwh):
        return None
    start_utc = _valid_slot_start(row.start)
    if start_utc is None or not _recording_is_eligible(
        _quality_flags(row.quality_flags), battery_present=battery_present
    ):
        return None

    energies = (
        _finite_number(row.import_kwh, nonnegative=True),
        _finite_number(row.export_kwh, nonnegative=True),
        _finite_number(row.load_kwh, nonnegative=True),
        _finite_number(row.water_kwh, nonnegative=True),
        _finite_number(row.ev_charging_kwh, nonnegative=True),
    )
    prices = (
        _finite_number(row.import_price_sek_kwh, nonnegative=False),
        _finite_number(row.export_price_sek_kwh, nonnegative=False),
    )
    battery_flows = (
        (
            _finite_number(row.batt_charge_kwh, nonnegative=True),
            _finite_number(row.batt_discharge_kwh, nonnegative=True),
        )
        if battery_present
        else (0.0, 0.0)
    )
    if any(value is None for value in (*energies, *prices, *battery_flows)):
        return None

    flags = _quality_flags(row.quality_flags)
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
            return None

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
        return None
    return _SlotCosts(
        start_utc,
        import_cost,
        export_revenue,
        ds_electricity_cost,
        ds_wear_cost,
        ds_cost,
        grid_only_cost,
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
    for start_utc in sorted(expected):
        candidates = by_start.get(start_utc, [])
        # Duplicate local ISO representations of one instant are ambiguous; exclude them.
        if len(candidates) != 1:
            continue
        costs = _slot_costs(
            candidates[0], battery_present=battery_present, cycle_cost_kwh=cycle_cost_kwh
        )
        if costs is not None:
            eligible.append(costs)

    covered = len(eligible)
    total = len(expected)
    excluded = total - covered
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
        },
        "time_axis": {
            "timezone": getattr(timezone, "zone", str(timezone)),
            "start": _local_iso(axis_start, timezone),
            "end": _local_iso(axis_end, timezone),
        },
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
