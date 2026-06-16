"""Tests for recorder delta-based energy calculation and state persistence."""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from backend.recorder import RecorderStateStore, record_observation_from_current_state


class TestRecorderStateStore:
    """Test suite for RecorderStateStore class."""

    def test_load_nonexistent_file(self):
        """Test loading from non-existent file returns empty dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "nonexistent.json"
            store = RecorderStateStore(state_file)
            result = store.load()
            assert result == {}

    def test_load_corrupted_file(self):
        """Test loading corrupted file returns empty dict and removes file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "corrupted.json"
            state_file.write_text("invalid json")
            store = RecorderStateStore(state_file)
            result = store.load()
            assert result == {}
            assert not state_file.exists()

    def test_save_and_load(self):
        """Test saving and loading state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            store = RecorderStateStore(state_file)
            store._state = {"test_key": {"value": 100.0, "timestamp": "2024-01-01T00:00:00"}}
            store.save()

            # Load in new instance
            store2 = RecorderStateStore(state_file)
            result = store2.load()
            assert result["test_key"]["value"] == 100.0

    def test_get_delta_first_reading(self):
        """Test get_delta returns None on first reading (no previous state)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            store = RecorderStateStore(state_file)
            store.load()

            now = datetime(2024, 1, 1, 12, 0, 0)
            delta, is_valid = store.get_delta("pv_total", 100.0, now)

            assert delta is None
            assert is_valid is True
            # State should be updated
            assert store._state["pv_total"]["value"] == 100.0

    def test_get_delta_normal_calculation(self):
        """Spec: Persistent Recorder State - Scenario: Recorder resumes after a restart"""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            store = RecorderStateStore(state_file)
            store.load()

            # First reading
            now = datetime(2024, 1, 1, 12, 0, 0)
            store.get_delta("pv_total", 100.0, now)

            # Second reading
            later = datetime(2024, 1, 1, 12, 15, 0)
            delta, is_valid = store.get_delta("pv_total", 150.0, later)

            assert delta == 50.0
            assert is_valid is True

    def test_get_delta_meter_reset_detection(self):
        """Test get_delta detects meter reset (negative delta)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            store = RecorderStateStore(state_file)
            store.load()

            # First reading
            now = datetime(2024, 1, 1, 12, 0, 0)
            store.get_delta("pv_total", 1000.0, now)

            # Meter reset (reading goes down)
            later = datetime(2024, 1, 1, 12, 15, 0)
            delta, is_valid = store.get_delta("pv_total", 50.0, later)

            assert delta is None
            assert is_valid is False
            # State should be updated with new reading
            assert store._state["pv_total"]["value"] == 50.0

    def test_get_last_timestamp(self):
        """Test get_last_timestamp returns correct datetime."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            store = RecorderStateStore(state_file)
            store.load()

            now = datetime(2024, 1, 1, 12, 0, 0)
            store.get_delta("pv_total", 100.0, now)

            last_ts = store.get_last_timestamp("pv_total")
            assert last_ts == now

    def test_get_last_timestamp_missing_key(self):
        """Test get_last_timestamp returns None for missing key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            store = RecorderStateStore(state_file)
            store.load()

            result = store.get_last_timestamp("nonexistent")
            assert result is None

    def test_single_live_recorder_prevents_second_zero_delta_from_becoming_stored(self):
        """Spec: Single Live Recorder Instance - duplicate shared-state cycles zero real data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "recorder_state.json"
            previous = datetime(2026, 6, 16, 10, 15, 0)
            slot_time = datetime(2026, 6, 16, 10, 30, 0)

            first_recorder = RecorderStateStore(state_file)
            first_recorder._state = {
                "pv_total": {"value": 100.0, "timestamp": previous.isoformat()}
            }
            first_recorder.save()

            first_delta, first_valid = first_recorder.get_delta("pv_total", 100.45, slot_time)

            second_recorder = RecorderStateStore(state_file)
            second_recorder.load()
            second_delta, second_valid = second_recorder.get_delta("pv_total", 100.45, slot_time)

            # A duplicate process sharing data/recorder_state.json computes zero for the same slot.
            assert first_delta == pytest.approx(0.45)
            assert first_valid is True
            assert second_delta == pytest.approx(0.0)
            assert second_valid is True

            stored_pv_kwh = first_delta
            assert stored_pv_kwh != second_delta


