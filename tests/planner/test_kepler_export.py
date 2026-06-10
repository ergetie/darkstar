from datetime import datetime, timedelta

import pytest

from planner.solver.adapter import config_to_kepler_config
from planner.solver.kepler import KeplerSolver
from planner.solver.types import KeplerConfig, KeplerInput, KeplerInputSlot


def test_kepler_solver_export_disabled():
    # 2 slots: High export prices
    start = datetime(2025, 1, 1, 12, 0)
    slots = []

    # Create slots with massive export incentive
    for i in range(2):
        slots.append(
            KeplerInputSlot(
                start_time=start + timedelta(minutes=15 * i),
                end_time=start + timedelta(minutes=15 * (i + 1)),
                load_kwh=0.0,
                pv_kwh=0.0,
                import_price_sek_kwh=2.0,
                export_price_sek_kwh=10.0,  # Massive incentive
            )
        )

    # Full battery to start
    input_data = KeplerInput(slots=slots, initial_soc_kwh=10.0)

    config = KeplerConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=10.0,
        max_discharge_power_kw=10.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        wear_cost_sek_per_kwh=0.2,  # Non-zero to prevent degenerate free cycling
        enable_export=False,  # KEY: Disable export
    )

    solver = KeplerSolver()

    # Verification: Ensure config is correctly set to disable export
    assert config.enable_export is False

    result = solver.solve(input_data, config)

    assert result.is_optimal

    for _, s in enumerate(result.slots):
        # Should be exactly 0
        assert s.grid_export_kwh == pytest.approx(0.0, abs=0.01)
        # Should NOT discharge since there is no load and we can't export
        assert s.discharge_kwh == pytest.approx(0.0, abs=0.01)


def test_export_threshold_config_mapping():
    """
    Regression test: config_to_kepler_config() must correctly map
    export_threshold_sek_per_kwh from config to KeplerConfig.
    """
    planner_config = {
        "config_version": 2,
        "system": {
            "battery": {
                "capacity_kwh": 10.0,
                "min_soc_percent": 10.0,
                "max_soc_percent": 100.0,
                "max_charge_a": 100.0,
                "max_discharge_a": 100.0,
                "nominal_voltage_v": 48.0,
                "charge_efficiency": 0.95,
                "discharge_efficiency": 0.95,
            },
            "grid": {"max_power_kw": 11.0},
        },
        "export_threshold_sek_per_kwh": 0.25,
        "battery_economics": {"battery_cycle_cost_kwh": 0.10},
        "executor": {"inverter": {"control_unit": "A"}},
    }

    kepler_cfg = config_to_kepler_config(planner_config)

    assert kepler_cfg.export_threshold_sek_per_kwh == pytest.approx(0.25), (
        f"export_threshold_sek_per_kwh should be 0.25, got "
        f"{kepler_cfg.export_threshold_sek_per_kwh}"
    )


def test_export_threshold_prevents_unprofitable_export():
    """
    Regression test: High export threshold should prevent marginal exports.

    Scenario: Export price is 0.50 SEK/kWh, but threshold is 0.60 SEK/kWh.
    Expected: No export because adjusted profit is negative.
    """
    start = datetime(2025, 1, 1, 12, 0)
    slots = [
        KeplerInputSlot(
            start_time=start,
            end_time=start + timedelta(minutes=15),
            load_kwh=0.0,
            pv_kwh=0.0,
            import_price_sek_kwh=1.0,
            export_price_sek_kwh=0.50,  # Export at 0.50 SEK
        )
    ]

    input_data = KeplerInput(slots=slots, initial_soc_kwh=5.0)

    # Threshold higher than export price -> should not export
    config = KeplerConfig(
        capacity_kwh=10.0,
        min_soc_percent=0,
        max_soc_percent=100,
        max_charge_power_kw=10,
        max_discharge_power_kw=10,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        export_threshold_sek_per_kwh=0.60,  # Higher than 0.50 export price
    )

    result = KeplerSolver().solve(input_data, config)
    assert result.is_optimal

    # Should NOT export because effective price = 0.50 - 0.60 = -0.10 < 0
    assert result.slots[0].grid_export_kwh == pytest.approx(0.0, abs=0.01), (
        f"Should not export when threshold ({config.export_threshold_sek_per_kwh}) "
        f"> export price ({slots[0].export_price_sek_kwh}). "
        f"Exported: {result.slots[0].grid_export_kwh} kWh"
    )


def test_reported_cost_uses_effective_export_price():
    """
    total_cost_sek must use (export_price − threshold) for export revenue,
    matching what the optimizer actually minimised.
    With threshold=0 the reported cost is unchanged; with threshold>0 it is higher
    (less revenue credited) while the schedule is identical.
    """
    start = datetime(2025, 1, 1, 12, 0)
    slots = [
        KeplerInputSlot(
            start_time=start + timedelta(minutes=15 * i),
            end_time=start + timedelta(minutes=15 * (i + 1)),
            load_kwh=0.0,
            pv_kwh=0.0,
            import_price_sek_kwh=3.0,
            export_price_sek_kwh=1.0,
        )
        for i in range(2)
    ]

    base_config = KeplerConfig(
        capacity_kwh=10.0,
        min_soc_percent=0,
        max_soc_percent=100,
        max_charge_power_kw=10,
        max_discharge_power_kw=10,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        export_threshold_sek_per_kwh=0.0,
    )
    threshold_config = KeplerConfig(
        capacity_kwh=10.0,
        min_soc_percent=0,
        max_soc_percent=100,
        max_charge_power_kw=10,
        max_discharge_power_kw=10,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        export_threshold_sek_per_kwh=0.3,
    )

    input_data = KeplerInput(slots=slots, initial_soc_kwh=5.0)

    result_base = KeplerSolver().solve(input_data, base_config)
    result_threshold = KeplerSolver().solve(input_data, threshold_config)

    assert result_base.is_optimal
    assert result_threshold.is_optimal

    # Both solvers should produce the same export schedule
    for s_base, s_thresh in zip(result_base.slots, result_threshold.slots):
        assert s_base.grid_export_kwh == pytest.approx(s_thresh.grid_export_kwh, abs=0.01)

    total_export = sum(s.grid_export_kwh for s in result_base.slots)

    # With threshold=0 the reported cost equals raw-price cost (unchanged)
    # With threshold=0.3 the reported cost = base_cost + threshold * total_export
    assert result_threshold.total_cost_sek == pytest.approx(
        result_base.total_cost_sek + 0.3 * total_export, abs=1e-4
    ), (
        f"Expected cost with threshold to be higher by {0.3 * total_export:.4f} SEK; "
        f"base={result_base.total_cost_sek:.4f}, threshold={result_threshold.total_cost_sek:.4f}"
    )
