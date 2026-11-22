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


class TestUnmeasuredDeviceMetricsAndHistory:
    @pytest.mark.asyncio
    async def test_load_mae_ignores_unmeasured_device_slots_and_history_flags_ev(self, tmp_path):
        import json

        from backend.learning.models import Base, SlotForecast, SlotObservation
        from backend.learning.store import LearningStore

        tz = pytz.timezone("Europe/Stockholm")
        store = LearningStore(str(tmp_path / "metrics.db"), tz)
        async with store.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        recent = (datetime.now(tz) - timedelta(hours=3)).replace(minute=0, second=0, microsecond=0)
        unknown_ev = json.dumps(
            {
                "recording": {
                    "components": {
                        "ev": {"method": "unknown", "owner": "recorder"},
                        "load": {"method": "derived_history", "owner": "recorder"},
                    }
                }
            }
        )
        async with store.AsyncSession() as session:
            for index, flags in enumerate([None, unknown_ev]):
                start = (recent + timedelta(minutes=15 * index)).isoformat()
                session.add(
                    SlotObservation(
                        slot_start=start,
                        slot_end=start,
                        load_kwh=1.0 if flags is None else 9.0,
                        quality_flags=flags,
                    )
                )
                session.add(
                    SlotForecast(
                        slot_start=start,
                        load_forecast_kwh=0.5,
                        base_load_forecast_kwh=0.5,
                        pv_forecast_kwh=0.0,
                        forecast_version="aurora",
                    )
                )
            await session.commit()

        # Only the measured slot counts: |1.0 - 0.5|, not the 9.0 kWh contaminated slot.
        metrics = await store.calculate_metrics(days_back=2)
        assert metrics["mae_load"] == pytest.approx(0.5)

        history = await store.get_history_range(
            recent - timedelta(hours=1), recent + timedelta(hours=1)
        )
        assert [row["actual_ev_available"] for row in history] == [True, False]
        assert all("quality_flags" not in row for row in history)
        await store.close()
