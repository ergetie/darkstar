from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from backend.battery_comparison import (
    BatteryModel,
    ComparisonBattery,
    FitDiagnostics,
    GridModel,
    RecordedObservation,
    build_comparison,
    fit_calibration,
    simulate_self_use,
)


def recording(
    count: int = 1_200,
    grid: GridModel = GridModel(0.94, 0.90),
    storage: BatteryModel = BatteryModel(0.92, 0.94),
) -> list[RecordedObservation]:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    state = 50.0
    capacity = 10.0
    flow_level = 0.6
    discharge_level = flow_level * storage.eta_charge * storage.eta_discharge
    rows = []
    for i in range(count):
        charging = i % 2 == 0
        charge, discharge = (flow_level, 0.0) if charging else (0.0, discharge_level)
        pv = 0.1 if charging else 0.4
        demand = 0.3 if charging else 0.7
        soc_start = state
        state += storage.stored_delta(charge, discharge) / capacity * 100
        net = grid.net_grid(pv, demand, charge, discharge)
        rows.append(
            RecordedObservation(
                start=start + i * timedelta(minutes=15),
                import_kwh=max(net, 0),
                export_kwh=max(-net, 0),
                import_price=-0.2 if i % 41 == 0 else 1.0 + i % 4 * 0.1,
                export_price=0.5,
                pv_kwh=pv,
                load_kwh=demand,
                water_kwh=0.0,
                ev_kwh=0.0,
                charge_kwh=charge,
                discharge_kwh=discharge,
                soc_start_percent=soc_start,
                soc_end_percent=state,
                quality_flags={"source": "recorder"},
            )
        )
    return rows


def test_calibration_fits_bounded_shared_model_and_negative_price_data() -> None:
    rows = recording()
    result = fit_calibration(rows, 10.0, rows[-1].start + timedelta(minutes=15))
    assert result.status == "available"
    assert result.diagnostics is not None
    fitted = result.diagnostics
    assert fitted.grid_model.eta_out == pytest.approx(0.94, abs=0.002)
    assert fitted.grid_model.eta_in == pytest.approx(0.90, abs=0.002)
    assert fitted.battery_model.eta_charge == pytest.approx(0.92, abs=0.002)
    assert fitted.battery_model.eta_discharge == pytest.approx(0.94, abs=0.002)
    assert fitted.grid_training_samples == 960
    assert fitted.grid_validation_samples == 240
    assert fitted.net_cost_error_sek == pytest.approx(0.0)


def test_calibration_excludes_backfilled_and_explicitly_excluded_rows() -> None:
    rows = recording()
    rows[0] = replace(rows[0], quality_flags={"source": "backfill"})
    rows[1] = replace(rows[1], quality_flags={"source": "recorder", "exclude": True})
    result = fit_calibration(rows, 10.0, rows[-1].start + timedelta(minutes=15))
    assert result.status == "available"
    assert result.diagnostics is not None
    assert (
        result.diagnostics.grid_training_samples + result.diagnostics.grid_validation_samples
        == 1198
    )


def test_ac_like_unity_and_deye_like_synthetic_boundaries_fit_independently() -> None:
    rows = recording(grid=GridModel(1.0, 1.0), storage=BatteryModel(1.0, 1.0))
    result = fit_calibration(rows, 10.0, rows[-1].start + timedelta(minutes=15))
    assert result.status == "available"
    assert result.diagnostics is not None
    assert result.diagnostics.grid_model == GridModel(1.0, 1.0)
    assert result.diagnostics.battery_model == BatteryModel(1.0, 1.0)


def test_unobserved_grid_direction_is_rejected() -> None:
    rows = [replace(row, pv_kwh=1.2) for row in recording()]
    result = fit_calibration(rows, 10.0, rows[-1].start + timedelta(minutes=15))
    assert result.status == "insufficient_data"
    assert result.reason == "unidentifiable_flow_direction"


def test_holdout_corruption_rejects_fit_without_training_leakage() -> None:
    rows = recording()
    rows[1_000:] = [
        replace(row, import_kwh=float(row.import_kwh or 0.0) + 0.5) for row in rows[1_000:]
    ]
    result = fit_calibration(rows, 10.0, rows[-1].start + timedelta(minutes=15))
    assert result.status == "unreliable_model"
    assert result.reason == "holdout_validation_failed"


