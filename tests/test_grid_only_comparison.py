from __future__ import annotations

import itertools
import math
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
import pytz

from backend.grid_only_comparison import (
    GridOnlyObservation,
    _component_method,
    _finite_number,
    _quality_flags,
    _valid_slot_start,
    build_grid_only_comparison,
)

TZ = pytz.timezone("Europe/Stockholm")
SLOT = timedelta(minutes=15)


def row(start: datetime, **values) -> GridOnlyObservation:
    defaults = {
        "import_kwh": 0.0,
        "export_kwh": 0.0,
        "import_price_sek_kwh": 2.0,
        "export_price_sek_kwh": 1.0,
        "load_kwh": 1.0,
        "water_kwh": 0.5,
        "ev_charging_kwh": 2.0,
        "quality_flags": {"source": "recorder"},
    }
    return GridOnlyObservation(start=start, **(defaults | values))


def compare(
    rows,
    starts,
    *,
    start=None,
    end=None,
    has_rows=True,
    hourly=True,
    battery_present=False,
    cycle_cost_kwh=0.0,
):
    first = start or starts[0]
    last = end or starts[-1] + SLOT
    return build_grid_only_comparison(
        rows,
        starts,
        timezone=TZ,
        hourly=hourly,
        axis_start=first,
        axis_end=last,
        has_completed_observations=has_rows,
        battery_present=battery_present,
        cycle_cost_kwh=cycle_cost_kwh,
    )


def test_prices_each_slot_and_counts_controlled_loads_once_with_gross_grid_flows():
    start = datetime(2026, 10, 5, tzinfo=UTC)
    result = compare(
        [
            row(
                start,
                import_kwh=1.0,
                export_kwh=0.5,
                import_price_sek_kwh=2.0,
                export_price_sek_kwh=1.0,
            ),
            row(
                start + SLOT,
                import_kwh=0.0,
                import_price_sek_kwh=4.0,
                export_price_sek_kwh=0.0,
            ),
        ],
        [start, start + SLOT],
    )
    assert result["grid_only_cost_sek"] == pytest.approx(21.0)
    assert result["ds_cost_sek"] == pytest.approx(1.5)
    assert result["saving_sek"] == pytest.approx(19.5)
    assert result["points"][0]["import_cost_sek"] == pytest.approx(2.0)
    assert result["points"][0]["export_revenue_sek"] == pytest.approx(0.5)


def test_configured_battery_wear_is_included_once_and_every_amount_reconciles():
    start = datetime(2026, 10, 5, tzinfo=UTC)
    result = compare(
        [
            row(
                start,
                import_kwh=2.0,
                export_kwh=0.5,
                batt_charge_kwh=20.0,
                batt_discharge_kwh=8.0,
            )
        ],
        [start],
        battery_present=True,
        cycle_cost_kwh=0.2,
    )
    # Wear is (20 + 8) * 0.2 * 0.5 = 2.8 kr; grid charging is
    # already included in import cost and is not deducted a second time.
    assert result["grid_only_cost_sek"] == pytest.approx(7.0)
    assert result["grid_only_wear_cost_sek"] == 0.0
    assert result["ds_electricity_cost_sek"] == pytest.approx(3.5)
    assert result["ds_wear_cost_sek"] == pytest.approx(2.8)
    assert result["ds_cost_sek"] == pytest.approx(6.3)
    assert result["saving_sek"] == pytest.approx(0.7)
    point = result["points"][0]
    assert point["ds_electricity_cost_sek"] + point["ds_wear_cost_sek"] == pytest.approx(
        point["ds_cost_sek"]
    )
    segment_end = result["segments"][0]["points"][-1]
    assert segment_end["cumulative_ds_cost_sek"] == pytest.approx(result["ds_cost_sek"])
    assert segment_end["cumulative_grid_only_cost_sek"] == pytest.approx(
        result["grid_only_cost_sek"]
    )
    assert (
        segment_end["cumulative_grid_only_cost_sek"] - segment_end["cumulative_ds_cost_sek"]
    ) == pytest.approx(result["saving_sek"])


def test_no_battery_does_not_require_battery_flow_readings_and_has_zero_wear():
    start = datetime(2026, 10, 5, tzinfo=UTC)
    result = compare(
        [row(start, batt_charge_kwh=None, batt_discharge_kwh=None)],
        [start],
        battery_present=False,
    )
    assert result["status"] == "available"
    assert result["ds_wear_cost_sek"] == 0.0
    assert result["grid_only_wear_cost_sek"] == 0.0


def test_finite_configured_cycle_cost_is_applied_without_substituting_a_new_default():
    start = datetime(2026, 10, 5, tzinfo=UTC)
    result = compare(
        [row(start, batt_charge_kwh=2.0, batt_discharge_kwh=0.0)],
        [start],
        battery_present=True,
        cycle_cost_kwh=-0.2,
    )
    assert result["ds_wear_cost_sek"] == pytest.approx(-0.2)
    assert result["ds_cost_sek"] == pytest.approx(result["ds_electricity_cost_sek"] - 0.2)


