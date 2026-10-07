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
    build_estimated_comparison,
    estimate_row_eligible,
    fit_calibration,
    observation_value_digest,
    simulate_self_use,
    trusted_row_provenance,
    trusted_soc_endpoint,
)
from backend.measurement_provenance import ENERGY_SEMANTICS


def trusted_flags() -> dict:
    return {
        "source": "recorder",
        "recording": {
            "schema_version": 1,
            "semantics": ENERGY_SEMANTICS,
            "boundary_fingerprint": "a" * 64,
            "algorithm": "power-history-step-zoh-v1",
            "components": {
                name: {"method": "power_history", "owner": "recorder"}
                for name in (
                    "import",
                    "export",
                    "pv",
                    "load",
                    "water",
                    "ev",
                    "battery_charge",
                    "battery_discharge",
                )
            },
            "soc": {"source": "live", "owner": "recorder"},
        },
    }


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
                quality_flags=trusted_flags(),
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
    rows[1] = replace(rows[1], quality_flags={**trusted_flags(), "exclude": True})
    result = fit_calibration(rows, 10.0, rows[-1].start + timedelta(minutes=15))
    assert result.status == "available"
    assert result.diagnostics is not None
    assert (
        result.diagnostics.grid_training_samples + result.diagnostics.grid_validation_samples
        == 1198
    )


def test_snapshot_fallback_is_excluded_before_the_fit_split():
    rows = recording()
    flags = trusted_flags()
    flags["recording"]["components"]["pv"]["method"] = "snapshot"
    rows[0] = replace(rows[0], quality_flags=flags)
    result = fit_calibration(rows, 10.0, rows[-1].start + timedelta(minutes=15), "a" * 64)
    assert result.status == "available"
    assert result.history is not None
    assert result.history["eligible_count"] == 1199
    assert result.history["exclusions"]["snapshot_or_mixed"] == 1


def test_unknown_legacy_rows_are_never_certified_by_a_good_fit():
    rows = [replace(row, quality_flags={"source": "recorder"}) for row in recording()]
    result = fit_calibration(rows, 10.0, rows[-1].start + timedelta(minutes=15))
    assert result.status == "insufficient_data"
    assert result.reason == "unverified_history"
    assert result.history is not None and result.history["eligible_count"] == 0


def test_explicit_legacy_attestation_makes_compatible_measured_history_eligible():
    rows = recording()
    attestation = {
        "schema_version": 1,
        "disposition": "verified_measured_energy",
        "semantics": ENERGY_SEMANTICS,
        "boundary_fingerprint": "a" * 64,
        "methods": dict.fromkeys(
            (
                "import",
                "export",
                "pv",
                "load",
                "water",
                "ev",
                "battery_charge",
                "battery_discharge",
            ),
            "cumulative_meter_energy",
        ),
        "evidence_digest": "b" * 64,
    }
    rows = [
        replace(
            row,
            quality_flags={
                "source": "recorder",
                "comparison_history": {
                    "schema_version": 1,
                    "disposition": "verified_measured_energy",
                    "evidence_digest": "b" * 64,
                },
                "legacy_attestation": {
                    **attestation,
                    "soc_method": "live_soc_history",
                    "affected_measurement_digest": observation_value_digest(row),
                },
            },
        )
        for row in rows
    ]
    result = fit_calibration(rows, 10.0, rows[-1].start + timedelta(minutes=15), "a" * 64)
    assert result.status == "available"
    assert result.history is not None
    assert result.history["cohort_id"].startswith("measured:")


def test_attested_legacy_and_observed_measured_energy_share_registered_cohort():
    rows = recording()
    methods = dict.fromkeys(
        ("import", "export", "pv", "load", "water", "ev", "battery_charge", "battery_discharge"),
        "cumulative_meter_energy",
    )
    for index, row in enumerate(rows[:600]):
        digest = "b" * 64
        flags = {
            "source": "recorder",
            "comparison_history": {
                "schema_version": 1,
                "disposition": "verified_measured_energy",
                "evidence_digest": digest,
            },
            "legacy_attestation": {
                "schema_version": 1,
                "disposition": "verified_measured_energy",
                "semantics": ENERGY_SEMANTICS,
                "boundary_fingerprint": "a" * 64,
                "methods": methods,
                "soc_method": "live_soc_history",
                "evidence_digest": digest,
                "affected_measurement_digest": observation_value_digest(row),
            },
        }
        rows[index] = replace(row, quality_flags=flags)
    rows[600] = replace(rows[600], quality_flags={**trusted_flags(), "app_version": "new-release"})
    result = fit_calibration(rows, 10.0, rows[-1].start + timedelta(minutes=15), "a" * 64)
    assert result.status == "available"
    assert result.history is not None and result.history["eligible_count"] == 1200
    assert result.history["cohort_id"].startswith("measured:")


