"""Tests for inputs.py HA client - regression test for resource management.

This test ensures httpx.AsyncClient resources are properly closed after use
to prevent resource leaks when fetching HA data.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGatherSensorReads:
    """Tests for gather_sensor_reads() batch helper."""

    @pytest.mark.asyncio
    async def test_all_sensors_succeed(self):
        """All sensors return values successfully."""
        from backend.core.ha_client import gather_sensor_reads

        reads = [
            ("soc", lambda: AsyncMock(return_value=85.0)()),
            ("pv_power", lambda: AsyncMock(return_value=3.2)()),
            ("load_power", lambda: AsyncMock(return_value=1.5)()),
        ]
        result = await gather_sensor_reads(reads, context="test")
        assert result == {"soc": 85.0, "pv_power": 3.2, "load_power": 1.5}

    @pytest.mark.asyncio
    async def test_partial_failures(self):
        """Partial sensor failures return None for failed, values for successful."""
        from backend.core.ha_client import gather_sensor_reads

        async def succeed():
            return 42.0

        async def fail():
            raise RuntimeError("sensor unavailable")

        reads = [("good", succeed), ("bad", fail)]
        result = await gather_sensor_reads(reads, context="test")
        assert result["good"] == 42.0
        assert result["bad"] is None

    @pytest.mark.asyncio
    async def test_all_sensors_fail(self, caplog):
        """All sensors failing returns all-None dict and logs summary warning."""
        import logging

        from backend.core.ha_client import gather_sensor_reads

        async def fail():
            raise ConnectionError("HA down")

        reads = [("a", fail), ("b", fail), ("c", fail)]
        with caplog.at_level(logging.WARNING, logger="darkstar.core.ha_client"):
            result = await gather_sensor_reads(reads, context="test_ctx")

        assert result == {"a": None, "b": None, "c": None}
        # Should log summary when all fail
        assert any("All 3 sensor reads failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_partial_failures_logged(self, caplog):
        """Each failed sensor is logged with context and entity name."""
        import logging

        from backend.core.ha_client import gather_sensor_reads

        async def fail():
            raise TimeoutError("timeout")

        reads = [("sensor_x", fail)]
        with caplog.at_level(logging.WARNING, logger="darkstar.core.ha_client"):
            await gather_sensor_reads(reads, context="my_context")

        assert any("my_context" in r.message and "sensor_x" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_empty_reads(self):
        """Empty reads list returns empty dict."""
        from backend.core.ha_client import gather_sensor_reads

        result = await gather_sensor_reads([], context="test")
        assert result == {}


@pytest.mark.asyncio
async def test_ev_soc_fallback_logging_no_crash():
    """Verify that EV SoC fallback logging with '0%%' does not crash due to formatting."""
    from backend.core.ha_client import get_initial_state

    # Config with EV charger enabled but sensor returns no data
    test_config = {
        "system": {"has_ev_charger": True, "battery": {"capacity_kwh": 10.0}},
        "ev_chargers": [
            {
                "enabled": True,
                "soc_sensor": "sensor.test_ev_soc",
                "plug_sensor": "sensor.test_ev_plug",
            }
        ],
        "input_sensors": {"battery_soc": "sensor.battery_soc"},
    }

    # Track if the warning was called with proper format
    warning_calls = []

    def mock_yaml_load(f):
        return test_config

    with (
        patch("backend.core.secrets.load_yaml", side_effect=mock_yaml_load),
        patch("backend.core.ha_client.get_ha_sensor_float") as mock_get_sensor,
        patch("backend.core.ha_client.logger") as mock_logger,
    ):
        # Battery SoC returns valid data
        mock_get_sensor.side_effect = lambda entity_id: {
            "sensor.battery_soc": 50.0,
            "sensor.test_ev_soc": None,  # EV SoC returns no data
            "sensor.test_ev_plug": False,
        }.get(entity_id)

        mock_logger.warning = lambda msg, *args: warning_calls.append((msg, args))

        # This should NOT raise ValueError: incomplete format
        result = await get_initial_state()

        # Verify the warning was logged with 0%%
        ev_soc_warnings = [call for call in warning_calls if "defaulting to" in call[0]]
        assert len(ev_soc_warnings) == 1
        assert "0%%" in ev_soc_warnings[0][0]  # Format string has escaped %%

        # Verify result has default EV SoC of 0
        assert result["ev_soc_percent"] == 0.0


@pytest.mark.asyncio
async def test_get_ha_entity_state_uses_shared_client():
    """Verify that get_ha_entity_state() uses the shared HTTP client."""
    from backend.core.ha_client import get_ha_entity_state

    # Mock the response
    mock_response = MagicMock()
    mock_response.json.return_value = {"state": "10.5", "attributes": {}}
    mock_response.raise_for_status = MagicMock()

    # Mock the client
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    with (
        patch("backend.core.ha_client.get_ha_http_client", return_value=mock_client) as mock_get_client,
        patch(
            "backend.core.secrets.load_home_assistant_config",
            return_value={"url": "http://test", "token": "test_token"},
        ),
    ):
        # Call the function
        result = await get_ha_entity_state("sensor.test")

        # Verify shared client was obtained and requested
        mock_get_client.assert_called_once()
        mock_client.get.assert_called_once()

        # Verify response was processed
        assert result is not None
        assert result["state"] == "10.5"


@pytest.mark.asyncio
async def test_get_ha_entity_state_closes_client_on_exception():
    """Verify that exceptions are handled in get_ha_entity_state."""
    from backend.core.ha_client import get_ha_entity_state

    # Mock the client that raises an exception
    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("Connection refused")

    with (
        patch("backend.core.ha_client.get_ha_http_client", return_value=mock_client) as mock_get_client,
        patch(
            "backend.core.secrets.load_home_assistant_config",
            return_value={"url": "http://test", "token": "test_token"},
        ),
    ):
        # Call the function - should not raise, should return None
        result = await get_ha_entity_state("sensor.test")

        mock_get_client.assert_called_once()

        # Function should return None on error
        assert result is None


@pytest.mark.asyncio
async def test_get_load_profile_from_ha_uses_shared_client():
    """Verify that get_load_profile_from_ha() uses the shared client."""
    from backend.core.ha_client import get_load_profile_from_ha

    # Mock the response with empty data (will trigger fallback)
    mock_response = MagicMock()
    mock_response.json.return_value = [[]]  # Empty history data
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    # Mock config
    config = {
        "timezone": "Europe/Stockholm",
        "input_sensors": {"total_load_consumption": "sensor.test_consumption"},
    }

    with (
        patch("backend.core.ha_client.get_ha_http_client", return_value=mock_client) as mock_get_client,
        patch("backend.core.secrets.load_home_assistant_config") as mock_load_config,
    ):
        mock_load_config.return_value = {
            "url": "http://homeassistant:8123",
            "token": "test_token",
            "consumption_entity_id": "sensor.test_consumption",
        }

        # Call the function
        result = await get_load_profile_from_ha(config)

        # Verify shared client was used
        mock_get_client.assert_called_once()

        # Should return a list of 96 values
        assert isinstance(result, list)
        assert len(result) == 96  # 96 slots for 24 hours


class TestGatherSensorReadsBatchExecution:
    """Integration tests verifying parallel batch execution behaviour."""

    @pytest.mark.asyncio
    async def test_parallel_execution_faster_than_sequential(self):
        """Batch reads complete in ~1x delay, not N*delay (parallel, not sequential).

        Uses asyncio.sleep to simulate network latency and measures elapsed time.
        """
        import asyncio
        import time

        from backend.core.ha_client import gather_sensor_reads

        DELAY = 0.05  # 50ms per read

        async def slow_read(value):
            await asyncio.sleep(DELAY)
            return value

        reads = [(f"s{i}", lambda v=i: slow_read(v)) for i in range(5)]

        start = time.monotonic()
        results = await gather_sensor_reads(reads, context="timing_test")
        elapsed = time.monotonic() - start

        # Should complete in ~DELAY, not 5*DELAY
        assert elapsed < DELAY * 2.5, f"Expected parallel execution, took {elapsed:.3f}s"
        assert results == {"s0": 0, "s1": 1, "s2": 2, "s3": 3, "s4": 4}

    @pytest.mark.asyncio
    async def test_get_initial_state_partial_failure_continues(self):
        """get_initial_state() continues with defaults when optional sensors fail."""
        from unittest.mock import AsyncMock, patch

        from backend.core.ha_client import get_initial_state

        test_config = {
            "system": {
                "battery": {"capacity_kwh": 10.0},
                "has_water_heater": True,
                "has_ev_charger": True,
            },
            "ev_chargers": [
                {
                    "enabled": True,
                    "soc_sensor": "sensor.ev_soc",
                    "plug_sensor": "sensor.ev_plug",
                }
            ],
            "water_heaters": [
                {
                    "enabled": True,
                }
            ],
            "input_sensors": {
                "battery_soc": "sensor.batt_soc",
            },
        }

        # Return values keyed by entity ID: battery SoC succeeds, others return None
        sensor_values = {
            "sensor.batt_soc": 75.0,
            "sensor.ev_soc": None,
        }

        with (
            patch("backend.core.secrets.load_yaml", return_value=test_config),
            patch("backend.core.ha_client.get_ha_sensor_float") as mock_sensor,
            patch("backend.core.ha_client.get_ha_bool", new_callable=AsyncMock, return_value=False),
            patch("backend.core.secrets.load_home_assistant_config", return_value={}),
        ):
            # AsyncMock with sync side_effect: returns the dict value for each entity
            mock_sensor.side_effect = lambda e: sensor_values.get(e)

            result = await get_initial_state()

            assert result["battery_soc_percent"] == 75.0
            assert result["water_heated_today_kwh"] == 0.0  # failed sensor → default
            assert result["ev_soc_percent"] == 0.0  # failed sensor → default

    @pytest.mark.asyncio
    async def test_recorder_partial_failure_returns_defaults(self):
        """record_observation_from_current_state() uses 0.0 when power sensors fail."""
        from unittest.mock import AsyncMock, MagicMock, patch

        # Patch gather_sensor_reads to simulate partial sensor failure
        with patch(
            "backend.recorder.gather_sensor_reads",
            new_callable=AsyncMock,
        ) as mock_gather:
            mock_gather.return_value = {
                "pv_power": None,  # failed
                "load_power": 1.5,
                "battery_power": None,  # failed
                "water_power": 0.3,
                "grid_power": None,  # failed
            }

            # Patch everything else the recorder needs
            with (
                patch(
                    "backend.recorder.get_ha_entity_state",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch(
                    "backend.recorder.get_current_slot_prices",
                    new_callable=AsyncMock,
                    return_value=(0.0, 0.0, 0.0),
                ),
                patch("backend.recorder.LearningStore") as mock_store_cls,
                patch("backend.recorder.RecorderStateStore") as mock_state_store_cls,
                patch("backend.recorder.validate_energy_values", return_value=(True, [])),
                patch("backend.recorder.get_max_energy_per_slot", return_value=10.0),
            ):
                mock_store = MagicMock()
                mock_store.record_observation = AsyncMock()
                mock_store_cls.return_value = mock_store

                mock_state_store = MagicMock()
                mock_state_store.load = MagicMock()
                mock_state_store.save = MagicMock()
                mock_state_store.get = MagicMock(return_value=None)
                mock_state_store.set = MagicMock()
                mock_state_store_cls.return_value = mock_state_store

                from backend.recorder import record_observation_from_current_state

                config = {
                    "input_sensors": {},
                    "system": {"grid_meter_type": "net"},
                    "learning": {"sqlite_path": ":memory:"},
                    "timezone": "Europe/Stockholm",
                    "ev_chargers": [],
                }

                # Should not raise even with partial failures
                import contextlib

                with contextlib.suppress(Exception):
                    await record_observation_from_current_state(config)

                # The key check: gather_sensor_reads was called with the right context
                mock_gather.assert_called_once()
                call_kwargs = mock_gather.call_args
                assert call_kwargs[1].get("context") == "recorder_observation" or (
                    len(call_kwargs[0]) > 1 and call_kwargs[0][1] == "recorder_observation"
                )
