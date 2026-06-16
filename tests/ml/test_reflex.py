"""
Tests for Aurora Reflex: Phase A (Safety Analyzer) and Phase B (Confidence Analyzer)

Tests the analyzers which tune s_index.base_factor and forecasting.pv_confidence_percent
based on historical data.
"""

import contextlib
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent))
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import pytz

from backend.learning.models import Base
from backend.learning.reflex import (
    BOUNDS,
    CONFIDENCE_BIAS_THRESHOLD,
    CONFIDENCE_LOOKBACK_DAYS,
    CONFIDENCE_MIN_SAMPLES,
    MAX_DAILY_CHANGE,
    SAFETY_CRITICAL_EVENT_COUNT,
    SAFETY_LOW_SOC_THRESHOLD,
    SAFETY_PEAK_HOURS,
    SAFETY_RELAXATION_DAYS,
    AuroraReflex,
)
from backend.learning.store import LearningStore


@pytest_asyncio.fixture
async def temp_db():
    """Create a temporary SQLite database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    tz = pytz.timezone("Europe/Stockholm")
    store = LearningStore(db_path, tz)

    # Create schema using async engine
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield db_path, store, tz

    # Cleanup DB and threads
    await store.close()
    with contextlib.suppress(OSError):
        Path(db_path).unlink()


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

    @pytest.mark.asyncio
    async def test_no_events_returns_empty(self, temp_db):
        """When no low-SoC events exist, return empty list."""
        _db_path, store, _tz = temp_db

        events = await store.get_low_soc_events(days_back=30)
        assert events == []

    @pytest.mark.asyncio
    async def test_finds_low_soc_during_peak(self, temp_db):
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

        events = await store.get_low_soc_events(
            days_back=30,
            threshold_percent=SAFETY_LOW_SOC_THRESHOLD,
            peak_hours=SAFETY_PEAK_HOURS,
        )

        assert len(events) == 1
        assert events[0]["soc_end_percent"] == 3.5

    @pytest.mark.asyncio
    async def test_ignores_low_soc_outside_peak(self, temp_db):
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
                (
                    off_peak_time.isoformat(),
                    (off_peak_time + timedelta(minutes=15)).isoformat(),
                    2.0,
                ),
            )
            conn.commit()

        events = await store.get_low_soc_events(
            days_back=30,
            threshold_percent=SAFETY_LOW_SOC_THRESHOLD,
            peak_hours=SAFETY_PEAK_HOURS,
        )

        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_ignores_soc_above_threshold(self, temp_db):
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

        events = await store.get_low_soc_events(
            days_back=30,
            threshold_percent=SAFETY_LOW_SOC_THRESHOLD,
            peak_hours=SAFETY_PEAK_HOURS,
        )

        assert len(events) == 0


class TestReflexState:
    """Test the reflex_state rate limiting functionality."""

    @pytest.mark.asyncio
    async def test_get_reflex_state_none_when_new(self, temp_db):
        """New parameters should return None."""
        _db_path, store, _tz = temp_db

        state = await store.get_reflex_state("s_index.base_factor")
        assert state is None

    @pytest.mark.asyncio
    async def test_update_and_get_reflex_state(self, temp_db):
        """Can store and retrieve reflex state."""
        _db_path, store, _tz = temp_db

        await store.update_reflex_state("s_index.base_factor", 1.12)

        state = await store.get_reflex_state("s_index.base_factor")
        assert state is not None
        assert state["last_value"] == 1.12
        assert state["change_count"] == 1

    @pytest.mark.asyncio
    async def test_change_count_increments(self, temp_db):
        """Multiple updates should increment change_count."""
        _db_path, store, _tz = temp_db

        await store.update_reflex_state("s_index.base_factor", 1.12)
        await store.update_reflex_state("s_index.base_factor", 1.14)

        state = await store.get_reflex_state("s_index.base_factor")
        assert state["change_count"] == 2
        assert state["last_value"] == 1.14


class TestAnalyzeSafety:
    """Test the analyze_safety analyzer logic."""

    @pytest.mark.asyncio
    async def test_some_events_in_60d_is_stable(self, temp_db, mock_config):
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

            updates, msg = await reflex.analyze_safety()

            assert updates == {}
            assert "Stable" in msg or "2 events" in msg

    @pytest.mark.asyncio
    async def test_many_events_increases_base_factor(self, temp_db, mock_config):
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

            updates, _msg = await reflex.analyze_safety()

            assert "s_index.base_factor" in updates
            new_value = updates["s_index.base_factor"]
            # Should increase by max_change (0.02) from 1.1 to 1.12
            assert new_value == 1.12

    @pytest.mark.asyncio
    async def test_no_events_60d_relaxes_base_factor(self, temp_db, mock_config):
        """With no events in 60 days, should propose decrease."""
        _db_path, store, tz = temp_db

        # No events inserted - database is empty

        with patch.object(AuroraReflex, "__init__", lambda self, path: None):
            reflex = AuroraReflex.__new__(AuroraReflex)
            reflex.config = mock_config
            reflex.store = store
            reflex.timezone = tz
            reflex.learning_engine = MagicMock()

            updates, _msg = await reflex.analyze_safety()

            assert "s_index.base_factor" in updates
            new_value = updates["s_index.base_factor"]
            # Should decrease by 0.01 (half of max_change) from 1.1 to 1.09
            assert new_value == 1.09

    @pytest.mark.asyncio
    async def test_rate_limit_blocks_same_day_change(self, temp_db, mock_config):
        """Cannot change parameter twice on the same day."""
        _db_path, store, tz = temp_db

        # Simulate a change made today
        await store.update_reflex_state("s_index.base_factor", 1.12)

        with patch.object(AuroraReflex, "__init__", lambda self, path: None):
            reflex = AuroraReflex.__new__(AuroraReflex)
            reflex.config = mock_config
            reflex.store = store
            reflex.timezone = tz
            reflex.learning_engine = MagicMock()

            updates, msg = await reflex.analyze_safety()

            assert updates == {}
            assert "Rate limited" in msg

    @pytest.mark.asyncio
    async def test_respects_max_bound(self, temp_db, mock_config):
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

            updates, msg = await reflex.analyze_safety()

            # Should not propose change since already at max
            assert updates == {}
            assert "at max" in msg

    @pytest.mark.asyncio
    async def test_respects_min_bound(self, temp_db, mock_config):
        """Should not go below minimum bound."""
        _db_path, store, tz = temp_db

        # Set current value to min
        mock_config["s_index"]["base_factor"] = 1.0

        with patch.object(AuroraReflex, "__init__", lambda self, path: None):
            reflex = AuroraReflex.__new__(AuroraReflex)
            reflex.config = mock_config
            reflex.store = store
            reflex.timezone = tz
            reflex.learning_engine = MagicMock()

            updates, msg = await reflex.analyze_safety()

            # Should not propose decrease since already at min
            assert updates == {}
            assert "at min" in msg or "Stable" in msg


class TestForecastVsActualQuery:
    """Test the get_forecast_vs_actual query method."""

    @pytest.mark.asyncio
    async def test_no_data_returns_empty_df(self, temp_db):
        """When no forecast data exists, return empty DataFrame."""
        _db_path, store, _tz = temp_db

        df = await store.get_forecast_vs_actual(days_back=14, target="pv")
        assert len(df) == 0

    @pytest.mark.asyncio
    async def test_returns_matched_data(self, temp_db):
        """Should return matched forecast and observation data."""
        db_path, store, tz = temp_db

        now = datetime.now(tz)
        slot_time = now.replace(hour=12, minute=0, second=0, microsecond=0)

        with sqlite3.connect(db_path) as conn:
            # Insert observation
            conn.execute(
                """
                INSERT INTO slot_observations (slot_start, slot_end, pv_kwh)
                VALUES (?, ?, ?)
                """,
                (slot_time.isoformat(), (slot_time + timedelta(minutes=15)).isoformat(), 2.5),
            )
            # Insert forecast
            conn.execute(
                """
                INSERT INTO slot_forecasts (slot_start, pv_forecast_kwh, forecast_version)
                VALUES (?, ?, ?)
                """,
                (slot_time.isoformat(), 3.0, "aurora"),
            )
            conn.commit()

        df = await store.get_forecast_vs_actual(days_back=14, target="pv")

        assert len(df) == 1
        assert df.iloc[0]["forecast"] == 3.0
        assert df.iloc[0]["actual"] == 2.5
        assert df.iloc[0]["error"] == 0.5  # forecast - actual = 3.0 - 2.5


class TestAnalyzeConfidence:
    """Test the analyze_confidence analyzer logic."""

    def _insert_forecast_data(self, conn, tz, num_samples, bias):
        """Helper to insert forecast vs actual data with specified bias."""
        now = datetime.now(tz)
        for i in range(num_samples):
            slot_time = (now - timedelta(hours=i)).replace(minute=0, second=0, microsecond=0)
            actual = 1.0  # Fixed actual
            forecast = actual + bias  # Add bias to forecast

            conn.execute(
                """
                INSERT OR REPLACE INTO slot_observations (slot_start, slot_end, pv_kwh)
                VALUES (?, ?, ?)
                """,
                (slot_time.isoformat(), (slot_time + timedelta(minutes=15)).isoformat(), actual),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO slot_forecasts (slot_start, pv_forecast_kwh, forecast_version)
                VALUES (?, ?, ?)
                """,
                (slot_time.isoformat(), forecast, "aurora"),
            )
        conn.commit()

    @pytest.mark.asyncio
    async def test_insufficient_data_no_change(self, temp_db, mock_config):
        """With insufficient data, should not make changes."""
        db_path, store, tz = temp_db

        # Insert fewer than CONFIDENCE_MIN_SAMPLES
        with sqlite3.connect(db_path) as conn:
            self._insert_forecast_data(conn, tz, 50, 0.0)

        with patch.object(AuroraReflex, "__init__", lambda self, path: None):
            reflex = AuroraReflex.__new__(AuroraReflex)
            reflex.config = mock_config
            reflex.store = store
            reflex.timezone = tz
            reflex.learning_engine = MagicMock()

            updates, msg = await reflex.analyze_confidence()

            assert updates == {}
            assert "Insufficient data" in msg

    @pytest.mark.asyncio
    async def test_over_prediction_lowers_confidence(self, temp_db, mock_config):
        """Systematic over-prediction should lower confidence."""
        db_path, store, tz = temp_db

        # Insert data with positive bias (over-prediction)
        with sqlite3.connect(db_path) as conn:
            self._insert_forecast_data(conn, tz, 150, 0.8)  # bias > 0.5

        with patch.object(AuroraReflex, "__init__", lambda self, path: None):
            reflex = AuroraReflex.__new__(AuroraReflex)
            reflex.config = mock_config
            reflex.store = store
            reflex.timezone = tz
            reflex.learning_engine = MagicMock()

            updates, msg = await reflex.analyze_confidence()

            assert "forecasting.pv_confidence_percent" in updates
            new_value = updates["forecasting.pv_confidence_percent"]
            # Should decrease by max_change (5.0) from 90 to 85
            assert new_value == 85.0
            assert "Over-predicting" in msg

    @pytest.mark.asyncio
    async def test_under_prediction_raises_confidence(self, temp_db, mock_config):
        """Systematic under-prediction should raise confidence."""
        db_path, store, tz = temp_db

        # Insert data with negative bias (under-prediction)
        with sqlite3.connect(db_path) as conn:
            self._insert_forecast_data(conn, tz, 150, -0.8)  # bias < -0.5

        with patch.object(AuroraReflex, "__init__", lambda self, path: None):
            reflex = AuroraReflex.__new__(AuroraReflex)
            reflex.config = mock_config
            reflex.store = store
            reflex.timezone = tz
            reflex.learning_engine = MagicMock()

            updates, msg = await reflex.analyze_confidence()

            assert "forecasting.pv_confidence_percent" in updates
            new_value = updates["forecasting.pv_confidence_percent"]
            # Should increase by max_change (5.0) from 90 to 95
            assert new_value == 95.0
            assert "Under-predicting" in msg

    @pytest.mark.asyncio
    async def test_small_bias_is_stable(self, temp_db, mock_config):
        """Small bias within threshold should be stable."""
        db_path, store, tz = temp_db

        # Insert data with small bias
        with sqlite3.connect(db_path) as conn:
            self._insert_forecast_data(conn, tz, 150, 0.3)  # |bias| < 0.5

        with patch.object(AuroraReflex, "__init__", lambda self, path: None):
            reflex = AuroraReflex.__new__(AuroraReflex)
            reflex.config = mock_config
            reflex.store = store
            reflex.timezone = tz
            reflex.learning_engine = MagicMock()

            updates, msg = await reflex.analyze_confidence()

            assert updates == {}
            assert "Stable" in msg

    @pytest.mark.asyncio
    async def test_respects_confidence_bounds(self, temp_db, mock_config):
        """Should not go below 80% or above 100%."""
        db_path, store, tz = temp_db

        # Set to old max (100)
        mock_config["forecasting"]["pv_confidence_percent"] = 120

        # Insert data with negative bias (would want to increase)
        with sqlite3.connect(db_path) as conn:
            self._insert_forecast_data(conn, tz, 150, -0.8)

        with patch.object(AuroraReflex, "__init__", lambda self, path: None):
            reflex = AuroraReflex.__new__(AuroraReflex)
            reflex.config = mock_config
            reflex.store = store
            reflex.timezone = tz
            reflex.learning_engine = MagicMock()

            updates, msg = await reflex.analyze_confidence()

            assert updates == {}
            assert "at max" in msg


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

    def test_confidence_thresholds(self):
        """Confidence thresholds should match plan."""
        assert CONFIDENCE_BIAS_THRESHOLD == 0.5
        assert CONFIDENCE_MIN_SAMPLES == 100
        assert CONFIDENCE_LOOKBACK_DAYS == 14

        min_val, max_val = BOUNDS["forecasting.pv_confidence_percent"]
        assert min_val == 70
        assert max_val == 120

    def test_cycle_cost_is_not_reflex_tunable(self):
        """battery_cycle_cost_kwh should be owned by config, not Reflex."""
        param = "battery_economics.battery_cycle_cost_kwh"
        assert param not in BOUNDS
        assert param not in MAX_DAILY_CHANGE


