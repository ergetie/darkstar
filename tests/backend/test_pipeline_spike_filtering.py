"""Tests for analytical pipeline spike filtering (read-time hardening)."""

from datetime import datetime, timedelta

import pandas as pd
import pytest
import pytz

from backend.learning.models import Base


async def init_db_schema(store):
    """Initialize database schema for in-memory test database."""
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


class TestLearningStoreSpikeFiltering:
    """Test suite for LearningStore spike filtering in read paths."""

    @pytest.mark.asyncio
    async def test_get_forecast_vs_actual_excludes_spikes(self):
        """Test that get_forecast_vs_actual excludes spike rows."""
        from backend.learning.store import LearningStore

        tz = pytz.timezone("Europe/Stockholm")
        store = LearningStore(":memory:", tz)
        try:
            await store.ensure_wal_mode()
            await init_db_schema(store)

            now = datetime.now(tz)

            # Store observations with spike
            observations = [
                {
                    "slot_start": now,
                    "slot_end": now + timedelta(minutes=15),
                    "pv_kwh": 2.0,  # Valid
                    "load_kwh": 1.0,
                    "import_kwh": 0.5,
                },
                {
                    "slot_start": now + timedelta(minutes=15),
                    "slot_end": now + timedelta(minutes=30),
                    "pv_kwh": 50.0,  # Spike
                    "load_kwh": 10.0,
                    "import_kwh": 0.5,
                },
            ]
            await store.store_slot_observations(pd.DataFrame(observations))

            # Store forecasts
            forecasts = [
                {
                    "slot_start": now.isoformat(),
                    "pv_forecast_kwh": 2.0,
                    "openmeteo_pv_forecast_kwh": 2.0,
                    "load_forecast_kwh": 1.0,
                    "forecast_version": "aurora",
                },
                {
                    "slot_start": (now + timedelta(minutes=15)).isoformat(),
                    "pv_forecast_kwh": 2.0,
                    "openmeteo_pv_forecast_kwh": 2.0,
                    "load_forecast_kwh": 1.0,
                    "forecast_version": "aurora",
                },
            ]
            await store.store_forecasts(forecasts, "aurora")

            # Get forecast vs actual with max_kwh=4.0
            df = await store.get_forecast_vs_actual(days_back=1, target="pv", max_kwh=4.0)

            # Should only return 1 row (excluding spike)
            assert len(df) == 1
            assert df.iloc[0]["actual"] == 2.0
        finally:
            await store.close()

    @pytest.mark.asyncio
    async def test_get_forecast_vs_actual_no_filtering_without_max_kwh(self):
        """Test that get_forecast_vs_actual includes all rows when max_kwh is None."""
        from backend.learning.store import LearningStore

        tz = pytz.timezone("Europe/Stockholm")
        store = LearningStore(":memory:", tz)
        try:
            await store.ensure_wal_mode()
            await init_db_schema(store)

            now = datetime.now(tz)

            # Store observations with spike
            observations = [
                {
                    "slot_start": now,
                    "slot_end": now + timedelta(minutes=15),
                    "pv_kwh": 50.0,  # Spike
                    "load_kwh": 10.0,
                    "import_kwh": 0.5,
                },
            ]
            await store.store_slot_observations(pd.DataFrame(observations))

            # Store forecast
            forecasts = [
                {
                    "slot_start": now.isoformat(),
                    "pv_forecast_kwh": 2.0,
                    "openmeteo_pv_forecast_kwh": 2.0,
                    "load_forecast_kwh": 1.0,
                    "forecast_version": "aurora",
                },
            ]
            await store.store_forecasts(forecasts, "aurora")

            # Get forecast vs actual without max_kwh
            df = await store.get_forecast_vs_actual(days_back=1, target="pv", max_kwh=None)

            # Should return the spike row
            assert len(df) == 1
            assert df.iloc[0]["actual"] == 50.0
        finally:
            await store.close()

    @pytest.mark.asyncio
    async def test_calculate_metrics_excludes_spikes(self):
        """Test that calculate_metrics excludes spike rows from MAE calculation."""
        from backend.learning.store import LearningStore

        tz = pytz.timezone("Europe/Stockholm")
        store = LearningStore(":memory:", tz)
        try:
            await store.ensure_wal_mode()
            await init_db_schema(store)

            now = datetime.now(tz)

            # Store observations with spike
            observations = [
                {
                    "slot_start": now,
                    "slot_end": now + timedelta(minutes=15),
                    "pv_kwh": 2.0,  # Valid
                    "load_kwh": 1.0,
                    "import_kwh": 0.5,
                },
                {
                    "slot_start": now + timedelta(minutes=15),
                    "slot_end": now + timedelta(minutes=30),
                    "pv_kwh": 100.0,  # Huge spike
                    "load_kwh": 50.0,  # Huge spike
                    "import_kwh": 0.5,
                },
            ]
            await store.store_slot_observations(pd.DataFrame(observations))

            # Store forecasts
            forecasts = [
                {
                    "slot_start": now.isoformat(),
                    "pv_forecast_kwh": 2.0,
                    "openmeteo_pv_forecast_kwh": 2.0,
                    "load_forecast_kwh": 1.0,
                    "forecast_version": "aurora",
                },
                {
                    "slot_start": (now + timedelta(minutes=15)).isoformat(),
                    "pv_forecast_kwh": 2.0,
                    "openmeteo_pv_forecast_kwh": 2.0,
                    "load_forecast_kwh": 1.0,
                    "forecast_version": "aurora",
                },
            ]
            await store.store_forecasts(forecasts, "aurora")

            # Calculate metrics with max_kwh=4.0
            metrics = await store.calculate_metrics(days_back=1, max_kwh=4.0)

            # MAE should only consider valid rows
            # With spike filtering, the spike row (pv_kwh=100, load_kwh=50) should be excluded
            # leaving only the valid row (pv_kwh=2, load_kwh=1)
            # The exact MAE depends on forecast values, but spikes should be excluded
            assert (
                "mae_pv" not in metrics
                or metrics.get("mae_pv") is None
                or metrics.get("mae_pv") <= 2.0
            )
            assert (
                "mae_load" not in metrics
                or metrics.get("mae_load") is None
                or metrics.get("mae_load") <= 2.0
            )
        finally:
            await store.close()

    @pytest.mark.asyncio
    async def test_calculate_metrics_includes_spikes_without_max_kwh(self):
        """Test that calculate_metrics includes spike rows when max_kwh is None."""
        from backend.learning.store import LearningStore

        tz = pytz.timezone("Europe/Stockholm")
        store = LearningStore(":memory:", tz)
        try:
            await store.ensure_wal_mode()
            await init_db_schema(store)

            now = datetime.now(tz)

            # Store observations with spike
            observations = [
                {
                    "slot_start": now,
                    "slot_end": now + timedelta(minutes=15),
                    "pv_kwh": 100.0,  # Huge spike
                    "load_kwh": 50.0,
                    "import_kwh": 0.5,
                },
            ]
            await store.store_slot_observations(pd.DataFrame(observations))

            # Store forecast
            forecasts = [
                {
                    "slot_start": now.isoformat(),
                    "pv_forecast_kwh": 2.0,
                    "load_forecast_kwh": 1.0,
                    "forecast_version": "aurora",
                },
            ]
            await store.store_forecasts(forecasts, "aurora")

            # Calculate metrics without max_kwh
            metrics = await store.calculate_metrics(days_back=1, max_kwh=None)

            # MAE should include spike (100.0 - 2.0 = 98.0 error for PV, 50.0 - 1.0 = 49.0 for load)
            # Note: metrics may vary depending on data matching
            assert metrics.get("mae_pv") is not None
            assert metrics.get("mae_pv") >= 98.0  # At least the spike contribution
            assert metrics.get("mae_load") is not None
            assert metrics.get("mae_load") >= 49.0  # At least the spike contribution
        finally:
            await store.close()
