import pytest
from datetime import datetime, timedelta
from backend.kepler.types import KeplerConfig, KeplerInputSlot, KeplerInput
from backend.kepler.solver import KeplerSolver


def test_export_threshold():
    # Scenario: Battery has energy. Export price is good, but below threshold.
    start = datetime(2025, 1, 1, 12, 0)
    slots = [
        KeplerInputSlot(
            start_time=start,
            end_time=start + timedelta(minutes=15),
            load_kwh=0.0,
            pv_kwh=0.0,
            import_price_sek_kwh=2.0,
            export_price_sek_kwh=1.0,  # Good price!
        )
    ]

    input_data = KeplerInput(slots=slots, initial_soc_kwh=5.0)  # Full battery

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
        export_threshold_sek_per_kwh=0.1,  # 1.0 - 0.1 = 0.9 profit
    )

    solver = KeplerSolver()
    result_low = solver.solve(input_data, config_low)
    assert result_low.slots[0].grid_export_kwh > 0.1

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
        export_threshold_sek_per_kwh=1.5,  # 1.0 - 1.5 = -0.5 profit (Loss)
    )

    result_high = solver.solve(input_data, config_high)
    assert result_high.slots[0].grid_export_kwh == pytest.approx(0.0)


def test_ramping_cost():
    # Scenario: Price flip-flop.
    # S1: Charge (Cheap)
    # S2: Discharge (Expensive)
    # S3: Charge (Cheap)
    # This creates a "Sawtooth": +Power, -Power, +Power.
    # Delta 1: (+P) - (0) = P
    # Delta 2: (-P) - (+P) = -2P (Huge penalty!)
    # Delta 3: (+P) - (-P) = +2P (Huge penalty!)

    start = datetime(2025, 1, 1, 12, 0)
    slots = []
    prices = [0.1, 10.0, 0.1, 10.0]  # Extreme spread to force action
    # S1: Charge (Cheap) -> S2: Discharge (Expensive)
    # S3: Charge (Cheap) -> S4: Discharge (Expensive)

    for i, p in enumerate(prices):
        slots.append(
            KeplerInputSlot(
                start_time=start + timedelta(minutes=15 * i),
                end_time=start + timedelta(minutes=15 * (i + 1)),
                load_kwh=0.0,
                pv_kwh=0.0,
                import_price_sek_kwh=p,
                export_price_sek_kwh=p,
            )
        )

    input_data = KeplerInput(slots=slots, initial_soc_kwh=0.0)

    # Case 1: No Ramping Cost -> Sawtooth
    config_no_ramp = KeplerConfig(
        capacity_kwh=10.0,
        min_soc_percent=0,
        max_soc_percent=100,
        max_charge_power_kw=4.0,
        max_discharge_power_kw=4.0,  # 1 kWh per slot
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        ramping_cost_sek_per_kw=0.0,
    )

    solver = KeplerSolver()
    res_no = solver.solve(input_data, config_no_ramp)

    # Should Charge S1, Discharge S2, Charge S3
    assert res_no.slots[0].charge_kwh > 0.9
    assert res_no.slots[1].discharge_kwh > 0.9
    assert res_no.slots[2].charge_kwh > 0.9

    # Case 2: Extreme Ramping Cost -> Flatline
    # Profit from S2 discharge = 1 kWh * 10 SEK = 10 SEK.
    # Cost of Ramping:
    # S1: 0 -> +4 kW. Delta=4. Cost = 4 * R
    # S2: +4 -> -4 kW. Delta=8. Cost = 8 * R
    # S3: -4 -> +4 kW. Delta=8. Cost = 8 * R
    # Total Ramp Cost = 20 * R.
    # If 20*R > 10 SEK, it shouldn't do it. R > 0.5.

    config_ramp = KeplerConfig(
        capacity_kwh=10.0,
        min_soc_percent=0,
        max_soc_percent=100,
        max_charge_power_kw=4.0,
        max_discharge_power_kw=4.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        ramping_cost_sek_per_kw=10.0,  # Huge cost
    )

    res_ramp = solver.solve(input_data, config_ramp)

    # Should NOT Discharge S2 because the ramping penalty is too high
    # It might still Charge S1 and Hold, or Charge S3.
    # But the flip-flop S1->S2->S3 is killed.

    # Check that we don't have the extreme flip-flop
    # S2 discharge should be 0
    assert res_ramp.slots[1].discharge_kwh == pytest.approx(0.0)
