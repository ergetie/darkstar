"""robust-sensor-reading: per-sensor isolation in ExecutorEngine._gather_system_state."""

import contextlib
import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from executor.actions import HAClient
from executor.config import (
    ControllerConfig,
    ExecutorConfig,
    InverterConfig,
    LoadBalancingConfig,
    NotificationConfig,
    WaterHeaterConfig,
    WaterHeaterDeviceConfig,
)
from executor.engine import ExecutorEngine
from executor.load_balancer import LoadBalancer


@pytest.fixture
def temp_schedule():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        path = f.name
    yield path
    with contextlib.suppress(OSError):
        Path(path).unlink()


def _make_engine(temp_schedule, heaters, states):
    config = ExecutorConfig(
        enabled=True,
        schedule_path=temp_schedule,
        timezone="Europe/Stockholm",
        inverter=InverterConfig(),
        water_heater=WaterHeaterConfig(),
        notifications=NotificationConfig(),
        controller=ControllerConfig(),
        water_heater_devices=heaters,
        has_water_heater=True,
        load_balancing=LoadBalancingConfig(enabled=True, sensor_stale_after_s=30),
    )
    full_config = {
        "system": {"grid_meter_type": "net"},
        "input_sensors": {
            "grid_current_l1": "sensor.l1",
            "grid_current_l2": "sensor.l2",
            "grid_current_l3": "sensor.l3",
        },
    }
    with (
        patch("executor.engine.load_executor_config", return_value=config),
        patch("executor.engine.load_yaml", return_value=full_config),
        patch.object(ExecutorEngine, "_get_db_path", return_value=":memory:"),
    ):
        engine = ExecutorEngine("config.yaml")

    now = datetime.now(UTC).isoformat()
    requested: list[str] = []

    async def get_state_value(entity_id):
        requested.append(entity_id)
        return states.get(entity_id, "0")

    async def get_state(entity_id):
        if entity_id.startswith("sensor.l"):
            return {
                "state": "10.0",
                "attributes": {"unit_of_measurement": "A", "device_class": "current"},
                "last_reported": now,
            }
        return None

    ha = MagicMock(spec=HAClient)
    ha.get_state_value = AsyncMock(side_effect=get_state_value)
    ha.get_state = AsyncMock(side_effect=get_state)
    engine.ha_client = ha
    return engine, requested


def _balancer_stale(engine, state) -> bool:
    lb = LoadBalancer(engine.config.load_balancing)
    now = datetime.now(UTC)
    return any(
        lb._is_stale(p, state.grid_current_a or {}, state.grid_current_updated_at or {}, now)
        for p in (1, 2, 3)
    )


@pytest.mark.asyncio
async def test_switch_heater_does_not_block_phase_currents(temp_schedule, caplog):
    """torleif case: switch heater target state 'on' must not abort the gather."""
    heater = WaterHeaterDeviceConfig(
        id="vvb", target_entity="switch.vvb", control_type="switch"
    )
    engine, requested = _make_engine(temp_schedule, [heater], {"switch.vvb": "on"})

    with caplog.at_level(logging.WARNING):
        state = await engine._gather_system_state()

    assert "switch.vvb" not in requested
    assert not [r for r in caplog.records if "switch.vvb" in r.getMessage()]
    assert state.current_water_temp == 50.0
    assert state.grid_current_a == {1: 10.0, 2: 10.0, 3: 10.0}
    assert not _balancer_stale(engine, state)


@pytest.mark.asyncio
async def test_temperature_heater_still_parsed(temp_schedule):
    heater = WaterHeaterDeviceConfig(
        id="vvb", target_entity="sensor.tank", control_type="temperature"
    )
    engine, _ = _make_engine(temp_schedule, [heater], {"sensor.tank": "55.5"})
    state = await engine._gather_system_state()
    assert state.current_water_temp == 55.5
    assert state.grid_current_a is not None


@pytest.mark.asyncio
async def test_mixed_heaters_only_first_read(temp_schedule):
    heaters = [
        WaterHeaterDeviceConfig(id="a", target_entity="sensor.tank", control_type="temperature"),
        WaterHeaterDeviceConfig(id="b", target_entity="switch.b", control_type="switch"),
    ]
    engine, requested = _make_engine(
        temp_schedule, heaters, {"sensor.tank": "41", "switch.b": "on"}
    )
    state = await engine._gather_system_state()
    assert state.current_water_temp == 41.0
    assert "switch.b" not in requested


@pytest.mark.asyncio
async def test_non_numeric_sensor_does_not_block_phase_currents(temp_schedule, caplog):
    heater = WaterHeaterDeviceConfig(
        id="vvb", target_entity="sensor.tank", control_type="temperature"
    )
    engine, _ = _make_engine(temp_schedule, [heater], {"sensor.tank": "garbage"})
    with caplog.at_level(logging.WARNING):
        state = await engine._gather_system_state()
    assert state.grid_current_a == {1: 10.0, 2: 10.0, 3: 10.0}
    assert any("sensor.tank" in r.getMessage() for r in caplog.records)


def test_safe_float_returns_none_and_rate_limits_warning(temp_schedule, caplog):
    engine, _ = _make_engine(temp_schedule, [], {})
    with caplog.at_level(logging.WARNING):
        assert engine._safe_float("sensor.x", "abc") is None
        assert engine._safe_float("sensor.x", "abc") is None
        assert engine._safe_float("sensor.y", "unavailable") is None
    msgs = [r.getMessage() for r in caplog.records]
    assert sum("sensor.x" in m for m in msgs) == 1
    assert sum("sensor.y" in m for m in msgs) == 1
    assert engine._safe_float("sensor.x", "1.5") == 1.5
    assert engine._safe_float("sensor.x", None) is None

    # After the interval a persistent fault logs again.
    engine._sensor_warn_at["sensor.x"] -= 301
    with caplog.at_level(logging.WARNING):
        engine._safe_float("sensor.x", "abc")
    assert sum("sensor.x" in r.getMessage() for r in caplog.records) == 2


@pytest.mark.asyncio
async def test_unavailable_warns_once_across_ticks_and_unconfigured_is_silent(
    temp_schedule, caplog
):
    """HA-startup 'unavailable' warns once per interval; unconfigured sensors never warn."""
    heater = WaterHeaterDeviceConfig(
        id="vvb", target_entity="sensor.tank", control_type="temperature"
    )
    engine, _ = _make_engine(temp_schedule, [heater], {"sensor.tank": "unavailable"})
    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            await engine._gather_system_state()
    msgs = [r.getMessage() for r in caplog.records]
    assert sum("sensor.tank" in m for m in msgs) == 1
    # Only configured entities may be named (soc/pv/load are unconfigured here).
    assert all("could not be read" not in m or "sensor.tank" in m for m in msgs)