def test_comparison_identical_actions_have_zero_saving_and_reconciled_endpoints() -> None:
    grid = GridModel(0.8, 0.9)
    storage = BatteryModel(0.92, 0.9)
    diagnostics = FitDiagnostics(
        grid,
        storage,
        960,
        240,
        200,
        50,
        "2026-09-01T00:00:00+00:00",
        "2026-09-10T00:00:00+00:00",
        "2026-09-10T00:15:00+00:00",
        "2026-09-12T00:00:00+00:00",
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        100.0,
    )
    start = datetime(2026, 9, 12, tzinfo=UTC)
    state = 60.0
    rows = []
    for i in range(4):
        next_state = state - 0.5 / storage.eta_discharge / 10 * 100
        net = grid.net_grid(0.0, 1.0, 0.0, 0.5)
        rows.append(
            RecordedObservation(
                start + timedelta(minutes=15 * i),
                max(net, 0),
                max(-net, 0),
                2.0,
                1.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                0.5,
                state,
                next_state,
            )
        )
        state = next_state
    battery = ComparisonBattery(10, 10, 95, 2000, 2000)
    result, reason = build_comparison(
        rows, None, battery, diagnostics, 0.2, lambda dt: dt.replace(minute=0).isoformat()
    )
    assert reason is None
    assert result is not None
    assert result["saving_sek"] == 0.0
    assert result["darkstar"]["comparison_cost_sek"] == result["self_use"]["comparison_cost_sek"]
    assert (
        result["points"][-1]["darkstar_cumulative_comparison_cost_sek"]
        == result["darkstar"]["comparison_cost_sek"]
    )
    assert (
        result["points"][-1]["self_use_cumulative_comparison_cost_sek"]
        == result["self_use"]["comparison_cost_sek"]
    )


def test_comparison_rejects_missing_start_soc_and_interior_gap() -> None:
    grid = GridModel(0.8, 0.9)
    storage = BatteryModel(0.92, 0.9)
    diagnostics = FitDiagnostics(
        grid, storage, 960, 240, 200, 50, "a", "b", "c", "d", 0, 0, 0, 0, 0, 1
    )
    start = datetime(2026, 9, 12, tzinfo=UTC)
    row = RecordedObservation(start, 0.2, 0, 1, 1, 0, 0.2, 0, 0, 0, 0, None, 50)
    battery = ComparisonBattery(10, 10, 95, 2000, 2000)
    result, reason = build_comparison(
        [row], None, battery, diagnostics, 0.2, lambda dt: dt.isoformat()
    )
    assert result is None
    assert reason == "missing_start_soc"
    result, reason = build_comparison(
        [row], 50, battery, diagnostics, 0.2, lambda dt: dt.isoformat()
    )
    assert reason is None and result is not None
    assert result["darkstar"]["stored_energy_change_kwh"] == 0
    assert result["self_use"]["stored_energy_change_kwh"] == pytest.approx(-0.278, abs=0.001)
    result, reason = build_comparison(
        [row, replace(row, start=row.start + timedelta(minutes=30))],
        50,
        battery,
        diagnostics,
        0.2,
        lambda dt: dt.isoformat(),
    )
    assert result is None and reason == "missing_completed_slot"


def test_self_use_applies_pv_conversion_and_separate_power_limits() -> None:
    row = RecordedObservation(
        datetime(2026, 9, 12, tzinfo=UTC),
        0,
        0,
        1,
        1,
        1.0,
        0.2,
        0.1,
        0.1,
        0,
        0,
        50,
        50,
    )
    battery = ComparisonBattery(10, 10, 95, 400, 2000)
    grid = GridModel(0.95, 0.9)
    storage = BatteryModel(0.92, 0.9)
    assert row.demand_kwh == pytest.approx(0.4)  # Base load + recorded water + recorded EV.
    charge = simulate_self_use(row, 5.0, battery, grid, storage)
    assert charge.charge_kwh == pytest.approx(0.1)  # Separate 400 W charge limit.
    assert charge.discharge_kwh == 0
    assert charge.grid_net_kwh == pytest.approx(-0.455)
    full = simulate_self_use(row, 9.5, battery, grid, storage)
    assert full.charge_kwh == 0

    deficit = replace(row, pv_kwh=0, load_kwh=1)
    discharge = simulate_self_use(deficit, 5.0, battery, grid, storage)
    assert discharge.discharge_kwh == pytest.approx(0.5)  # Separate 2 kW discharge limit.
    assert discharge.grid_net_kwh > 0  # Remaining demand imports; the battery never exports.
    empty = simulate_self_use(deficit, 1.0, battery, grid, storage)
    assert empty.discharge_kwh == 0


