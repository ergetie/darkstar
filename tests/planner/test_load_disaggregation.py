from unittest.mock import AsyncMock, patch

import pytest

from backend.loads.base import DeferrableLoad, LoadType
from backend.loads.service import LoadDisaggregator


@pytest.fixture
def mock_config():
    return {
        "deferrable_loads": [
            {
                "id": "water_heater",
                "name": "Water Heater",
                "sensor_key": "water_power_sensor",
                "type": "binary",
                "nominal_power_kw": 3.0,
            },
            {
                "id": "ev_charger",
                "name": "EV Charger",
                "sensor_key": "sensor.ev_power",
                "type": "variable",
                "nominal_power_kw": 11.0,
            },
        ],
        "input_sensors": {"water_power_sensor": "sensor.water_heater_power"},
    }


@pytest.fixture
def disaggregator(mock_config):
    return LoadDisaggregator(mock_config)


def test_load_registration(disaggregator):
    """Test that loads are correctly registered from config."""
    loads = disaggregator.list_active_loads()
    assert len(loads) == 2

    wh = disaggregator.get_load_by_id("water_heater")
    assert wh is not None
    assert wh.name == "Water Heater"
    assert wh.sensor_key == "sensor.water_heater_power"
    assert wh.type == LoadType.BINARY

    ev = disaggregator.get_load_by_id("ev_charger")
    assert ev.sensor_key == "sensor.ev_power"
    assert ev.type == LoadType.VARIABLE


@pytest.mark.asyncio
async def test_update_current_power(disaggregator):
    """Test fetching power from HA sensors with unit-aware normalization."""
    with patch(
        "backend.loads.service.get_ha_sensor_kw_normalized", new_callable=AsyncMock
    ) as mock_get:
        # sensor.water_heater_power -> 3.0 kW, sensor.ev_power -> 5.5 kW
        mock_get.side_effect = lambda sensor: 3.0 if "water" in sensor else 5.5

        total_controllable = await disaggregator.update_current_power()

        assert total_controllable == 8.5
        assert disaggregator.get_load_by_id("water_heater").current_power_kw == 3.0
        assert disaggregator.get_load_by_id("ev_charger").current_power_kw == 5.5
        assert disaggregator.get_load_by_id("water_heater").is_healthy is True


@pytest.mark.asyncio
async def test_update_current_power_failure(disaggregator):
    """Test handling of sensor failures."""
    with patch(
        "backend.loads.service.get_ha_sensor_kw_normalized", new_callable=AsyncMock
    ) as mock_get:
        mock_get.side_effect = lambda sensor: None if "water" in sensor else 5.5

        total_controllable = await disaggregator.update_current_power()

        assert total_controllable == 5.5
        assert disaggregator.get_load_by_id("water_heater").is_healthy is False
        assert disaggregator.get_load_by_id("water_heater").current_power_kw == 0.0
        assert disaggregator.metrics["sensor_failures"] == 1


def test_calculate_base_load(disaggregator):
    """Test base load subtraction and quality metrics."""
    # Normal case
    base = disaggregator.calculate_base_load(total_load_kw=10.0, controllable_kw=3.0)
    assert base == 7.0
    assert disaggregator.metrics["total_calculations"] == 1

    # Negative base load (small drift)
    base = disaggregator.calculate_base_load(total_load_kw=2.0, controllable_kw=2.05)
    assert base == 0.0
    assert (
        disaggregator.metrics["negative_base_load_count"] == 0
    )  # Small drift (<0.1) shouldn't count

    # Negative base load (significant drift)
    base = disaggregator.calculate_base_load(total_load_kw=2.0, controllable_kw=3.0)
    assert base == 0.0
    assert disaggregator.metrics["negative_base_load_count"] == 1

    metrics = disaggregator.get_quality_metrics()
    assert metrics["metrics"]["negative_base_load_count"] == 1
    assert metrics["drift_rate"] == 1 / 3


def test_manual_load_registration(disaggregator):
    """Test dynamic load registration at runtime."""
    new_load = DeferrableLoad(
        load_id="dynamic_load",
        name="Dynamic",
        sensor_key="sensor.dynamic",
        load_type=LoadType.VARIABLE,
        nominal_power_kw=1.0,
    )
    disaggregator.register_load(new_load)
    assert disaggregator.get_load_by_id("dynamic_load") == new_load
    assert len(disaggregator.list_active_loads()) == 3