class TestReflexRunIntegrity:
    @pytest.mark.asyncio
    async def test_run_never_proposes_cycle_cost_update(self, mock_config):
        with patch.object(AuroraReflex, "__init__", lambda self, path: None):
            reflex = AuroraReflex.__new__(AuroraReflex)
            reflex.config = mock_config
            reflex.analyze_safety = AsyncMock(return_value=({}, "Safety: Stable"))
            reflex.analyze_confidence = AsyncMock(return_value=({}, "Confidence: Stable"))
            reflex.analyze_capacity = AsyncMock(
                return_value=({"battery.capacity_kwh": 33.7}, "Capacity: Fade detected")
            )
            reflex.update_config = AsyncMock()

            report = await reflex.run(dry_run=True)

            assert not hasattr(reflex, "analyze_roi")
            reflex.update_config.assert_awaited_once()
            updates = reflex.update_config.await_args.args[0]
            assert "battery_economics.battery_cycle_cost_kwh" not in updates
            assert all("ROI" not in message for message in report)


class TestCapacityEstimate:
    """Test the get_capacity_estimate query method."""

    @pytest.mark.asyncio
    async def test_insufficient_data_returns_none(self, temp_db):
        """With insufficient data, should return None."""
        _db_path, store, _tz = temp_db

        estimated = await store.get_capacity_estimate(days_back=30)
        assert estimated is None

    @pytest.mark.asyncio
    async def test_estimates_capacity(self, temp_db):
        """Should estimate capacity from discharge data."""
        db_path, store, tz = temp_db

        now = datetime.now(tz)

        # Insert discharge observations
        # If we discharge 3.0 kWh and SoC drops from 50% to 40%,
        # capacity ≈ 3.0 / 0.10 = 30 kWh
        with sqlite3.connect(db_path) as conn:
            for i in range(20):
                slot_time = (now - timedelta(hours=i)).replace(minute=0, second=0, microsecond=0)
                conn.execute(
                    """
                    INSERT INTO slot_observations
                        (slot_start, slot_end, soc_start_percent, soc_end_percent, batt_discharge_kwh)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        slot_time.isoformat(),
                        (slot_time + timedelta(minutes=15)).isoformat(),
                        50.0 - i * 0.5,
                        45.0 - i * 0.5,
                        1.5,
                    ),  # ~5% drop, 1.5 kWh = 30 kWh capacity
                )
            conn.commit()

        estimated = await store.get_capacity_estimate(days_back=30)

        # Should estimate around 30 kWh
        assert estimated is not None
        assert 25 < estimated < 35


class TestAnalyzeCapacity:
    """Test the analyze_capacity analyzer logic."""

    @pytest.mark.asyncio
    async def test_insufficient_data_no_change(self, temp_db, mock_config):
        """With insufficient data, should not make changes."""
        _db_path, store, tz = temp_db

        with patch.object(AuroraReflex, "__init__", lambda self, path: None):
            reflex = AuroraReflex.__new__(AuroraReflex)
            reflex.config = mock_config
            reflex.store = store
            reflex.timezone = tz
            reflex.learning_engine = MagicMock()

            updates, msg = await reflex.analyze_capacity()

            assert updates == {}
            assert "Insufficient data" in msg

    @pytest.mark.asyncio
    async def test_healthy_capacity_no_change(self, temp_db, mock_config):
        """When capacity is healthy, should not make changes."""
        db_path, store, tz = temp_db

        # Set configured capacity
        mock_config["battery"]["capacity_kwh"] = 34.0

        now = datetime.now(tz)

        # Insert data showing healthy capacity (~34 kWh)
        with sqlite3.connect(db_path) as conn:
            for i in range(20):
                slot_time = (now - timedelta(hours=i)).replace(minute=0, second=0, microsecond=0)
                # 3.4 kWh per 10% = 34 kWh capacity
                conn.execute(
                    """
                    INSERT INTO slot_observations
                        (slot_start, slot_end, soc_start_percent, soc_end_percent, batt_discharge_kwh)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        slot_time.isoformat(),
                        (slot_time + timedelta(minutes=15)).isoformat(),
                        50.0,
                        40.0,
                        3.4,
                    ),  # 10% drop, 3.4 kWh = 34 kWh capacity
                )
            conn.commit()

        with patch.object(AuroraReflex, "__init__", lambda self, path: None):
            reflex = AuroraReflex.__new__(AuroraReflex)
            reflex.config = mock_config
            reflex.store = store
            reflex.timezone = tz
            reflex.learning_engine = MagicMock()

            updates, msg = await reflex.analyze_capacity()

            assert updates == {}
            assert "Healthy" in msg
