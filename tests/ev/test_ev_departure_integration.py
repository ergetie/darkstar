"""
REV K25 Phase 6: Integration Tests for EV Departure Time Constraint
Updated for multi-device EVChargerInput API.
"""

from datetime import datetime, timedelta

from pytz import timezone as pytz_timezone

from planner.pipeline import calculate_ev_deadline
from planner.solver.kepler import KeplerSolver
from planner.solver.types import (
    EVChargerInput,
    KeplerConfig,
    KeplerInput,
    KeplerInputSlot,
)


def _ev_config(
    deadline=None,
    soc_percent=50.0,
    max_power_kw=3.0,
    battery_capacity_kwh=50.0,
) -> KeplerConfig:
    # Soft target: charge to 100% SoC by the deadline
    required_kwh = battery_capacity_kwh * (1.0 - soc_percent / 100.0)
    return KeplerConfig(
        capacity_kwh=10.0,
        min_soc_percent=10.0,
        max_soc_percent=100.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        wear_cost_sek_per_kwh=0.1,
        ev_chargers=[
            EVChargerInput(
                id="test_ev",
                max_power_kw=max_power_kw,
                battery_capacity_kwh=battery_capacity_kwh,
                current_soc_percent=soc_percent,
                plugged_in=True,
                deadline=deadline,
                required_kwh=required_kwh,
            )
        ],
    )


class TestEVDepartureIntegration:
    """Integration tests for EV departure time feature."""

    def create_test_input(self, num_slots: int = 24, start_hour: int = 0) -> KeplerInput:
        """Create test input with slots spanning multiple hours."""
        slots = []
        tz = pytz_timezone("Europe/Stockholm")
        base_time = tz.localize(datetime(2024, 1, 15, start_hour, 0, 0))

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

    def test_scenario1_plug_at_15_departure_07(self):
        """
        Test 1: Car plugged in at 15:00, departure 07:00 → charges overnight before 07:00.
        """
        tz = pytz_timezone("Europe/Stockholm")
        now = tz.localize(datetime(2024, 1, 15, 15, 0, 0))

        deadline = calculate_ev_deadline("07:00", now, "Europe/Stockholm")
        assert deadline.day == 16
        assert deadline.hour == 7
        assert deadline.minute == 0

        slots = []
        base_time = now
        for i in range(24):
            start = base_time + timedelta(hours=i)
            end = start + timedelta(hours=1)
            slots.append(
                KeplerInputSlot(
                    start_time=start,
                    end_time=end,
                    load_kwh=1.0,
                    pv_kwh=0.0,
                    import_price_sek_kwh=0.5 if i > 10 else 2.0,
                    export_price_sek_kwh=0.3,
                )
            )

        input_data = KeplerInput(slots=slots, initial_soc_kwh=5.0)
        config = _ev_config(deadline=deadline)

        solver = KeplerSolver()
        result = solver.solve(input_data, config)

        deadline_slot = None
        for i, s in enumerate(result.slots):
            if s.end_time > deadline:
                deadline_slot = i
                break

        assert deadline_slot is not None, "Should find deadline slot"
        pre_deadline_ev = sum(s.ev_charge_kw for s in result.slots[:deadline_slot])
        post_deadline_ev = sum(s.ev_charge_kw for s in result.slots[deadline_slot:])

        assert pre_deadline_ev > 0, "Should charge before deadline"
        assert post_deadline_ev == 0, f"Should NOT charge after deadline, got {post_deadline_ev} kW"

    def test_scenario2_plug_at_06_departure_07(self):
        """
        Test 2: Car plugged in at 06:00, departure 07:00 → charges in the 1-hour window.
        """
        tz = pytz_timezone("Europe/Stockholm")
        now = tz.localize(datetime(2024, 1, 15, 6, 0, 0))

        deadline = calculate_ev_deadline("07:00", now, "Europe/Stockholm")
        assert deadline.day == 15
        assert deadline.hour == 7
        assert deadline.minute == 0

        hours_to_deadline = (deadline - now).total_seconds() / 3600
        assert hours_to_deadline == 1.0

        slots = []
        base_time = now
        for i in range(6):
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

        input_data = KeplerInput(slots=slots, initial_soc_kwh=5.0)
        config = _ev_config(deadline=deadline, soc_percent=20.0)

        solver = KeplerSolver()
        result = solver.solve(input_data, config)

        assert result.slots[0].ev_charge_kw > 0, "Should charge in first slot"
        assert result.slots[1].ev_charge_kw == 0, "Should NOT charge after deadline"

    def test_scenario3_plug_at_09_after_deadline(self):
        """
        Test 3: Car plugged in at 09:00 (after deadline) → charges for next day's deadline.
        """
        tz = pytz_timezone("Europe/Stockholm")
        now = tz.localize(datetime(2024, 1, 15, 9, 0, 0))

        deadline = calculate_ev_deadline("07:00", now, "Europe/Stockholm")
        assert deadline.day == 16
        assert deadline.hour == 7
        assert deadline.minute == 0

        slots = []
        base_time = now
        for i in range(48):
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

        input_data = KeplerInput(slots=slots, initial_soc_kwh=5.0)
        config = _ev_config(deadline=deadline)

        solver = KeplerSolver()
        result = solver.solve(input_data, config)

        deadline_slot = None
        for i, s in enumerate(result.slots):
            if s.end_time > deadline:
                deadline_slot = i
                break

        assert deadline_slot is not None, "Should find deadline slot"
        pre_deadline_ev = sum(s.ev_charge_kw for s in result.slots[:deadline_slot])
        post_deadline_ev = sum(s.ev_charge_kw for s in result.slots[deadline_slot:])

        assert pre_deadline_ev > 0, "Should charge before next day's deadline"
        assert post_deadline_ev == 0, f"Should NOT charge after deadline, got {post_deadline_ev} kW"
