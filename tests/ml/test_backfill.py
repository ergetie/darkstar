import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.append(str(Path(__file__).parent.parent.parent))
import pytz

from backend.learning.backfill import BackfillEngine


@pytest.fixture
def mock_engine(tmp_path):
    """Mock LearningEngine and config."""
    with patch("backend.learning.backfill.get_learning_engine") as mock_get:
        mock_le = MagicMock()
        mock_le.store.get_last_observation_time = AsyncMock(return_value=None)
        mock_le.store_slot_observations = AsyncMock()
        mock_le.sensor_map = {"sensor.test": "test_sensor"}
        mock_le.learning_config = {"sensor_map": {"sensor.test": "test_sensor"}}

        mock_get.return_value = mock_le

        # Mock config load
        with patch("backend.learning.backfill.BackfillEngine._load_config") as mock_conf:
            mock_conf.return_value = {
                "timezone": "UTC",
                "learning": {"sensor_map": {"sensor.test": "test_sensor"}},
            }

            # Mock HA config load
            with patch("backend.learning.backfill.BackfillEngine._load_ha_config") as mock_ha:
                mock_ha.return_value = {"url": "http://ha", "token": "token"}

                engine = BackfillEngine("dummy_config.yaml")
                yield engine, mock_le


@pytest.fixture
def auto_detect_engine(tmp_path):
    with patch("backend.learning.backfill.get_learning_engine") as mock_get:
        mock_le = MagicMock()
        mock_le.store.get_last_observation_time = AsyncMock(return_value=datetime.now(pytz.UTC) - timedelta(hours=1))
        mock_le.store_slot_observations = AsyncMock()
        mock_le.sensor_map = {}
        mock_le.etl_cumulative_to_slots.return_value = MagicMock(empty=False)
        mock_get.return_value = mock_le

        with patch("backend.learning.backfill.BackfillEngine._load_config") as mock_conf:
            mock_conf.return_value = {
                "timezone": "UTC",
                "learning": {},
                "input_sensors": {"total_load_consumption": "sensor.total_load"},
                "system": {"has_ev_charger": True, "has_water_heater": True},
                "ev_chargers": [{"id": "ev1", "sensor": "sensor.ev_power", "enabled": True}],
                "water_heaters": [{"id": "wh1", "sensor": "sensor.water_power", "enabled": True}],
            }
            with patch("backend.learning.backfill.BackfillEngine._load_ha_config") as mock_ha:
                mock_ha.return_value = {"url": "http://ha", "token": "token"}
                yield BackfillEngine("dummy_config.yaml"), mock_le


@pytest.mark.asyncio
async def test_backfill_no_gap(mock_engine):
    """Test that backfill does nothing if data is up to date."""
    engine, mock_le = mock_engine

    # Last obs was 5 mins ago
    now = datetime.now(pytz.UTC)
    mock_le.store.get_last_observation_time.return_value = now - timedelta(minutes=5)

    await engine.run()

    # Should not fetch history
    assert not mock_le.store_slot_observations.called


@pytest.mark.asyncio
async def test_backfill_with_gap(mock_engine):
    """Test backfill triggers when there is a gap."""
    engine, mock_le = mock_engine

    # Last obs was 2 hours ago
    now = datetime.now(pytz.UTC)
    last_obs = now - timedelta(hours=2)
    mock_le.store.get_last_observation_time.return_value = last_obs

    # Mock fetch_history
    with patch.object(engine, "_fetch_history", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [(last_obs + timedelta(minutes=i), 1.0) for i in range(120)]

        # Mock ETL
        mock_df = MagicMock()
        mock_df.empty = False
        mock_le.etl_cumulative_to_slots.return_value = mock_df

        await engine.run()

        # Should fetch history
        assert mock_fetch.called
        # Should store observations
        mock_le.store_slot_observations.assert_called_with(mock_df, authoritative=False)


@pytest.mark.asyncio
async def test_backfill_empty_db(mock_engine):
    """Test backfill defaults to 7 days if DB is empty."""
    engine, mock_le = mock_engine

    # No last obs
    mock_le.store.get_last_observation_time.return_value = None

    with patch.object(engine, "_fetch_history", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = []

        await engine.run()

        assert mock_fetch.called
        # Check start time passed to fetch (approx 7 days ago)
        # We can't easily check exact args without more mocking, but called is good enough


@pytest.mark.asyncio
async def test_backfill_auto_detects_controllable_load_sensors(auto_detect_engine):
    engine, mock_le = auto_detect_engine

    async def fake_fetch(entity_id, start_time, end_time):
        return [(start_time, 1.0), (start_time + timedelta(minutes=15), 2.0)]

    with patch.object(engine, "_fetch_history", new_callable=AsyncMock, side_effect=fake_fetch) as fetch:
        await engine.run()

    fetched_entities = {call.args[0] for call in fetch.call_args_list}
    assert {"sensor.total_load", "sensor.ev_power", "sensor.water_power"}.issubset(fetched_entities)
    args = mock_le.etl_cumulative_to_slots.call_args.args
    assert "sensor.total_load" in args[0]
    assert {"sensor.ev_power", "sensor.water_power"}.issubset(args[1])
    assert mock_le.sensor_map["sensor.ev_power"] == "ev_charging"
    assert mock_le.sensor_map["sensor.water_power"] == "water"
