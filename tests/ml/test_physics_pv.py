"""
Unit tests for physics-based PV calculation functions.
"""

from datetime import datetime

import pytest
import pytz

from ml.weather import (
    _calculate_poa_irradiance,  # type: ignore[reportPrivateUsage]
    _calculate_solar_position,  # type: ignore[reportPrivateUsage]
    calculate_physics_for_slots,
    calculate_physics_pv,
    calculate_physics_pv_simple,
)


class TestSolarPosition:
    """Tests for solar position calculation."""

    def test_solar_position_noon_stockholm_summer(self):
        """Test solar position at noon in Stockholm during summer."""
        # June 21, 2024 at 12:00 local time (approximately summer solstice)
        tz = pytz.timezone("Europe/Stockholm")
        dt = tz.localize(datetime(2024, 6, 21, 12, 0, 0))

        pos = _calculate_solar_position(59.3, 18.1, dt)

        # At noon on summer solstice, sun should be high in the sky
        assert pos["elevation"] > 50.0, f"Expected high elevation, got {pos['elevation']}"
        assert pos["elevation"] < 60.0, f"Expected elevation < 60, got {pos['elevation']}"
        # Azimuth should be approximately south (180°) at noon
        assert 150 < pos["azimuth"] < 210, f"Expected south-facing azimuth, got {pos['azimuth']}"

    def test_solar_position_noon_stockholm_winter(self):
        """Test solar position at noon in Stockholm during winter."""
        # December 21, 2024 at 12:00 local time (approximately winter solstice)
        tz = pytz.timezone("Europe/Stockholm")
        dt = tz.localize(datetime(2024, 12, 21, 12, 0, 0))

        pos = _calculate_solar_position(59.3, 18.1, dt)

        # At noon on winter solstice, sun should be low in the sky
        assert pos["elevation"] > 0, f"Expected sun above horizon at noon, got {pos['elevation']}"
        assert pos["elevation"] < 15.0, f"Expected low elevation, got {pos['elevation']}"

    def test_solar_position_nighttime(self):
        """Test solar position at night."""
        tz = pytz.timezone("Europe/Stockholm")
        dt = tz.localize(datetime(2024, 6, 21, 2, 0, 0))

        pos = _calculate_solar_position(59.3, 18.1, dt)

        # Sun should be below horizon at 2 AM
        assert pos["elevation"] < 0, f"Expected sun below horizon, got {pos['elevation']}"


class TestPoaIrradiance:
    """Tests for POA irradiance calculation."""

    def test_poa_horizontal_panel(self):
        """Test POA for horizontal panel."""
        # Horizontal panel (tilt=0) should receive GHI
        poa = _calculate_poa_irradiance(
            radiation_w_m2=800.0,
            panel_tilt=0.0,
            panel_azimuth=0.0,
            solar_elevation=45.0,
            solar_azimuth=180.0,
        )
        # For horizontal panel, POA should be close to GHI
        assert 600 < poa < 900, f"Expected POA close to GHI, got {poa}"

    def test_poa_vertical_panel(self):
        """Test POA for vertical panel."""
        # Vertical south-facing panel
        poa = _calculate_poa_irradiance(
            radiation_w_m2=800.0,
            panel_tilt=90.0,
            panel_azimuth=0.0,  # South
            solar_elevation=45.0,
            solar_azimuth=0.0,  # Sun in south
        )
        # Should receive some irradiance
        assert poa > 0, f"Expected positive POA, got {poa}"

    def test_poa_zero_radiation(self):
        """Test POA with zero radiation."""
        poa = _calculate_poa_irradiance(
            radiation_w_m2=0.0,
            panel_tilt=30.0,
            panel_azimuth=0.0,
            solar_elevation=45.0,
            solar_azimuth=180.0,
        )
        assert poa == 0.0

    def test_poa_sun_below_horizon(self):
        """Test POA when sun is below horizon."""
        poa = _calculate_poa_irradiance(
            radiation_w_m2=800.0,
            panel_tilt=30.0,
            panel_azimuth=0.0,
            solar_elevation=-5.0,
            solar_azimuth=180.0,
        )
        assert poa == 0.0


