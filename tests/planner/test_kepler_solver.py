from datetime import datetime, timedelta

import pytest

from planner.solver.kepler import KeplerSolver
from planner.solver.types import (
    EVChargerInput,
    KeplerConfig,
    KeplerInput,
    KeplerInputSlot,
)


def test_kepler_solver_basic():
    # Create a simple 2-slot scenario
    start = datetime(2025, 1, 1, 12, 0)
    slots = []
    for i in range(2):
        s = start + timedelta(minutes=15 * i)
        e = s + timedelta(minutes=15)
        slots.append(
            KeplerInputSlot(
                start_time=s,
                end_time=e,
                load_kwh=1.0,  # 1 kWh load
                pv_kwh=0.0,
                import_price_sek_kwh=1.0,  # Expensive import
                export_price_sek_kwh=0.0,  # Worthless export
            )
        )

    # Initial battery: 5 kWh (50% of 10kWh)
    input_data = KeplerInput(slots=slots, initial_soc_kwh=5.0)

    config = KeplerConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        wear_cost_sek_per_kwh=0.01,  # Small wear cost to prevent free dumping
        target_soc_kwh=0.0,  # Allow depletion
    )

    solver = KeplerSolver()
    result = solver.solve(input_data, config)

    assert result.is_optimal
    assert len(result.slots) == 2

    # Check that it discharged to cover load (since import is expensive)
    # Total load = 2 kWh. Initial battery = 5 kWh.
    # Should discharge 2 kWh.
    total_discharge = sum(s.discharge_kwh for s in result.slots)
    total_import = sum(s.grid_import_kwh for s in result.slots)

    print(f"Total Discharge: {total_discharge}")
    print(f"Total Import: {total_import}")

    assert total_discharge == pytest.approx(2.0, abs=0.01)

    # Check that import is 0
    assert total_import == pytest.approx(0.0, abs=0.01)


def test_kepler_solver_arbitrage():
    # 2 slots: Cheap import, then Expensive export
    start = datetime(2025, 1, 1, 12, 0)
    slots = []

    # Slot 0: Cheap import (0.1 SEK), High export (0.05 SEK) - Charge
    slots.append(
        KeplerInputSlot(
            start_time=start,
            end_time=start + timedelta(minutes=15),
            load_kwh=0.0,
            pv_kwh=0.0,
            import_price_sek_kwh=0.1,
            export_price_sek_kwh=0.05,
        )
    )

    # Slot 1: Expensive import (2.0 SEK), High export (1.5 SEK) - Discharge/Export
    slots.append(
        KeplerInputSlot(
            start_time=start + timedelta(minutes=15),
            end_time=start + timedelta(minutes=30),
            load_kwh=0.0,
            pv_kwh=0.0,
            import_price_sek_kwh=2.0,
            export_price_sek_kwh=1.5,
        )
    )

    input_data = KeplerInput(slots=slots, initial_soc_kwh=0.0)  # Empty battery

    config = KeplerConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=4.0,  # 1 kWh per 15 min
        max_discharge_power_kw=4.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        wear_cost_sek_per_kwh=0.0,
    )

    solver = KeplerSolver()
    result = solver.solve(input_data, config)

    assert result.is_optimal

    # Slot 0: Should charge max (1 kWh)
    assert result.slots[0].charge_kwh == pytest.approx(1.0, abs=0.01)


