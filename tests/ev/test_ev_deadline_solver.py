"""
Tests for REV K25 Phase 4: EV Deadline Constraint in Kepler Solver
Updated for multi-device EVChargerInput API.
"""

from datetime import datetime, timedelta

from pytz import timezone as pytz_timezone

from planner.solver.kepler import KeplerSolver
from planner.solver.types import (
    EVChargerInput,
    KeplerConfig,
    KeplerInput,
    KeplerInputSlot,
)


def _make_ev_charger(
    deadline=None,
    max_power_kw=3.0,
    battery_capacity_kwh=50.0,
    current_soc_percent=50.0,
    plugged_in=True,
    required_kwh=None,
):
    """Helper to create a single EVChargerInput."""
    if required_kwh is None:
        # Default soft target: charge to 100% SoC
        required_kwh = battery_capacity_kwh * (1.0 - current_soc_percent / 100.0)
    return EVChargerInput(
        id="test_ev",
        max_power_kw=max_power_kw,
        battery_capacity_kwh=battery_capacity_kwh,
        current_soc_percent=current_soc_percent,
        plugged_in=plugged_in,
        deadline=deadline,
        required_kwh=required_kwh,
    )


def _make_base_config(ev_charger: EVChargerInput) -> KeplerConfig:
    return KeplerConfig(
        capacity_kwh=10.0,
        min_soc_percent=10.0,
        max_soc_percent=100.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        wear_cost_sek_per_kwh=0.1,
        ev_chargers=[ev_charger],
    )


class TestEVDeadlineConstraint:
    """Test that EV charging respects the deadline constraint."""

    def create_test_input(self, num_slots: int = 24) -> KeplerInput:
        """Create test input with slots spanning multiple hours."""
        slots = []
        tz = pytz_timezone("Europe/Stockholm")
        base_time = tz.localize(datetime(2024, 1, 15, 0, 0, 0))

        for i in range(num_slots):
            start = base_time + timedelta(hours=i)
            end = start + timedelta(hours=1)
            slots.append(
                KeplerInputSlot(
                    start_time=start,
                    end_time=end,
                    load_kwh=1.0,
                    pv_kwh=0.0,
                    import_price_sek_kwh=1.0,
                    export_price_sek_kwh=0.5,
                )
            )

        return KeplerInput(
            slots=slots,
            initial_soc_kwh=5.0,
        )

    def test_ev_charging_before_deadline(self):
        """Test that EV charges before the deadline."""
        tz = pytz_timezone("Europe/Stockholm")
        input_data = self.create_test_input(24)

        deadline = tz.localize(datetime(2024, 1, 15, 10, 0, 0))
        config = _make_base_config(_make_ev_charger(deadline=deadline))

        solver = KeplerSolver()
        result = solver.solve(input_data, config)

        pre_deadline_ev = sum(s.ev_charge_kw for s in result.slots[:10])
        assert pre_deadline_ev > 0, "Should charge EV before deadline"

    def test_ev_no_charging_after_deadline(self):
        """Test that EV does NOT charge after the deadline."""
        tz = pytz_timezone("Europe/Stockholm")
        input_data = self.create_test_input(24)

        deadline = tz.localize(datetime(2024, 1, 15, 10, 0, 0))
        config = _make_base_config(_make_ev_charger(deadline=deadline))

        solver = KeplerSolver()
        result = solver.solve(input_data, config)

        post_deadline_ev = sum(s.ev_charge_kw for s in result.slots[10:])
        assert post_deadline_ev == 0, (
            f"Should NOT charge EV after deadline, but charged {post_deadline_ev} kW"
        )

    def test_ev_charges_without_deadline(self):
        """Test that EV charges normally when no deadline is set."""
        input_data = self.create_test_input(24)
        config = _make_base_config(_make_ev_charger(deadline=None))

        solver = KeplerSolver()
        result = solver.solve(input_data, config)

        total_ev = sum(s.ev_charge_kw for s in result.slots)
        assert total_ev > 0, "Should charge EV when no deadline"

    def test_ev_max_charging_with_urgent_deadline(self):
        """Test that EV charges before a tight deadline."""
        tz = pytz_timezone("Europe/Stockholm")
        input_data = self.create_test_input(24)

        # Deadline at 02:00 (covers slots 0 and 1)
        deadline = tz.localize(datetime(2024, 1, 15, 2, 0, 0))
        config = _make_base_config(_make_ev_charger(deadline=deadline))

        solver = KeplerSolver()
        result = solver.solve(input_data, config)

        pre_deadline_ev = sum(s.ev_charge_kw for s in result.slots[:2])
        assert pre_deadline_ev > 0, f"Should charge before deadline, got {pre_deadline_ev} kW"

        post_deadline_ev = sum(s.ev_charge_kw for s in result.slots[2:])
        assert post_deadline_ev == 0, (
            f"Should NOT charge after deadline, charged {post_deadline_ev} kW"
        )