class TestCalculatePhysicsPv:
    """Tests for calculate_physics_pv function."""

    def test_physics_pv_basic(self):
        """Test basic physics PV calculation."""
        tz = pytz.timezone("Europe/Stockholm")
        dt = tz.localize(datetime(2024, 6, 21, 12, 0, 0))

        solar_arrays = [{"name": "South Roof", "kwp": 5.0, "tilt": 30.0, "azimuth": 180.0}]

        total_kwh, per_array = calculate_physics_pv(
            radiation_w_m2=800.0,
            solar_arrays=solar_arrays,
            slot_start=dt,
            latitude=59.3,
            longitude=18.1,
        )

        assert total_kwh is not None
        assert total_kwh > 0, f"Expected positive PV, got {total_kwh}"
        assert len(per_array) == 1
        assert per_array[0]["name"] == "South Roof"
        assert "poa_w_m2" in per_array[0]

    def test_physics_pv_multi_array(self):
        """Test physics PV with multiple arrays."""
        tz = pytz.timezone("Europe/Stockholm")
        dt = tz.localize(datetime(2024, 6, 21, 12, 0, 0))

        solar_arrays = [
            {"name": "East Roof", "kwp": 3.0, "tilt": 30.0, "azimuth": 90.0},
            {"name": "West Roof", "kwp": 3.0, "tilt": 30.0, "azimuth": 270.0},
        ]

        total_kwh, per_array = calculate_physics_pv(
            radiation_w_m2=800.0,
            solar_arrays=solar_arrays,
            slot_start=dt,
            latitude=59.3,
            longitude=18.1,
        )

        assert total_kwh is not None
        assert total_kwh > 0
        assert len(per_array) == 2
        # Total should be sum of both arrays
        expected_sum = sum(arr["kwh"] for arr in per_array)
        assert abs(total_kwh - expected_sum) < 0.001

    def test_physics_pv_nighttime(self):
        """Test physics PV at night returns None (no radiation)."""
        tz = pytz.timezone("Europe/Stockholm")
        dt = tz.localize(datetime(2024, 6, 21, 2, 0, 0))

        solar_arrays = [{"name": "South Roof", "kwp": 5.0, "tilt": 30.0, "azimuth": 180.0}]

        # With 0 radiation, returns None (no production data)
        total_kwh, per_array = calculate_physics_pv(
            radiation_w_m2=0.0,
            solar_arrays=solar_arrays,
            slot_start=dt,
            latitude=59.3,
            longitude=18.1,
        )

        # When radiation is 0, the function returns None early
        assert total_kwh is None
        assert len(per_array) == 0

    def test_physics_pv_sun_below_horizon(self):
        """Test physics PV when sun is below horizon but radiation > 0 (edge case)."""
        tz = pytz.timezone("Europe/Stockholm")
        # 2 AM in June in Stockholm - sun might still be up at this latitude in summer
        # Let's use winter to ensure sun is down
        dt = tz.localize(datetime(2024, 12, 21, 2, 0, 0))

        solar_arrays = [{"name": "South Roof", "kwp": 5.0, "tilt": 30.0, "azimuth": 180.0}]

        # Even if we pass radiation > 0, sun being below horizon should return 0
        total_kwh, per_array = calculate_physics_pv(
            radiation_w_m2=100.0,  # Some radiation data
            solar_arrays=solar_arrays,
            slot_start=dt,
            latitude=59.3,
            longitude=18.1,
        )

        # Sun below horizon -> 0 production
        assert total_kwh == 0.0
        assert len(per_array) == 0

    def test_physics_pv_no_radiation(self):
        """Test physics PV with no radiation data."""
        tz = pytz.timezone("Europe/Stockholm")
        dt = tz.localize(datetime(2024, 6, 21, 12, 0, 0))

        solar_arrays = [{"name": "South Roof", "kwp": 5.0, "tilt": 30.0, "azimuth": 180.0}]

        total_kwh, per_array = calculate_physics_pv(
            radiation_w_m2=None,
            solar_arrays=solar_arrays,
            slot_start=dt,
            latitude=59.3,
            longitude=18.1,
        )

        assert total_kwh is None
        assert len(per_array) == 0

    def test_physics_pv_no_arrays(self):
        """Test physics PV with no solar arrays configured."""
        tz = pytz.timezone("Europe/Stockholm")
        dt = tz.localize(datetime(2024, 6, 21, 12, 0, 0))

        total_kwh, per_array = calculate_physics_pv(
            radiation_w_m2=800.0,
            solar_arrays=[],
            slot_start=dt,
            latitude=59.3,
            longitude=18.1,
        )

        assert total_kwh is None
        assert len(per_array) == 0

    def test_physics_pv_zero_kwp_array(self):
        """Test physics PV with zero kwp array (should be skipped)."""
        tz = pytz.timezone("Europe/Stockholm")
        dt = tz.localize(datetime(2024, 6, 21, 12, 0, 0))

        solar_arrays = [
            {"name": "Empty", "kwp": 0.0, "tilt": 30.0, "azimuth": 180.0},
            {"name": "Valid", "kwp": 5.0, "tilt": 30.0, "azimuth": 180.0},
        ]

        total_kwh, per_array = calculate_physics_pv(
            radiation_w_m2=800.0,
            solar_arrays=solar_arrays,
            slot_start=dt,
            latitude=59.3,
            longitude=18.1,
        )

        assert total_kwh is not None
        assert len(per_array) == 1  # Only valid array
        assert per_array[0]["name"] == "Valid"