def test_kepler_ev_solar_charging():
    # Scenario: High PV, High Grid Prices. EV should charge from PV (REV F51).
    # Uses incentive buckets instead of target_soc_percent and penalty
    start = datetime(2025, 1, 1, 12, 0)
    slots = []
    # 1 hour (4 slots)
    for i in range(4):
        slots.append(
            KeplerInputSlot(
                start_time=start + timedelta(minutes=15 * i),
                end_time=start + timedelta(minutes=15 * (i + 1)),
                load_kwh=1.0,  # 1kWh load
                pv_kwh=10.0,  # 10kWh PV (very sunny)
                import_price_sek_kwh=5.0,  # Very expensive grid
                export_price_sek_kwh=0.0,  # No export value
            )
        )

    input_data = KeplerInput(slots=slots, initial_soc_kwh=5.0)

    config = KeplerConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        wear_cost_sek_per_kwh=0.01,
        curtailment_penalty_sek=1.0,  # Encourage using solar
        max_export_power_kw=0.0,  # Force solar into battery/EV
        enable_export=False,
        # EV Settings: soft target to add 10 kWh before the end of the horizon
        ev_chargers=[
            EVChargerInput(
                id="test_ev",
                max_power_kw=10.0,  # 2.5kWh per slot
                battery_capacity_kwh=100.0,
                current_soc_percent=50.0,
                plugged_in=True,
                deadline=slots[-1].end_time,
                required_kwh=10.0,
            )
        ],
    )

    solver = KeplerSolver()
    result = solver.solve(input_data, config)

    assert result.is_optimal

    # Total PV = 40kWh. Total Load = 4kWh. Need 10kWh for EV.
    # Total charge into car should be 10kWh.
    total_ev_charge = sum(s.ev_charge_kw * 0.25 for s in result.slots)
    assert total_ev_charge == pytest.approx(10.0, abs=0.1)

    # Grid import should be 0 because we have plenty of solar
    total_import = sum(s.grid_import_kwh for s in result.slots)
    assert total_import == pytest.approx(0.0, abs=0.01)

    # Battery should be charging from solar too
    assert result.slots[0].soc_kwh > 5.0


def test_kepler_ev_no_battery_drain():
    # Scenario: Zero PV, High Grid Prices, Battery Full.
    # EV should NOT charge from battery even if target is not met (REV F51).
    # Uses high incentive bucket (80%+) to discourage charging.
    start = datetime(2025, 1, 1, 12, 0)
    slots = []
    for i in range(4):
        slots.append(
            KeplerInputSlot(
                start_time=start + timedelta(minutes=15 * i),
                end_time=start + timedelta(minutes=15 * (i + 1)),
                load_kwh=0.0,
                pv_kwh=0.0,
                import_price_sek_kwh=10.0,  # Extremely expensive
                export_price_sek_kwh=0.0,  # No incentive to export
            )
        )

    # Battery is full
    input_data = KeplerInput(slots=slots, initial_soc_kwh=10.0)

    config = KeplerConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        target_soc_kwh=10.0,  # Want to keep battery full!
        # EV Settings: no charging goal, so the solver must not charge from grid/battery
        ev_chargers=[
            EVChargerInput(
                id="test_ev",
                max_power_kw=10.0,
                battery_capacity_kwh=100.0,
                current_soc_percent=10.0,
                plugged_in=True,
                deadline=None,
                required_kwh=0.0,
            )
        ],
        wear_cost_sek_per_kwh=0.01,
    )

    solver = KeplerSolver()
    result = solver.solve(input_data, config)

    assert result.is_optimal

    # REV F51: EV should NOT charge when penalty (-10 SEK/kWh) makes it uneconomic
    # compared to grid price (10 SEK/kWh) and limited solar.
    # EV cannot charge from battery because it's full (100%) and grid is too expensive.
    for s in result.slots:
        # EV should not charge when grid is expensive and penalty is applied
        assert s.ev_charge_kw == pytest.approx(0.0, abs=0.01), (
            f"EV should not charge when penalty is applied and grid is expensive. "
            f"Got ev_charge_kw={s.ev_charge_kw}"
        )

    # And total discharge cannot be more than load (0 in this case)
    total_discharge = sum(s.discharge_kwh for s in result.slots)
    assert total_discharge == pytest.approx(0.0, abs=0.01)


