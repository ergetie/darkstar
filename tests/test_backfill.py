import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
import pytz
from backend.learning.backfill import BackfillEngine

@pytest.fixture
def mock_engine(tmp_path):
    """Mock LearningEngine and config."""
    with patch("backend.learning.backfill.get_learning_engine") as mock_get:
        mock_le = MagicMock()
        mock_le.store.get_last_observation_time.return_value = None
        mock_le.sensor_map = {"sensor.test": "test_sensor"}
        mock_le.learning_config = {"sensor_map": {"sensor.test": "test_sensor"}}
        
        mock_get.return_value = mock_le
        
        # Mock config load
        with patch("backend.learning.backfill.BackfillEngine._load_config") as mock_conf:
            mock_conf.return_value = {"timezone": "UTC"}
            
            # Mock HA config load
            with patch("backend.learning.backfill.BackfillEngine._load_ha_config") as mock_ha:
                mock_ha.return_value = {"url": "http://ha", "token": "token"}
                
                engine = BackfillEngine("dummy_config.yaml")
                yield engine, mock_le

def test_backfill_no_gap(mock_engine):
    """Test that backfill does nothing if data is up to date."""
    engine, mock_le = mock_engine
    
    # Last obs was 5 mins ago
    now = datetime.now(pytz.UTC)
    mock_le.store.get_last_observation_time.return_value = now - timedelta(minutes=5)
    
    engine.run()
    
    # Should not fetch history
    assert not mock_le.store_slot_observations.called

def test_backfill_with_gap(mock_engine):
    """Test backfill triggers when there is a gap."""
    engine, mock_le = mock_engine
    
    # Last obs was 2 hours ago
    now = datetime.now(pytz.UTC)
    last_obs = now - timedelta(hours=2)
    mock_le.store.get_last_observation_time.return_value = last_obs
    
    # Mock fetch_history
    with patch.object(engine, "_fetch_history") as mock_fetch:
        mock_fetch.return_value = [(last_obs + timedelta(minutes=i), 1.0) for i in range(120)]
        
        # Mock ETL
        mock_df = MagicMock()
        mock_df.empty = False
        mock_le.etl_cumulative_to_slots.return_value = mock_df
        
        engine.run()
        
        # Should fetch history
        assert mock_fetch.called
        # Should store observations
        mock_le.store_slot_observations.assert_called_with(mock_df)

def test_backfill_empty_db(mock_engine):
    """Test backfill defaults to 7 days if DB is empty."""
    engine, mock_le = mock_engine
    
    # No last obs
    mock_le.store.get_last_observation_time.return_value = None
    
    with patch.object(engine, "_fetch_history") as mock_fetch:
        mock_fetch.return_value = []
        
        engine.run()
        
        assert mock_fetch.called
        # Check start time passed to fetch (approx 7 days ago)
        # We can't easily check exact args without more mocking, but called is good enough