class TestCalculatePhysicsPvSimple:
    """Tests for calculate_physics_pv_simple fallback function."""

    def test_simple_pv_basic(self):
        """Test simple physics PV calculation."""
        pv = calculate_physics_pv_simple(
            radiation_w_m2=800.0,
            total_capacity_kw=10.0,
        )
        assert pv is not None
        # Formula: (800/1000) * 10 * 0.85 * 0.25 = 1.7 kWh
        expected = (800.0 / 1000.0) * 10.0 * 0.85 * 0.25
        assert abs(pv - expected) < 0.01

    def test_simple_pv_no_radiation(self):
        """Test simple physics PV with no radiation."""
        pv = calculate_physics_pv_simple(
            radiation_w_m2=None,
            total_capacity_kw=10.0,
        )
        assert pv is None

    def test_simple_pv_no_capacity(self):
        """Test simple physics PV with no capacity."""
        pv = calculate_physics_pv_simple(
            radiation_w_m2=800.0,
            total_capacity_kw=0.0,
        )
        assert pv is None

    def test_simple_pv_custom_efficiency(self):
        """Test simple physics PV with custom efficiency."""
        pv = calculate_physics_pv_simple(
            radiation_w_m2=800.0,
            total_capacity_kw=10.0,
            efficiency=0.75,
        )
        assert pv is not None
        # Lower efficiency = lower output
        pv_default = calculate_physics_pv_simple(
            radiation_w_m2=800.0,
            total_capacity_kw=10.0,
        )
        assert pv_default is not None
        assert pv < pv_default


