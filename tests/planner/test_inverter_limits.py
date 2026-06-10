"""Tests for inverter power limit constraints."""

from datetime import datetime, timedelta

from planner.solver.kepler import KeplerSolver
from planner.solver.types import KeplerConfig, KeplerInput, KeplerInputSlot


def test_inverter_ac_limit_caps_discharge_with_pv():
    """
    Test that when max_inverter_ac_kw=10.0 is set, high PV + battery discharge is capped.

    Scenario: 2-slot scenario with pv_kwh=2.0 (8kW average in 15min), full battery,
    high export price. Without constraint, planner would discharge full battery + export PV.
    With constraint, discharge + pv_kwh <= 2.5 per slot (10kW * 0.25h).
    """
    start = datetime(2025, 1, 1, 12, 0)
    slots = []

    # Create 2 slots with high PV (8kW average = 2kWh per 15min slot)
    for i in range(2):
        slots.append(
            KeplerInputSlot(
                start_time=start + timedelta(minutes=15 * i),
                end_time=start + timedelta(minutes=15 * (i + 1)),
                load_kwh=0.0,  # No load
                pv_kwh=2.0,  # 8kW average
                import_price_sek_kwh=0.5,
                export_price_sek_kwh=2.0,  # High export price
            )
        )

    # Full battery
    input_data = KeplerInput(slots=slots, initial_soc_kwh=10.0)

    config = KeplerConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=10.0,
        max_discharge_power_kw=10.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        wear_cost_sek_per_kwh=0.1,
        max_inverter_ac_kw=10.0,  # 10kW AC limit
        max_export_power_kw=20.0,  # High export limit so inverter limit is the constraint
        enable_export=True,
    )

    solver = KeplerSolver()
    result = solver.solve(input_data, config)

    assert result.is_optimal

    # Each slot: discharge + pv_kwh should be <= 2.5 (10kW * 0.25h)
    # PV is 2.0 kWh per slot (constant from input)
    for i, s in enumerate(result.slots):
        pv_kwh = input_data.slots[i].pv_kwh  # Get PV from input slot
        total_ac_output = s.discharge_kwh + pv_kwh
        assert total_ac_output <= 2.5 + 0.01, (
            f"Inverter AC output {total_ac_output} exceeds limit 2.5 kWh "
            f"({config.max_inverter_ac_kw}kW * 0.25h)"
        )


def test_inverter_ac_limit_none_allows_unconstrained_export():
    """
    Test that when max_inverter_ac_kw is None, behavior is unchanged (no constraint applied).

    Same scenario as test_inverter_ac_limit_caps_discharge_with_pv but without AC limit.
    Discharge should be unconstrained by inverter.
    """
    start = datetime(2025, 1, 1, 12, 0)
    slots = []

    # Create 2 slots with high PV (8kW average = 2kWh per 15min slot)
    for i in range(2):
        slots.append(
            KeplerInputSlot(
                start_time=start + timedelta(minutes=15 * i),
                end_time=start + timedelta(minutes=15 * (i + 1)),
                load_kwh=0.0,  # No load
                pv_kwh=2.0,  # 8kW average
                import_price_sek_kwh=0.5,
                export_price_sek_kwh=2.0,  # High export price
            )
        )

    # Full battery
    input_data = KeplerInput(slots=slots, initial_soc_kwh=10.0)

    config = KeplerConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=10.0,
        max_discharge_power_kw=10.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        wear_cost_sek_per_kwh=0.1,
        max_inverter_ac_kw=None,  # No AC limit
        max_export_power_kw=20.0,  # Export limit to keep problem bounded
        enable_export=True,
    )

    solver = KeplerSolver()
    result = solver.solve(input_data, config)

    assert result.is_optimal

    # Without inverter limit, we should be able to export more
    # Total possible export per slot: 2kWh PV + up to 2.5kWh discharge = 4.5kWh
    # But grid export limit might still apply (none set in this config)
    total_exported = sum(s.grid_export_kwh for s in result.slots)

    # Should be able to export significantly more than 2.5kWh per slot (which would be the limit with 10kW AC cap)
    # With 10kW discharge power and 8kW PV, we could export up to 4.5kWh per slot = 9kWh total
    assert total_exported > 5.0, (
        f"Expected significant export without inverter limit, got {total_exported} kWh"
    )