class TestARC15EntityArrays:
    """Test LoadDisaggregator with new water_heaters[] and ev_chargers[] arrays (ARC15)."""

    @pytest.fixture
    def mock_config_arc15(self):
        return {
            "config_version": 2,
            "water_heaters": [
                {
                    "id": "main_tank",
                    "name": "Main",
                    "enabled": True,
                    "power_kw": 3.0,
                    "sensor": "sensor.vvb",
                    "type": "binary",
                },
                {
                    "id": "disabled",
                    "enabled": False,
                    "power_kw": 3.0,
                    "sensor": "sensor.off",
                    "type": "binary",
                },
            ],
            "ev_chargers": [
                {
                    "id": "tesla",
                    "name": "Tesla",
                    "enabled": True,
                    "max_power_kw": 11.0,
                    "sensor": "sensor.tesla",
                    "type": "variable",
                }
            ],
        }

    def test_arc15_load_registration(self, mock_config_arc15):
        disaggregator = LoadDisaggregator(mock_config_arc15)
        loads = disaggregator.list_active_loads()
        assert len(loads) == 2
        assert disaggregator.get_load_by_id("main_tank") is not None
        assert disaggregator.get_load_by_id("tesla") is not None
        assert disaggregator.get_load_by_id("disabled") is None

    @pytest.mark.asyncio
    async def test_arc15_update_current_power(self, mock_config_arc15):
        disaggregator = LoadDisaggregator(mock_config_arc15)
        with patch(
            "backend.loads.service.get_ha_sensor_kw_normalized", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = lambda s: 3.0 if "vvb" in s else 5.5
            total = await disaggregator.update_current_power()
            assert total == 8.5
            assert disaggregator.get_load_by_id("main_tank").current_power_kw == 3.0

    def test_ev_charger_current_type_no_fallback_warning(self, caplog):
        config = {
            "config_version": 2,
            "ev_chargers": [
                {
                    "id": "ev_charger_1",
                    "name": "Charger",
                    "enabled": True,
                    "max_power_kw": 11.0,
                    "sensor": "sensor.ev",
                    "type": "current",
                }
            ],
        }
        with caplog.at_level("WARNING", logger="loads"):
            disaggregator = LoadDisaggregator(config)

        ev = disaggregator.get_load_by_id("ev_charger_1")
        assert ev.type == LoadType.CURRENT
        assert not any("Invalid load type" in msg for msg in caplog.messages)

    def test_water_heater_modulating_type_no_fallback_warning(self, caplog):
        config = {
            "config_version": 2,
            "water_heaters": [
                {
                    "id": "wh_1",
                    "name": "Water Heater",
                    "enabled": True,
                    "power_kw": 3.0,
                    "sensor": "sensor.vvb",
                    "type": "modulating",
                }
            ],
        }
        with caplog.at_level("WARNING", logger="loads"):
            disaggregator = LoadDisaggregator(config)

        wh = disaggregator.get_load_by_id("wh_1")
        assert wh.type == LoadType.MODULATING
        assert not any("Invalid load type" in msg for msg in caplog.messages)


class TestBackwardCompatibility:
    """Test that legacy deferrable_loads format still works (ARC15)."""

    def test_legacy_load_registration(self):
        config = {
            "config_version": 1,
            "deferrable_loads": [
                {"id": "wh", "name": "WH", "sensor_key": "s1", "type": "binary"},
                {"id": "ev", "name": "EV", "sensor_key": "s2", "type": "variable"},
            ],
            "input_sensors": {"s1": "sensor.wh", "s2": "sensor.ev"},
        }
        disaggregator = LoadDisaggregator(config)
        assert len(disaggregator.list_active_loads()) == 2
        assert disaggregator.get_load_by_id("wh").sensor_key == "sensor.wh"

    def test_mixed_config_prefers_arc15(self):
        config = {
            "config_version": 2,
            "deferrable_loads": [
                {"id": "legacy", "name": "L", "sensor_key": "s1", "type": "binary"}
            ],
            "water_heaters": [
                {
                    "id": "arc15",
                    "name": "A",
                    "enabled": True,
                    "power_kw": 3.0,
                    "sensor": "s2",
                    "type": "binary",
                }
            ],
        }
        disaggregator = LoadDisaggregator(config)
        assert len(disaggregator.list_active_loads()) == 1
        assert disaggregator.get_load_by_id("arc15") is not None
