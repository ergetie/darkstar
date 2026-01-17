# ruff: noqa
import pytest
from datetime import datetime, timedelta

from planner.solver.kepler import KeplerConfig, KeplerInput, KeplerSolver
from planner.solver.types import KeplerInputSlot


def create_mock_slots(count=24, start_hour=12):
    """Create N hours of mock slots (2 slots per hour)."""
    start_time = datetime(2025, 1, 1, start_hour, 0)
    slots = []
    for i in range(count):
        s = start_time + timedelta(minutes=30 * i)
        slots.append(KeplerInputSlot(
            start_time=s,
            end_time=s + timedelta(minutes=30),
            load_kwh=0.5,
            pv_kwh=1.0 if 8 <= s.hour <= 16 else 0.0,
            import_price_sek_kwh=1.0,  # expensive default
            export_price_sek_kwh=0.0
        ))
    return slots

def get_base_config():
    return KeplerConfig(
        capacity_kwh=10.0,
        min_soc_percent=0,
        max_soc_percent=100,
        max_charge_power_kw=5,
        max_discharge_power_kw=5,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,

        # Water enabled
        water_heating_power_kw=2.0,
        water_heating_min_kwh=0.0, # Test spacing purely
        water_heating_max_gap_hours=0.0,

        # Default spacing
        water_min_spacing_hours=4.0,
        water_spacing_penalty_sek=0.0 # Deprecated/Unused
    )

def test_strict_spacing_enforced():
    """Verify that heater cannot restart within the strict spacing window."""
    solver = KeplerSolver()
    input_data = KeplerInput(slots=create_mock_slots(count=24), initial_soc_kwh=5.0)
    slots = input_data.slots

    # Manipulate prices to force heating at specific times if allowed
    # T=0 (12:00) -> Cheap (Should Heat)
    slots[0].import_price_sek_kwh = 0.1
    # T=4 (14:00) -> Cheap (Should Heat if allowed)
    slots[4].import_price_sek_kwh = 0.1

    # Config: Spacing 4 hours (8 slots)
    # T=0 to T=4 is only 2 hours. Should be BLOCKED.
    config = get_base_config()
    config.water_heating_min_kwh = 1.0 # Need at least 1 slot worth (2kW * 0.5h = 1kwh)

    result = solver.solve(input_data, config)
    assert result.is_optimal

    # Check heating schedule
    heat_map = [1 if s.water_heat_kw > 0 else 0 for s in result.slots]

    # Expect: Heat at T=0
    assert heat_map[0] == 1

    # Expect: NO Heat at T=4 because it's within 4h window
    assert heat_map[4] == 0

    # Verify no restarts in window
    # A block start is where 0 -> 1.
    starts = []
    for i in range(1, len(heat_map)):
        if heat_map[i] == 1 and heat_map[i-1] == 0:
            starts.append(i)
    if heat_map[0] == 1: starts.insert(0, 0)

    # If we have multiple starts, check distance
    if len(starts) > 1:
        dist = (starts[1] - starts[0]) * 0.5 # hours
        assert dist >= 4.0, f"Second start at {dist}h is too soon (< 4.0h)"

def test_spacing_disabled():
    """Verify normal operation when spacing is disabled (0h)."""
    solver = KeplerSolver()
    input_data = KeplerInput(slots=create_mock_slots(count=24), initial_soc_kwh=5.0)
    slots = input_data.slots

    # Scenario: Cheap at T=0 and T=1.
    # If spacing was 1.0h (2 slots), it would BLOCK T=1 because T=0 was heated.
    # With spacing=0, it should allow T=0 and T=1.
    slots[0].import_price_sek_kwh = 0.01
    slots[1].import_price_sek_kwh = 0.01
    slots[2].import_price_sek_kwh = 1.0 # Expensive

    config = get_base_config()
    config.water_min_spacing_hours = 0.0 # DISABLED
    config.water_heating_min_kwh = 2.0 # Needs 2 slots (2kW * 0.5h * 2 = 2kWh)
    config.water_block_start_penalty_sek = 0.0

    result = solver.solve(input_data, config)
    assert result.is_optimal

    heat_map = [1 if s.water_heat_kw > 0 else 0 for s in result.slots]

    # Needs 2 slots. Cheapest are 0 and 1.
    # If spacing was active, it might force 0 and... wait...
    # Actually if spacing is 0, 0->1 is allowed.
    assert heat_map[0] == 1
    assert heat_map[1] == 1