class TestCalculatePhysicsForSlots:
    """Tests for calculate_physics_for_slots function."""

    def test_physics_for_slots_basic(self):
        """Test calculating physics for multiple slots."""
        tz = pytz.timezone("Europe/Stockholm")
        dt1 = tz.localize(datetime(2024, 6, 21, 10, 0, 0))
        dt2 = tz.localize(datetime(2024, 6, 21, 12, 0, 0))
        dt3 = tz.localize(datetime(2024, 6, 21, 14, 0, 0))

        slots = [
            {"slot_start": dt1.isoformat(), "shortwave_radiation_w_m2": 600.0},
            {"slot_start": dt2.isoformat(), "shortwave_radiation_w_m2": 800.0},
            {"slot_start": dt3.isoformat(), "shortwave_radiation_w_m2": 700.0},
        ]

        config = {
            "system": {
                "location": {"latitude": 59.3, "longitude": 18.1},
                "solar_arrays": [{"name": "South", "kwp": 5.0, "tilt": 30.0, "azimuth": 180.0}],
            }
        }

        results = calculate_physics_for_slots(slots, config)

        assert len(results) == 3
        for r in results:
            assert "physics_kwh" in r
            assert "physics_arrays" in r
            # All should have positive physics during daytime
            if r.get("physics_kwh") is not None:
                assert r["physics_kwh"] >= 0

    def test_physics_for_slots_no_arrays(self):
        """Test calculating physics with no arrays configured."""
        tz = pytz.timezone("Europe/Stockholm")
        dt = tz.localize(datetime(2024, 6, 21, 12, 0, 0))

        slots = [
            {"slot_start": dt.isoformat(), "shortwave_radiation_w_m2": 800.0},
        ]

        config = {
            "system": {
                "location": {"latitude": 59.3, "longitude": 18.1},
            }
        }

        results = calculate_physics_for_slots(slots, config)

        assert len(results) == 1
        assert results[0]["physics_kwh"] is None

    def test_physics_for_slots_missing_radiation(self):
        """Test calculating physics with missing radiation data."""
        tz = pytz.timezone("Europe/Stockholm")
        dt = tz.localize(datetime(2024, 6, 21, 12, 0, 0))

        slots = [
            {"slot_start": dt.isoformat()},  # No radiation
        ]

        config = {
            "system": {
                "location": {"latitude": 59.3, "longitude": 18.1},
                "solar_arrays": [{"name": "South", "kwp": 5.0, "tilt": 30.0, "azimuth": 180.0}],
            }
        }

        results = calculate_physics_for_slots(slots, config)

        assert len(results) == 1
        # Should return None when radiation is missing
        assert results[0]["physics_kwh"] is None or results[0]["physics_kwh"] == 0.0

    def test_physics_for_slots_legacy_array(self):
        """Test calculating physics with legacy single array config."""
        tz = pytz.timezone("Europe/Stockholm")
        dt = tz.localize(datetime(2024, 6, 21, 12, 0, 0))

        slots = [
            {"slot_start": dt.isoformat(), "shortwave_radiation_w_m2": 800.0},
        ]

        config = {
            "system": {
                "location": {"latitude": 59.3, "longitude": 18.1},
                "solar_array": {"kwp": 6.0, "tilt": 25.0, "azimuth": 180.0},
            }
        }

        results = calculate_physics_for_slots(slots, config)

        assert len(results) == 1
        assert results[0]["physics_kwh"] is not None
        assert results[0]["physics_kwh"] > 0


class TestPanelOrientationZero:
    """Tilt 0 and azimuth 0 are honoured; defaults only when missing/None."""

    @staticmethod
    def _kwh(array: dict) -> float:
        tz = pytz.timezone("Europe/Stockholm")
        dt = tz.localize(datetime(2024, 6, 21, 9, 0, 0))
        total, _ = calculate_physics_pv(
            radiation_w_m2=800.0,
            solar_arrays=[{"name": "A", "kwp": 5.0, **array}],
            slot_start=dt,
            latitude=59.3,
            longitude=18.1,
        )
        assert total is not None
        return total

    def test_tilt_zero_differs_from_default(self):
        assert self._kwh({"tilt": 0, "azimuth": 180}) != pytest.approx(
            self._kwh({"tilt": 30, "azimuth": 180})
        )

    def test_azimuth_zero_differs_from_default(self):
        assert self._kwh({"tilt": 30, "azimuth": 0}) != pytest.approx(
            self._kwh({"tilt": 30, "azimuth": 180})
        )

    def test_missing_and_none_use_defaults(self):
        explicit = self._kwh({"tilt": 30, "azimuth": 180})
        assert self._kwh({}) == pytest.approx(explicit)
        assert self._kwh({"tilt": None, "azimuth": None}) == pytest.approx(explicit)
