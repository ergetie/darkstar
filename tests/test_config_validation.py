"""
Config Validation Tests (REV LCL01)

Tests for system profile toggle consistency validation.
"""

import logging

import pytest

from planner.pipeline import PlannerPipeline


class TestConfigValidation:
    """Test config validation catches misconfigurations."""

    def test_battery_misconfiguration_raises_error(self):
        """ERROR when has_battery=true but capacity=0."""
        bad_config = {
            "battery": {"capacity_kwh": 0},
            "battery_economics": {},
            "system": {"has_battery": True},
        }
        with pytest.raises(ValueError, match=r"battery\.capacity_kwh"):
            PlannerPipeline(bad_config)

    def test_battery_misconfiguration_with_missing_capacity(self):
        """ERROR when has_battery=true but capacity key missing."""
        bad_config = {
            "battery": {},  # No capacity_kwh
            "battery_economics": {},
            "system": {"has_battery": True},
        }
        with pytest.raises(ValueError, match=r"battery\.capacity_kwh"):
            PlannerPipeline(bad_config)

    def test_battery_disabled_allows_zero_capacity(self):
        """No error when has_battery=false and capacity=0."""
        config = {
            "battery": {"capacity_kwh": 0},
            "battery_economics": {},
            "system": {"has_battery": False},
        }
        # Should NOT raise
        pipeline = PlannerPipeline(config)
        assert pipeline is not None

    def test_water_heater_misconfiguration_logs_warning(self, caplog):
        """WARNING when has_water_heater=true but power_kw=0."""
        config = {
            "battery": {"capacity_kwh": 10},
            "battery_economics": {},
            "system": {"has_water_heater": True},
            "water_heating": {"power_kw": 0},
        }
        with caplog.at_level(logging.WARNING):
            pipeline = PlannerPipeline(config)

        # Should log warning but not raise
        assert pipeline is not None
        assert "water_heating.power_kw=0" in caplog.text

    def test_solar_misconfiguration_logs_warning(self, caplog):
        """WARNING when has_solar=true but kwp=0."""
        config = {
            "battery": {"capacity_kwh": 10},
            "battery_economics": {},
            "system": {
                "has_solar": True,
                "solar_array": {"kwp": 0},
            },
        }
        with caplog.at_level(logging.WARNING):
            pipeline = PlannerPipeline(config)

        # Should log warning but not raise
        assert pipeline is not None
        assert "solar_array.kwp=0" in caplog.text

    def test_valid_config_passes(self):
        """Valid config with all toggles properly configured passes."""
        good_config = {
            "battery": {"capacity_kwh": 10},
            "battery_economics": {},
            "system": {
                "has_solar": True,
                "has_battery": True,
                "has_water_heater": True,
                "solar_array": {"kwp": 5},
            },
            "water_heating": {"power_kw": 3},
        }
        # Should NOT raise
        pipeline = PlannerPipeline(good_config)
        assert pipeline is not None

    def test_all_features_disabled_passes(self):
        """Config with all has_* toggles off passes even with no values."""
        minimal_config = {
            "battery": {"capacity_kwh": 0},
            "battery_economics": {},
            "system": {
                "has_solar": False,
                "has_battery": False,
                "has_water_heater": False,
            },
        }
        # Should NOT raise
        pipeline = PlannerPipeline(minimal_config)
        assert pipeline is not None
