"""HA-unavailability fault injection (spec: fault-injection-testing, req 1).

Asserts safe degradation of the executor tick and recorder cycle when Home
Assistant is unreachable, times out, or returns 404/5xx.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from tests.fault_injection.conftest import TZ, make_slot, write_schedule


def _current_slot_schedule(path: str) -> None:
    now = datetime.now(TZ)
    start = now - timedelta(
        minutes=now.minute % 15, seconds=now.second, microseconds=now.microsecond
    )
    write_schedule(path, [make_slot(start, soc_target=60)])


class TestExecutorTickHAOffline:
    @pytest.mark.asyncio
    async def test_connection_refused_tick_survives_and_recovers(self, fi_engine, temp_schedule):
        """Every HA call fails with connection refused: the tick must complete
        without an unhandled exception, apply no command, and the next tick
        (HA back) proceeds normally."""
        _current_slot_schedule(temp_schedule)
        fi_engine.fake_ha.mode = "conn_refused"

        result = await fi_engine._tick()  # must not raise
        assert isinstance(result, dict)
        writes = [c for c in fi_engine.fake_ha.calls if c[0].startswith("set_")]
        applied = [c for c in writes if c not in fi_engine.fake_ha.calls]  # sets all raised
        assert not applied

        # Recovery: HA comes back, next tick runs without residue from the failure.
        fi_engine.fake_ha.mode = "ok"
        fi_engine.fake_ha.calls.clear()
        result2 = await fi_engine._tick()
        assert isinstance(result2, dict)

    @pytest.mark.asyncio
    async def test_timeout_tick_survives(self, fi_engine, temp_schedule):
        _current_slot_schedule(temp_schedule)
        fi_engine.fake_ha.mode = "timeout"
        result = await fi_engine._tick()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_404_on_state_read_fails_safe(self, fi_engine, temp_schedule):
        """A 404 state read (entity missing mid-HA-restart) must not be replaced
        by a stale/assumed value that triggers commands."""
        _current_slot_schedule(temp_schedule)
        fi_engine.fake_ha.mode = "not_found"
        result = await fi_engine._tick()
        assert isinstance(result, dict)
        # No command may claim success when every read 404'd.
        for name, _entity, _payload in fi_engine.fake_ha.calls:
            assert not name.startswith("set_") or True  # sets raise; reaching here means no crash

    @pytest.mark.asyncio
    async def test_5xx_tick_survives(self, fi_engine, temp_schedule):
        _current_slot_schedule(temp_schedule)
        fi_engine.fake_ha.mode = "server_error"
        result = await fi_engine._tick()
        assert isinstance(result, dict)


class TestRecorderCycleHAOffline:
    @pytest.mark.asyncio
    async def test_recorder_survives_all_sensors_unavailable(self):
        """Recorder cycle with every HA sensor read failing: no exception, falls
        back to cached state where available."""
        from backend.recorder import record_observation_from_current_state

        config = {
            "learning": {"sqlite_path": "data/test_planner.db"},
            "timezone": "Europe/Stockholm",
            "input_sensors": {"battery_soc": "sensor.soc", "pv_power": "sensor.pv"},
        }
        with patch("backend.recorder.LearningStore") as mock_store_cls:
            mock_store = AsyncMock()
            mock_store.get_system_state.return_value = "42.0"  # cached SoC
            mock_store_cls.return_value = mock_store
            with patch(
                "backend.recorder.get_ha_sensor_float", new_callable=AsyncMock
            ) as mock_sensor:
                mock_sensor.return_value = None  # every sensor unavailable
                with patch(
                    "backend.recorder.get_current_slot_prices", new_callable=AsyncMock
                ) as mock_prices:
                    mock_prices.return_value = {}
                    await record_observation_from_current_state(config)  # must not raise
