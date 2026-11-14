"""Tests for sensor validation utilities."""

from unittest.mock import patch

import pytest

from backend.validation import get_max_energy_per_slot, validate_energy_values


class TestGetMaxEnergyPerSlot:
    """Test suite for get_max_energy_per_slot function."""

    def test_calculates_correctly_with_valid_config(self):
        """Test threshold calculation from grid max power."""
        config = {"system": {"grid": {"max_power_kw": 8.0}}}

        result = get_max_energy_per_slot(config)

        # 8.0 kW * 0.25h * 2.0 = 4.0 kWh
        assert result == 4.0

    def test_calculates_with_different_power_values(self):
        """Test calculation with various power ratings."""
        test_cases = [
            (6.0, 3.0),  # 6.0 * 0.25 * 2.0 = 3.0
            (10.0, 5.0),  # 10.0 * 0.25 * 2.0 = 5.0
            (16.0, 8.0),  # 16.0 * 0.25 * 2.0 = 8.0
            (20.0, 10.0),  # 20.0 * 0.25 * 2.0 = 10.0
        ]

        for power_kw, expected_kwh in test_cases:
            config = {"system": {"grid": {"max_power_kw": power_kw}}}
            result = get_max_energy_per_slot(config)
            assert result == expected_kwh, f"Failed for {power_kw} kW"

    def test_raises_error_when_config_missing(self):
        """Test that missing config raises ValueError."""
        config = {}

        with pytest.raises(ValueError) as exc_info:
            get_max_energy_per_slot(config)

        assert "system.grid.max_power_kw" in str(exc_info.value)
        assert "required" in str(exc_info.value).lower()

    def test_raises_error_when_grid_section_missing(self):
        """Test that missing grid section raises ValueError."""
        config = {"system": {}}

        with pytest.raises(ValueError) as exc_info:
            get_max_energy_per_slot(config)

        assert "system.grid.max_power_kw" in str(exc_info.value)

    def test_raises_error_when_max_power_missing(self):
        """Test that missing max_power_kw raises ValueError."""
        config = {"system": {"grid": {}}}

        with pytest.raises(ValueError) as exc_info:
            get_max_energy_per_slot(config)

        assert "system.grid.max_power_kw" in str(exc_info.value)


class TestValidateEnergyValues:
    """Test suite for validate_energy_values function."""

    def test_valid_values_preserved(self):
        """Test that valid values are unchanged."""
        record = {
            "pv_kwh": 2.5,
            "load_kwh": 1.8,
            "import_kwh": 0.5,
            "export_kwh": 0.0,
        }
        max_kwh = 4.0

        result = validate_energy_values(record, max_kwh)

        assert result["pv_kwh"] == 2.5
        assert result["load_kwh"] == 1.8
        assert result["import_kwh"] == 0.5
        assert result["export_kwh"] == 0.0

    def test_spike_values_zeroed(self):
        """Test that spike values exceeding threshold are zeroed."""
        record = {
            "pv_kwh": 10.0,  # Spike: exceeds 4.0
            "load_kwh": 1.8,  # Valid
            "import_kwh": 50.0,  # Spike: exceeds 4.0
        }
        max_kwh = 4.0

        with patch("backend.validation.logger") as mock_logger:
            result = validate_energy_values(record, max_kwh)

        assert result["pv_kwh"] == 0.0
        assert result["load_kwh"] == 1.8
        assert result["import_kwh"] == 0.0
        assert mock_logger.warning.call_count == 2

    def test_exact_threshold_value_allowed(self):
        """Test that values exactly at threshold are allowed."""
        record = {
            "pv_kwh": 4.0,  # Exactly at threshold
            "load_kwh": 3.999,  # Just under threshold
        }
        max_kwh = 4.0

        with patch("backend.validation.logger") as mock_logger:
            result = validate_energy_values(record, max_kwh)

        assert result["pv_kwh"] == 4.0
        assert result["load_kwh"] == 3.999
        assert mock_logger.warning.call_count == 0

    def test_nan_values_zeroed(self):
        """Test that NaN values are zeroed."""
        record = {
            "pv_kwh": float("nan"),
            "load_kwh": 1.5,
        }
        max_kwh = 4.0

        with patch("backend.validation.logger") as mock_logger:
            result = validate_energy_values(record, max_kwh)

        assert result["pv_kwh"] == 0.0
        assert result["load_kwh"] == 1.5
        mock_logger.warning.assert_called_once()
        assert "NaN" in mock_logger.warning.call_args[0][0]

    def test_inf_values_zeroed(self):
        """Test that Inf values are zeroed."""
        record = {
            "pv_kwh": float("inf"),
            "load_kwh": float("-inf"),
        }
        max_kwh = 4.0

        with patch("backend.validation.logger") as mock_logger:
            result = validate_energy_values(record, max_kwh)

        assert result["pv_kwh"] == 0.0
        assert result["load_kwh"] == 0.0
        assert mock_logger.warning.call_count == 2

    def test_none_values_preserved(self):
        """Test that None values are preserved (not validated)."""
        record = {
            "pv_kwh": None,
            "load_kwh": 1.5,
        }
        max_kwh = 4.0

        with patch("backend.validation.logger") as mock_logger:
            result = validate_energy_values(record, max_kwh)

        assert result["pv_kwh"] is None
        assert result["load_kwh"] == 1.5
        assert mock_logger.warning.call_count == 0

    def test_non_numeric_values_zeroed(self):
        """Test that non-numeric values are zeroed."""
        record = {
            "pv_kwh": "invalid",
            "load_kwh": [1, 2, 3],
            "import_kwh": 1.5,
        }
        max_kwh = 4.0

        with patch("backend.validation.logger") as mock_logger:
            result = validate_energy_values(record, max_kwh)

        assert result["pv_kwh"] == 0.0
        assert result["load_kwh"] == 0.0
        assert result["import_kwh"] == 1.5
        assert mock_logger.warning.call_count == 2

    def test_all_energy_fields_validated(self):
        """Test that all energy fields are checked."""
        record = {
            "pv_kwh": 5.0,  # Spike
            "load_kwh": 5.0,  # Spike
            "import_kwh": 5.0,  # Spike
            "export_kwh": 5.0,  # Spike
            "water_kwh": 5.0,  # Spike
            "ev_charging_kwh": 5.0,  # Spike
            "batt_charge_kwh": 5.0,  # Spike
            "batt_discharge_kwh": 5.0,  # Spike
        }
        max_kwh = 4.0

        with patch("backend.validation.logger") as mock_logger:
            result = validate_energy_values(record, max_kwh)

        for field in record:
            assert result[field] == 0.0, f"Field {field} should be zeroed"

        assert mock_logger.warning.call_count == 8

    def test_original_record_not_modified(self):
        """Test that the original record is not modified."""
        record = {
            "pv_kwh": 10.0,
            "load_kwh": 1.5,
        }
        max_kwh = 4.0

        with patch("backend.validation.logger"):
            result = validate_energy_values(record, max_kwh)

        # Original should be unchanged
        assert record["pv_kwh"] == 10.0
        assert record["load_kwh"] == 1.5

        # Result should be modified
        assert result["pv_kwh"] == 0.0
        assert result["load_kwh"] == 1.5

    def test_missing_fields_handled_gracefully(self):
        """Test that missing fields don't cause errors."""
        record = {
            "pv_kwh": 1.5,
            # load_kwh is missing
        }
        max_kwh = 4.0

        with patch("backend.validation.logger") as mock_logger:
            result = validate_energy_values(record, max_kwh)

        assert result["pv_kwh"] == 1.5
        assert "load_kwh" not in result
        assert mock_logger.warning.call_count == 0

    def test_warning_includes_field_name_and_value(self):
        """Test that warning message includes field name and detected value."""
        record = {"pv_kwh": 10.0}
        max_kwh = 4.0

        with patch("backend.validation.logger") as mock_logger:
            validate_energy_values(record, max_kwh)

        warning_msg = mock_logger.warning.call_args[0][0]
        assert "pv_kwh" in warning_msg
        assert "10.000" in warning_msg
        assert "4.000" in warning_msg


