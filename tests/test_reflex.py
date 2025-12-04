"""
Tests for Aurora Reflex: Phase A (Safety Analyzer)

Tests the analyze_safety() method which tunes s_index.base_factor
based on historical low-SoC events during peak hours.
"""
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import pytz

from backend.learning.store import LearningStore
from backend.learning.reflex import (
    AuroraReflex,
    BOUNDS,
    MAX_DAILY_CHANGE,
    SAFETY_CRITICAL_EVENT_COUNT,
    SAFETY_LOW_SOC_THRESHOLD,
    SAFETY_PEAK_HOURS,
    SAFETY_RELAXATION_DAYS,
)


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    tz = pytz.timezone("Europe/Stockholm")
    store = LearningStore(db_path, tz)
    
    yield db_path, store, tz
    
    # Cleanup
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
def mock_config():
    """Mock config with default s_index values."""
    return {
        "learning": {"reflex_enabled": True},
        "s_index": {"base_factor": 1.1},
        "forecasting": {"pv_confidence_percent": 90},
        "battery_economics": {"battery_cycle_cost_kwh": 0.2},
        "battery": {"capacity_kwh": 34.2},
        "timezone": "Europe/Stockholm",
    }


class TestLowSocEventsQuery:
    """Test the get_low_soc_events query method."""

    def test_no_events_returns_empty(self, temp_db):
        """When no low-SoC events exist, return empty list."""
        db_path, store, tz = temp_db
        
        events = store.get_low_soc_events(days_back=30)
        assert events == []

    def test_finds_low_soc_during_peak(self, temp_db):
        """Find events where SoC < threshold during peak hours."""
        db_path, store, tz = temp_db
        
        # Insert a low-SoC observation during peak hours
        now = datetime.now(tz)
        peak_time = now.replace(hour=17, minute=0, second=0, microsecond=0)
        
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO slot_observations (slot_start, slot_end, soc_end_percent)
                VALUES (?, ?, ?)
                """,
                (peak_time.isoformat(), (peak_time + timedelta(minutes=15)).isoformat(), 3.5),
            )
            conn.commit()
        
        events = store.get_low_soc_events(
            days_back=30,
            threshold_percent=SAFETY_LOW_SOC_THRESHOLD,
            peak_hours=SAFETY_PEAK_HOURS,
        )
        
        assert len(events) == 1
        assert events[0]["soc_end_percent"] == 3.5

    def test_ignores_low_soc_outside_peak(self, temp_db):
        """Low SoC outside peak hours should not be counted."""
        db_path, store, tz = temp_db
        
        now = datetime.now(tz)
        off_peak_time = now.replace(hour=10, minute=0, second=0, microsecond=0)
        
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO slot_observations (slot_start, slot_end, soc_end_percent)
                VALUES (?, ?, ?)
                """,
                (off_peak_time.isoformat(), (off_peak_time + timedelta(minutes=15)).isoformat(), 2.0),
            )
            conn.commit()
        
        events = store.get_low_soc_events(
            days_back=30,
            threshold_percent=SAFETY_LOW_SOC_THRESHOLD,
            peak_hours=SAFETY_PEAK_HOURS,
        )
        
        assert len(events) == 0

    def test_ignores_soc_above_threshold(self, temp_db):
        """SoC above threshold should not be counted."""
        db_path, store, tz = temp_db
        
        now = datetime.now(tz)
        peak_time = now.replace(hour=18, minute=0, second=0, microsecond=0)
        
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO slot_observations (slot_start, slot_end, soc_end_percent)
                VALUES (?, ?, ?)
                """,
                (peak_time.isoformat(), (peak_time + timedelta(minutes=15)).isoformat(), 10.0),
            )
            conn.commit()
        
        events = store.get_low_soc_events(
            days_back=30,
            threshold_percent=SAFETY_LOW_SOC_THRESHOLD,
            peak_hours=SAFETY_PEAK_HOURS,
        )
        
        assert len(events) == 0


class TestReflexState:
    """Test the reflex_state rate limiting functionality."""

    def test_get_reflex_state_none_when_new(self, temp_db):
        """New parameters should return None."""
        db_path, store, tz = temp_db
        
        state = store.get_reflex_state("s_index.base_factor")
        assert state is None

    def test_update_and_get_reflex_state(self, temp_db):
        """Can store and retrieve reflex state."""
        db_path, store, tz = temp_db
        
        store.update_reflex_state("s_index.base_factor", 1.12)
        
        state = store.get_reflex_state("s_index.base_factor")
        assert state is not None
        assert state["last_value"] == 1.12
        assert state["change_count"] == 1

    def test_change_count_increments(self, temp_db):
        """Multiple updates should increment change_count."""
        db_path, store, tz = temp_db
        
        store.update_reflex_state("s_index.base_factor", 1.12)
        store.update_reflex_state("s_index.base_factor", 1.14)
        
        state = store.get_reflex_state("s_index.base_factor")
        assert state["change_count"] == 2
        assert state["last_value"] == 1.14


class TestAnalyzeSafety:
    """Test the analyze_safety analyzer logic."""

    def test_some_events_in_60d_is_stable(self, temp_db, mock_config):
        """With 1-2 events in 30 days, should report stable (not enough to increase)."""
        db_path, store, tz = temp_db
        
        # Insert 2 events (below threshold of 3)
        now = datetime.now(tz)
        with sqlite3.connect(db_path) as conn:
            for i in range(2):
                peak_time = (now - timedelta(days=i)).replace(
                    hour=17, minute=0, second=0, microsecond=0
                )
                conn.execute(
                    """
                    INSERT INTO slot_observations (slot_start, slot_end, soc_end_percent)
                    VALUES (?, ?, ?)
                    """,
                    (peak_time.isoformat(), (peak_time + timedelta(minutes=15)).isoformat(), 3.0),
                )
            conn.commit()
        
        with patch.object(AuroraReflex, "__init__", lambda self, path: None):
            reflex = AuroraReflex.__new__(AuroraReflex)
            reflex.config = mock_config
            reflex.store = store
            reflex.timezone = tz
            reflex.learning_engine = MagicMock()
            
            updates, msg = reflex.analyze_safety()
            
            assert updates == {}
            assert "Stable" in msg or "2 events" in msg

    def test_many_events_increases_base_factor(self, temp_db, mock_config):
        """With 3+ events in 30 days, should propose increase."""
        db_path, store, tz = temp_db
        
        # Insert multiple low-SoC events
        now = datetime.now(tz)
        with sqlite3.connect(db_path) as conn:
            for i in range(4):
                peak_time = (now - timedelta(days=i)).replace(
                    hour=17, minute=0, second=0, microsecond=0
                )
                conn.execute(
                    """
                    INSERT INTO slot_observations (slot_start, slot_end, soc_end_percent)
                    VALUES (?, ?, ?)
                    """,
                    (peak_time.isoformat(), (peak_time + timedelta(minutes=15)).isoformat(), 3.0),
                )
            conn.commit()
        
        with patch.object(AuroraReflex, "__init__", lambda self, path: None):
            reflex = AuroraReflex.__new__(AuroraReflex)
            reflex.config = mock_config
            reflex.store = store
            reflex.timezone = tz
            reflex.learning_engine = MagicMock()
            
            updates, msg = reflex.analyze_safety()
            
            assert "s_index.base_factor" in updates
            new_value = updates["s_index.base_factor"]
            # Should increase by max_change (0.02) from 1.1 to 1.12
            assert new_value == 1.12

    def test_no_events_60d_relaxes_base_factor(self, temp_db, mock_config):
        """With no events in 60 days, should propose decrease."""
        db_path, store, tz = temp_db
        
        # No events inserted - database is empty
        
        with patch.object(AuroraReflex, "__init__", lambda self, path: None):
            reflex = AuroraReflex.__new__(AuroraReflex)
            reflex.config = mock_config
            reflex.store = store
            reflex.timezone = tz
            reflex.learning_engine = MagicMock()
            
            updates, msg = reflex.analyze_safety()
            
            assert "s_index.base_factor" in updates
            new_value = updates["s_index.base_factor"]
            # Should decrease by 0.01 (half of max_change) from 1.1 to 1.09
            assert new_value == 1.09

    def test_rate_limit_blocks_same_day_change(self, temp_db, mock_config):
        """Cannot change parameter twice on the same day."""
        db_path, store, tz = temp_db
        
        # Simulate a change made today
        store.update_reflex_state("s_index.base_factor", 1.12)
        
        with patch.object(AuroraReflex, "__init__", lambda self, path: None):
            reflex = AuroraReflex.__new__(AuroraReflex)
            reflex.config = mock_config
            reflex.store = store
            reflex.timezone = tz
            reflex.learning_engine = MagicMock()
            
            updates, msg = reflex.analyze_safety()
            
            assert updates == {}
            assert "Rate limited" in msg

    def test_respects_max_bound(self, temp_db, mock_config):
        """Should not exceed maximum bound."""
        db_path, store, tz = temp_db
        
        # Set current value to max
        mock_config["s_index"]["base_factor"] = 1.3
        
        # Insert events to trigger increase
        now = datetime.now(tz)
        with sqlite3.connect(db_path) as conn:
            for i in range(5):
                peak_time = (now - timedelta(days=i)).replace(
                    hour=17, minute=0, second=0, microsecond=0
                )
                conn.execute(
                    """
                    INSERT INTO slot_observations (slot_start, slot_end, soc_end_percent)
                    VALUES (?, ?, ?)
                    """,
                    (peak_time.isoformat(), (peak_time + timedelta(minutes=15)).isoformat(), 2.0),
                )
            conn.commit()
        
        with patch.object(AuroraReflex, "__init__", lambda self, path: None):
            reflex = AuroraReflex.__new__(AuroraReflex)
            reflex.config = mock_config
            reflex.store = store
            reflex.timezone = tz
            reflex.learning_engine = MagicMock()
            
            updates, msg = reflex.analyze_safety()
            
            # Should not propose change since already at max
            assert updates == {}
            assert "at max" in msg

    def test_respects_min_bound(self, temp_db, mock_config):
        """Should not go below minimum bound."""
        db_path, store, tz = temp_db
        
        # Set current value to min
        mock_config["s_index"]["base_factor"] = 1.0
        
        with patch.object(AuroraReflex, "__init__", lambda self, path: None):
            reflex = AuroraReflex.__new__(AuroraReflex)
            reflex.config = mock_config
            reflex.store = store
            reflex.timezone = tz
            reflex.learning_engine = MagicMock()
            
            updates, msg = reflex.analyze_safety()
            
            # Should not propose decrease since already at min
            assert updates == {}
            assert "at min" in msg or "Stable" in msg


class TestConstants:
    """Verify the constants are set correctly."""

    def test_bounds_for_base_factor(self):
        """base_factor bounds should be 1.0 to 1.3."""
        min_val, max_val = BOUNDS["s_index.base_factor"]
        assert min_val == 1.0
        assert max_val == 1.3

    def test_max_daily_change_for_base_factor(self):
        """Max daily change for base_factor should be 0.02."""
        assert MAX_DAILY_CHANGE["s_index.base_factor"] == 0.02

    def test_safety_thresholds(self):
        """Safety thresholds should match plan."""
        assert SAFETY_LOW_SOC_THRESHOLD == 5.0
        assert SAFETY_PEAK_HOURS == (16, 20)
        assert SAFETY_CRITICAL_EVENT_COUNT == 3
        assert SAFETY_RELAXATION_DAYS == 60
