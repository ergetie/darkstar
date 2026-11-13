from unittest.mock import AsyncMock, patch

import pytest

from backend.recorder import record_observation_from_current_state


@pytest.mark.asyncio
async def test_recorder_fallback_logic():
    # Mock config
    config = {
        "learning": {"sqlite_path": ":memory:"},
        "timezone": "Europe/Stockholm",
        "input_sensors": {"battery_soc": "sensor.soc", "pv_power": "sensor.pv"},
    }

    # Mock Store
    with patch("backend.recorder.LearningStore") as MockStoreClass:
        mock_store = AsyncMock()
        MockStoreClass.return_value = mock_store

        # Case 1: Sensor Available
        with patch(
            "backend.recorder.get_ha_sensor_float", new_callable=AsyncMock
        ) as mock_get_sensor:
            # Setup: Sensor returns 50.0
            mock_get_sensor.side_effect = lambda entity: 50.0 if entity == "sensor.soc" else 0.0
            # Mock prices
            with patch(
                "backend.recorder.get_current_slot_prices", new_callable=AsyncMock
            ) as mock_prices:
                mock_prices.return_value = {}

                await record_observation_from_current_state(config)

                # Verify: set_system_state called with "50.0"
                mock_store.set_system_state.assert_called_with("last_known_soc", "50.0")
                # Verify: store_slot_observations called
                assert mock_store.store_slot_observations.called

        # Case 2: Sensor Unavailable, Cache Available
        mock_store.reset_mock()
        mock_store.get_system_state.return_value = "75.0"

        with patch(
            "backend.recorder.get_ha_sensor_float", new_callable=AsyncMock
        ) as mock_get_sensor:
            # Setup: Sensor returns None for soc, 0.0 for others
            mock_get_sensor.side_effect = lambda entity: None if entity == "sensor.soc" else 0.0

            with patch(
                "backend.recorder.get_current_slot_prices", new_callable=AsyncMock
            ) as mock_prices:
                mock_prices.return_value = {}

                await record_observation_from_current_state(config)

                # Verify: store_slot_observations called (using cached 75.0)
                assert mock_store.store_slot_observations.called
                # Verify call args contain 75.0
                args, _ = mock_store.store_slot_observations.call_args
                df = args[0]
                assert df.iloc[0]["soc_end_percent"] == 75.0

        # Case 3: Sensor Unavailable, No Cache
        mock_store.reset_mock()
        mock_store.get_system_state.return_value = None

        with patch(
            "backend.recorder.get_ha_sensor_float", new_callable=AsyncMock
        ) as mock_get_sensor:
            # Setup: Sensor returns None
            mock_get_sensor.side_effect = lambda entity: None if entity == "sensor.soc" else 0.0

            with patch(
                "backend.recorder.get_current_slot_prices", new_callable=AsyncMock
            ) as mock_prices:
                mock_prices.return_value = {}

                await record_observation_from_current_state(config)

                # Verify: store_slot_observations NOT called (skipped)
                assert not mock_store.store_slot_observations.called
                assert mock_store.close.called

        # Case 4: Sensor Unavailable, Corrupt Cache
        mock_store.reset_mock()
        mock_store.get_system_state.return_value = "invalid_float"

        with patch(
            "backend.recorder.get_ha_sensor_float", new_callable=AsyncMock
        ) as mock_get_sensor:
            # Setup: Sensor returns None
            mock_get_sensor.side_effect = lambda entity: None if entity == "sensor.soc" else 0.0

            with patch(
                "backend.recorder.get_current_slot_prices", new_callable=AsyncMock
            ) as mock_prices:
                mock_prices.return_value = {}

                await record_observation_from_current_state(config)

                # Verify: store_slot_observations NOT called (skipped due to corrupt cache)
                assert not mock_store.store_slot_observations.called
                assert mock_store.close.called