def test_exclusion_counts_include_rows_from_an_older_incompatible_boundary():
    rows = recording()
    for index, row in enumerate(rows[-100:], start=len(rows) - 100):
        flags = trusted_flags()
        flags["recording"]["boundary_fingerprint"] = "c" * 64
        rows[index] = replace(row, quality_flags=flags)
    result = fit_calibration(rows, 10.0, rows[-1].start + timedelta(minutes=15))
    assert result.status == "insufficient_data"
    assert result.history is not None
    assert result.history["eligible_count"] == 100
    assert result.history["exclusions"]["incompatible_cohort"] == 1100
    assert result.history["considered_count"] == result.history["eligible_count"] + sum(
        result.history["exclusions"].values()
    )


def test_newest_algorithm_cohort_does_not_fall_back_to_older_supported_cohort():
    rows = recording()
    new_cohort = []
    for row in rows[-100:]:
        flags = trusted_flags()
        flags["recording"]["algorithm"] = "future-semantics-v2"
        new_cohort.append(replace(row, quality_flags=flags))
    rows[-100:] = new_cohort
    result = fit_calibration(rows, 10.0, rows[-1].start + timedelta(minutes=15), "a" * 64)
    assert result.status == "insufficient_data"
    assert result.reason == "unverified_history"
    assert result.history is not None and result.history["eligible_count"] == 0


def test_cached_soc_and_changed_sensor_boundary_are_not_current_cohort_rows():
    rows = recording()
    cached = trusted_flags()
    cached["recording"]["soc"]["source"] = "cached"
    rows[0] = replace(rows[0], quality_flags=cached)
    other_boundary = trusted_flags()
    other_boundary["recording"]["boundary_fingerprint"] = "c" * 64
    rows[1] = replace(rows[1], quality_flags=other_boundary)
    result = fit_calibration(rows, 10.0, rows[-1].start + timedelta(minutes=15), "a" * 64)
    assert result.status == "available"
    assert result.history is not None
    assert result.history["eligible_count"] == 1198
    assert result.history["exclusions"]["cached_soc"] == 1
    assert result.history["exclusions"]["boundary_mismatch"] == 1
    assert result.history["considered_count"] == result.history["eligible_count"] + sum(
        result.history["exclusions"].values()
    )


def test_estimate_accepts_only_assumed_legacy_or_supported_live_rows():
    row = recording(1)[0]
    legacy = replace(row, quality_flags='{"source":"recorder"}')
    assert estimate_row_eligible(legacy, "a" * 64)

    unsupported = trusted_flags()
    unsupported["recording"]["components"]["pv"]["method"] = "snapshot"
    assert not estimate_row_eligible(replace(row, quality_flags=unsupported), "a" * 64)

    cached = trusted_flags()
    cached["recording"]["soc"]["source"] = "cached"
    assert not estimate_row_eligible(replace(row, quality_flags=cached), "a" * 64)
    assert not estimate_row_eligible(replace(row, quality_flags={"source": "backfill"}))
    assert not estimate_row_eligible(
        replace(row, quality_flags={"source": "recorder", "recording": {"schema_version": 2}})
    )


def test_configured_estimate_returns_amounts_without_synthetic_calibration_diagnostics():
    row = replace(recording(1)[0], quality_flags='{"source":"recorder"}')
    result, reason = build_estimated_comparison(
        [row],
        50.0,
        ComparisonBattery(10.0, 10.0, 95.0, 2000.0, 2000.0),
        GridModel(1.0, 1.0),
        BatteryModel(0.95, 0.95),
        0.2,
        lambda start: start.isoformat(),
    )
    assert reason is None
    assert result is not None
    assert result["status"] == "estimated"
    assert result["basis"] == "configured_losses"
    assert "calibration" not in result
    assert result["points"]

    invalid, invalid_reason = build_estimated_comparison(
        [replace(row, import_price=float("nan"))],
        50.0,
        ComparisonBattery(10.0, 10.0, 95.0, 2000.0, 2000.0),
        GridModel(1.0, 1.0),
        BatteryModel(0.95, 0.95),
        0.2,
        lambda start: start.isoformat(),
    )
    assert invalid is None and invalid_reason == "missing_price"