def test_negative_reference_price_preserves_stored_energy_valuation_sign() -> None:
    grid = GridModel(0.8, 0.9)
    storage = BatteryModel(0.92, 0.9)
    diagnostics = FitDiagnostics(
        grid, storage, 960, 240, 200, 50, "a", "b", "c", "d", 0, 0, 0, 0, 0, 1
    )
    row = RecordedObservation(
        datetime(2026, 9, 12, tzinfo=UTC),
        0,
        0,
        -2,
        -2,
        1,
        0.8,
        0,
        0,
        0,
        0,
        50,
        60,
    )
    result, reason = build_comparison(
        [row],
        None,
        ComparisonBattery(10, 10, 95, 2000, 2000),
        diagnostics,
        0,
        lambda dt: dt.isoformat(),
    )
    assert reason is None and result is not None
    assert result["reference_price_sek_kwh"] == pytest.approx(-1.44)
    assert result["darkstar"]["stored_energy_value_sek"] == pytest.approx(-1.44)
    assert result["saving_sek"] < 0


def test_overlap_is_netted_on_both_comparison_sides() -> None:
    diagnostics = FitDiagnostics(
        GridModel(0.8, 0.9),
        BatteryModel(0.92, 0.9),
        960,
        240,
        200,
        50,
        "a",
        "b",
        "c",
        "d",
        0,
        0,
        0,
        0,
        0,
        20,
    )
    row = RecordedObservation(
        datetime(2026, 9, 12, tzinfo=UTC),
        0.5,
        0.2,
        2.0,
        1.0,
        0,
        0.3,
        0,
        0,
        0,
        0,
        50,
        50,
    )
    result, reason = build_comparison(
        [row],
        None,
        ComparisonBattery(10, 10, 95, 2000, 2000),
        diagnostics,
        0,
        lambda dt: dt.isoformat(),
    )
    assert reason is None and result is not None
    # Gross metered cash cost is 0.8 kr; shared signed-net validation costs 0.6 kr.
    # The self-use simulation then discharges into the household load, eliminating
    # the remaining import. Its cost can differ from the metered baseline.
    assert result["darkstar"]["grid_cost_sek"] == pytest.approx(0.6)
    assert result["self_use"]["grid_cost_sek"] == pytest.approx(0)
    # Stored-energy valuation closes the period comparison at the metered ending SoC.
    assert result["saving_sek"] == pytest.approx(0)


def test_comparison_points_keep_repeated_dst_hours_distinct_and_utc_ordered() -> None:
    import pytz

    tz = pytz.timezone("Europe/Stockholm")
    first = tz.localize(datetime(2026, 10, 25, 2, 45), is_dst=True)
    second = tz.localize(datetime(2026, 10, 25, 2, 0), is_dst=False)
    diagnostics = FitDiagnostics(
        GridModel(0.8, 0.9),
        BatteryModel(0.92, 0.9),
        960,
        240,
        200,
        50,
        "a",
        "b",
        "c",
        "d",
        0,
        0,
        0,
        0,
        0,
        20,
    )

    def row(start: datetime) -> RecordedObservation:
        return RecordedObservation(start, 0, 0, 1, 1, 1, 0.8, 0, 0, 0, 0, 50, 50)

    result, reason = build_comparison(
        [row(first), row(second)],
        None,
        ComparisonBattery(10, 10, 95, 2000, 2000),
        diagnostics,
        0,
        lambda dt: dt.astimezone(tz).replace(minute=0, second=0, microsecond=0).isoformat(),
    )
    assert reason is None and result is not None
    assert len(result["points"]) == 2
    assert result["points"][0]["start"].endswith("+02:00")
    assert result["points"][1]["start"].endswith("+01:00")