def test_inverter_ac_limit_respected_at_night():
    """
    Test that at night (no PV), full AC capacity is available for battery discharge.
    """
    start = datetime(2025, 1, 1, 0, 0)  # Midnight
    slots = []

    # Create 2 nighttime slots with no PV
    for i in range(2):
        slots.append(
            KeplerInputSlot(
                start_time=start + timedelta(minutes=15 * i),
                end_time=start + timedelta(minutes=15 * (i + 1)),
                load_kwh=0.0,
                pv_kwh=0.0,  # No sun at night
                import_price_sek_kwh=0.5,
                export_price_sek_kwh=2.0,  # High export price
            )
        )

    # Full battery
    input_data = KeplerInput(slots=slots, initial_soc_kwh=10.0)

    config = KeplerConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=10.0,
        max_discharge_power_kw=10.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        wear_cost_sek_per_kwh=0.1,
        max_inverter_ac_kw=10.0,  # 10kW AC limit
        max_export_power_kw=20.0,  # Export limit to keep problem bounded
        enable_export=True,
    )

    solver = KeplerSolver()
    result = solver.solve(input_data, config)

    assert result.is_optimal

    # At night with no PV, we can discharge up to full inverter capacity
    for s in result.slots:
        # Should be able to discharge up to 2.5 kWh (10kW * 0.25h)
        assert s.discharge_kwh <= 2.5 + 0.01
        # Since export is profitable, should discharge significantly
        assert s.discharge_kwh > 1.0, "Should discharge at night when export is profitable"


def test_dc_coupled_pv_above_inverter_limit_routes_surplus_to_battery():
    """dc_coupled: PV surplus above AC limit routes to battery, not curtailment/infeasibility."""
    start = datetime(2025, 6, 1, 12, 0)
    slots = [
        KeplerInputSlot(
            start_time=start + timedelta(minutes=15 * i),
            end_time=start + timedelta(minutes=15 * (i + 1)),
            load_kwh=0.0,
            pv_kwh=2.1177,  # > inverter_ac_kwh=2.0
            import_price_sek_kwh=1.0,
            export_price_sek_kwh=0.4,
        )
        for i in range(4)
    ]
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
        max_inverter_ac_kw=8.0,  # 8kW * 0.25h = 2.0 kWh/slot
        inverter_topology="dc_coupled",
        # curtailment penalty > wear cost → solver prefers routing surplus to battery
        curtailment_penalty_sek=0.5,
        enable_export=True,
    )
    result = KeplerSolver().solve(input_data, config)

    assert result.is_optimal
    # Surplus 0.1177 kWh/slot should be absorbed by battery rather than curtailed
    total_charge = sum(s.charge_kwh for s in result.slots)
    assert total_charge > 0.3, (
        f"dc_coupled: expected battery to absorb PV surplus, got {total_charge} kWh total charge"
    )