@pytest.mark.parametrize(
    ("battery", "grid", "storage", "cycle_cost"),
    [
        (
            ComparisonBattery(float("nan"), 10.0, 95.0, 2000.0, 2000.0),
            GridModel(1.0, 1.0),
            BatteryModel(0.95, 0.95),
            0.2,
        ),
        (
            ComparisonBattery(10.0, 95.0, 10.0, 2000.0, 2000.0),
            GridModel(1.0, 1.0),
            BatteryModel(0.95, 0.95),
            0.2,
        ),
        (
            ComparisonBattery(10.0, 10.0, 95.0, -1.0, 2000.0),
            GridModel(1.0, 1.0),
            BatteryModel(0.95, 0.95),
            0.2,
        ),
        (
            ComparisonBattery(10.0, 10.0, 95.0, 2000.0, 2000.0),
            GridModel(float("nan"), 1.0),
            BatteryModel(0.95, 0.95),
            0.2,
        ),
        (
            ComparisonBattery(10.0, 10.0, 95.0, 2000.0, 2000.0),
            GridModel(1.0, 1.0),
            BatteryModel(1.01, 0.95),
            0.2,
        ),
        (
            ComparisonBattery(10.0, 10.0, 95.0, 2000.0, 2000.0),
            GridModel(1.0, 1.0),
            BatteryModel(0.95, 0.95),
            float("inf"),
        ),
    ],
)
def test_configured_estimate_rejects_invalid_model_configuration(
    battery: ComparisonBattery,
    grid: GridModel,
    storage: BatteryModel,
    cycle_cost: float,
):
    result, reason = build_estimated_comparison(
        [replace(recording(1)[0], quality_flags='{"source":"recorder"}')],
        50.0,
        battery,
        grid,
        storage,
        cycle_cost,
        lambda start: start.isoformat(),
    )
    assert result is None and reason == "invalid_configuration"


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
                quality_flags=trusted_flags(),
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
    row = RecordedObservation(
        start, 0.2, 0, 1, 1, 0, 0.2, 0, 0, 0, 0, None, 50, quality_flags=trusted_flags()
    )
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
        quality_flags=trusted_flags(),
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
        quality_flags=trusted_flags(),
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
        quality_flags=trusted_flags(),
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
        return RecordedObservation(
            start, 0, 0, 1, 1, 1, 0.8, 0, 0, 0, 0, 50, 50, quality_flags=trusted_flags()
        )

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
        datetime(2026, 9, 12, tzinfo=UTC),
        5.3,
        5,
        2,
        1,
        0,
        0.3,
        0,
        0,
        0,
        0,
        50,
        50,
        quality_flags=trusted_flags(),
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
        datetime(2026, 9, 12, tzinfo=UTC),
        0,
        0,
        1,
        0.5,
        pv,
        load,
        water,
        ev,
        0,
        0,
        95,
        95,
        quality_flags=trusted_flags(),
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


@pytest.mark.parametrize("field", ["boundary_fingerprint", "semantics", "algorithm"])
def test_component_and_soc_identities_cannot_borrow_the_row_summary(field):
    row = recording(1)[0]
    for target in ("pv", "soc"):
        flags = trusted_flags()
        metadata = (
            flags["recording"]["soc"]
            if target == "soc"
            else flags["recording"]["components"][target]
        )
        metadata[field] = "unsupported-identity"
        assert trusted_row_provenance(replace(row, quality_flags=flags)) is None


def test_retained_cached_start_soc_is_not_certified_by_live_end_soc():
    row = recording(1)[0]
    flags = trusted_flags()
    flags["recording"]["soc"].update(
        {
            "start": {"source": "cached", "owner": "recorder"},
            "end": {"source": "live", "owner": "recorder"},
        }
    )
    row = replace(row, quality_flags=flags)
    assert trusted_row_provenance(row) is not None
    assert not trusted_soc_endpoint(row, "start")
    assert trusted_soc_endpoint(row, "end")
    diagnostics = FitDiagnostics(
        GridModel(0.94, 0.90),
        BatteryModel(0.92, 0.94),
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
        1,
    )
    result, reason = build_comparison(
        [row],
        None,
        ComparisonBattery(10, 10, 95, 2000, 2000),
        diagnostics,
        0.2,
        lambda dt: dt.isoformat(),
    )
    assert result is None and reason == "missing_start_soc"