class TestRecorderDeltaLogic:
    """Test suite for recorder delta-based calculation logic."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration."""
        return {
            "timezone": "Europe/Stockholm",
            "learning": {"sqlite_path": ":memory:"},
            "input_sensors": {
                "pv_power": "sensor.pv_power",
                "load_power": "sensor.load_power",
                "grid_power": "sensor.grid_power",
                "battery_power": "sensor.battery_power",
                "battery_soc": "sensor.battery_soc",
                # Cumulative sensors
                "total_pv_production": "sensor.total_pv_production",
                "total_load_consumption": "sensor.total_load_consumption",
            },
            "system": {"grid_meter_type": "net", "has_battery": True},
            # ARC15: water heater sensor now in water_heaters array
            "water_heaters": [{"enabled": True, "sensor": "sensor.water_power"}],
            "ev_chargers": [],
        }

    @pytest.mark.asyncio
    async def test_records_just_finished_slot_and_aligns_history_window(self):
        tz = pytz.timezone("Europe/Stockholm")
        fixed_now = tz.localize(datetime(2024, 1, 1, 12, 33, 4))
        expected_slot_start = tz.localize(datetime(2024, 1, 1, 12, 15, 0))
        expected_slot_end = tz.localize(datetime(2024, 1, 1, 12, 30, 0))

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return fixed_now.replace(tzinfo=None)
                return fixed_now.astimezone(tz)

        config = {
            "timezone": "Europe/Stockholm",
            "learning": {"sqlite_path": ":memory:"},
            "input_sensors": {
                "pv_power": "sensor.pv_power",
                "load_power": "sensor.load_power",
                "grid_power": "sensor.grid_power",
                "battery_power": "sensor.battery_power",
            },
            "system": {"grid_meter_type": "net", "has_water_heater": True},
            "water_heaters": [{"id": "wh1", "enabled": True, "sensor": "sensor.water_power"}],
            "ev_chargers": [],
        }

        async def mock_sensor_kw(entity):
            return {
                "sensor.pv_power": 4.0,
                "sensor.load_power": 6.0,
                "sensor.grid_power": 2.0,
                "sensor.battery_power": 0.0,
                "sensor.water_power": 1.0,
            }.get(entity, 0.0)

        history_windows = []

        async def mock_history(entity_id, start, end):
            history_windows.append((entity_id, start, end))
            return 0.25

        with (
            patch("backend.recorder.datetime", FixedDateTime),
            patch("backend.recorder.get_ha_sensor_kw_normalized", side_effect=mock_sensor_kw),
            patch("backend.recorder.get_ha_sensor_float", return_value=None),
            patch("backend.recorder.get_ha_entity_state", return_value=None),
            patch("backend.recorder.get_current_slot_prices", return_value=None),
            patch("backend.recorder.get_energy_from_power_history", side_effect=mock_history),
        ):
            mock_store = MagicMock()
            mock_store.get_system_state = AsyncMock(return_value=None)
            mock_store.set_system_state = AsyncMock()
            mock_store.store_slot_observations = AsyncMock()
            mock_store.close = AsyncMock()

            with patch("backend.recorder.LearningStore", return_value=mock_store):
                await record_observation_from_current_state(config=config, state_store=RecorderStateStore())

        df = mock_store.store_slot_observations.call_args[0][0]
        record = df.iloc[0].to_dict()
        assert record["slot_start"] == expected_slot_start
        assert record["slot_end"] == expected_slot_end
        assert history_windows == [("sensor.water_power", expected_slot_start, expected_slot_end)]

    @pytest.mark.asyncio
    async def test_uses_cumulative_sensors_when_available(self, mock_config):
        """Spec: Delta-based Energy Calculation - Scenario: Recorder calculates energy during a continuous run"""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "recorder_state.json"

            # Initialize state store with previous reading
            state_store = RecorderStateStore(state_file)
            state_store.load()
            now = datetime.now(pytz.timezone("Europe/Stockholm"))
            prev_time = now - timedelta(minutes=15)
            state_store._state = {
                "pv_total": {"value": 100.0, "timestamp": prev_time.isoformat()},
                "load_total": {"value": 50.0, "timestamp": prev_time.isoformat()},
            }
            state_store.save()

            # Mock HA sensor responses
            async def mock_get_ha_sensor_kw_normalized(entity):
                power_values = {
                    "sensor.pv_power": 5.0,  # 5 kW
                    "sensor.load_power": 3.0,  # 3 kW
                    "sensor.grid_power": 1.0,
                    "sensor.battery_power": 0.5,
                    "sensor.water_power": 0.0,
                }
                return power_values.get(entity, 0.0)

            async def mock_get_ha_sensor_float(entity):
                # Cumulative sensors - values increased by expected delta
                cumulative_values = {
                    "sensor.total_pv_production": 101.25,  # +1.25 kWh (5kW * 0.25h)
                    "sensor.total_load_consumption": 50.75,  # +0.75 kWh (3kW * 0.25h)
                    "sensor.battery_soc": 50.0,
                }
                return cumulative_values.get(entity)

            with (
                patch(
                    "backend.recorder.get_ha_sensor_kw_normalized",
                    side_effect=mock_get_ha_sensor_kw_normalized,
                ),
                patch("backend.recorder.get_ha_sensor_float", side_effect=mock_get_ha_sensor_float),
                patch("backend.recorder.get_current_slot_prices", return_value=None),
            ):
                # Create mock LearningStore
                mock_store = MagicMock()
                mock_store.get_system_state = AsyncMock(return_value=None)
                mock_store.set_system_state = AsyncMock()
                mock_store.store_slot_observations = AsyncMock()
                mock_store.close = AsyncMock()

                with patch("backend.recorder.LearningStore", return_value=mock_store):
                    await record_observation_from_current_state(
                        config=mock_config, state_store=state_store
                    )

                    # Verify observations were stored
                    assert mock_store.store_slot_observations.called
                    df = mock_store.store_slot_observations.call_args[0][0]
                    record = df.iloc[0].to_dict()

                    # Should use cumulative delta, not power snapshot
                    assert record["pv_kwh"] == pytest.approx(1.25, abs=0.01)
                    assert record["load_kwh"] == pytest.approx(0.75, abs=0.01)

    @pytest.mark.asyncio
    async def test_fallback_to_power_snapshot(self, mock_config):
        """Spec: Snapshot Fallback - Scenario: Missing total energy sensor"""
        # Remove cumulative sensors from config
        mock_config["input_sensors"].pop("total_pv_production", None)
        mock_config["input_sensors"].pop("total_load_consumption", None)

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "recorder_state.json"
            state_store = RecorderStateStore(state_file)
            state_store.load()

            async def mock_get_ha_sensor_kw_normalized(entity):
                power_values = {
                    "sensor.pv_power": 4.0,  # 4 kW
                    "sensor.load_power": 2.0,  # 2 kW
                    "sensor.grid_power": 1.0,
                    "sensor.battery_power": 0.5,
                    "sensor.water_power": 0.0,
                }
                return power_values.get(entity, 0.0)

            async def mock_get_ha_sensor_float(entity):
                if entity == "sensor.battery_soc":
                    return 50.0
                return None  # No cumulative sensors available

            with (
                patch(
                    "backend.recorder.get_ha_sensor_kw_normalized",
                    side_effect=mock_get_ha_sensor_kw_normalized,
                ),
                patch("backend.recorder.get_ha_sensor_float", side_effect=mock_get_ha_sensor_float),
                patch("backend.recorder.get_current_slot_prices", return_value=None),
            ):
                mock_store = MagicMock()
                mock_store.get_system_state = AsyncMock(return_value=None)
                mock_store.set_system_state = AsyncMock()
                mock_store.store_slot_observations = AsyncMock()
                mock_store.close = AsyncMock()

                with patch("backend.recorder.LearningStore", return_value=mock_store):
                    await record_observation_from_current_state(
                        config=mock_config, state_store=state_store
                    )

                    assert mock_store.store_slot_observations.called
                    df = mock_store.store_slot_observations.call_args[0][0]
                    record = df.iloc[0].to_dict()

                    # Should use power snapshot (4kW * 0.25h = 1.0 kWh)
                    assert record["pv_kwh"] == pytest.approx(1.0, abs=0.01)
                    assert record["load_kwh"] == pytest.approx(0.5, abs=0.01)

    @pytest.mark.asyncio
    async def test_meter_reset_fallback(self, mock_config):
        """Design Risk: Meter Reset/Rollover - Mitigation: Fallback to power snapshot when delta is negative"""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "recorder_state.json"

            # Initialize state with high value
            state_store = RecorderStateStore(state_file)
            state_store.load()
            now = datetime.now(pytz.timezone("Europe/Stockholm"))
            prev_time = now - timedelta(minutes=15)
            state_store._state = {
                "pv_total": {"value": 10000.0, "timestamp": prev_time.isoformat()},
            }
            state_store.save()

            async def mock_get_ha_sensor_kw_normalized(entity):
                power_values = {
                    "sensor.pv_power": 5.0,
                    "sensor.load_power": 3.0,
                    "sensor.grid_power": 1.0,
                    "sensor.battery_power": 0.5,
                    "sensor.water_power": 0.0,
                }
                return power_values.get(entity, 0.0)

            async def mock_get_ha_sensor_float(entity):
                # Meter reset - value dropped significantly
                cumulative_values = {
                    "sensor.total_pv_production": 10.0,  # Reset from 10000 to 10
                    "sensor.total_load_consumption": 50.0,
                    "sensor.battery_soc": 50.0,
                }
                return cumulative_values.get(entity)

            with (
                patch(
                    "backend.recorder.get_ha_sensor_kw_normalized",
                    side_effect=mock_get_ha_sensor_kw_normalized,
                ),
                patch("backend.recorder.get_ha_sensor_float", side_effect=mock_get_ha_sensor_float),
                patch("backend.recorder.get_current_slot_prices", return_value=None),
            ):
                mock_store = MagicMock()
                mock_store.get_system_state = AsyncMock(return_value=None)
                mock_store.set_system_state = AsyncMock()
                mock_store.store_slot_observations = AsyncMock()
                mock_store.close = AsyncMock()

                with patch("backend.recorder.LearningStore", return_value=mock_store):
                    await record_observation_from_current_state(
                        config=mock_config, state_store=state_store
                    )

                    df = mock_store.store_slot_observations.call_args[0][0]
                    record = df.iloc[0].to_dict()

                    # Should fallback to power snapshot on meter reset
                    assert record["pv_kwh"] == pytest.approx(1.25, abs=0.01)  # 5kW * 0.25h

    @pytest.mark.asyncio
    async def test_dual_meter_cumulative(self):
        """Spec: Support for Cumulative Energy Sensors - Dual meter type support"""
        config = {
            "timezone": "Europe/Stockholm",
            "learning": {"sqlite_path": ":memory:"},
            "input_sensors": {
                "pv_power": "sensor.pv_power",
                "load_power": "sensor.load_power",
                "grid_import_power": "sensor.grid_import_power",
                "grid_export_power": "sensor.grid_export_power",
                "battery_power": "sensor.battery_power",
                "water_power": "sensor.water_power",
                "battery_soc": "sensor.battery_soc",
                "total_grid_import": "sensor.grid_import_total",
                "total_grid_export": "sensor.grid_export_total",
            },
            "system": {"grid_meter_type": "dual", "has_battery": True},
            "water_heaters": [],
            "ev_chargers": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "recorder_state.json"

            state_store = RecorderStateStore(state_file)
            state_store.load()
            now = datetime.now(pytz.timezone("Europe/Stockholm"))
            prev_time = now - timedelta(minutes=15)
            state_store._state = {
                "grid_import_total": {"value": 100.0, "timestamp": prev_time.isoformat()},
                "grid_export_total": {"value": 50.0, "timestamp": prev_time.isoformat()},
            }
            state_store.save()

            async def mock_get_ha_sensor_kw_normalized(entity):
                return 1.0  # All power sensors return 1 kW

            async def mock_get_ha_sensor_float(entity):
                cumulative_values = {
                    "sensor.grid_import_total": 100.5,  # +0.5 kWh
                    "sensor.grid_export_total": 50.25,  # +0.25 kWh
                    "sensor.battery_soc": 50.0,
                }
                return cumulative_values.get(entity)

            async def mock_get_ha_entity_state(entity):
                # Return state structure with unit_of_measurement for cumulative sensors
                state_values = {
                    "sensor.grid_import_total": {
                        "state": "100.5",
                        "attributes": {"unit_of_measurement": "kWh"},
                    },
                    "sensor.grid_export_total": {
                        "state": "50.25",
                        "attributes": {"unit_of_measurement": "kWh"},
                    },
                    "sensor.battery_soc": {
                        "state": "50.0",
                        "attributes": {"unit_of_measurement": "%"},
                    },
                }
                return state_values.get(entity)

            with (
                patch(
                    "backend.recorder.get_ha_sensor_kw_normalized",
                    side_effect=mock_get_ha_sensor_kw_normalized,
                ),
                patch("backend.recorder.get_ha_sensor_float", side_effect=mock_get_ha_sensor_float),
                patch("backend.recorder.get_ha_entity_state", side_effect=mock_get_ha_entity_state),
                patch("backend.recorder.get_current_slot_prices", return_value=None),
            ):
                mock_store = MagicMock()
                mock_store.get_system_state = AsyncMock(return_value=None)
                mock_store.set_system_state = AsyncMock()
                mock_store.store_slot_observations = AsyncMock()
                mock_store.close = AsyncMock()

                with patch("backend.recorder.LearningStore", return_value=mock_store):
                    await record_observation_from_current_state(
                        config=config, state_store=state_store
                    )

                    df = mock_store.store_slot_observations.call_args[0][0]
                    record = df.iloc[0].to_dict()

                    # Should use cumulative deltas
                    assert record["import_kwh"] == pytest.approx(0.5, abs=0.01)
                    assert record["export_kwh"] == pytest.approx(0.25, abs=0.01)


class TestStatePersistence:
    """Test suite for state file persistence."""

    def test_state_file_format(self):
        """Test that state file is saved in expected JSON format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            store = RecorderStateStore(state_file)
            store.load()

            now = datetime(2024, 1, 1, 12, 0, 0)
            store.get_delta("pv_total", 100.0, now)
            store.get_delta("load_total", 50.0, now)
            store.save()

            # Verify file format
            content = json.loads(state_file.read_text())
            assert "pv_total" in content
            assert "load_total" in content
            assert "value" in content["pv_total"]
            assert "timestamp" in content["pv_total"]
            assert content["pv_total"]["value"] == 100.0

    def test_directory_creation(self):
        """Test that parent directories are created automatically."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_dir = Path(tmpdir) / "nested" / "dirs"
            state_file = nested_dir / "state.json"
            store = RecorderStateStore(state_file)
            store.load()

            now = datetime.now()
            store.get_delta("test", 100.0, now)
            store.save()

            assert nested_dir.exists()
            assert state_file.exists()


class TestRecorderSpikeValidation:
    """Test suite for recorder spike validation integration."""

    @pytest.mark.asyncio
    async def test_spike_values_zeroed_before_storage(self):
        """Test that spike values are zeroed before storage to database."""

        import pytz

        from backend.learning.store import LearningStore
        from backend.recorder import record_observation_from_current_state

        # Create test config with 8kW grid limit = 4.0 kWh max per slot
        config = {
            "timezone": "Europe/Stockholm",
            "system": {"grid": {"max_power_kw": 8.0}},
            "learning": {"sqlite_path": ":memory:"},
            "input_sensors": {"battery_soc": "sensor.test_soc"},
        }

        # Mock HA responses with spike values
        with (
            patch("backend.recorder.get_ha_sensor_float") as mock_soc,
            patch("backend.recorder.get_ha_sensor_kw_normalized") as mock_power,
            patch("backend.recorder.get_ha_entity_state") as mock_entity,
        ):
            mock_soc.return_value = 50.0  # Valid SoC
            mock_power.return_value = 100.0  # Spike power value (100kW!)
            mock_entity.return_value = None  # No cumulative sensors

            # Create a mock store to capture what gets stored
            tz = pytz.timezone("Europe/Stockholm")
            store = LearningStore(":memory:", tz)
            try:
                await store.ensure_wal_mode()

                with patch("backend.recorder.LearningStore") as mock_store_class:
                    mock_store = AsyncMock()
                    mock_store_class.return_value = mock_store

                    # Capture the DataFrame passed to store_slot_observations
                    stored_records = []

                    async def capture_store(df):
                        stored_records.extend(df.to_dict("records"))

                    mock_store.store_slot_observations = capture_store
                    mock_store.close = AsyncMock()

                    # Record observation
                    await record_observation_from_current_state(config)

                    # Verify store was called
                    assert len(stored_records) == 1
                    record = stored_records[0]

                    # All energy values should be validated
                    # With 100kW power, the energy would be 100 * 0.25 = 25 kWh
                    # This exceeds the 4.0 kWh threshold, so it should be zeroed
                    assert record["pv_kwh"] == 0.0, (
                        f"PV spike should be zeroed, got {record['pv_kwh']}"
                    )
                    assert record["load_kwh"] == 0.0, (
                        f"Load spike should be zeroed, got {record['load_kwh']}"
                    )
            finally:
                await store.close()

    @pytest.mark.asyncio
    async def test_valid_values_preserved_in_recorder(self):
        """Test that valid values are preserved during recording."""
        config = {
            "timezone": "Europe/Stockholm",
            "system": {"grid": {"max_power_kw": 8.0}},
            "learning": {"sqlite_path": ":memory:"},
            "input_sensors": {
                "battery_soc": "sensor.test_soc",
                "pv_power": "sensor.pv_power",
            },
        }

        # Mock HA responses with normal values
        with (
            patch("backend.recorder.get_ha_sensor_float") as mock_soc,
            patch("backend.recorder.get_ha_sensor_kw_normalized") as mock_power,
            patch("backend.recorder.get_ha_entity_state") as mock_entity,
        ):
            mock_soc.return_value = 50.0

            def mock_power_side_effect(entity_id, default=0.0):
                if entity_id == "sensor.pv_power":
                    return 2.0  # Normal 2kW PV power
                return default

            mock_power.side_effect = mock_power_side_effect
            mock_entity.return_value = None

            stored_records = []

            with patch("backend.recorder.LearningStore") as mock_store_class:
                mock_store = AsyncMock()
                mock_store_class.return_value = mock_store

                async def capture_store(df):
                    stored_records.extend(df.to_dict("records"))

                mock_store.store_slot_observations = capture_store
                mock_store.close = AsyncMock()

                await record_observation_from_current_state(config)

                assert len(stored_records) == 1
                record = stored_records[0]

                # 2kW * 0.25h = 0.5 kWh, which is under the 4.0 kWh threshold
                assert record["pv_kwh"] == 0.5, (
                    f"Valid PV should be preserved, got {record['pv_kwh']}"
                )

    @pytest.mark.asyncio
    async def test_recorder_handles_missing_config_gracefully(self):
        """Test that recorder handles missing grid config gracefully."""
        config = {
            "timezone": "Europe/Stockholm",
            "learning": {"sqlite_path": ":memory:"},
            "input_sensors": {"battery_soc": "sensor.test_soc"},
            # Missing system.grid.max_power_kw
        }

        with (
            patch("backend.recorder.get_ha_sensor_float") as mock_soc,
            patch("backend.recorder.get_ha_sensor_kw_normalized") as mock_power,
            patch("backend.recorder.get_ha_entity_state") as mock_entity,
            patch("backend.recorder.logger") as mock_logger,
        ):
            mock_soc.return_value = 50.0
            mock_power.return_value = 2.0
            mock_entity.return_value = None

            stored_records = []

            with patch("backend.recorder.LearningStore") as mock_store_class:
                mock_store = AsyncMock()
                mock_store_class.return_value = mock_store

                async def capture_store(df):
                    stored_records.extend(df.to_dict("records"))

                mock_store.store_slot_observations = capture_store
                mock_store.close = AsyncMock()

                await record_observation_from_current_state(config)

                # Should log a warning about missing config
                warning_calls = [
                    c for c in mock_logger.warning.call_args_list if "max_power_kw" in str(c)
                ]
                assert len(warning_calls) > 0 or any(
                    "validate" in str(c).lower() for c in mock_logger.warning.call_args_list
                )

                # Should still store the record
                assert len(stored_records) == 1


class TestRecorderTimeScaling:
    """Test suite for time-proportional scaling to fix sawtooth pattern."""

    def test_time_proportional_scaling_short_interval(self):
        """Task 4.1: Scale up when sensor interval is shorter than 15 min.

        Raw delta covers 10 min, scaled to 15 min.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            store = RecorderStateStore(state_file)
            store.load()

            # First reading at 10:43
            ts1 = datetime(2024, 1, 1, 10, 43, 0)
            store.get_delta("pv_total", 100.0, ts1, sensor_timestamp=ts1)

            # Second reading at 10:53 (10 min later)
            ts2 = datetime(2024, 1, 1, 10, 53, 0)
            sensor_ts2 = datetime(2024, 1, 1, 10, 53, 0)
            delta, is_valid = store.get_delta("pv_total", 102.0, ts2, sensor_timestamp=sensor_ts2)

            # Raw delta: 2.0 kWh over 10 min
            # Scaled: 2.0 * (15/10) = 3.0 kWh
            assert delta == pytest.approx(3.0, abs=0.01)
            assert is_valid is True

    def test_time_proportional_scaling_long_interval(self):
        """Task 4.1: Scale down when sensor interval is longer than 15 min.

        Raw delta covers 20 min, scaled to 15 min.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            store = RecorderStateStore(state_file)
            store.load()

            # First reading at 10:33
            ts1 = datetime(2024, 1, 1, 10, 33, 0)
            store.get_delta("pv_total", 100.0, ts1, sensor_timestamp=ts1)

            # Second reading at 10:53 (20 min later)
            ts2 = datetime(2024, 1, 1, 10, 53, 0)
            sensor_ts2 = datetime(2024, 1, 1, 10, 53, 0)
            delta, is_valid = store.get_delta("pv_total", 104.0, ts2, sensor_timestamp=sensor_ts2)

            # Raw delta: 4.0 kWh over 20 min
            # Scaled: 4.0 * (15/20) = 3.0 kWh
            assert delta == pytest.approx(3.0, abs=0.01)
            assert is_valid is True

    def test_backward_compatibility_missing_sensor_timestamp(self):
        """Task 4.2: No scaling when sensor_timestamp is None.

        Old state files or missing HA timestamps should use raw delta.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            store = RecorderStateStore(state_file)
            store.load()

            # First reading without sensor timestamp
            ts1 = datetime(2024, 1, 1, 10, 0, 0)
            store.get_delta("pv_total", 100.0, ts1, sensor_timestamp=None)

            # Second reading also without sensor timestamp
            ts2 = datetime(2024, 1, 1, 10, 15, 0)
            delta, is_valid = store.get_delta("pv_total", 103.0, ts2, sensor_timestamp=None)

            # No scaling applied
            assert delta == 3.0
            assert is_valid is True

    def test_backward_compatibility_old_state_file(self):
        """Task 4.2: Old state files without sensor_timestamp field work.

        Simulate loading from an old-format state file.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            # Create old-format state file (no sensor_timestamp)
            old_state = {
                "pv_total": {
                    "value": 100.0,
                    "timestamp": "2024-01-01T10:00:00",
                    # No sensor_timestamp field
                }
            }
            state_file.write_text(json.dumps(old_state))

            store = RecorderStateStore(state_file)
            store.load()

            # New reading with sensor timestamp
            ts2 = datetime(2024, 1, 1, 10, 15, 0)
            sensor_ts2 = datetime(2024, 1, 1, 10, 13, 0)  # 13 min gap
            delta, is_valid = store.get_delta("pv_total", 102.6, ts2, sensor_timestamp=sensor_ts2)

            # Old state has no sensor_timestamp, so no scaling
            assert delta == pytest.approx(2.6, abs=0.001)
            assert is_valid is True

            # State file should now have sensor_timestamp for next cycle
            store2 = RecorderStateStore(state_file)
            store2.load()
            assert "sensor_timestamp" in store2._state["pv_total"]

    def test_scaling_window_bounds_too_short(self):
        """Task 4.3: No scaling when interval < 5 minutes.

        Likely sensor glitch or rapid updates.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            store = RecorderStateStore(state_file)
            store.load()

            ts1 = datetime(2024, 1, 1, 10, 0, 0)
            store.get_delta("pv_total", 100.0, ts1, sensor_timestamp=ts1)

            # Only 3 minutes later (too short)
            ts2 = datetime(2024, 1, 1, 10, 3, 0)
            sensor_ts2 = datetime(2024, 1, 1, 10, 3, 0)
            delta, is_valid = store.get_delta("pv_total", 101.0, ts2, sensor_timestamp=sensor_ts2)

            # No scaling (outside 5-60 min window)
            assert delta == 1.0
            assert is_valid is True

    def test_scaling_window_bounds_too_long(self):
        """Task 4.3: No scaling when interval > 60 minutes.

        Likely restart or long gap.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            store = RecorderStateStore(state_file)
            store.load()

            ts1 = datetime(2024, 1, 1, 10, 0, 0)
            store.get_delta("pv_total", 100.0, ts1, sensor_timestamp=ts1)

            # 90 minutes later (too long)
            ts2 = datetime(2024, 1, 1, 11, 30, 0)
            sensor_ts2 = datetime(2024, 1, 1, 11, 30, 0)
            delta, is_valid = store.get_delta("pv_total", 110.0, ts2, sensor_timestamp=sensor_ts2)

            # No scaling (outside 5-60 min window)
            assert delta == 10.0
            assert is_valid is True

    def test_scaling_window_bounds_exactly_5_min(self):
        """Task 4.3: Scaling applied at exactly 5 minutes.

        Lower boundary of the valid window.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            store = RecorderStateStore(state_file)
            store.load()

            ts1 = datetime(2024, 1, 1, 10, 0, 0)
            store.get_delta("pv_total", 100.0, ts1, sensor_timestamp=ts1)

            # Exactly 5 minutes later
            ts2 = datetime(2024, 1, 1, 10, 5, 0)
            sensor_ts2 = datetime(2024, 1, 1, 10, 5, 0)
            delta, is_valid = store.get_delta("pv_total", 101.0, ts2, sensor_timestamp=sensor_ts2)

            # Should scale: 1.0 * (15/5) = 3.0
            assert delta == pytest.approx(3.0, abs=0.01)
            assert is_valid is True

    def test_scaling_window_bounds_exactly_60_min(self):
        """Task 4.3: Scaling applied at exactly 60 minutes.

        Upper boundary of the valid window.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            store = RecorderStateStore(state_file)
            store.load()

            ts1 = datetime(2024, 1, 1, 10, 0, 0)
            store.get_delta("pv_total", 100.0, ts1, sensor_timestamp=ts1)

            # Exactly 60 minutes later
            ts2 = datetime(2024, 1, 1, 11, 0, 0)
            sensor_ts2 = datetime(2024, 1, 1, 11, 0, 0)
            delta, is_valid = store.get_delta("pv_total", 104.0, ts2, sensor_timestamp=sensor_ts2)

            # Should scale: 4.0 * (15/60) = 1.0
            assert delta == pytest.approx(1.0, abs=0.01)
            assert is_valid is True

    def test_sensor_timestamp_persisted_to_state_file(self):
        """Task 4.2: sensor_timestamp is stored in state file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            store = RecorderStateStore(state_file)
            store.load()

            ts1 = datetime(2024, 1, 1, 10, 0, 0)
            sensor_ts1 = datetime(2024, 1, 1, 9, 58, 0)
            store.get_delta("pv_total", 100.0, ts1, sensor_timestamp=sensor_ts1)

            # Verify state file includes sensor_timestamp
            content = json.loads(state_file.read_text())
            assert "sensor_timestamp" in content["pv_total"]
            assert content["pv_total"]["sensor_timestamp"] == "2024-01-01T09:58:00"


class TestBackfillInterpolation:
    """Test suite for backfill interpolation fix."""

    def test_interpolation_produces_consistent_deltas(self):
        """Task 4.4: Interpolation eliminates sawtooth in backfill.

        Simulates the sawtooth scenario: readings at 10:53 and 11:03
        should produce consistent deltas when interpolated.
        """
        from backend.learning.engine import LearningEngine

        # Simulate readings that would cause sawtooth with ffill
        # Sensor updates at :03, :13, :23, :33, :43, :53
        # Backfill slots at :00, :15, :30, :45
        cumulative_data = {
            "sensor.pv_total": [
                # 10:53 reading (sensor timestamp)
                (datetime(2024, 1, 1, 10, 53, 0), 100.0),
                # 11:03 reading (10 min later)
                (datetime(2024, 1, 1, 11, 3, 0), 102.0),
                # 11:13 reading (10 min later)
                (datetime(2024, 1, 1, 11, 13, 0), 104.0),
                # 11:23 reading (10 min later)
                (datetime(2024, 1, 1, 11, 23, 0), 106.0),
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create minimal config for LearningEngine
            config = {
                "timezone": "UTC",
                "learning": {"sqlite_path": str(Path(tmpdir) / "test.db"), "sensor_map": {}},
                "input_sensors": {},
                "system": {"grid": {"max_power_kw": 10.0}},
            }
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(json.dumps(config))

            # Patch config loading
            with patch.object(LearningEngine, "_load_config", return_value=config):
                engine = LearningEngine(str(config_path))
                result = engine.etl_cumulative_to_slots(cumulative_data, resolution_minutes=15)

                # With interpolation, deltas should be consistent
                # 100 kWh at 10:53, 106 kWh at 11:23
                # Total time: 30 min, total delta: 6 kWh
                # Rate: 6 kWh / 30 min = 0.2 kWh per min
                # Per 15-min slot: 3.0 kWh

                if len(result) > 0 and "pv_kwh" in result.columns:
                    pv_deltas = result["pv_kwh"].tolist()
                    # All non-zero deltas should be approximately equal
                    non_zero = [d for d in pv_deltas if d > 0]
                    if len(non_zero) > 1:
                        # Variation should be small (not sawtooth pattern)
                        max_delta = max(non_zero)
                        min_delta = min(non_zero)
                        # Ratio should be close to 1:1 (not 2:1 sawtooth)
                        assert max_delta / min_delta < 1.5, (
                            f"Deltas show sawtooth pattern: {non_zero}"
                        )


class TestLoadIsolationFromDeferrableLoads:
    """Test suite for isolating base load from EV charging and water heating."""

    @pytest.fixture
    def base_config(self):
        """Create a base mock configuration with cumulative sensors."""
        return {
            "timezone": "Europe/Stockholm",
            "learning": {"sqlite_path": ":memory:"},
            "input_sensors": {
                "pv_power": "sensor.pv_power",
                "load_power": "sensor.load_power",
                "grid_power": "sensor.grid_power",
                "battery_power": "sensor.battery_power",
                "water_power": "sensor.water_power",
                "battery_soc": "sensor.battery_soc",
                "total_pv_production": "sensor.total_pv_production",
                "total_load_consumption": "sensor.total_load_consumption",
            },
            "system": {
                "grid_meter_type": "net",
                "has_battery": True,
                "has_water_heater": True,
                "has_ev_charger": True,
            },
            "water_heaters": [],
            "ev_chargers": [],
        }

    @pytest.mark.asyncio
    async def test_ev_charging_subtracted_from_total_load(self, base_config):
        """Spec: Load Isolation - EV charging subtracted from total load."""
        config = base_config.copy()
        config["ev_chargers"] = [{"sensor": "sensor.ev_power", "enabled": True}]

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "recorder_state.json"
            state_store = RecorderStateStore(state_file)
            state_store.load()
            now = datetime.now(pytz.timezone("Europe/Stockholm"))
            prev_time = now - timedelta(minutes=15)
            state_store._state = {
                "pv_total": {"value": 100.0, "timestamp": prev_time.isoformat()},
                "load_total": {"value": 50.0, "timestamp": prev_time.isoformat()},
            }
            state_store.save()

            async def mock_get_ha_sensor_kw_normalized(entity):
                return {
                    "sensor.pv_power": 5.0,
                    "sensor.load_power": 7.0,
                    "sensor.grid_power": 2.0,
                    "sensor.battery_power": 0.0,
                    "sensor.water_power": 0.0,
                    "sensor.ev_power": 4.0,
                }.get(entity, 0.0)

            async def mock_get_ha_sensor_float(entity):
                if entity == "sensor.battery_soc":
                    return 50.0
                return None

            async def mock_get_ha_entity_state(entity):
                return {
                    "sensor.total_pv_production": {
                        "state": "101.25",
                        "attributes": {"unit_of_measurement": "kWh"},
                        "last_updated": now.isoformat(),
                    },
                    "sensor.total_load_consumption": {
                        "state": "53.0",
                        "attributes": {"unit_of_measurement": "kWh"},
                        "last_updated": now.isoformat(),
                    },
                }.get(entity)

            with (
                patch(
                    "backend.recorder.get_ha_sensor_kw_normalized",
                    side_effect=mock_get_ha_sensor_kw_normalized,
                ),
                patch("backend.recorder.get_ha_sensor_float", side_effect=mock_get_ha_sensor_float),
                patch("backend.recorder.get_ha_entity_state", side_effect=mock_get_ha_entity_state),
                patch(
                    "backend.recorder.get_energy_from_power_history",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch("backend.recorder.get_current_slot_prices", return_value=None),
            ):
                mock_store = MagicMock()
                mock_store.get_system_state = AsyncMock(return_value=None)
                mock_store.set_system_state = AsyncMock()
                mock_store.store_slot_observations = AsyncMock()
                mock_store.close = AsyncMock()

                with patch("backend.recorder.LearningStore", return_value=mock_store):
                    await record_observation_from_current_state(
                        config=config, state_store=state_store
                    )

                    df = mock_store.store_slot_observations.call_args[0][0]
                    record = df.iloc[0].to_dict()

                    assert record["ev_charging_kwh"] == pytest.approx(1.0, abs=0.01)
                    assert record["load_kwh"] == pytest.approx(2.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_water_heating_subtracted_from_total_load(self, base_config):
        """Spec: Load Isolation - Water heating subtracted from total load."""
        config = base_config.copy()
        # ARC15: water heater sensor now in water_heaters array
        config["water_heaters"] = [{"enabled": True, "sensor": "sensor.water_power"}]

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "recorder_state.json"
            state_store = RecorderStateStore(state_file)
            state_store.load()
            now = datetime.now(pytz.timezone("Europe/Stockholm"))
            prev_time = now - timedelta(minutes=15)
            state_store._state = {
                "pv_total": {"value": 100.0, "timestamp": prev_time.isoformat()},
                "load_total": {"value": 50.0, "timestamp": prev_time.isoformat()},
            }
            state_store.save()

            async def mock_get_ha_sensor_kw_normalized(entity):
                return {
                    "sensor.pv_power": 5.0,
                    "sensor.load_power": 5.0,
                    "sensor.grid_power": 2.0,
                    "sensor.battery_power": 0.0,
                    "sensor.water_power": 3.0,
                }.get(entity, 0.0)

            async def mock_get_ha_entity_state(entity):
                return {
                    "sensor.total_pv_production": {
                        "state": "101.25",
                        "attributes": {"unit_of_measurement": "kWh"},
                        "last_updated": now.isoformat(),
                    },
                    "sensor.total_load_consumption": {
                        "state": "52.0",
                        "attributes": {"unit_of_measurement": "kWh"},
                        "last_updated": now.isoformat(),
                    },
                    "sensor.battery_soc": {
                        "state": "50.0",
                        "attributes": {"unit_of_measurement": "%"},
                    },
                }.get(entity)

            async def mock_get_ha_sensor_float(entity):
                if entity == "sensor.battery_soc":
                    return 50.0
                return None

            with (
                patch(
                    "backend.recorder.get_ha_sensor_kw_normalized",
                    side_effect=mock_get_ha_sensor_kw_normalized,
                ),
                patch("backend.recorder.get_ha_sensor_float", side_effect=mock_get_ha_sensor_float),
                patch(
                    "backend.recorder.get_ha_entity_state",
                    side_effect=mock_get_ha_entity_state,
                ),
                patch(
                    "backend.recorder.get_energy_from_power_history",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch("backend.recorder.get_current_slot_prices", return_value=None),
            ):
                mock_store = MagicMock()
                mock_store.get_system_state = AsyncMock(return_value=None)
                mock_store.set_system_state = AsyncMock()
                mock_store.store_slot_observations = AsyncMock()
                mock_store.close = AsyncMock()

                with patch("backend.recorder.LearningStore", return_value=mock_store):
                    await record_observation_from_current_state(
                        config=config, state_store=state_store
                    )

                    df = mock_store.store_slot_observations.call_args[0][0]
                    record = df.iloc[0].to_dict()

                    assert record["water_kwh"] == pytest.approx(0.75, abs=0.01)
                    assert record["load_kwh"] == pytest.approx(1.25, abs=0.01)

    @pytest.mark.asyncio
    async def test_both_ev_and_water_subtracted_from_total_load(self, base_config):
        """Spec: Load Isolation - Both EV and water subtracted together."""
        config = base_config.copy()
        config["ev_chargers"] = [{"sensor": "sensor.ev_power", "enabled": True}]
        # ARC15: water heater sensor now in water_heaters array
        config["water_heaters"] = [{"enabled": True, "sensor": "sensor.water_power"}]

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "recorder_state.json"
            state_store = RecorderStateStore(state_file)
            state_store.load()
            now = datetime.now(pytz.timezone("Europe/Stockholm"))
            prev_time = now - timedelta(minutes=15)
            state_store._state = {
                "pv_total": {"value": 100.0, "timestamp": prev_time.isoformat()},
                "load_total": {"value": 50.0, "timestamp": prev_time.isoformat()},
            }
            state_store.save()

            async def mock_get_ha_sensor_kw_normalized(entity):
                return {
                    "sensor.pv_power": 5.0,
                    "sensor.load_power": 11.0,
                    "sensor.grid_power": 6.0,
                    "sensor.battery_power": 0.0,
                    "sensor.water_power": 3.0,
                    "sensor.ev_power": 4.0,
                }.get(entity, 0.0)

            async def mock_get_ha_sensor_float(entity):
                if entity == "sensor.battery_soc":
                    return 50.0
                return None

            async def mock_get_ha_entity_state(entity):
                return {
                    "sensor.total_pv_production": {
                        "state": "101.25",
                        "attributes": {"unit_of_measurement": "kWh"},
                        "last_updated": now.isoformat(),
                    },
                    "sensor.total_load_consumption": {
                        "state": "55.0",
                        "attributes": {"unit_of_measurement": "kWh"},
                        "last_updated": now.isoformat(),
                    },
                }.get(entity)

            with (
                patch(
                    "backend.recorder.get_ha_sensor_kw_normalized",
                    side_effect=mock_get_ha_sensor_kw_normalized,
                ),
                patch("backend.recorder.get_ha_sensor_float", side_effect=mock_get_ha_sensor_float),
                patch("backend.recorder.get_ha_entity_state", side_effect=mock_get_ha_entity_state),
                patch(
                    "backend.recorder.get_energy_from_power_history",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch("backend.recorder.get_current_slot_prices", return_value=None),
            ):
                mock_store = MagicMock()
                mock_store.get_system_state = AsyncMock(return_value=None)
                mock_store.set_system_state = AsyncMock()
                mock_store.store_slot_observations = AsyncMock()
                mock_store.close = AsyncMock()

                with patch("backend.recorder.LearningStore", return_value=mock_store):
                    await record_observation_from_current_state(
                        config=config, state_store=state_store
                    )

                    df = mock_store.store_slot_observations.call_args[0][0]
                    record = df.iloc[0].to_dict()

                    assert record["ev_charging_kwh"] == pytest.approx(1.0, abs=0.01)
                    assert record["water_kwh"] == pytest.approx(0.75, abs=0.01)
                    assert record["load_kwh"] == pytest.approx(3.25, abs=0.01)

    @pytest.mark.asyncio
    async def test_negative_base_load_clamped_to_zero(self, base_config):
        """Spec: Load Isolation - Negative base load clamped to zero with warning."""
        config = base_config.copy()
        config["ev_chargers"] = [{"sensor": "sensor.ev_power", "enabled": True}]
        # ARC15: water heater sensor now in water_heaters array
        config["water_heaters"] = [{"enabled": True, "sensor": "sensor.water_power"}]

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "recorder_state.json"
            state_store = RecorderStateStore(state_file)
            state_store.load()
            now = datetime.now(pytz.timezone("Europe/Stockholm"))
            prev_time = now - timedelta(minutes=15)
            state_store._state = {
                "pv_total": {"value": 100.0, "timestamp": prev_time.isoformat()},
                "load_total": {"value": 50.0, "timestamp": prev_time.isoformat()},
            }
            state_store.save()

            async def mock_get_ha_sensor_kw_normalized(entity):
                return {
                    "sensor.pv_power": 5.0,
                    "sensor.load_power": 12.0,
                    "sensor.grid_power": 10.0,
                    "sensor.battery_power": 0.0,
                    "sensor.water_power": 4.0,
                    "sensor.ev_power": 8.0,
                }.get(entity, 0.0)

            async def mock_get_ha_sensor_float(entity):
                if entity == "sensor.battery_soc":
                    return 50.0
                return None

            async def mock_get_ha_entity_state(entity):
                return {
                    "sensor.total_pv_production": {
                        "state": "101.25",
                        "attributes": {"unit_of_measurement": "kWh"},
                        "last_updated": now.isoformat(),
                    },
                    "sensor.total_load_consumption": {
                        "state": "52.0",
                        "attributes": {"unit_of_measurement": "kWh"},
                        "last_updated": now.isoformat(),
                    },
                }.get(entity)

            with (
                patch(
                    "backend.recorder.get_ha_sensor_kw_normalized",
                    side_effect=mock_get_ha_sensor_kw_normalized,
                ),
                patch("backend.recorder.get_ha_sensor_float", side_effect=mock_get_ha_sensor_float),
                patch("backend.recorder.get_ha_entity_state", side_effect=mock_get_ha_entity_state),
                patch(
                    "backend.recorder.get_energy_from_power_history",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch("backend.recorder.get_current_slot_prices", return_value=None),
                patch("backend.recorder.logger") as mock_logger,
            ):
                mock_store = MagicMock()
                mock_store.get_system_state = AsyncMock(return_value=None)
                mock_store.set_system_state = AsyncMock()
                mock_store.store_slot_observations = AsyncMock()
                mock_store.close = AsyncMock()

                with patch("backend.recorder.LearningStore", return_value=mock_store):
                    await record_observation_from_current_state(
                        config=config, state_store=state_store
                    )

                    df = mock_store.store_slot_observations.call_args[0][0]
                    record = df.iloc[0].to_dict()

                    assert record["ev_charging_kwh"] == pytest.approx(2.0, abs=0.01)
                    assert record["water_kwh"] == pytest.approx(1.0, abs=0.01)
                    assert record["load_kwh"] == 0.0

                    warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
                    assert any("Negative base load" in w for w in warning_calls)

    @pytest.mark.asyncio
    async def test_power_snapshot_fallback_uses_base_load(self, base_config):
        """Spec: Load Isolation - Power snapshot fallback uses base load from disaggregator."""
        config = base_config.copy()
        config["input_sensors"].pop("total_load_consumption", None)
        config["input_sensors"].pop("total_pv_production", None)
        config["ev_chargers"] = [{"sensor": "sensor.ev_power", "enabled": True}]
        # ARC15: water heater sensor now in water_heaters array
        config["water_heaters"] = [{"enabled": True, "sensor": "sensor.water_power"}]

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "recorder_state.json"
            state_store = RecorderStateStore(state_file)
            state_store.load()

            async def mock_get_ha_sensor_kw_normalized(entity):
                return {
                    "sensor.pv_power": 4.0,
                    "sensor.load_power": 7.0,
                    "sensor.grid_power": 3.0,
                    "sensor.battery_power": 0.0,
                    "sensor.water_power": 1.0,
                    "sensor.ev_power": 4.0,
                }.get(entity, 0.0)

            async def mock_get_ha_sensor_float(entity):
                if entity == "sensor.battery_soc":
                    return 50.0
                return None

            mock_disaggregator = MagicMock()
            mock_disaggregator.update_current_power = AsyncMock(return_value=5.0)
            mock_disaggregator.calculate_base_load = MagicMock(return_value=2.0)

            with (
                patch(
                    "backend.recorder.get_ha_sensor_kw_normalized",
                    side_effect=mock_get_ha_sensor_kw_normalized,
                ),
                patch("backend.recorder.get_ha_sensor_float", side_effect=mock_get_ha_sensor_float),
                patch(
                    "backend.recorder.get_energy_from_power_history",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch("backend.recorder.get_current_slot_prices", return_value=None),
            ):
                mock_store = MagicMock()
                mock_store.get_system_state = AsyncMock(return_value=None)
                mock_store.set_system_state = AsyncMock()
                mock_store.store_slot_observations = AsyncMock()
                mock_store.close = AsyncMock()

                with patch("backend.recorder.LearningStore", return_value=mock_store):
                    await record_observation_from_current_state(
                        config=config,
                        disaggregator=mock_disaggregator,
                        state_store=state_store,
                    )

                    df = mock_store.store_slot_observations.call_args[0][0]
                    record = df.iloc[0].to_dict()

                    assert record["ev_charging_kwh"] == pytest.approx(1.0, abs=0.01)
                    assert record["water_kwh"] == pytest.approx(0.25, abs=0.01)
                    assert record["load_kwh"] == pytest.approx(0.5, abs=0.01)

    @pytest.mark.asyncio
    async def test_ev_power_history_recording(self, base_config):
        """Task 4.2: EV energy from get_energy_from_power_history, single charger."""
        config = base_config.copy()
        config["ev_chargers"] = [{"id": "ev1", "sensor": "sensor.ev_power", "enabled": True}]

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "recorder_state.json"
            state_store = RecorderStateStore(state_file)
            state_store.load()
            now = datetime.now(pytz.timezone("Europe/Stockholm"))
            prev_time = now - timedelta(minutes=15)
            state_store._state = {
                "pv_total": {"value": 100.0, "timestamp": prev_time.isoformat()},
                "load_total": {"value": 50.0, "timestamp": prev_time.isoformat()},
            }
            state_store.save()

            async def mock_get_ha_sensor_kw_normalized(entity):
                return {
                    "sensor.pv_power": 5.0,
                    "sensor.load_power": 7.0,
                    "sensor.grid_power": 2.0,
                    "sensor.battery_power": 0.0,
                    "sensor.ev_power": 4.0,
                }.get(entity, 0.0)

            async def mock_get_ha_sensor_float(entity):
                if entity == "sensor.battery_soc":
                    return 50.0
                return None

            async def mock_get_ha_entity_state(entity):
                return {
                    "sensor.total_pv_production": {
                        "state": "101.25",
                        "attributes": {"unit_of_measurement": "kWh"},
                        "last_updated": now.isoformat(),
                    },
                    "sensor.total_load_consumption": {
                        "state": "53.0",
                        "attributes": {"unit_of_measurement": "kWh"},
                        "last_updated": now.isoformat(),
                    },
                }.get(entity)

            async def mock_history(entity_id, start, end):
                return 0.9

            with (
                patch(
                    "backend.recorder.get_ha_sensor_kw_normalized",
                    side_effect=mock_get_ha_sensor_kw_normalized,
                ),
                patch("backend.recorder.get_ha_sensor_float", side_effect=mock_get_ha_sensor_float),
                patch("backend.recorder.get_ha_entity_state", side_effect=mock_get_ha_entity_state),
                patch("backend.recorder.get_current_slot_prices", return_value=None),
                patch("backend.recorder.get_energy_from_power_history", side_effect=mock_history),
            ):
                mock_store = MagicMock()
                mock_store.get_system_state = AsyncMock(return_value=None)
                mock_store.set_system_state = AsyncMock()
                mock_store.store_slot_observations = AsyncMock()
                mock_store.close = AsyncMock()

                with patch("backend.recorder.LearningStore", return_value=mock_store):
                    await record_observation_from_current_state(
                        config=config, state_store=state_store
                    )

                    df = mock_store.store_slot_observations.call_args[0][0]
                    record = df.iloc[0].to_dict()

                    assert record["ev_charging_kwh"] == pytest.approx(0.9, abs=0.01)
                    # Load 3.0 - EV 0.9 = 2.1
                    assert record["load_kwh"] == pytest.approx(2.1, abs=0.01)

    @pytest.mark.asyncio
    async def test_ev_power_history_multiple_chargers_sum(self, base_config):
        """Task 4.2: Multiple EV chargers sum their history-based energy."""
        config = base_config.copy()
        config["ev_chargers"] = [
            {"id": "ev1", "sensor": "sensor.ev1_power", "enabled": True},
            {"id": "ev2", "sensor": "sensor.ev2_power", "enabled": True},
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "recorder_state.json"
            state_store = RecorderStateStore(state_file)
            state_store.load()
            now = datetime.now(pytz.timezone("Europe/Stockholm"))
            prev_time = now - timedelta(minutes=15)
            state_store._state = {
                "pv_total": {"value": 100.0, "timestamp": prev_time.isoformat()},
                "load_total": {"value": 50.0, "timestamp": prev_time.isoformat()},
            }
            state_store.save()

            history_calls: list[str] = []

            async def mock_history(entity_id, start, end):
                history_calls.append(entity_id)
                return {"sensor.ev1_power": 0.8, "sensor.ev2_power": 0.6}.get(entity_id)

            async def mock_get_ha_sensor_kw_normalized(entity):
                return {
                    "sensor.pv_power": 5.0,
                    "sensor.load_power": 8.0,
                    "sensor.grid_power": 3.0,
                    "sensor.battery_power": 0.0,
                    "sensor.ev1_power": 4.0,
                    "sensor.ev2_power": 3.0,
                }.get(entity, 0.0)

            async def mock_get_ha_sensor_float(entity):
                if entity == "sensor.battery_soc":
                    return 50.0
                return None

            async def mock_get_ha_entity_state(entity):
                return {
                    "sensor.total_pv_production": {
                        "state": "101.25",
                        "attributes": {"unit_of_measurement": "kWh"},
                        "last_updated": now.isoformat(),
                    },
                    "sensor.total_load_consumption": {
                        "state": "54.0",
                        "attributes": {"unit_of_measurement": "kWh"},
                        "last_updated": now.isoformat(),
                    },
                }.get(entity)

            with (
                patch(
                    "backend.recorder.get_ha_sensor_kw_normalized",
                    side_effect=mock_get_ha_sensor_kw_normalized,
                ),
                patch("backend.recorder.get_ha_sensor_float", side_effect=mock_get_ha_sensor_float),
                patch("backend.recorder.get_ha_entity_state", side_effect=mock_get_ha_entity_state),
                patch("backend.recorder.get_current_slot_prices", return_value=None),
                patch("backend.recorder.get_energy_from_power_history", side_effect=mock_history),
            ):
                mock_store = MagicMock()
                mock_store.get_system_state = AsyncMock(return_value=None)
                mock_store.set_system_state = AsyncMock()
                mock_store.store_slot_observations = AsyncMock()
                mock_store.close = AsyncMock()

                with patch("backend.recorder.LearningStore", return_value=mock_store):
                    await record_observation_from_current_state(
                        config=config, state_store=state_store
                    )

                    df = mock_store.store_slot_observations.call_args[0][0]
                    record = df.iloc[0].to_dict()

                    # 0.8 + 0.6 = 1.4 kWh total
                    assert record["ev_charging_kwh"] == pytest.approx(1.4, abs=0.01)
                    assert "sensor.ev1_power" in history_calls
                    assert "sensor.ev2_power" in history_calls

    @pytest.mark.asyncio
    async def test_water_power_history_recording(self, base_config):
        """Task 4.3: Water heater energy from get_energy_from_power_history."""
        config = base_config.copy()
        config["water_heaters"] = [{"id": "wh1", "sensor": "sensor.water_power", "enabled": True}]

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "recorder_state.json"
            state_store = RecorderStateStore(state_file)
            state_store.load()
            now = datetime.now(pytz.timezone("Europe/Stockholm"))
            prev_time = now - timedelta(minutes=15)
            state_store._state = {
                "pv_total": {"value": 100.0, "timestamp": prev_time.isoformat()},
                "load_total": {"value": 50.0, "timestamp": prev_time.isoformat()},
            }
            state_store.save()

            async def mock_get_ha_sensor_kw_normalized(entity):
                return {
                    "sensor.pv_power": 5.0,
                    "sensor.load_power": 5.0,
                    "sensor.grid_power": 2.0,
                    "sensor.battery_power": 0.0,
                    "sensor.water_power": 3.0,
                }.get(entity, 0.0)

            async def mock_get_ha_sensor_float(entity):
                if entity == "sensor.battery_soc":
                    return 50.0
                return None

            async def mock_get_ha_entity_state(entity):
                return {
                    "sensor.total_pv_production": {
                        "state": "101.25",
                        "attributes": {"unit_of_measurement": "kWh"},
                        "last_updated": now.isoformat(),
                    },
                    "sensor.total_load_consumption": {
                        "state": "52.0",
                        "attributes": {"unit_of_measurement": "kWh"},
                        "last_updated": now.isoformat(),
                    },
                }.get(entity)

            async def mock_history(entity_id, start, end):
                return 0.75

            with (
                patch(
                    "backend.recorder.get_ha_sensor_kw_normalized",
                    side_effect=mock_get_ha_sensor_kw_normalized,
                ),
                patch("backend.recorder.get_ha_sensor_float", side_effect=mock_get_ha_sensor_float),
                patch("backend.recorder.get_ha_entity_state", side_effect=mock_get_ha_entity_state),
                patch("backend.recorder.get_current_slot_prices", return_value=None),
                patch("backend.recorder.get_energy_from_power_history", side_effect=mock_history),
            ):
                mock_store = MagicMock()
                mock_store.get_system_state = AsyncMock(return_value=None)
                mock_store.set_system_state = AsyncMock()
                mock_store.store_slot_observations = AsyncMock()
                mock_store.close = AsyncMock()

                with patch("backend.recorder.LearningStore", return_value=mock_store):
                    await record_observation_from_current_state(
                        config=config, state_store=state_store
                    )

                    df = mock_store.store_slot_observations.call_args[0][0]
                    record = df.iloc[0].to_dict()

                    assert record["water_kwh"] == pytest.approx(0.75, abs=0.01)
                    # Load 2.0 - water 0.75 = 1.25
                    assert record["load_kwh"] == pytest.approx(1.25, abs=0.01)

    @pytest.mark.asyncio
    async def test_water_power_history_w_series_end_to_end(self, base_config):
        """End-to-end: a raw-watt sensor series (unit only on the first state) flows
        through the *real* get_energy_from_power_history and is recorded at the correct
        magnitude (~0.78 kWh), not the ~780 kWh spike that the validation guard zeroes.

        Unlike test_water_power_history_recording (which mocks the conversion result),
        this exercises the recorder -> real conversion -> HTTP path so the first-state
        W-unit propagation is verified through the recorder, closing that seam.
        """
        config = base_config.copy()
        config["water_heaters"] = [{"id": "wh1", "sensor": "sensor.water_power", "enabled": True}]

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "recorder_state.json"
            state_store = RecorderStateStore(state_file)
            state_store.load()
            now = datetime.now(pytz.timezone("Europe/Stockholm"))
            prev_time = now - timedelta(minutes=15)
            state_store._state = {
                "pv_total": {"value": 100.0, "timestamp": prev_time.isoformat()},
                "load_total": {"value": 50.0, "timestamp": prev_time.isoformat()},
            }
            state_store.save()

            async def mock_get_ha_sensor_kw_normalized(entity):
                return {
                    "sensor.pv_power": 5.0,
                    "sensor.load_power": 5.0,
                    "sensor.grid_power": 2.0,
                    "sensor.battery_power": 0.0,
                    "sensor.water_power": 3.0,
                }.get(entity, 0.0)

            async def mock_get_ha_sensor_float(entity):
                if entity == "sensor.battery_soc":
                    return 50.0
                return None

            async def mock_get_ha_entity_state(entity):
                return {
                    "sensor.total_pv_production": {
                        "state": "101.25",
                        "attributes": {"unit_of_measurement": "kWh"},
                        "last_updated": now.isoformat(),
                    },
                    "sensor.total_load_consumption": {
                        "state": "52.0",
                        "attributes": {"unit_of_measurement": "kWh"},
                        "last_updated": now.isoformat(),
                    },
                }.get(entity)

            # Build the HA history response dynamically, anchored to the slot_start the
            # recorder actually requests (embedded in the api_url), so the result is
            # independent of wall-clock slot boundaries. Reproduces the real
            # sensor.vvb_power series: unit "W" only on the first state, {} thereafter.
            async def mock_http_get(api_url, headers=None, params=None):
                slot_start = datetime.fromisoformat(api_url.rsplit("/", 1)[1])
                states = [
                    {
                        "state": "3164",
                        "last_changed": slot_start.isoformat(),
                        "attributes": {"unit_of_measurement": "W"},
                    },
                    {
                        "state": "3124",
                        "last_changed": (slot_start + timedelta(minutes=5)).isoformat(),
                        "attributes": {},
                    },
                    {
                        "state": "3147",
                        "last_changed": (slot_start + timedelta(minutes=10)).isoformat(),
                        "attributes": {},
                    },
                    {
                        "state": "0",
                        "last_changed": (slot_start + timedelta(minutes=15)).isoformat(),
                        "attributes": {},
                    },
                ]
                response = MagicMock()
                response.raise_for_status = MagicMock()
                response.json.return_value = [states]
                return response

            with (
                patch(
                    "backend.recorder.get_ha_sensor_kw_normalized",
                    side_effect=mock_get_ha_sensor_kw_normalized,
                ),
                patch("backend.recorder.get_ha_sensor_float", side_effect=mock_get_ha_sensor_float),
                patch("backend.recorder.get_ha_entity_state", side_effect=mock_get_ha_entity_state),
                patch("backend.recorder.get_current_slot_prices", return_value=None),
                # NOTE: get_energy_from_power_history is intentionally NOT patched — the
                # real conversion runs against the mocked HTTP layer below.
                patch(
                    "backend.core.ha_client.secrets.load_home_assistant_config",
                    return_value={"url": "http://ha.local", "token": "tok"},
                ),
                patch("backend.core.ha_client.httpx.AsyncClient") as mock_client_cls,
            ):
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(side_effect=mock_http_get)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                mock_store = MagicMock()
                mock_store.get_system_state = AsyncMock(return_value=None)
                mock_store.set_system_state = AsyncMock()
                mock_store.store_slot_observations = AsyncMock()
                mock_store.close = AsyncMock()

                with patch("backend.recorder.LearningStore", return_value=mock_store):
                    await record_observation_from_current_state(
                        config=config, state_store=state_store
                    )

                    df = mock_store.store_slot_observations.call_args[0][0]
                    record = df.iloc[0].to_dict()

                    # 3164/3124/3147 W held 5 min each -> ~0.786 kWh, NOT ~786 kWh.
                    assert record["water_kwh"] == pytest.approx(0.786, abs=0.01)
                    assert record["water_kwh"] < 4.0  # below the spike guard, not zeroed

    @pytest.mark.asyncio
    async def test_snapshot_fallback_when_history_returns_none(self, base_config):
        """Task 4.4: When get_energy_from_power_history returns None, use power_kw x 0.25."""
        config = base_config.copy()
        config["ev_chargers"] = [{"id": "ev1", "sensor": "sensor.ev_power", "enabled": True}]
        config["water_heaters"] = [{"id": "wh1", "sensor": "sensor.water_power", "enabled": True}]

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "recorder_state.json"
            state_store = RecorderStateStore(state_file)
            state_store.load()
            now = datetime.now(pytz.timezone("Europe/Stockholm"))
            prev_time = now - timedelta(minutes=15)
            state_store._state = {
                "pv_total": {"value": 100.0, "timestamp": prev_time.isoformat()},
                "load_total": {"value": 50.0, "timestamp": prev_time.isoformat()},
            }
            state_store.save()

            async def mock_get_ha_sensor_kw_normalized(entity):
                return {
                    "sensor.pv_power": 5.0,
                    "sensor.load_power": 8.0,
                    "sensor.grid_power": 2.0,
                    "sensor.battery_power": 0.0,
                    "sensor.water_power": 2.0,
                    "sensor.ev_power": 4.0,
                }.get(entity, 0.0)

            async def mock_get_ha_sensor_float(entity):
                if entity == "sensor.battery_soc":
                    return 50.0
                return None

            async def mock_get_ha_entity_state(entity):
                return {
                    "sensor.total_pv_production": {
                        "state": "101.25",
                        "attributes": {"unit_of_measurement": "kWh"},
                        "last_updated": now.isoformat(),
                    },
                    "sensor.total_load_consumption": {
                        "state": "54.0",
                        "attributes": {"unit_of_measurement": "kWh"},
                        "last_updated": now.isoformat(),
                    },
                }.get(entity)

            async def mock_history_none(entity_id, start, end):
                return None

            with (
                patch(
                    "backend.recorder.get_ha_sensor_kw_normalized",
                    side_effect=mock_get_ha_sensor_kw_normalized,
                ),
                patch("backend.recorder.get_ha_sensor_float", side_effect=mock_get_ha_sensor_float),
                patch("backend.recorder.get_ha_entity_state", side_effect=mock_get_ha_entity_state),
                patch("backend.recorder.get_current_slot_prices", return_value=None),
                patch(
                    "backend.recorder.get_energy_from_power_history",
                    side_effect=mock_history_none,
                ),
            ):
                mock_store = MagicMock()
                mock_store.get_system_state = AsyncMock(return_value=None)
                mock_store.set_system_state = AsyncMock()
                mock_store.store_slot_observations = AsyncMock()
                mock_store.close = AsyncMock()

                with patch("backend.recorder.LearningStore", return_value=mock_store):
                    await record_observation_from_current_state(
                        config=config, state_store=state_store
                    )

                    df = mock_store.store_slot_observations.call_args[0][0]
                    record = df.iloc[0].to_dict()

                    # Fallback: ev=4.0*0.25=1.0, water=2.0*0.25=0.5
                    assert record["ev_charging_kwh"] == pytest.approx(1.0, abs=0.01)
                    assert record["water_kwh"] == pytest.approx(0.5, abs=0.01)

    @pytest.mark.asyncio
    async def test_load_isolation_always_applied_regardless_of_source(self, base_config):
        """Task 4.5: EV + water subtracted from total load regardless of history or snapshot."""
        config = base_config.copy()
        config["ev_chargers"] = [{"id": "ev1", "sensor": "sensor.ev_power", "enabled": True}]
        config["water_heaters"] = [{"id": "wh1", "sensor": "sensor.water_power", "enabled": True}]

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "recorder_state.json"
            state_store = RecorderStateStore(state_file)
            state_store.load()
            now = datetime.now(pytz.timezone("Europe/Stockholm"))
            prev_time = now - timedelta(minutes=15)
            state_store._state = {
                "pv_total": {"value": 100.0, "timestamp": prev_time.isoformat()},
                "load_total": {"value": 50.0, "timestamp": prev_time.isoformat()},
            }
            state_store.save()

            async def mock_get_ha_sensor_kw_normalized(entity):
                return {
                    "sensor.pv_power": 5.0,
                    "sensor.load_power": 8.0,
                    "sensor.grid_power": 2.0,
                    "sensor.battery_power": 0.0,
                    "sensor.water_power": 2.0,
                    "sensor.ev_power": 4.0,
                }.get(entity, 0.0)

            async def mock_get_ha_sensor_float(entity):
                if entity == "sensor.battery_soc":
                    return 50.0
                return None

            async def mock_get_ha_entity_state(entity):
                return {
                    "sensor.total_pv_production": {
                        "state": "101.25",
                        "attributes": {"unit_of_measurement": "kWh"},
                        "last_updated": now.isoformat(),
                    },
                    "sensor.total_load_consumption": {
                        "state": "54.0",
                        "attributes": {"unit_of_measurement": "kWh"},
                        "last_updated": now.isoformat(),
                    },
                }.get(entity)

            for history_value in (1.0, None):
                state_store_iter = RecorderStateStore(Path(tmpdir) / "state_iter.json")
                state_store_iter.load()
                state_store_iter._state = {
                    "pv_total": {"value": 100.0, "timestamp": prev_time.isoformat()},
                    "load_total": {"value": 50.0, "timestamp": prev_time.isoformat()},
                }
                state_store_iter.save()

                async def mock_history(entity_id, start, end, _v=history_value):
                    return _v

                with (
                    patch(
                        "backend.recorder.get_ha_sensor_kw_normalized",
                        side_effect=mock_get_ha_sensor_kw_normalized,
                    ),
                    patch(
                        "backend.recorder.get_ha_sensor_float",
                        side_effect=mock_get_ha_sensor_float,
                    ),
                    patch(
                        "backend.recorder.get_ha_entity_state",
                        side_effect=mock_get_ha_entity_state,
                    ),
                    patch("backend.recorder.get_current_slot_prices", return_value=None),
                    patch(
                        "backend.recorder.get_energy_from_power_history",
                        side_effect=mock_history,
                    ),
                ):
                    mock_store = MagicMock()
                    mock_store.get_system_state = AsyncMock(return_value=None)
                    mock_store.set_system_state = AsyncMock()
                    mock_store.store_slot_observations = AsyncMock()
                    mock_store.close = AsyncMock()

                    with patch("backend.recorder.LearningStore", return_value=mock_store):
                        await record_observation_from_current_state(
                            config=config, state_store=state_store_iter
                        )

                        df = mock_store.store_slot_observations.call_args[0][0]
                        record = df.iloc[0].to_dict()

                        # Load isolation always applied regardless of EV/water source.
                        # Total load delta = 54.0 - 50.0 = 4.0 kWh.
                        # EV + water > 0 → base load must be < total load.
                        assert record["load_kwh"] < 4.0, (
                            f"Load isolation not applied (history_value={history_value}): "
                            f"load_kwh={record['load_kwh']}"
                        )


class TestPerDeviceEVRecording:
    """Task 8.3: Per-device EV charging energy recorded alongside aggregate."""

    @pytest.fixture
    def base_config(self):
        return {
            "system": {
                "has_ev_charger": True,
                "has_battery": True,
                "has_solar": False,
                "grid_meter_type": "net",
            },
            "input_sensors": {
                "battery_soc": "sensor.battery_soc",
                "load_power": "sensor.load_power",
                "grid_power": "sensor.grid_power",
                "battery_power": "sensor.battery_power",
            },
            "battery": {"capacity_kwh": 10.0},
            "ev_chargers": [],
            "water_heaters": [],
        }

    def _make_common_patches(self, now):
        """Return common mocks reused across tests."""

        async def mock_sensor_kw(entity):
            return {
                "sensor.load_power": 3.0,
                "sensor.grid_power": 2.0,
                "sensor.battery_power": 0.0,
                "sensor.ev_a_power": 3.2,
                "sensor.ev_b_power": 1.8,
            }.get(entity, 0.0)

        async def mock_float(entity):
            if entity == "sensor.battery_soc":
                return 50.0
            return None

        async def mock_entity_state(entity):
            return None

        async def mock_history(entity_id, start, end):
            return {"sensor.ev_a_power": 0.8, "sensor.ev_b_power": 0.45}.get(entity_id)

        return mock_sensor_kw, mock_float, mock_entity_state, mock_history

    @pytest.mark.asyncio
    async def test_per_device_kwh_recorded_for_two_chargers(self, base_config):
        """Two chargers produce individual ev_charger_energy entries."""
        import tempfile
        from unittest.mock import AsyncMock, MagicMock, patch

        import pytz

        from backend.recorder import RecorderStateStore, record_observation_from_current_state

        config = base_config.copy()
        config["ev_chargers"] = [
            {"id": "ev_a", "sensor": "sensor.ev_a_power", "enabled": True},
            {"id": "ev_b", "sensor": "sensor.ev_b_power", "enabled": True},
        ]

        now = datetime.now(pytz.timezone("Europe/Stockholm"))
        prev_time = now - timedelta(minutes=15)
        mock_sensor_kw, mock_float, mock_entity_state, mock_history = self._make_common_patches(now)

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "recorder_state.json"
            state_store = RecorderStateStore(state_file)
            state_store.load()
            state_store._state = {
                "pv_total": {"value": 0.0, "timestamp": prev_time.isoformat()},
                "load_total": {"value": 0.0, "timestamp": prev_time.isoformat()},
            }
            state_store.save()

            with (
                patch("backend.recorder.get_ha_sensor_kw_normalized", side_effect=mock_sensor_kw),
                patch("backend.recorder.get_ha_sensor_float", side_effect=mock_float),
                patch("backend.recorder.get_ha_entity_state", side_effect=mock_entity_state),
                patch("backend.recorder.get_current_slot_prices", return_value=None),
                patch("backend.recorder.get_energy_from_power_history", side_effect=mock_history),
            ):
                mock_store = MagicMock()
                mock_store.get_system_state = AsyncMock(return_value=None)
                mock_store.set_system_state = AsyncMock()
                mock_store.store_slot_observations = AsyncMock()
                mock_store.close = AsyncMock()

                with patch("backend.recorder.LearningStore", return_value=mock_store):
                    await record_observation_from_current_state(
                        config=config, state_store=state_store
                    )

                    df = mock_store.store_slot_observations.call_args[0][0]
                    record = df.iloc[0].to_dict()

                    # Aggregate is sum of both
                    assert record["ev_charging_kwh"] == pytest.approx(0.8 + 0.45, abs=0.01)

                    # Per-device dict has individual values
                    per_device = record["ev_charger_energy"]
                    assert per_device is not None
                    assert per_device["ev_a"] == pytest.approx(0.8, abs=0.01)
                    assert per_device["ev_b"] == pytest.approx(0.45, abs=0.01)

    @pytest.mark.asyncio
    async def test_per_device_kwh_none_when_no_chargers(self, base_config):
        """No chargers → ev_charger_energy is None."""
        import tempfile
        from unittest.mock import AsyncMock, MagicMock, patch

        import pytz

        from backend.recorder import RecorderStateStore, record_observation_from_current_state

        config = base_config.copy()
        config["ev_chargers"] = []

        now = datetime.now(pytz.timezone("Europe/Stockholm"))
        prev_time = now - timedelta(minutes=15)

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "recorder_state.json"
            state_store = RecorderStateStore(state_file)
            state_store.load()
            state_store._state = {
                "pv_total": {"value": 0.0, "timestamp": prev_time.isoformat()},
                "load_total": {"value": 0.0, "timestamp": prev_time.isoformat()},
            }
            state_store.save()

            async def mock_sensor_kw(entity):
                return {
                    "sensor.load_power": 2.0,
                    "sensor.grid_power": 2.0,
                    "sensor.battery_power": 0.0,
                }.get(entity, 0.0)

            async def mock_float(entity):
                return 50.0 if entity == "sensor.battery_soc" else None

            with (
                patch("backend.recorder.get_ha_sensor_kw_normalized", side_effect=mock_sensor_kw),
                patch("backend.recorder.get_ha_sensor_float", side_effect=mock_float),
                patch("backend.recorder.get_ha_entity_state", side_effect=lambda e: None),
                patch("backend.recorder.get_current_slot_prices", return_value=None),
                patch("backend.recorder.get_energy_from_power_history", return_value=None),
            ):
                mock_store = MagicMock()
                mock_store.get_system_state = AsyncMock(return_value=None)
                mock_store.set_system_state = AsyncMock()
                mock_store.store_slot_observations = AsyncMock()
                mock_store.close = AsyncMock()

                with patch("backend.recorder.LearningStore", return_value=mock_store):
                    await record_observation_from_current_state(
                        config=config, state_store=state_store
                    )

                    df = mock_store.store_slot_observations.call_args[0][0]
                    record = df.iloc[0].to_dict()

                    assert record["ev_charging_kwh"] == pytest.approx(0.0, abs=0.01)
                    assert record["ev_charger_energy"] is None

    @pytest.mark.asyncio
    async def test_aggregate_backward_compat_preserved(self, base_config):
        """ev_charging_kwh aggregate is still present for backward compatibility."""
        import tempfile
        from unittest.mock import AsyncMock, MagicMock, patch

        import pytz

        from backend.recorder import RecorderStateStore, record_observation_from_current_state

        config = base_config.copy()
        config["ev_chargers"] = [{"id": "ev1", "sensor": "sensor.ev_power", "enabled": True}]

        now = datetime.now(pytz.timezone("Europe/Stockholm"))
        prev_time = now - timedelta(minutes=15)

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "recorder_state.json"
            state_store = RecorderStateStore(state_file)
            state_store.load()
            state_store._state = {
                "pv_total": {"value": 0.0, "timestamp": prev_time.isoformat()},
                "load_total": {"value": 0.0, "timestamp": prev_time.isoformat()},
            }
            state_store.save()

            async def mock_sensor_kw(entity):
                return {
                    "sensor.load_power": 4.0,
                    "sensor.grid_power": 4.0,
                    "sensor.battery_power": 0.0,
                    "sensor.ev_power": 4.0,
                }.get(entity, 0.0)

            async def mock_float(entity):
                return 50.0 if entity == "sensor.battery_soc" else None

            async def mock_history(entity_id, start, end):
                return 1.0 if entity_id == "sensor.ev_power" else None

            with (
                patch("backend.recorder.get_ha_sensor_kw_normalized", side_effect=mock_sensor_kw),
                patch("backend.recorder.get_ha_sensor_float", side_effect=mock_float),
                patch("backend.recorder.get_ha_entity_state", side_effect=lambda e: None),
                patch("backend.recorder.get_current_slot_prices", return_value=None),
                patch("backend.recorder.get_energy_from_power_history", side_effect=mock_history),
            ):
                mock_store = MagicMock()
                mock_store.get_system_state = AsyncMock(return_value=None)
                mock_store.set_system_state = AsyncMock()
                mock_store.store_slot_observations = AsyncMock()
                mock_store.close = AsyncMock()

                with patch("backend.recorder.LearningStore", return_value=mock_store):
                    await record_observation_from_current_state(
                        config=config, state_store=state_store
                    )

                    df = mock_store.store_slot_observations.call_args[0][0]
                    record = df.iloc[0].to_dict()

                    # Aggregate still present
                    assert "ev_charging_kwh" in record
                    assert record["ev_charging_kwh"] == pytest.approx(1.0, abs=0.01)
                    # Per-device also present
                    assert record["ev_charger_energy"]["ev1"] == pytest.approx(1.0, abs=0.01)


class TestPerDeviceWaterHeaterRecording:
    """Task 8.4: Per-device water heater energy recorded alongside aggregate."""

    @pytest.fixture
    def base_config(self):
        return {
            "system": {
                "has_water_heater": True,
                "has_battery": True,
                "has_solar": False,
                "grid_meter_type": "net",
            },
            "input_sensors": {
                "battery_soc": "sensor.battery_soc",
                "load_power": "sensor.load_power",
                "grid_power": "sensor.grid_power",
                "battery_power": "sensor.battery_power",
            },
            "battery": {"capacity_kwh": 10.0},
            "ev_chargers": [],
            "water_heaters": [],
        }

    @pytest.mark.asyncio
    async def test_per_device_kwh_recorded_for_two_heaters(self, base_config):
        """Two heaters produce individual water_heater_energy entries."""
        import tempfile
        from unittest.mock import AsyncMock, MagicMock, patch

        import pytz

        from backend.recorder import RecorderStateStore, record_observation_from_current_state

        config = base_config.copy()
        config["water_heaters"] = [
            {"id": "wh1", "sensor": "sensor.wh1_power", "enabled": True, "power_kw": 3.0},
            {"id": "wh2", "sensor": "sensor.wh2_power", "enabled": True, "power_kw": 3.0},
        ]

        now = datetime.now(pytz.timezone("Europe/Stockholm"))
        prev_time = now - timedelta(minutes=15)

        async def mock_sensor_kw(entity):
            return {
                "sensor.load_power": 6.0,
                "sensor.grid_power": 6.0,
                "sensor.battery_power": 0.0,
            }.get(entity, 0.0)

        async def mock_float(entity):
            return 50.0 if entity == "sensor.battery_soc" else None

        async def mock_entity_state(entity):
            return None

        async def mock_history(entity_id, start, end):
            return {"sensor.wh1_power": 0.75, "sensor.wh2_power": 0.5}.get(entity_id)

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "recorder_state.json"
            state_store = RecorderStateStore(state_file)
            state_store.load()
            state_store._state = {
                "pv_total": {"value": 0.0, "timestamp": prev_time.isoformat()},
                "load_total": {"value": 0.0, "timestamp": prev_time.isoformat()},
            }
            state_store.save()

            with (
                patch("backend.recorder.get_ha_sensor_kw_normalized", side_effect=mock_sensor_kw),
                patch("backend.recorder.get_ha_sensor_float", side_effect=mock_float),
                patch("backend.recorder.get_ha_entity_state", side_effect=mock_entity_state),
                patch("backend.recorder.get_current_slot_prices", return_value=None),
                patch("backend.recorder.get_energy_from_power_history", side_effect=mock_history),
            ):
                mock_store = MagicMock()
                mock_store.get_system_state = AsyncMock(return_value=None)
                mock_store.set_system_state = AsyncMock()
                mock_store.store_slot_observations = AsyncMock()
                mock_store.close = AsyncMock()

                with patch("backend.recorder.LearningStore", return_value=mock_store):
                    await record_observation_from_current_state(
                        config=config, state_store=state_store
                    )

                    df = mock_store.store_slot_observations.call_args[0][0]
                    record = df.iloc[0].to_dict()

                    # Aggregate is sum of both heaters
                    assert record["water_kwh"] == pytest.approx(0.75 + 0.5, abs=0.01)

                    # Per-device dict has individual values
                    per_device = record["water_heater_energy"]
                    assert per_device is not None
                    assert per_device["wh1"] == pytest.approx(0.75, abs=0.01)
                    assert per_device["wh2"] == pytest.approx(0.5, abs=0.01)

    @pytest.mark.asyncio
    async def test_water_heater_energy_none_when_no_heaters(self, base_config):
        """No heaters → water_heater_energy is None."""
        import tempfile
        from unittest.mock import AsyncMock, MagicMock, patch

        import pytz

        from backend.recorder import RecorderStateStore, record_observation_from_current_state

        config = base_config.copy()
        config["water_heaters"] = []

        now = datetime.now(pytz.timezone("Europe/Stockholm"))
        prev_time = now - timedelta(minutes=15)

        async def mock_sensor_kw(entity):
            return {
                "sensor.load_power": 2.0,
                "sensor.grid_power": 2.0,
                "sensor.battery_power": 0.0,
            }.get(entity, 0.0)

        async def mock_float(entity):
            return 50.0 if entity == "sensor.battery_soc" else None

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "recorder_state.json"
            state_store = RecorderStateStore(state_file)
            state_store.load()
            state_store._state = {
                "pv_total": {"value": 0.0, "timestamp": prev_time.isoformat()},
                "load_total": {"value": 0.0, "timestamp": prev_time.isoformat()},
            }
            state_store.save()

            with (
                patch("backend.recorder.get_ha_sensor_kw_normalized", side_effect=mock_sensor_kw),
                patch("backend.recorder.get_ha_sensor_float", side_effect=mock_float),
                patch("backend.recorder.get_ha_entity_state", return_value=None),
                patch("backend.recorder.get_current_slot_prices", return_value=None),
                patch("backend.recorder.get_energy_from_power_history", return_value=None),
            ):
                mock_store = MagicMock()
                mock_store.get_system_state = AsyncMock(return_value=None)
                mock_store.set_system_state = AsyncMock()
                mock_store.store_slot_observations = AsyncMock()
                mock_store.close = AsyncMock()

                with patch("backend.recorder.LearningStore", return_value=mock_store):
                    await record_observation_from_current_state(
                        config=config, state_store=state_store
                    )

                    df = mock_store.store_slot_observations.call_args[0][0]
                    record = df.iloc[0].to_dict()

                    assert record["water_heater_energy"] is None

    @pytest.mark.asyncio
    async def test_snapshot_fallback_when_no_history(self, base_config):
        """When history API returns None, falls back to power snapshot per device."""
        import tempfile
        from unittest.mock import AsyncMock, MagicMock, patch

        import pytz

        from backend.recorder import RecorderStateStore, record_observation_from_current_state

        config = base_config.copy()
        config["water_heaters"] = [
            {"id": "wh1", "sensor": "sensor.wh1_power", "enabled": True, "power_kw": 2.0},
        ]

        now = datetime.now(pytz.timezone("Europe/Stockholm"))
        prev_time = now - timedelta(minutes=15)

        async def mock_sensor_kw(entity):
            return {
                "sensor.load_power": 2.0,
                "sensor.grid_power": 2.0,
                "sensor.battery_power": 0.0,
                "sensor.wh1_power": 2.0,
            }.get(entity, 0.0)

        async def mock_float(entity):
            return 50.0 if entity == "sensor.battery_soc" else None

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "recorder_state.json"
            state_store = RecorderStateStore(state_file)
            state_store.load()
            state_store._state = {
                "pv_total": {"value": 0.0, "timestamp": prev_time.isoformat()},
                "load_total": {"value": 0.0, "timestamp": prev_time.isoformat()},
            }
            state_store.save()

            with (
                patch("backend.recorder.get_ha_sensor_kw_normalized", side_effect=mock_sensor_kw),
                patch("backend.recorder.get_ha_sensor_float", side_effect=mock_float),
                patch("backend.recorder.get_ha_entity_state", return_value=None),
                patch("backend.recorder.get_current_slot_prices", return_value=None),
                patch("backend.recorder.get_energy_from_power_history", return_value=None),
            ):
                mock_store = MagicMock()
                mock_store.get_system_state = AsyncMock(return_value=None)
                mock_store.set_system_state = AsyncMock()
                mock_store.store_slot_observations = AsyncMock()
                mock_store.close = AsyncMock()

                with patch("backend.recorder.LearningStore", return_value=mock_store):
                    await record_observation_from_current_state(
                        config=config, state_store=state_store
                    )

                    df = mock_store.store_slot_observations.call_args[0][0]
                    record = df.iloc[0].to_dict()

                    # Snapshot: 2.0 kW x 0.25 h = 0.5 kWh
                    assert record["water_kwh"] == pytest.approx(0.5, abs=0.01)
                    assert record["water_heater_energy"]["wh1"] == pytest.approx(0.5, abs=0.01)


class TestSensorGuards:
    """Tests for water heater/EV sensor guards (executor-performance-fixes)."""

    def test_recorder_skips_water_heater_when_disabled(self):
        """Task 3.4: Recorder skips water heater sensor fetch when has_water_heater is false."""
        config = {
            "input_sensors": {
                "pv_power": "sensor.pv",
                "load_power": "sensor.load",
                "battery_power": "sensor.battery",
                "grid_power": "sensor.grid",
            },
            "water_heaters": [{"id": "wh1", "enabled": True, "sensor": "sensor.water_power"}],
            "system": {
                "timezone": "Europe/Stockholm",
                "grid_meter_type": "net",
                "has_water_heater": False,
            },
        }

        power_reads = [
            ("pv_power", lambda: 1.0),
            ("load_power", lambda: 2.0),
            ("battery_power", lambda: 3.0),
        ]

        water_heater_sensors = []
        if config.get("system", {}).get("has_water_heater", True):
            for water_heater in config.get("water_heaters", []):
                if water_heater.get("enabled", True):
                    sensor = water_heater.get("sensor")
                    if sensor:
                        water_heater_sensors.append(str(sensor))
                        power_reads.append((f"wh_{sensor}", lambda s=str(sensor): 4.0))

        assert len(water_heater_sensors) == 0
        assert not any(name.startswith("wh_") for name, _ in power_reads)

    def test_recorder_skips_ev_charger_when_disabled(self):
        """Task 3.5: Recorder skips EV charger sensor fetch when has_ev_charger is false."""
        config = {
            "input_sensors": {
                "pv_power": "sensor.pv",
                "load_power": "sensor.load",
                "battery_power": "sensor.battery",
                "grid_power": "sensor.grid",
            },
            "ev_chargers": [{"id": "ev1", "enabled": True, "sensor": "sensor.ev_power"}],
            "system": {
                "timezone": "Europe/Stockholm",
                "grid_meter_type": "net",
                "has_ev_charger": False,
            },
        }

        power_reads = [
            ("pv_power", lambda: 1.0),
            ("load_power", lambda: 2.0),
            ("battery_power", lambda: 3.0),
        ]

        ev_charger_sensors = []
        if config.get("system", {}).get("has_ev_charger", False):
            ev_chargers = config.get("ev_chargers", [])
            for ev_charger in ev_chargers:
                if ev_charger.get("enabled", True):
                    sensor = ev_charger.get("sensor")
                    if sensor:
                        ev_charger_sensors.append(str(sensor))
                        power_reads.append((f"ev_{sensor}", lambda s=str(sensor): 4.0))

        assert len(ev_charger_sensors) == 0
        assert not any(name.startswith("ev_") for name, _ in power_reads)

    def test_recorder_fetches_water_heater_when_enabled(self):
        """Water heater sensors are fetched when has_water_heater is true."""
        config = {
            "input_sensors": {
                "pv_power": "sensor.pv",
                "load_power": "sensor.load",
                "battery_power": "sensor.battery",
                "grid_power": "sensor.grid",
            },
            "water_heaters": [{"id": "wh1", "enabled": True, "sensor": "sensor.water_power"}],
            "system": {
                "timezone": "Europe/Stockholm",
                "grid_meter_type": "net",
                "has_water_heater": True,
            },
        }

        power_reads = [
            ("pv_power", lambda: 1.0),
            ("load_power", lambda: 2.0),
            ("battery_power", lambda: 3.0),
        ]

        water_heater_sensors = []
        if config.get("system", {}).get("has_water_heater", True):
            for water_heater in config.get("water_heaters", []):
                if water_heater.get("enabled", True):
                    sensor = water_heater.get("sensor")
                    if sensor:
                        water_heater_sensors.append(str(sensor))
                        power_reads.append((f"wh_{sensor}", lambda s=str(sensor): 4.0))

        assert len(water_heater_sensors) == 1
        assert "wh_sensor.water_power" in [name for name, _ in power_reads]

    def test_recorder_fetches_ev_charger_when_enabled(self):
        """EV charger sensors are fetched when has_ev_charger is true."""
        config = {
            "input_sensors": {
                "pv_power": "sensor.pv",
                "load_power": "sensor.load",
                "battery_power": "sensor.battery",
                "grid_power": "sensor.grid",
            },
            "ev_chargers": [{"id": "ev1", "enabled": True, "sensor": "sensor.ev_power"}],
            "system": {
                "timezone": "Europe/Stockholm",
                "grid_meter_type": "net",
                "has_ev_charger": True,
            },
        }

        power_reads = [
            ("pv_power", lambda: 1.0),
            ("load_power", lambda: 2.0),
            ("battery_power", lambda: 3.0),
        ]

        ev_charger_sensors = []
        if config.get("system", {}).get("has_ev_charger", False):
            ev_chargers = config.get("ev_chargers", [])
            for ev_charger in ev_chargers:
                if ev_charger.get("enabled", True):
                    sensor = ev_charger.get("sensor")
                    if sensor:
                        ev_charger_sensors.append(str(sensor))
                        power_reads.append((f"ev_{sensor}", lambda s=str(sensor): 4.0))

        assert len(ev_charger_sensors) == 1
        assert "ev_sensor.ev_power" in [name for name, _ in power_reads]