def test_overlap_does_not_fail_net_cost_calibration() -> None:
    rows = [
        replace(r, import_kwh=r.import_kwh + 2, export_kwh=r.export_kwh + 2) for r in recording()
    ]
    result = fit_calibration(rows, 10, rows[-1].start + timedelta(minutes=15))
    assert result.status == "available"
    assert result.diagnostics is not None
    assert result.diagnostics.net_cost_error_sek == pytest.approx(0, abs=1e-8)
    assert result.diagnostics.gross_billing_volume_sek > 800


@pytest.mark.parametrize("price", [None, float("nan"), float("inf")])
def test_calibration_with_no_finite_prices_is_withheld(price) -> None:
    rows = [replace(r, import_price=price) for r in recording()]
    result = fit_calibration(rows, 10, rows[-1].start + timedelta(minutes=15))
    assert result.status == "insufficient_data"


@pytest.mark.parametrize("price", [None, float("nan"), float("inf")])
def test_comparison_rejects_invalid_prices(price) -> None:
    diagnostics = FitDiagnostics(
        GridModel(1, 1),
        BatteryModel(1, 1),
        960,
        240,
        200,
        50,
        "a",
        "b",
        "c",
        "d",
        0,
        0,
        0,
        0,
        0,
        20,
    )
    row = replace(recording()[0], import_price=price)
    result, reason = build_comparison(
        [row],
        None,
        ComparisonBattery(10, 10, 95, 2000, 2000),
        diagnostics,
        0,
        lambda dt: dt.isoformat(),
    )
    assert result is None and reason == "missing_price"


def test_proportional_simultaneous_battery_flows_are_unidentifiable() -> None:
    from backend.battery_comparison import _fit_battery

    start = datetime(2026, 9, 1, tzinfo=UTC)
    samples = [
        (start + i * timedelta(minutes=15), 0.2 + i % 5 * 0.1, 0.2 + i % 5 * 0.1, 0)
        for i in range(300)
    ]
    assert _fit_battery(samples) is None


def test_calibration_never_uses_incomplete_or_naive_observations() -> None:
    rows = recording()
    end = rows[-1].start + timedelta(minutes=10)
    rows.append(replace(rows[0], start=rows[-1].start.replace(tzinfo=None)))
    result = fit_calibration(rows, 10, end)
    assert result.status == "available" and result.diagnostics is not None
    assert (
        result.diagnostics.grid_training_samples + result.diagnostics.grid_validation_samples
        == 1199
    )


def test_large_meter_overlap_does_not_fail_selected_period_net_cost_gate() -> None:
    diagnostics = FitDiagnostics(
        GridModel(1, 1),
        BatteryModel(1, 1),
        960,
        240,
        200,
        50,
        "a",
        "b",
        "c",
        "d",
        0,
        0,
        0,
        0,
        0,
        20,
    )
    row = RecordedObservation(
        datetime(2026, 9, 12, tzinfo=UTC), 5.3, 5, 2, 1, 0, 0.3, 0, 0, 0, 0, 50, 50
    )
    result, reason = build_comparison(
        [row],
        None,
        ComparisonBattery(10, 10, 95, 2000, 2000),
        diagnostics,
        0,
        lambda dt: dt.isoformat(),
    )
    assert reason is None and result is not None
    assert result["darkstar"]["grid_cost_sek"] == pytest.approx(0.6)


@pytest.mark.parametrize(
    "load,water,ev,pv,expected_discharge,expected_grid",
    [
        (0, 0, 1, 0, 0, 1),
        (0.3, 0.1, 1, 0, 0.4 / 0.8, 1),
        (0.3, 0.1, 1, 0.75, 0, 0.8),
        (0.3, 0.1, 1, 2, 0, -0.2),
    ],
)
def test_self_use_never_discharges_battery_into_ev(
    load, water, ev, pv, expected_discharge, expected_grid
):
    row = RecordedObservation(
        datetime(2026, 9, 12, tzinfo=UTC), 0, 0, 1, 0.5, pv, load, water, ev, 0, 0, 95, 95
    )
    flow = simulate_self_use(
        row,
        9.5,
        ComparisonBattery(10, 10, 95, 4000, 4000),
        GridModel(0.8, 0.9),
        BatteryModel(0.92, 0.9),
    )
    assert flow.discharge_kwh == pytest.approx(expected_discharge)
    assert flow.grid_net_kwh == pytest.approx(expected_grid)
    if expected_discharge == 0:
        assert flow.stored_kwh == pytest.approx(9.5)