def test_dc_coupled_pv_to_ac_independently_capped():
    """dc_coupled: PV-to-AC (load+export) is independently capped at inverter limit."""
    start = datetime(2025, 6, 1, 12, 0)
    slots = [
        KeplerInputSlot(
            start_time=start + timedelta(minutes=15 * i),
            end_time=start + timedelta(minutes=15 * (i + 1)),
            load_kwh=0.0,
            pv_kwh=3.0,  # well above inverter_ac_kwh=2.0
            import_price_sek_kwh=5.0,  # high import cost prevents arbitrage
            export_price_sek_kwh=0.5,
        )
        for i in range(2)
    ]
    input_data = KeplerInput(slots=slots, initial_soc_kwh=0.0)  # empty battery, room to absorb
    config = KeplerConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        wear_cost_sek_per_kwh=0.01,
        max_inverter_ac_kw=8.0,  # 8kW * 0.25h = 2.0 kWh/slot
        inverter_topology="dc_coupled",
        curtailment_penalty_sek=0.5,  # incentivise battery over curtailment
        enable_export=True,
    )
    result = KeplerSolver().solve(input_data, config)

    assert result.is_optimal
    inverter_ac_kwh = 2.0
    for i, s in enumerate(result.slots):
        # No load, no import (high import cost) → grid_export = pv_to_ac + discharge <= 2.0
        assert s.grid_export_kwh <= inverter_ac_kwh + 0.01, (
            f"Slot {i}: grid_export {s.grid_export_kwh:.3f} exceeds AC limit {inverter_ac_kwh}"
        )
    # Battery absorbs excess (3.0 - 2.0 = 1.0 kWh/slot routes to battery via DC path)
    total_charge = sum(s.charge_kwh for s in result.slots)
    assert total_charge > 0.5


def test_ac_coupled_battery_counts_against_ac_limit():
    """ac_coupled: combined PV output + discharge is bounded by the inverter AC limit."""
    start = datetime(2025, 6, 1, 12, 0)
    slots = [
        KeplerInputSlot(
            start_time=start + timedelta(minutes=15 * i),
            end_time=start + timedelta(minutes=15 * (i + 1)),
            load_kwh=0.0,
            pv_kwh=1.5,  # PV=1.5 kWh, inverter_ac=2.0 kWh → discharge headroom is 0.5
            import_price_sek_kwh=5.0,  # high import cost prevents arbitrage inflating export
            export_price_sek_kwh=2.0,
        )
        for i in range(2)
    ]
    input_data = KeplerInput(slots=slots, initial_soc_kwh=10.0)  # full battery
    config = KeplerConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=10.0,
        max_discharge_power_kw=10.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        wear_cost_sek_per_kwh=0.1,
        max_inverter_ac_kw=8.0,  # 8kW * 0.25h = 2.0 kWh/slot
        inverter_topology="ac_coupled",
        enable_export=True,
    )
    result = KeplerSolver().solve(input_data, config)

    assert result.is_optimal
    # ac_coupled: (pv_to_ac + pv_to_battery) + discharge <= 2.0
    # Battery is full → pv_to_battery=0, pv_to_ac=1.5 → discharge <= 0.5
    for i, s in enumerate(result.slots):
        assert s.discharge_kwh <= 0.5 + 0.01, (
            f"Slot {i}: ac_coupled discharge {s.discharge_kwh:.3f} exceeds 0.5 kWh cap"
        )


def test_unset_inverter_limit_no_ac_constraint():
    """When max_inverter_ac_kw is None, no AC constraint is applied (PV routing vars omitted)."""
    start = datetime(2025, 6, 1, 12, 0)
    slots = [
        KeplerInputSlot(
            start_time=start + timedelta(minutes=15 * i),
            end_time=start + timedelta(minutes=15 * (i + 1)),
            load_kwh=0.0,
            pv_kwh=3.0,  # High PV — should not be constrained
            import_price_sek_kwh=1.0,
            export_price_sek_kwh=2.0,
        )
        for i in range(2)
    ]
    input_data = KeplerInput(slots=slots, initial_soc_kwh=10.0)  # full battery
    config = KeplerConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=10.0,
        max_discharge_power_kw=10.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        wear_cost_sek_per_kwh=0.1,
        max_inverter_ac_kw=None,  # no AC limit
        enable_export=True,
        max_export_power_kw=20.0,
    )
    result = KeplerSolver().solve(input_data, config)

    assert result.is_optimal
    # Without an AC limit, PV + discharge is unconstrained; grid_export can exceed any per-slot cap
    total_export = sum(s.grid_export_kwh for s in result.slots)
    # Full battery + high export price → should export significantly (PV + discharge)
    assert total_export > 5.0, (
        f"Expected unconstrained export > 5.0 kWh, got {total_export}"
    )