def test_kepler_ev_blocks_discharge():
    """Verify solver cannot plan discharge and EV charging in the same slot.

    Scenario: Battery is full, house has load, grid is cheap (good for EV charging),
    and there's a high export price (making discharge attractive). The solver must
    NOT discharge and charge EV in the same slot.
    """
    start = datetime(2025, 1, 1, 12, 0)
    slots = []
    for i in range(4):
        slots.append(
            KeplerInputSlot(
                start_time=start + timedelta(minutes=15 * i),
                end_time=start + timedelta(minutes=15 * (i + 1)),
                load_kwh=0.5,  # Some house load
                pv_kwh=0.0,  # No solar
                import_price_sek_kwh=0.5,  # Cheap grid (good for EV)
                export_price_sek_kwh=3.0,  # High export price (tempting discharge)
            )
        )

    input_data = KeplerInput(slots=slots, initial_soc_kwh=10.0)

    config = KeplerConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        target_soc_kwh=0.0,  # No target - free to discharge
        wear_cost_sek_per_kwh=0.01,
        enable_export=True,
        max_export_power_kw=5.0,
        # EV Settings: small battery with a 0.5 kWh soft target, fills in ~1 slot,
        # leaving remaining slots free to discharge for export (3 SEK/kWh)
        ev_chargers=[
            EVChargerInput(
                id="test_ev",
                max_power_kw=2.0,
                battery_capacity_kwh=1.0,  # Small: 50% target = 0.5 kWh, fills in ~1 slot
                current_soc_percent=0.0,
                plugged_in=True,
                deadline=slots[-1].end_time,
                required_kwh=0.5,
            )
        ],
    )

    solver = KeplerSolver()
    result = solver.solve(input_data, config)

    assert result.is_optimal

    for s in result.slots:
        if s.ev_charge_kw > 0.1:
            # In any slot where EV is charging, discharge MUST be zero
            assert s.discharge_kwh == pytest.approx(0.0, abs=0.01), (
                f"Discharge must be 0 when EV is charging! "
                f"Got discharge={s.discharge_kwh}, ev_charge={s.ev_charge_kw}"
            )

    # Verify constraint is non-binding when EV is not charging.
    # Once the 0.5 kWh incentive bucket is full, remaining slots have no EV reward;
    # export at 3 SEK/kWh beats wear cost (0.01 SEK/kWh), so the solver WILL discharge.
    non_ev_slots = [s for s in result.slots if s.ev_charge_kw <= 0.1]
    assert len(non_ev_slots) > 0, "Expected some slots without EV charging after bucket fills"
    total_non_ev_discharge = sum(s.discharge_kwh for s in non_ev_slots)
    assert total_non_ev_discharge > 0.0, (
        "Solver should discharge for export in non-EV slots when export price (3 SEK/kWh) "
        f"exceeds wear cost — got total discharge in non-EV slots={total_non_ev_discharge}"
    )


def test_kepler_ev_load_pressure_mutual_exclusion():
    """Verify mutual exclusion is symmetric: discharge slots must also have zero EV charging.

    Scenario: Battery is partially charged, house load is high (driving discharge to serve
    load), grid import is expensive, and EV is plugged in with a small incentive. The solver
    must never discharge and charge EV in the same slot, from either direction.
    """
    start = datetime(2025, 1, 1, 12, 0)
    slots = []
    for i in range(4):
        slots.append(
            KeplerInputSlot(
                start_time=start + timedelta(minutes=15 * i),
                end_time=start + timedelta(minutes=15 * (i + 1)),
                load_kwh=0.8,  # High house load driving discharge
                pv_kwh=0.0,
                import_price_sek_kwh=2.0,  # Expensive grid (discharge saves money)
                export_price_sek_kwh=1.5,  # Profitable export too
            )
        )

    input_data = KeplerInput(slots=slots, initial_soc_kwh=5.0)

    config = KeplerConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        target_soc_kwh=0.0,
        wear_cost_sek_per_kwh=0.01,
        enable_export=True,
        max_export_power_kw=5.0,
        ev_chargers=[
            EVChargerInput(
                id="test_ev",
                max_power_kw=5.0,
                battery_capacity_kwh=100.0,
                current_soc_percent=0.0,
                plugged_in=True,
                deadline=slots[-1].end_time,
                required_kwh=20.0,
            )
        ],
    )

    solver = KeplerSolver()
    result = solver.solve(input_data, config)

    assert result.is_optimal

    for s in result.slots:
        # Full mutual exclusion: both directions
        assert not (s.ev_charge_kw > 0.1 and s.discharge_kwh > 0.01), (
            f"Discharge and EV charging must never co-occur in the same slot! "
            f"Got discharge={s.discharge_kwh:.3f} kWh, ev_charge={s.ev_charge_kw:.3f} kW"
        )


