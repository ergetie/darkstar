from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytz

from backend.grid_only_comparison import GridOnlyObservation, build_grid_only_comparison

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
        segment_end["cumulative_grid_only_cost_sek"]
        - segment_end["cumulative_ds_cost_sek"]
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
        {"source": "recorder", "recording": {"schema_version": 1, "semantics": "slot-energy-v1", "components": {}}},
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
    assert compare(
        [row(start, batt_charge_kwh=0, batt_discharge_kwh=0, quality_flags=flags)],
        [start],
        battery_present=True,
    )["status"] == "unavailable"


@pytest.mark.parametrize("field", ["batt_charge_kwh", "batt_discharge_kwh"])
@pytest.mark.parametrize("value", [None, float("nan"), -0.1, float("inf")])
def test_configured_battery_requires_finite_nonnegative_flows(field, value):
    start = datetime(2026, 10, 5, tzinfo=UTC)
    assert compare(
        [row(start, **{field: value})],
        [start],
        battery_present=True,
    )["status"] == "unavailable"


@pytest.mark.parametrize(
    ("price", "expected_grid", "expected_ds", "expected_saving"),
    [(0.0, 0.0, 0.0, 0.0), (-1.0, -3.5, -1.0, -2.5)],
)
def test_zero_and_negative_tariffs_are_preserved(price, expected_grid, expected_ds, expected_saving):
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
    assert compare([row(start, ev_charging_kwh=0, quality_flags=flags)], [start])["status"] == "available"
    assert compare([row(start, ev_charging_kwh=1, quality_flags=flags)], [start])["status"] == "unavailable"


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
    assert result["coverage"] == {"covered_slots": 7, "total_slots": 8, "excluded_slots": 1}
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
        [row(value, load_kwh=0, water_kwh=0, ev_charging_kwh=0, import_kwh=0.1) for value in starts],
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
