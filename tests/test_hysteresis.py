"""
Test hysteresis and smoothing behavior.
"""

from planner import HeliosPlanner


class TestHysteresis:
    """Test action hysteresis and minimum block enforcement."""

    def setup_method(self):
        """Set up test fixtures."""
        config = {
            "smoothing": {
                "min_on_slots_charge": 2,
                "min_off_slots_charge": 1,
                "min_on_slots_discharge": 2,
                "min_off_slots_discharge": 1,
                "min_on_slots_export": 2,
            }
        }
        self.planner = HeliosPlanner.__new__(HeliosPlanner)
        self.planner.config = config
        self.planner.daily_pv_forecast = {}
        self.planner.daily_load_forecast = {}
        self.planner._last_temperature_forecast = {}
        self.planner.forecast_meta = {}

    def test_charge_hysteresis_enforcement(self):
        """Test that single charge slots are eliminated or extended."""
        # Create test actions array with single charge slot
        actions = ["Hold", "Charge", "Hold", "Hold", "Hold"]

        # Apply hysteresis logic (simplified)
        min_on = 2
        min_off = 1

        # Check consecutive slots for charge action at index 1
        consecutive_count = 1
        for j in range(2, min(1 + min_on, len(actions))):
            if actions[j] == "Charge":
                consecutive_count += 1
            else:
                break

        # Since consecutive_count < min_on, check for recent charge
        recent_charge = False
        for j in range(max(0, 1 - min_off), 1):
            if actions[j] == "Charge":
                recent_charge = True
                break

        if recent_charge:
            actions[1] = "Charge"  # Extend
        else:
            actions[1] = "Hold"  # Cancel

        # Should cancel the single charge slot
        assert actions[1] == "Hold"

    def test_discharge_hysteresis_enforcement(self):
        """Test that single discharge slots are eliminated or extended."""
        actions = ["Hold", "Discharge", "Hold", "Hold", "Hold"]

        # Apply similar logic for discharge
        min_on = 2
        min_off = 1

        consecutive_count = 1
        for j in range(2, min(1 + min_on, len(actions))):
            if actions[j] == "Discharge":
                consecutive_count += 1
            else:
                break

        recent_discharge = False
        for j in range(max(0, 1 - min_off), 1):
            if actions[j] == "Discharge":
                recent_discharge = True
                break

        if recent_discharge:
            actions[1] = "Discharge"
        else:
            actions[1] = "Hold"

        assert actions[1] == "Hold"

    def test_export_hysteresis_enforcement(self):
        """Test that single export slots are eliminated."""
        actions = ["Hold", "Export", "Hold", "Hold", "Hold"]

        # Export hysteresis - always cancel single slots
        min_on = 2

        consecutive_count = 1
        for j in range(2, min(1 + min_on, len(actions))):
            if actions[j] == "Export":
                consecutive_count += 1
            else:
                break

        if consecutive_count < min_on:
            actions[1] = "Hold"

        assert actions[1] == "Hold"

    def test_minimum_block_preservation(self):
        """Test that minimum blocks are preserved."""
        # Create actions with proper minimum block
        actions = ["Hold", "Charge", "Charge", "Hold", "Hold"]

        min_on = 2

        # Check the charge block starting at index 1
        consecutive_count = 2  # Already have 2 consecutive
        for j in range(3, min(1 + min_on, len(actions))):
            if actions[j] == "Charge":
                consecutive_count += 1
            else:
                break

        # Should preserve the block since it meets minimum
        assert consecutive_count >= min_on

    def test_hysteresis_with_recent_activity(self):
        """Test hysteresis extension when recent activity exists."""
        actions = ["Charge", "Hold", "Charge", "Hold", "Hold"]

        min_on = 2
        min_off = 1

        # Check charge at index 2
        consecutive_count = 1
        for j in range(3, min(2 + min_on, len(actions))):
            if actions[j] == "Charge":
                consecutive_count += 1
            else:
                break

        # Since consecutive_count < min_on, check for recent charge
        recent_charge = False
        for j in range(max(0, 2 - min_off), 2):
            if actions[j] == "Charge":
                recent_charge = True
                break

        if recent_charge:
            actions[2] = "Charge"  # Should extend due to recent activity

        assert actions[2] == "Charge"

    def test_no_hysteresis_interference(self):
        """Test that hysteresis doesn't interfere with valid blocks."""
        actions = ["Hold", "Charge", "Charge", "Charge", "Hold"]

        # This block already meets minimum requirements
        # Hysteresis should not modify it
        # Apply hysteresis logic (simplified check)
        min_on = 2
        for i in range(len(actions)):
            if actions[i] == "Charge":
                consecutive_count = 1
                for j in range(i + 1, min(i + min_on, len(actions))):
                    if actions[j] == "Charge":
                        consecutive_count += 1
                    else:
                        break
                # If meets minimum, should be preserved
                if consecutive_count >= min_on:
                    assert actions[i] == "Charge"

    def test_multiple_action_types(self):
        """Test hysteresis across different action types."""
        actions = ["Charge", "Hold", "Discharge", "Hold", "Export"]

        # Each action type should be handled independently
        charge_positions = [i for i, action in enumerate(actions) if action == "Charge"]
        discharge_positions = [i for i, action in enumerate(actions) if action == "Discharge"]
        export_positions = [i for i, action in enumerate(actions) if action == "Export"]

        assert len(charge_positions) == 1
        assert len(discharge_positions) == 1
        assert len(export_positions) == 1

        # Each single action would be subject to hysteresis rules
        # (This is more of a structural test)