@pytest.mark.parametrize("cycle_cost", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_configured_cycle_cost_makes_battery_slots_unavailable(cycle_cost):
    start = datetime(2026, 10, 5, tzinfo=UTC)
    result = compare(
        [row(start, batt_charge_kwh=2.0, batt_discharge_kwh=0.0)],
        [start],
        battery_present=True,
        cycle_cost_kwh=cycle_cost,
    )
    assert result["status"] == "unavailable"
    assert "saving_sek" not in result


@pytest.mark.parametrize(
    "flags",
    [
        {
            "source": "recorder",
            "recording": {"schema_version": 1, "semantics": "slot-energy-v1", "components": {}},
        },
        {
            "source": "recorder",
            "recording": {
                "schema_version": 1,
                "semantics": "slot-energy-v1",
                "components": {
                    name: {"method": "power_history", "owner": "recorder"}
                    for name in ("import", "export", "load", "water", "ev")
                }
                | {
                    "battery_charge": {"method": "snapshot", "owner": "recorder"},
                    "battery_discharge": {"method": "power_history", "owner": "recorder"},
                },
            },
        },
        {
            "source": "recorder",
            "recording": {
                "schema_version": 1,
                "semantics": "slot-energy-v1",
                "components": {
                    name: {"method": "power_history", "owner": "recorder"}
                    for name in ("import", "export", "load", "water", "ev", "battery_charge")
                }
                | {"battery_discharge": {"method": "mixed", "owner": "recorder"}},
            },
        },
    ],
)
def test_configured_battery_missing_or_ineligible_provenance_is_rejected(flags):
    start = datetime(2026, 10, 5, tzinfo=UTC)
    assert (
        compare(
            [row(start, batt_charge_kwh=0, batt_discharge_kwh=0, quality_flags=flags)],
            [start],
            battery_present=True,
        )["status"]
        == "unavailable"
    )


@pytest.mark.parametrize("field", ["batt_charge_kwh", "batt_discharge_kwh"])
@pytest.mark.parametrize("value", [None, float("nan"), -0.1, float("inf")])
def test_configured_battery_requires_finite_nonnegative_flows(field, value):
    start = datetime(2026, 10, 5, tzinfo=UTC)
    assert (
        compare(
            [row(start, **{field: value})],
            [start],
            battery_present=True,
        )["status"]
        == "unavailable"
    )


@pytest.mark.parametrize(
    ("price", "expected_grid", "expected_ds", "expected_saving"),
    [(0.0, 0.0, 0.0, 0.0), (-1.0, -3.5, -1.0, -2.5)],
)
def test_zero_and_negative_tariffs_are_preserved(
    price, expected_grid, expected_ds, expected_saving
):
    start = datetime(2026, 10, 5, tzinfo=UTC)
    result = compare(
        [row(start, import_kwh=1.0, import_price_sek_kwh=price, export_price_sek_kwh=price)],
        [start],
    )
    assert result["grid_only_cost_sek"] == pytest.approx(expected_grid)
    assert result["ds_cost_sek"] == pytest.approx(expected_ds)
    assert result["saving_sek"] == pytest.approx(expected_saving)


def test_each_slot_is_priced_instead_of_using_an_average_tariff():
    start = datetime(2026, 10, 5, tzinfo=UTC)
    result = compare(
        [
            row(start, load_kwh=1, water_kwh=0, ev_charging_kwh=0, import_price_sek_kwh=1),
            row(start + SLOT, load_kwh=3, water_kwh=0, ev_charging_kwh=0, import_price_sek_kwh=3),
        ],
        [start, start + SLOT],
    )
    assert result["grid_only_cost_sek"] == pytest.approx(10.0)


def test_legacy_recorder_rows_are_usable_without_pv_battery_or_soc():
    start = datetime(2026, 10, 5, tzinfo=UTC)
    legacy = row(start, quality_flags={"source": "recorder"})
    assert compare([legacy], [start])["status"] == "available"


@pytest.mark.parametrize(
    "flags",
    [
        {"source": "recorder", "exclude": True},
        {"source": "backfill"},
        {"source": "placeholder"},
        {
            "source": "recorder",
            "recording": {
                "schema_version": 1,
                "semantics": "slot-energy-v1",
                "components": {
                    name: {"method": "snapshot", "owner": "recorder"}
                    for name in ("import", "export", "load", "water", "ev")
                },
            },
        },
    ],
)
def test_exclusions_backfills_placeholders_and_snapshot_measurements_are_rejected(flags):
    start = datetime(2026, 10, 5, tzinfo=UTC)
    assert compare([row(start, quality_flags=flags)], [start])["status"] == "unavailable"


@pytest.mark.parametrize(
    "field,value",
    [
        ("load_kwh", None),
        ("water_kwh", float("nan")),
        ("ev_charging_kwh", -0.1),
        ("import_kwh", float("inf")),
        ("export_kwh", -1),
        ("import_price_sek_kwh", None),
        ("export_price_sek_kwh", float("nan")),
    ],
)
def test_missing_invalid_and_nonfinite_relevant_values_are_rejected(field, value):
    start = datetime(2026, 10, 5, tzinfo=UTC)
    assert compare([row(start, **{field: value})], [start])["status"] == "unavailable"


def test_disabled_zero_is_valid_but_positive_disabled_component_is_not():
    start = datetime(2026, 10, 5, tzinfo=UTC)
    flags = {
        "source": "recorder",
        "recording": {
            "schema_version": 1,
            "semantics": "slot-energy-v1",
            "components": {
                name: {
                    "method": "disabled_zero" if name == "ev" else "power_history",
                    "owner": "recorder",
                }
                for name in ("import", "export", "load", "water", "ev")
            },
        },
    }
    assert (
        compare([row(start, ev_charging_kwh=0, quality_flags=flags)], [start])["status"]
        == "available"
    )
    assert (
        compare([row(start, ev_charging_kwh=1, quality_flags=flags)], [start])["status"]
        == "unavailable"
    )


def test_missing_slot_keeps_anchor_and_returns_independent_segments_with_reconciliation():
    start = datetime(2026, 10, 5, 8, tzinfo=UTC)
    starts = [start + SLOT * index for index in range(8)]
    rows = [
        row(starts[index], load_kwh=1, ev_charging_kwh=0, water_kwh=0, import_kwh=0.5)
        for index in (0, 1, 3, 4, 5, 6, 7)
    ]
    result = compare(rows, starts)
    comparison_points = result["points"]
    segments = result["segments"]
    assert result["coverage"] == {
        "covered_slots": 7,
        "total_slots": 8,
        "excluded_slots": 1,
        "water_unmeasured_slots": 0,
        "water_unmeasured_hours": 0.0,
        "excluded_by_reason": {"missing_slot": 1},
    }
    assert result["status"] == "partial"
    assert len(segments) == 2
    assert segments[0]["start"].endswith("10:00:00+02:00")
    assert segments[0]["end"].endswith("10:30:00+02:00")
    assert segments[1]["start"].endswith("10:45:00+02:00")
    assert segments[1]["points"][0]["cumulative_ds_cost_sek"] == pytest.approx(2.0)
    assert len(segments[0]["points"]) == 3
    assert len(segments[1]["points"]) == 6
    assert comparison_points[-1]["cumulative_ds_cost_sek"] == pytest.approx(result["ds_cost_sek"])
    assert segments[-1]["points"][-1]["cumulative_grid_only_cost_sek"] == pytest.approx(
        result["grid_only_cost_sek"]
    )
    assert comparison_points[0]["ds_cost_sek"] == pytest.approx(3.0)


def test_contiguous_segment_crosses_hour_and_local_day_boundaries():
    start = datetime(2026, 10, 5, 21, 45, tzinfo=UTC)
    starts = [start + SLOT * index for index in range(6)]
    result = compare(
        [
            row(value, load_kwh=0, water_kwh=0, ev_charging_kwh=0, import_kwh=0.1)
            for value in starts
        ],
        starts,
        hourly=False,
    )
    assert len(result["segments"]) == 1
    assert len(result["points"]) == 2
    assert result["segments"][0]["points"][-1]["cumulative_ds_cost_sek"] == pytest.approx(
        result["ds_cost_sek"]
    )


@pytest.mark.parametrize(
    ("day", "hours", "slots"),
    [(datetime(2026, 3, 29).date(), 23, 92), (datetime(2026, 10, 25).date(), 25, 100)],
)
def test_dst_day_uses_elapsed_utc_slots_and_full_local_axis(day, hours, slots):
    start_local = TZ.localize(datetime.combine(day, datetime.min.time()))
    end_local = TZ.localize(datetime.combine(day + timedelta(days=1), datetime.min.time()))
    start_utc, end_utc = start_local.astimezone(UTC), end_local.astimezone(UTC)
    starts = [start_utc + SLOT * index for index in range(slots)]
    rows = [row(value, load_kwh=0, water_kwh=0, ev_charging_kwh=0) for value in starts]
    result = compare(
        rows,
        starts,
        start=start_utc,
        end=end_utc,
        hourly=True,
    )
    assert result["coverage"]["total_slots"] == slots
    assert result["coverage"]["covered_slots"] == slots
    assert result["time_axis"]["start"] == start_local.isoformat()
    assert result["time_axis"]["end"] == end_local.isoformat()
    assert len(result["points"]) == hours
    if hours == 25:
        repeated = [point["start"] for point in result["points"] if "T02:00:00" in point["start"]]
        assert repeated == ["2026-10-25T02:00:00+02:00", "2026-10-25T02:00:00+01:00"]


def test_no_data_and_all_invalid_responses_omit_money_and_keep_axis():
    start = datetime(2026, 10, 5, tzinfo=UTC)
    expected = [start, start + SLOT]
    no_data = compare([], expected, has_rows=False)
    unavailable = compare([row(start, load_kwh=None)], expected)
    for result in (no_data, unavailable):
        assert "grid_only_cost_sek" not in result
        assert "saving_sek" not in result
        assert "points" not in result
        assert "segments" not in result
        assert result["time_axis"]["timezone"] == "Europe/Stockholm"
    assert no_data["status"] == "no_data"
    assert unavailable["status"] == "unavailable"


def test_non_quarter_or_naive_timestamps_are_ineligible():
    valid = datetime(2026, 10, 5, tzinfo=UTC)
    expected = [valid]
    naive = row(datetime(2026, 10, 5))
    off_grid = row(valid + timedelta(minutes=1))
    assert compare([naive], expected)["status"] == "unavailable"
    assert compare([off_grid], expected)["status"] == "unavailable"


def recording_flags(**methods: str) -> dict:
    names = ("import", "export", "load", "water", "ev")
    base = {
        "import": "power_history",
        "export": "power_history",
        "load": "derived_history",
        "water": "power_history",
        "ev": "power_history",
    }
    base.update(methods)
    return {
        "source": "recorder",
        "recording": {
            "schema_version": 1,
            "semantics": "slot-energy-v1",
            "components": {n: {"method": base[n], "owner": "recorder"} for n in names},
        },
    }


def test_unmeasured_water_slot_is_included_with_note_and_exact_demand():
    start = datetime(2026, 10, 5, tzinfo=UTC)
    result = compare(
        [row(start, water_kwh=0.0, quality_flags=recording_flags(water="unknown"))], [start]
    )
    assert result["coverage"]["covered_slots"] == 1
    assert result["coverage"]["excluded_slots"] == 0
    assert result["coverage"]["water_unmeasured_slots"] == 1
    assert result["coverage"]["water_unmeasured_hours"] == pytest.approx(0.25)
    assert result["grid_only_cost_sek"] == pytest.approx((1.0 + 0.0 + 2.0) * 2.0)


def test_null_water_with_unavailable_sensor_counts_as_zero():
    start = datetime(2026, 10, 5, tzinfo=UTC)
    result = compare(
        [row(start, water_kwh=None, quality_flags=recording_flags(water="unknown"))], [start]
    )
    assert result["coverage"]["water_unmeasured_slots"] == 1
    assert result["grid_only_cost_sek"] == pytest.approx(6.0)


@pytest.mark.parametrize("load_method", ["snapshot", "mixed", "unknown", "power_history"])
def test_unknown_water_with_non_derived_load_is_rejected(load_method):
    start = datetime(2026, 10, 5, tzinfo=UTC)
    flags = recording_flags(water="unknown", load=load_method)
    result = compare([row(start, water_kwh=0.0, quality_flags=flags)], [start])
    assert result["coverage"]["covered_slots"] == 0
    assert result["coverage"]["water_unmeasured_slots"] == 0


def test_clamp_suspect_unknown_water_slot_is_rejected():
    start = datetime(2026, 10, 5, tzinfo=UTC)
    flags = recording_flags(water="unknown")
    result = compare(
        [row(start, water_kwh=0.0, load_kwh=0.0, ev_charging_kwh=1.0, quality_flags=flags)],
        [start],
    )
    assert result["coverage"]["covered_slots"] == 0
    # Zero EV with zero load is fine (nothing could have been clamped).
    ok = compare(
        [row(start, water_kwh=0.0, load_kwh=0.0, ev_charging_kwh=0.0, quality_flags=flags)],
        [start],
    )
    assert ok["coverage"]["covered_slots"] == 1


@pytest.mark.parametrize("component", ["ev", "import", "export"])
def test_other_unknown_components_stay_rejected_with_unknown_water(component):
    start = datetime(2026, 10, 5, tzinfo=UTC)
    flags = recording_flags(water="unknown", **{component: "unknown"})
    result = compare([row(start, water_kwh=0.0, quality_flags=flags)], [start])
    assert result["coverage"]["covered_slots"] == 0


def test_mixed_day_counts_totals_and_hours_and_zero_when_none():
    start = datetime(2026, 10, 5, tzinfo=UTC)
    starts = [start + i * SLOT for i in range(8)]
    rows = [
        row(
            s,
            water_kwh=0.0,
            quality_flags=recording_flags(water="unknown" if i < 3 else "power_history"),
        )
        for i, s in enumerate(starts)
    ]
    result = compare(rows, starts)
    assert result["coverage"]["covered_slots"] == 8
    assert result["coverage"]["water_unmeasured_slots"] == 3
    assert result["coverage"]["water_unmeasured_hours"] == pytest.approx(0.75)
    assert result["grid_only_cost_sek"] == pytest.approx(8 * 6.0)
    none = compare(rows[3:], starts[3:])
    assert none["coverage"]["water_unmeasured_slots"] == 0
    assert none["coverage"]["water_unmeasured_hours"] == 0


def test_large_unmeasured_fixture_is_fully_included():
    start = datetime(2026, 9, 1, tzinfo=UTC)
    starts = [start + i * SLOT for i in range(851)]
    flags = recording_flags(water="unknown")
    result = compare([row(s, water_kwh=0.0, quality_flags=flags) for s in starts], starts)
    assert result["coverage"]["covered_slots"] == 851
    assert result["coverage"]["water_unmeasured_hours"] == pytest.approx(851 * 0.25)


# --- Eligibility parity: reference copy of the logic before reasons were added ----
# Kept verbatim so that reporting exclusion reasons can never change which slots count.


def _ref_recording_is_eligible(
    flags: dict[str, Any], *, battery_present: bool, allow_unmeasured_water: bool = False
) -> bool:
    """Whether recorder provenance allows the slot into the comparison.

    ``allow_unmeasured_water`` accepts a water component with method ``unknown`` only
    when the load was derived from history (so it still contains the unmeasured water)
    and every other relevant component is eligible.
    """
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
        if (
            name == "water"
            and method == "unknown"
            and owner == "recorder"
            and allow_unmeasured_water
            and _component_method(flags, "load") == "derived_history"
        ):
            continue
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


def _ref_slot_eligible(
    row: GridOnlyObservation,
    *,
    battery_present: bool,
    cycle_cost_kwh: float,
) -> bool:
    if battery_present and not math.isfinite(cycle_cost_kwh):
        return False
    start_utc = _valid_slot_start(row.start)
    if start_utc is None:
        return False
    flags = _quality_flags(row.quality_flags)
    if not _ref_recording_is_eligible(
        flags, battery_present=battery_present, allow_unmeasured_water=True
    ):
        return False
    water_unmeasured = _component_method(flags, "water") == "unknown"

    # Unmeasured water (null or zero) is not a filled value: derived load still contains it.
    water_value = _finite_number(row.water_kwh, nonnegative=True)
    if water_unmeasured and water_value is None and row.water_kwh is None:
        water_value = 0.0
    energies = (
        _finite_number(row.import_kwh, nonnegative=True),
        _finite_number(row.export_kwh, nonnegative=True),
        _finite_number(row.load_kwh, nonnegative=True),
        water_value,
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
        return False

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
        return False
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
            return False

    grid_only_cost = (load_kwh + water_kwh + ev_kwh) * import_price
    import_cost = import_kwh * import_price
    export_revenue = export_kwh * export_price
    ds_wear_cost = (charge_kwh + discharge_kwh) * cycle_cost_kwh * 0.5
    return all(
        math.isfinite(v)
        for v in (
            import_cost,
            export_revenue,
            grid_only_cost,
            import_cost - export_revenue,
            ds_wear_cost,
            import_cost - export_revenue + ds_wear_cost,
        )
    )


def _component_flags(**overrides: dict | None) -> dict:
    components = {
        name: {"method": "power_history", "owner": "recorder"}
        for name in (
            "import",
            "export",
            "load",
            "water",
            "ev",
            "battery_charge",
            "battery_discharge",
        )
    }
    components["load"] = {"method": "derived_history", "owner": "recorder"}
    for name, value in overrides.items():
        if value is None:
            components.pop(name)
        else:
            components[name] = value
    return {
        "source": "recorder",
        "recording": {"schema_version": 1, "semantics": "slot-energy-v1", "components": components},
    }


def _unknown(owner: str = "recorder") -> dict:
    return {"method": "unknown", "owner": owner}


PARITY_FLAGS: list[Any] = [
    None,
    "not json",
    '{"source": "recorder"}',
    {},
    {"source": "backfill"},
    {"source": "recorder"},
    {"source": "recorder", "exclude": True},
    {"source": "recorder", "placeholder": True},
    {"source": "recorder", "is_placeholder": True},
    {"source": "recorder", "backfill": True},
    {"source": "recorder", "comparison_history": {"disposition": "exclude_from_comparison"}},
    {"source": "recorder", "comparison_history": {"disposition": "keep"}},
    {"source": "recorder", "recording": "bad"},
    {"source": "recorder", "recording": {"schema_version": 2, "semantics": "slot-energy-v1"}},
    {"source": "recorder", "recording": {"schema_version": 1, "semantics": "other"}},
    {"source": "recorder", "recording": {"schema_version": 1, "semantics": "slot-energy-v1"}},
    _component_flags(),
    _component_flags(water=_unknown()),
    _component_flags(water=_unknown("unknown")),
    _component_flags(water=_unknown("backfill")),
    _component_flags(water=None),
    _component_flags(water={"method": "snapshot", "owner": "recorder"}),
    _component_flags(water={"method": "mixed", "owner": "recorder"}),
    _component_flags(water={"method": "unconfigured_zero", "owner": "recorder"}),
    _component_flags(water={"method": "disabled_zero", "owner": "recorder"}),
    _component_flags(water={"method": "bogus", "owner": "recorder"}),
    _component_flags(water=_unknown(), load={"method": "snapshot", "owner": "recorder"}),
    _component_flags(water=_unknown(), load={"method": "mixed", "owner": "recorder"}),
    _component_flags(water=_unknown(), load={"method": "power_history", "owner": "recorder"}),
    _component_flags(water=_unknown(), load=_unknown()),
    _component_flags(ev=_unknown()),
    _component_flags(ev=_unknown(), water=_unknown()),
    _component_flags(ev={"method": "disabled_zero", "owner": "recorder"}),
    _component_flags(load={"method": "power_history", "owner": "backfill"}),
    _component_flags(**{"import": _unknown()}),
    _component_flags(**{"import": None}),
    _component_flags(export={"method": "snapshot", "owner": "recorder"}),
    _component_flags(battery_charge={"method": "disabled_zero", "owner": "recorder"}),
    _component_flags(battery_discharge={"method": "snapshot", "owner": "recorder"}),
    _component_flags(battery_charge=None),
    _component_flags(battery_discharge=_unknown()),
]
PARITY_VALUES: list[dict] = [
    {},
    {"water_kwh": None},
    {"water_kwh": 0.0},
    {"water_kwh": -0.1},
    {"water_kwh": float("nan")},
    {"load_kwh": None},
    {"load_kwh": 0.0, "ev_charging_kwh": 1.0, "water_kwh": 0.0},
    {"load_kwh": 0.0, "ev_charging_kwh": 0.0, "water_kwh": 0.0},
    {"import_kwh": -1.0},
    {"export_kwh": float("inf")},
    {"ev_charging_kwh": None},
    {"import_price_sek_kwh": None},
    {"export_price_sek_kwh": float("nan")},
    {"import_price_sek_kwh": -0.5},
    {"water_kwh": 0.3, "ev_charging_kwh": 0.4},
    {"batt_charge_kwh": 0.0, "batt_discharge_kwh": 0.0},
    {"batt_charge_kwh": 1.0, "batt_discharge_kwh": 0.5},
    {"batt_charge_kwh": None, "batt_discharge_kwh": 0.0},
    {"batt_charge_kwh": -1.0, "batt_discharge_kwh": 0.0},
    {"import_kwh": 1e308, "import_price_sek_kwh": 1e308},
]


@pytest.mark.parametrize(
    "battery_present,cycle_cost", [(False, 0.2), (True, 0.2), (True, math.nan)]
)
def test_eligibility_matches_reference_copy_over_slot_matrix(battery_present, cycle_cost):
    start = datetime(2026, 10, 5, tzinfo=UTC)
    eligible_seen = excluded_seen = 0
    for flags, values in itertools.product(PARITY_FLAGS, PARITY_VALUES):
        observation = row(start, quality_flags=flags, **values)
        expected = _ref_slot_eligible(
            observation, battery_present=battery_present, cycle_cost_kwh=cycle_cost
        )
        covered = compare(
            [observation], [start], battery_present=battery_present, cycle_cost_kwh=cycle_cost
        )["coverage"]["covered_slots"]
        assert covered == int(expected), (flags, values)
        eligible_seen += expected
        excluded_seen += not expected
    assert excluded_seen > 100
    assert (eligible_seen > 0) is not (battery_present and math.isnan(cycle_cost))


# --- Exclusion reasons and spans ------------------------------------------------------

START = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)


def _mixed_fixture() -> tuple[list[GridOnlyObservation], list[datetime]]:
    starts = [START + SLOT * index for index in range(8)]
    unknown_water = recording_flags(water="unknown")
    rows = {
        0: row(starts[0], import_kwh=0.5),
        1: row(starts[1], import_kwh=0.5),
        3: row(starts[3], import_kwh=0.5, water_kwh=0.0, quality_flags=unknown_water),
        4: row(starts[4], quality_flags={"source": "recorder", "exclude": True}),
        5: row(starts[5], import_kwh=0.5),
        6: row(starts[6], import_price_sek_kwh=None),
        7: row(starts[7], import_kwh=0.5),
    }
    return [rows[index] for index in sorted(rows)], starts


# Response captured from the code before reasons were added, for the same input.
LEGACY_RESPONSE = {
    "status": "partial",
    "reason": "partial_coverage",
    "method_version": "grid-only-bill-v1",
    "coverage": {
        "covered_slots": 5,
        "total_slots": 8,
        "excluded_slots": 3,
        "water_unmeasured_slots": 1,
        "water_unmeasured_hours": 0.25,
    },
    "time_axis": {
        "timezone": "Europe/Stockholm",
        "start": "2026-10-05T10:00:00+02:00",
        "end": "2026-10-05T12:00:00+02:00",
    },
    "through": "2026-10-05T12:00:00+02:00",
    "grid_only_cost_sek": 34.0,
    "grid_only_wear_cost_sek": 0.0,
    "ds_electricity_cost_sek": 5.0,
    "ds_wear_cost_sek": 0.0,
    "ds_cost_sek": 5.0,
    "saving_sek": 29.0,
    "points": [
        {
            "start": "2026-10-05T10:00:00+02:00",
            "end": "2026-10-05T11:00:00+02:00",
            "import_cost_sek": 3.0,
            "export_revenue_sek": 0.0,
            "ds_electricity_cost_sek": 3.0,
            "ds_wear_cost_sek": 0.0,
            "grid_only_wear_cost_sek": 0.0,
            "ds_cost_sek": 3.0,
            "grid_only_cost_sek": 20.0,
            "cumulative_ds_cost_sek": 3.0,
            "cumulative_grid_only_cost_sek": 20.0,
        },
        {
            "start": "2026-10-05T11:00:00+02:00",
            "end": "2026-10-05T12:00:00+02:00",
            "import_cost_sek": 2.0,
            "export_revenue_sek": 0.0,
            "ds_electricity_cost_sek": 2.0,
            "ds_wear_cost_sek": 0.0,
            "grid_only_wear_cost_sek": 0.0,
            "ds_cost_sek": 2.0,
            "grid_only_cost_sek": 14.0,
            "cumulative_ds_cost_sek": 5.0,
            "cumulative_grid_only_cost_sek": 34.0,
        },
    ],
    "segments": [
        {
            "start": "2026-10-05T10:00:00+02:00",
            "end": "2026-10-05T10:30:00+02:00",
            "points": [
                {
                    "at": "2026-10-05T10:00:00+02:00",
                    "cumulative_ds_cost_sek": 0.0,
                    "cumulative_grid_only_cost_sek": 0.0,
                },
                {
                    "at": "2026-10-05T10:15:00+02:00",
                    "cumulative_ds_cost_sek": 1.0,
                    "cumulative_grid_only_cost_sek": 7.0,
                },
                {
                    "at": "2026-10-05T10:30:00+02:00",
                    "cumulative_ds_cost_sek": 2.0,
                    "cumulative_grid_only_cost_sek": 14.0,
                },
            ],
        },
        {
            "start": "2026-10-05T10:45:00+02:00",
            "end": "2026-10-05T11:00:00+02:00",
            "points": [
                {
                    "at": "2026-10-05T10:45:00+02:00",
                    "cumulative_ds_cost_sek": 2.0,
                    "cumulative_grid_only_cost_sek": 14.0,
                },
                {
                    "at": "2026-10-05T11:00:00+02:00",
                    "cumulative_ds_cost_sek": 3.0,
                    "cumulative_grid_only_cost_sek": 20.0,
                },
            ],
        },
        {
            "start": "2026-10-05T11:15:00+02:00",
            "end": "2026-10-05T11:30:00+02:00",
            "points": [
                {
                    "at": "2026-10-05T11:15:00+02:00",
                    "cumulative_ds_cost_sek": 3.0,
                    "cumulative_grid_only_cost_sek": 20.0,
                },
                {
                    "at": "2026-10-05T11:30:00+02:00",
                    "cumulative_ds_cost_sek": 4.0,
                    "cumulative_grid_only_cost_sek": 27.0,
                },
            ],
        },
        {
            "start": "2026-10-05T11:45:00+02:00",
            "end": "2026-10-05T12:00:00+02:00",
            "points": [
                {
                    "at": "2026-10-05T11:45:00+02:00",
                    "cumulative_ds_cost_sek": 4.0,
                    "cumulative_grid_only_cost_sek": 27.0,
                },
                {
                    "at": "2026-10-05T12:00:00+02:00",
                    "cumulative_ds_cost_sek": 5.0,
                    "cumulative_grid_only_cost_sek": 34.0,
                },
            ],
        },
    ],
}


def test_existing_response_fields_are_unchanged_by_reason_reporting():
    rows, starts = _mixed_fixture()
    result = compare(rows, starts)
    result["coverage"].pop("excluded_by_reason")
    result.pop("excluded_spans")
    assert result == LEGACY_RESPONSE


def test_mixed_fixture_reports_spans_and_totals_that_sum_to_excluded_slots():
    rows, starts = _mixed_fixture()
    result = compare(rows, starts)
    coverage = result["coverage"]
    assert coverage["excluded_slots"] == 3
    assert coverage["excluded_by_reason"] == {
        "missing_slot": 1,
        "user_excluded": 1,
        "missing_price": 1,
    }
    assert sum(coverage["excluded_by_reason"].values()) == coverage["excluded_slots"]
    spans = result["excluded_spans"]
    assert [(span["reason"], span["slots"]) for span in spans] == [
        ("missing_slot", 1),
        ("user_excluded", 1),
        ("missing_price", 1),
    ]
    assert sum(span["slots"] for span in spans) == coverage["excluded_slots"]
    assert spans[0] == {
        "start": starts[2].astimezone(TZ).isoformat(),
        "end": starts[3].astimezone(TZ).isoformat(),
        "slots": 1,
        "reason": "missing_slot",
        "component": None,
    }
    assert spans[0]["start"].endswith("+02:00")


def test_single_span_merges_contiguous_slots_with_component():
    starts = [START + SLOT * index for index in range(10)]
    flags = recording_flags(ev="unknown")
    rows = [
        row(s, quality_flags=flags if 2 <= i < 10 else {"source": "recorder"})
        for i, s in enumerate(starts)
    ]
    result = compare(rows, starts)
    assert result["excluded_spans"] == [
        {
            "start": starts[2].astimezone(TZ).isoformat(),
            "end": (starts[9] + SLOT).astimezone(TZ).isoformat(),
            "slots": 8,
            "reason": "unknown_component",
            "component": "ev",
        }
    ]
    assert result["coverage"]["excluded_by_reason"] == {"unknown_component": 8}


def test_adjacent_slots_with_different_reasons_are_separate_spans():
    starts = [START + SLOT * index for index in range(8)]
    rows = [row(s, import_price_sek_kwh=None) for s in starts[4:]]
    result = compare(rows, starts)
    assert [(s["reason"], s["slots"]) for s in result["excluded_spans"]] == [
        ("missing_slot", 4),
        ("missing_price", 4),
    ]


def test_non_contiguous_slots_with_same_reason_are_separate_spans():
    starts = [START + SLOT * index for index in range(5)]
    rows = [row(starts[1]), row(starts[3])]
    result = compare(rows, starts)
    assert [(s["reason"], s["slots"]) for s in result["excluded_spans"]] == [
        ("missing_slot", 1),
        ("missing_slot", 1),
        ("missing_slot", 1),
    ]


def test_dst_fall_back_day_spans_are_contiguous_in_elapsed_time_with_offsets():
    # 2026-10-25 is the Stockholm fall-back day (25 hours); 00:00 local = 22:00 UTC the day before.
    day_start = datetime(2026, 10, 24, 22, 0, tzinfo=UTC)
    starts = [day_start + SLOT * index for index in range(100)]
    rows = [row(s) for s in starts[:4]] + [row(s) for s in starts[-4:]]
    result = compare(rows, starts, hourly=False)
    (span,) = result["excluded_spans"]
    assert span["slots"] == 92
    assert span["start"].endswith("01:00:00+02:00")
    assert span["end"].endswith("23:00:00+01:00")
    assert result["coverage"]["excluded_slots"] == 92


def test_nothing_excluded_returns_empty_list_and_object():
    starts = [START + SLOT * index for index in range(3)]
    result = compare([row(s) for s in starts], starts)
    assert result["excluded_spans"] == []
    assert result["coverage"]["excluded_by_reason"] == {}


def test_no_data_and_unavailable_responses_still_carry_spans():
    starts = [START + SLOT * index for index in range(3)]
    empty = compare([], starts, has_rows=False)
    assert [(s["reason"], s["slots"]) for s in empty["excluded_spans"]] == [("missing_slot", 3)]
    assert empty["coverage"]["excluded_by_reason"] == {"missing_slot": 3}


def test_duplicate_rows_for_one_instant_are_ambiguous():
    starts = [START]
    rows = [row(START), row(START.astimezone(TZ))]
    result = compare(rows, starts)
    assert result["excluded_spans"][0]["reason"] == "ambiguous_rows"
    assert result["coverage"]["excluded_by_reason"] == {"ambiguous_rows": 1}


def _reason(observation: GridOnlyObservation, **kwargs) -> tuple[str, str | None]:
    result = compare([observation], [START], **kwargs)
    (span,) = result["excluded_spans"]
    return span["reason"], span["component"]


def _flags(**overrides) -> dict:
    return recording_flags(**overrides)


@pytest.mark.parametrize(
    ("observation", "kwargs", "expected"),
    [
        (
            row(START, batt_charge_kwh=0.0, batt_discharge_kwh=0.0),
            {"battery_present": True, "cycle_cost_kwh": float("nan")},
            ("battery_cost_invalid", None),
        ),
        (row(START, quality_flags={"source": "backfill"}), {}, ("not_recorder", None)),
        (
            row(START, quality_flags={"source": "recorder", "placeholder": True}),
            {},
            ("not_recorder", None),
        ),
        (
            row(START, quality_flags={"source": "recorder", "backfill": True}),
            {},
            ("not_recorder", None),
        ),
        (
            row(START, quality_flags={"source": "recorder", "exclude": True}),
            {},
            ("user_excluded", None),
        ),
        (
            row(
                START,
                quality_flags={
                    "source": "recorder",
                    "comparison_history": {"disposition": "exclude_from_comparison"},
                },
            ),
            {},
            ("user_excluded", None),
        ),
        (
            row(
                START,
                quality_flags={
                    "source": "recorder",
                    "recording": {"schema_version": 2, "semantics": "slot-energy-v1"},
                },
            ),
            {},
            ("unsupported_provenance", None),
        ),
        (
            row(START, quality_flags=_flags(ev="unconfigured_zero")),
            {},
            ("unconfigured_sensor", "ev"),
        ),
        (
            row(START, quality_flags=_flags(load="snapshot")),
            {},
            ("estimated_component", "load"),
        ),
        (
            row(START, quality_flags=_flags(water="unknown", load="mixed")),
            {},
            ("estimated_component", "load"),
        ),
        (row(START, quality_flags=_flags(ev="unknown")), {}, ("unknown_component", "ev")),
        (
            row(START, water_kwh=0.0, quality_flags=_flags(water="unknown", load="snapshot")),
            {},
            ("estimated_component", "load"),
        ),
        (row(START, import_price_sek_kwh=None), {}, ("missing_price", None)),
        (row(START, load_kwh=None), {}, ("missing_energy_value", "load")),
        (
            row(
                START,
                water_kwh=0.0,
                load_kwh=0.0,
                ev_charging_kwh=1.0,
                quality_flags=_flags(water="unknown"),
            ),
            {},
            ("clamp_hidden_demand", None),
        ),
        (
            row(START, water_kwh=0.5, quality_flags=_flags(water="disabled_zero")),
            {},
            ("disabled_nonzero", "water"),
        ),
    ],
)
def test_each_reason_code_is_reported_with_its_component(observation, kwargs, expected):
    assert _reason(observation, **kwargs) == expected


def test_battery_disabled_zero_and_battery_component_reasons():
    flags = recording_flags()
    flags["recording"]["components"]["battery_charge"] = {
        "method": "disabled_zero",
        "owner": "recorder",
    }
    flags["recording"]["components"]["battery_discharge"] = {
        "method": "power_history",
        "owner": "recorder",
    }
    observation = row(START, batt_charge_kwh=0.0, batt_discharge_kwh=0.0, quality_flags=flags)
    assert _reason(observation, battery_present=True) == ("battery_disabled_zero", "battery_charge")


def test_unknown_owner_and_missing_component_are_unknown_component():
    flags = recording_flags()
    flags["recording"]["components"]["water"] = {"method": "power_history", "owner": "unknown"}
    assert _reason(row(START, quality_flags=flags)) == ("unknown_component", "water")
    del flags["recording"]["components"]["ev"]
    flags["recording"]["components"]["water"] = {"method": "power_history", "owner": "recorder"}
    assert _reason(row(START, quality_flags=flags)) == ("unknown_component", "ev")


def test_first_failing_check_wins():
    flags = {"source": "recorder", "backfill": True, **recording_flags(water="unknown")}
    observation = row(START, import_price_sek_kwh=None, quality_flags=flags)
    assert _reason(observation) == ("not_recorder", None)
    # Provenance outranks values, and price outranks energy values.
    assert _reason(row(START, quality_flags=_flags(ev="unknown"), load_kwh=None)) == (
        "unknown_component",
        "ev",
    )
    assert _reason(row(START, import_price_sek_kwh=None, load_kwh=None)) == ("missing_price", None)


def test_fixed_fees_never_enter_grid_only_comparison(monkeypatch):
    """Grid-only comparison is energy-only: results are identical with non-zero fixed fees."""
    import inspect

    import backend.grid_only_comparison as module
    from backend.core import fixed_fees

    starts = [TZ.localize(datetime(2026, 10, 5, 10)) + i * SLOT for i in range(4)]
    rows = [row(s, import_kwh=1.0, load_kwh=1.0) for s in starts]
    baseline = compare(rows, starts)

    def _boom(*args, **kwargs):
        raise AssertionError("fixed fees must not be read by the grid-only comparison")

    monkeypatch.setattr(fixed_fees, "fixed_fees_for_range", _boom)
    with_fees = compare(rows, starts)

    assert with_fees == baseline
    source = inspect.getsource(module)
    assert "fixed_fee" not in source
    assert "subscription_fee" not in source
    assert "supplier_fee" not in source
