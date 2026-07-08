import sys
from datetime import datetime
from pathlib import Path

# Add current directory to path
sys.path.append(str(Path.cwd()))

from planner.solver.kepler import KeplerSolver
from planner.solver.types import (
    EVChargerInput,
    KeplerConfig,
    KeplerInput,
    KeplerInputSlot,
)


def _ev(
    max_power_kw=7.4,
    battery_capacity_kwh=100.0,
    soc_percent=50.0,
    plugged_in=True,
    deadline=None,
    required_kwh=None,
) -> EVChargerInput:
    if required_kwh is None:
        required_kwh = battery_capacity_kwh * (1.0 - soc_percent / 100.0)
    return EVChargerInput(
        id="test_ev",
        max_power_kw=max_power_kw,
        battery_capacity_kwh=battery_capacity_kwh,
        current_soc_percent=soc_percent,
        plugged_in=plugged_in,
        deadline=deadline,
        required_kwh=required_kwh,
    )


def test_ev_modulation():
    print("\n--- Testing EV Modulation (Grid Limit - Now Binary Blocked) ---")
    solver = KeplerSolver()

    config = KeplerConfig(
        capacity_kwh=0.0,
        min_soc_percent=10.0,
        max_soc_percent=90.0,
        max_charge_power_kw=0.0,
        max_discharge_power_kw=0.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        grid_import_limit_kw=5.0,
        ev_chargers=[
            _ev(
                max_power_kw=7.4,
                battery_capacity_kwh=100.0,
                soc_percent=50.0,
                deadline=datetime(2026, 1, 1, 1, 0),
                required_kwh=50.0,
            )
        ],
    )

    slots = [
        KeplerInputSlot(
            start_time=datetime(2026, 1, 1, 0, 0),
            end_time=datetime(2026, 1, 1, 1, 0),
            load_kwh=3.0,
            pv_kwh=0.0,
            import_price_sek_kwh=1.0,
            export_price_sek_kwh=1.0,
        )
    ]
    input_data = KeplerInput(slots=slots, initial_soc_kwh=5.0)

    result = solver.solve(input_data, config)

    print(f"Status: {result.status_msg}")
    print(f"EV Charge Power: {result.slots[0].ev_charge_kw} kW")
    print(f"Grid Import: {result.slots[0].grid_import_kwh} kWh (per 1h)")

    assert abs(result.slots[0].ev_charge_kw - 0.0) < 0.1
    print("Modulation binary block test SUCCESS")


def test_ev_economic_stop():
    print("\n--- Testing EV Economic Stop (Price Guard) ---")
    solver = KeplerSolver()

    config = KeplerConfig(
        capacity_kwh=10.0,
        min_soc_percent=10.0,
        max_soc_percent=90.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        ev_chargers=[_ev(required_kwh=0.0)],
    )

    slots = [
        KeplerInputSlot(
            start_time=datetime(2026, 1, 1, 0, 0),
            end_time=datetime(2026, 1, 1, 1, 0),
            load_kwh=0.0,
            pv_kwh=0.0,
            import_price_sek_kwh=3.0,
            export_price_sek_kwh=0.5,
        )
    ]
    input_data = KeplerInput(slots=slots, initial_soc_kwh=5.0)

    result = solver.solve(input_data, config)

    print(f"EV Charge Power: {result.slots[0].ev_charge_kw} kW")
    assert result.slots[0].ev_charge_kw < 0.01
    print("Economic stop test SUCCESS")


def test_deferral_to_cheaper_slots():
    print("\n--- Testing EV Deferral to Cheaper Slots ---")
    solver = KeplerSolver()

    # 70 kWh soft target can be met entirely in the two cheapest slots,
    # so the solver should avoid the expensive first slot.
    config = KeplerConfig(
        capacity_kwh=0.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        max_charge_power_kw=100.0,
        max_discharge_power_kw=100.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        ev_chargers=[
            _ev(
                max_power_kw=30.0,
                battery_capacity_kwh=100.0,
                soc_percent=30.0,
                deadline=datetime(2026, 1, 1, 3, 0),
                required_kwh=60.0,
            )
        ],
    )

    slots = [
        KeplerInputSlot(
            start_time=datetime(2026, 1, 1, 0, 0),
            end_time=datetime(2026, 1, 1, 1, 0),
            load_kwh=0.0,
            pv_kwh=0.0,
            import_price_sek_kwh=5.0,
            export_price_sek_kwh=0.0,
        ),
        KeplerInputSlot(
            start_time=datetime(2026, 1, 1, 1, 0),
            end_time=datetime(2026, 1, 1, 2, 0),
            load_kwh=0.0,
            pv_kwh=0.0,
            import_price_sek_kwh=1.0,
            export_price_sek_kwh=0.0,
        ),
        KeplerInputSlot(
            start_time=datetime(2026, 1, 1, 2, 0),
            end_time=datetime(2026, 1, 1, 3, 0),
            load_kwh=0.0,
            pv_kwh=0.0,
            import_price_sek_kwh=0.1,
            export_price_sek_kwh=0.0,
        ),
    ]
    input_data = KeplerInput(slots=slots, initial_soc_kwh=0.0)

    result = solver.solve(input_data, config)

    print(f"Slot 0 (Price 5.0): {result.slots[0].ev_charge_kw} kW")
    print(f"Slot 1 (Price 1.0): {result.slots[1].ev_charge_kw} kW")
    print(f"Slot 2 (Price 0.1): {result.slots[2].ev_charge_kw} kW")

    assert abs(result.slots[0].ev_charge_kw - 0.0) < 0.1
    assert abs(result.slots[1].ev_charge_kw - 30.0) < 0.1
    assert abs(result.slots[2].ev_charge_kw - 30.0) < 0.1
    print("Deferral to cheaper slots test SUCCESS")


if __name__ == "__main__":
    try:
        test_ev_modulation()
        test_ev_economic_stop()
        test_deferral_to_cheaper_slots()
        print("\nALL VERIFICATIONS PASSED")
    except Exception as e:
        print(f"\nVERIFICATION FAILED: {e}")
        import traceback

        traceback.print_exc()