def test_unsupported_latest_schema_does_not_fall_back_to_old_fit():
    rows = recording()
    flags = trusted_flags()
    flags["recording"]["schema_version"] = 99
    rows[-1] = replace(rows[-1], quality_flags=flags)
    result = fit_calibration(rows, 10, rows[-1].start + timedelta(minutes=15), "a" * 64)
    assert result.status == "insufficient_data"
    assert result.history["eligible_count"] == 0
    assert result.history["considered_count"] == sum(result.history["exclusions"].values())


def test_legacy_attestation_is_invalidated_by_manual_numeric_correction():
    row = recording(1)[0]
    attestation = {
        "schema_version": 1,
        "disposition": "verified_measured_energy",
        "semantics": ENERGY_SEMANTICS,
        "boundary_fingerprint": "a" * 64,
        "methods": dict.fromkeys(
            (
                "import",
                "export",
                "pv",
                "load",
                "water",
                "ev",
                "battery_charge",
                "battery_discharge",
            ),
            "cumulative_meter_energy",
        ),
        "soc_method": "live_soc_history",
        "evidence_digest": "b" * 64,
        "affected_measurement_digest": observation_value_digest(row),
    }
    flags = {
        "source": "recorder",
        "legacy_attestation": attestation,
        "comparison_history": {
            "schema_version": 1,
            "disposition": "verified_measured_energy",
            "evidence_digest": "b" * 64,
        },
    }
    row = replace(row, quality_flags=flags)
    assert trusted_row_provenance(row) is not None
    assert trusted_row_provenance(replace(row, pv_kwh=2)) is None


def test_disabled_zeros_qualify_but_enabled_unconfigured_zeros_do_not():
    row = recording(1)[0]
    flags = trusted_flags()
    flags["recording"]["components"]["ev"]["method"] = "disabled_zero"
    assert trusted_row_provenance(replace(row, quality_flags=flags)) is not None
    flags["recording"]["components"]["ev"]["method"] = "unconfigured_zero"
    assert trusted_row_provenance(replace(row, quality_flags=flags)) is None


@pytest.mark.parametrize(
    "target,value",
    [
        ("method", []),
        ("owner", {}),
        ("algorithm", []),
        ("boundary_fingerprint", {}),
        ("schema_version", True),
    ],
)
def test_malformed_provenance_values_are_unknown_without_crashing(target, value):
    row = recording(1)[0]
    flags = trusted_flags()
    if target in {"method", "owner"}:
        flags["recording"]["components"]["pv"][target] = value
    else:
        flags["recording"][target] = value
    assert trusted_row_provenance(replace(row, quality_flags=flags)) is None
    result = fit_calibration(
        [replace(row, quality_flags=flags)], 10, row.start + timedelta(minutes=15), "a" * 64
    )
    assert result.status == "insufficient_data"


@pytest.mark.parametrize("taint", ["snapshot", "exclusion", "backfill", "cached", "unsupported"])
def test_estimate_builder_itself_rejects_known_unusable_provenance(taint):
    row = recording(1)[0]
    flags = trusted_flags()
    if taint == "snapshot":
        flags["recording"]["components"]["pv"]["method"] = "snapshot"
    elif taint == "exclusion":
        flags["comparison_history"] = {"disposition": "exclude_from_comparison"}
    elif taint == "backfill":
        flags["recording"]["components"]["battery_charge"]["owner"] = "backfill"
    elif taint == "cached":
        flags["recording"]["soc"]["source"] = "cached"
    else:
        flags["recording"]["schema_version"] = 2
    result, reason = build_estimated_comparison(
        [replace(row, quality_flags=flags)],
        50,
        ComparisonBattery(10, 10, 95, 2000, 2000),
        GridModel(1, 1),
        BatteryModel(0.95, 0.95),
        0.2,
        lambda start: start.isoformat(),
        "a" * 64,
    )
    assert result is None and reason == "unsupported_period_measurements"