def test_export_threshold_k5():
    """Verify export threshold logic prevents uneconomic exports (REV K5)."""
    from planner.solver.types import KeplerConfig, KeplerInput, KeplerInputSlot

    start = datetime(2025, 1, 1, 12, 0)
    slots = [
        KeplerInputSlot(
            start_time=start,
            end_time=start + timedelta(minutes=15),
            load_kwh=0.0,
            pv_kwh=0.0,
            import_price_sek_kwh=2.0,
            export_price_sek_kwh=1.0,
        )
    ]
    input_data = KeplerInput(slots=slots, initial_soc_kwh=5.0)

    # Case 1: Low Threshold -> Should Export
    config_low = KeplerConfig(
        capacity_kwh=10.0,
        min_soc_percent=0,
        max_soc_percent=100,
        max_charge_power_kw=10,
        max_discharge_power_kw=10,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        export_threshold_sek_per_kwh=0.1,
    )
    res_low = KeplerSolver().solve(input_data, config_low)
    assert res_low.slots[0].grid_export_kwh > 0.1

    # Case 2: High Threshold -> Should NOT Export
    config_high = KeplerConfig(
        capacity_kwh=10.0,
        min_soc_percent=0,
        max_soc_percent=100,
        max_charge_power_kw=10,
        max_discharge_power_kw=10,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        export_threshold_sek_per_kwh=1.5,
    )
    res_high = KeplerSolver().solve(input_data, config_high)
    assert res_high.slots[0].grid_export_kwh == pytest.approx(0.0)


def test_ramping_cost_k5():
    """Verify ramping cost prevents excessive flip-flopping (REV K5)."""
    from planner.solver.types import KeplerConfig, KeplerInput, KeplerInputSlot

    start = datetime(2025, 1, 1, 12, 0)
    prices = [0.1, 10.0, 0.1, 10.0]
    slots = [
        KeplerInputSlot(
            start_time=start + timedelta(minutes=15 * i),
            end_time=start + timedelta(minutes=15 * (i + 1)),
            load_kwh=0.0,
            pv_kwh=0.0,
            import_price_sek_kwh=p,
            export_price_sek_kwh=p,
        )
        for i, p in enumerate(prices)
    ]
    input_data = KeplerInput(slots=slots, initial_soc_kwh=0.0)
    config_ramp = KeplerConfig(
        capacity_kwh=10.0,
        min_soc_percent=0,
        max_soc_percent=100,
        max_charge_power_kw=4.0,
        max_discharge_power_kw=4.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        ramping_cost_sek_per_kw=10.0,
    )
    res_ramp = KeplerSolver().solve(input_data, config_ramp)
    # S2 discharge should be suppressed by ramping penalty
    assert res_ramp.slots[1].discharge_kwh == pytest.approx(0.0)


def test_no_force_dumping_with_target_soc():
    """
    Regression test: Solver should NOT export battery energy at zero/negative
    prices to reduce end-of-horizon SoC to the target (Safety Floor).

    Scenario: Battery starts full, target_soc is set low (Safety Floor),
    export price is zero. The solver should keep the energy in the battery,
    not discharge it to zero to hit the target.
    """
    start = datetime(2025, 1, 1, 12, 0)
    slots = []
    # 4 slots (1 hour) with zero export price and minimal load
    for i in range(4):
        slots.append(
            KeplerInputSlot(
                start_time=start + timedelta(minutes=15 * i),
                end_time=start + timedelta(minutes=15 * (i + 1)),
                load_kwh=0.1,  # Tiny load to make the problem feasible
                pv_kwh=0.0,  # No solar
                import_price_sek_kwh=1.0,  # Import is expensive
                export_price_sek_kwh=0.0,  # Zero export price
            )
        )

    # Battery starts full (10 kWh), capacity 10 kWh
    # Target SoC = 2 kWh (20%) - Safety Floor
    # With the old bidirectional penalty, solver would dump 8 kWh to reach 2 kWh
    # With the fix, solver should keep energy and maybe discharge slowly for the load
    input_data = KeplerInput(slots=slots, initial_soc_kwh=10.0)

    config = KeplerConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=10.0,
        max_discharge_power_kw=10.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        wear_cost_sek_per_kwh=0.01,
        target_soc_kwh=2.0,  # Safety Floor at 2 kWh (20%)
        target_soc_penalty_sek=200.0,  # High penalty for being UNDER target
        curtailment_penalty_sek=0.1,
    )

    solver = KeplerSolver()
    result = solver.solve(input_data, config)

    assert result.is_optimal

    # Ending SoC should be well above target (>2 kWh)
    # It might discharge slightly for the 0.1 kWh load per slot (0.4 kWh total)
    final_soc = result.slots[-1].soc_kwh
    assert final_soc >= 9.0, (
        f"Should NOT discharge battery to hit target. "
        f"Final SoC: {final_soc}, target: {config.target_soc_kwh}"
    )

    # Should NOT export to zero-price grid
    total_export = sum(s.grid_export_kwh for s in result.slots)
    assert total_export == pytest.approx(0.0, abs=0.01), (
        f"Should NOT export energy at zero price. Total export: {total_export} kWh"
    )