class TestSpikeMarksDevicesUnknown:
    @staticmethod
    def _record(**values):
        flags = {
            "recording": {
                "components": {
                    "ev": {"method": "power_history", "owner": "recorder"},
                    "water": {"method": "power_history", "owner": "recorder"},
                }
            },
            "water_heater_energy": {
                "devices": {"tank": {"energy_kwh": 1.0, "source": "power_history"}}
            },
            "ev_charger_devices": {
                "ev1": {"energy_kwh": 1.0, "source": "power_history", "coverage": "complete"}
            },
        }
        return {"quality_flags": flags, "water_kwh": 0.5, "ev_charging_kwh": 0.5} | values

    def test_ev_spike_is_zeroed_and_marked_unknown_with_unavailable_chargers(self):
        record = self._record(ev_charging_kwh=50.0, ev_charger_energy={"ev1": 50.0})
        result = validate_energy_values(record, 4.0)
        flags = result["quality_flags"]
        assert result["ev_charging_kwh"] == 0.0
        assert flags["recording"]["components"]["ev"]["method"] == "unknown"
        assert flags["recording"]["components"]["water"]["method"] == "power_history"
        assert flags["ev_charger_devices"]["ev1"] == {
            "energy_kwh": None,
            "source": "unavailable",
            "coverage": "unavailable",
        }
        assert flags["water_heater_energy"]["devices"]["tank"]["source"] == "power_history"
        # The input record is never mutated.
        assert record["quality_flags"]["recording"]["components"]["ev"]["method"] == "power_history"

    def test_water_spike_still_marks_water_only(self):
        result = validate_energy_values(self._record(water_kwh=50.0), 4.0)
        flags = result["quality_flags"]
        assert flags["recording"]["components"]["water"]["method"] == "unknown"
        assert flags["recording"]["components"]["ev"]["method"] == "power_history"
        assert result["water_heater_energy"] is None

    def test_both_spikes_mark_both_devices(self):
        result = validate_energy_values(self._record(water_kwh=50.0, ev_charging_kwh=50.0), 4.0)
        components = result["quality_flags"]["recording"]["components"]
        assert (components["ev"]["method"], components["water"]["method"]) == ("unknown", "unknown")

    def test_no_spike_leaves_provenance_untouched(self):
        record = self._record()
        assert validate_energy_values(record, 4.0)["quality_flags"] == record["quality_flags"]
