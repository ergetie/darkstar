import logging
from pathlib import Path

import pytest

# Setup logging
logging.basicConfig(level=logging.INFO)


class TestDeprecatedKeyRemoval:
    """Test that deprecated keys are actually deleted."""

    def test_remove_deprecated_keys_root_level(self):
        from backend.config_migration import remove_deprecated_keys

        config = {
            "config_version": 2,
            "deferrable_loads": [],
            "ev_charger": {},
            "solar_array": {},
        }
        result, changed = remove_deprecated_keys(config)
        assert changed
        assert "deferrable_loads" not in result
        assert "ev_charger" not in result
        assert "solar_array" not in result

    def test_remove_deprecated_keys_nested(self):
        from backend.config_migration import remove_deprecated_keys

        config = {
            "executor": {
                "inverter": {
                    "work_mode": "select.ems_mode",
                    "work_mode_entity": "select.ems_mode",  # Deprecated
                    "soc_target": "",
                    "soc_target_entity": "",  # Deprecated
                }
            }
        }
        result, changed = remove_deprecated_keys(config)
        assert changed
        assert "work_mode" in result["executor"]["inverter"]
        assert "work_mode_entity" not in result["executor"]["inverter"]
        assert "soc_target_entity" not in result["executor"]["inverter"]

    def test_remove_fictional_water_penalty_keys(self):
        """fix-water-comfort-truthfulness: the four global water_heating penalty
        keys were never read by the solver and must be stripped on migration,
        while the real controls are preserved."""
        from backend.config_migration import remove_deprecated_keys

        config = {
            "water_heating": {
                "comfort_level": 3,
                "defer_up_to_hours": 6,
                "enable_top_ups": True,
                "vacation_mode": {"enabled": False},
                "reliability_penalty_sek": 1000.0,  # fictional
                "block_penalty_sek": 0.5,  # fictional
                "spacing_penalty_sek": 0.20,  # fictional
                "block_start_penalty_sek": 3.0,  # fictional
            }
        }
        result, changed = remove_deprecated_keys(config)
        wh = result["water_heating"]
        assert changed
        for dead in (
            "reliability_penalty_sek",
            "block_penalty_sek",
            "spacing_penalty_sek",
            "block_start_penalty_sek",
        ):
            assert dead not in wh
        # Real controls preserved
        assert wh["comfort_level"] == 3
        assert wh["defer_up_to_hours"] == 6
        assert wh["enable_top_ups"] is True
        assert wh["vacation_mode"] == {"enabled": False}


class TestInverterKeyMigration:
    """Test migration of system.inverter.max_power_kw to max_ac_power_kw."""

    def test_migrate_inverter_max_power_kw_to_max_ac_power_kw(self):
        """Old key should be migrated to new key when new key doesn't exist."""
        from backend.config_migration import _migrate_inverter_keys

        config = {
            "system": {
                "inverter": {
                    "max_power_kw": 8.8,  # Old key
                }
            }
        }

        result, changed = _migrate_inverter_keys(config)

        assert changed is True
        assert result["system"]["inverter"]["max_ac_power_kw"] == 8.8

    def test_migrate_inverter_does_not_overwrite_existing(self):
        """Should NOT overwrite existing max_ac_power_kw when both keys exist."""
        from backend.config_migration import _migrate_inverter_keys

        config = {
            "system": {
                "inverter": {
                    "max_power_kw": 8.8,  # Old key
                    "max_ac_power_kw": 10.0,  # New key already exists
                }
            }
        }

        result, changed = _migrate_inverter_keys(config)

        assert changed is False
        assert result["system"]["inverter"]["max_ac_power_kw"] == 10.0

    def test_migrate_inverter_no_change_when_no_old_key(self):
        """Should not change anything when old key doesn't exist."""
        from backend.config_migration import _migrate_inverter_keys

        config = {"system": {"inverter": {}}}

        result, changed = _migrate_inverter_keys(config)

        assert changed is False
        assert "max_ac_power_kw" not in result["system"]["inverter"]

    def test_migrate_inverter_creates_inverter_section_if_missing(self):
        """Should handle missing inverter section gracefully."""
        from backend.config_migration import _migrate_inverter_keys

        config = {"system": {}}

        _result, changed = _migrate_inverter_keys(config)

        assert changed is False


class TestBackendSave:
    """Test backend save logic with template merge."""

    @pytest.mark.asyncio
    async def test_backend_save_removes_deprecated_keys(self, tmp_path, monkeypatch):
        from ruamel.yaml import YAML

        from backend.api.routers.config import save_config

        yaml_loader = YAML()

        config_file = tmp_path / "config.yaml"
        default_file = tmp_path / "config.default.yaml"

        user_config = {
            "config_version": 2,
            "deferrable_loads": [{"id": "old_load"}],
            "timezone": "Europe/London",
            "system": {
                "system_id": "test",
                "inverter_profile": "test",
                "has_solar": False,
                "has_battery": False,
            },
            "battery": {},
            "executor": {},
            "input_sensors": {},
        }

        default_config = {
            "config_version": 2,
            "timezone": "Europe/London",
            "system": {
                "system_id": "test",
                "inverter_profile": "test",
                "has_solar": False,
                "has_battery": False,
            },
            "battery": {},
            "executor": {},
            "input_sensors": {},
        }

        with config_file.open("w") as f:
            yaml_loader.dump(user_config, f)
        with default_file.open("w") as f:
            yaml_loader.dump(default_config, f)

        import backend.api.routers.config as config_router

        monkeypatch.setattr(
            config_router,
            "Path",
            lambda p: tmp_path / p if p in ["config.yaml", "config.default.yaml"] else Path(p),
        )
        monkeypatch.setattr(config_router, "get_executor_instance", lambda: None)
        monkeypatch.setattr(config_router, "_validate_config_for_save", lambda x, *_: [])

        await save_config({"timezone": "Europe/Stockholm"})

        with config_file.open() as f:
            saved_data = yaml_loader.load(f)
        assert saved_data["timezone"] == "Europe/Stockholm"
        assert "deferrable_loads" not in saved_data


class TestBackupSystem:
    """Test timestamped backup system."""

    def test_create_timestamped_backup(self, tmp_path):
        from backend.config_migration import create_timestamped_backup

        config_file = tmp_path / "config.yaml"
        config_file.write_text("test content")

        backup_path = create_timestamped_backup(config_file)
        assert backup_path is not None
        assert backup_path.exists()
        assert "config.yaml_" in backup_path.name


class TestTemplateAwareMerge:
    """Test template_aware_merge functionality."""

    def test_merge_preserves_comments(self):
        from ruamel.yaml import YAML

        from backend.config_migration import template_aware_merge

        yaml_loader = YAML()
        template_str = """
# Global Comment
system:
  # Section Comment
  id: "default_id"
"""
        user_cfg = {"system": {"id": "user_id"}}
        template_cfg = yaml_loader.load(template_str)
        template_aware_merge(template_cfg, user_cfg)
        assert template_cfg["system"]["id"] == "user_id"


class TestFullMigrationFlow:
    """Test the complete migration pipeline."""

    @pytest.mark.asyncio
    async def test_migrate_config_idempotent_for_clean_config(self, tmp_path, monkeypatch):
        """Verify that a clean config_version=2 config with no deprecated keys is not rewritten."""
        from ruamel.yaml import YAML

        import backend.config_migration as cm

        yaml_loader = YAML()
        config_file = tmp_path / "config.yaml"
        default_file = tmp_path / "config.default.yaml"

        clean_config = {
            "config_version": 2,
            "system": {
                "system_id": "test",
                "inverter_profile": "test",
                "has_solar": False,
                "has_battery": True,
            },
            "battery": {"min_soc_percent": 20},
            "executor": {},
            "input_sensors": {},
        }

        with config_file.open("w") as f:
            yaml_loader.dump(clean_config, f)
        with default_file.open("w") as f:
            yaml_loader.dump(clean_config, f)

        monkeypatch.setattr(
            cm,
            "Path",
            lambda p: tmp_path / p if p in ["config.yaml", "config.default.yaml"] else Path(p),
        )

        write_calls: list = []

        def mock_write(*args, **kwargs):
            write_calls.append(args)

        monkeypatch.setattr(cm, "_write_config", mock_write)

        await cm.migrate_config(strict_validation=False)

        assert len(write_calls) == 0, (
            f"_write_config was called {len(write_calls)} time(s) but should not have been "
            f"for a clean config with no deprecated keys"
        )


class TestWaterHeaterMigration:
    """Test water heater field migration from legacy locations to water_heaters[] array."""

    def test_migrate_all_water_heater_fields(self):
        """Legacy config with all three keys → values migrate into water_heaters[0], old keys removed."""
        from backend.config_migration import _migrate_water_heater_fields

        config = {
            "config_version": 2,
            "input_sensors": {
                "water_power": "sensor.boiler_power",
                "water_heater_consumption": "sensor.boiler_energy",
                "grid_power": "sensor.grid",
            },
            "executor": {
                "water_heater": {
                    "target_entity": "climate.boiler",
                    "temp_off": 40,
                    "temp_normal": 60,
                }
            },
            "water_heaters": [
                {
                    "id": "main_tank",
                    "sensor": "",
                    "energy_sensor": "",
                    "target_entity": "",
                    "power_kw": 3.0,
                }
            ],
        }

        result, changed = _migrate_water_heater_fields(config)

        assert changed is True
        # Values should be migrated
        assert result["water_heaters"][0]["sensor"] == "sensor.boiler_power"
        assert result["water_heaters"][0]["target_entity"] == "climate.boiler"
        # Old keys should be removed
        assert "water_power" not in result["input_sensors"]
        assert "water_heater_consumption" not in result["input_sensors"]
        assert "target_entity" not in result["executor"]["water_heater"]
        # Other keys should remain
        assert result["input_sensors"]["grid_power"] == "sensor.grid"
        assert result["executor"]["water_heater"]["temp_off"] == 40

    def test_migrate_preserves_existing_sensor(self):
        """Config with sensor already set → input_sensors.water_power is NOT copied, old key still removed."""
        from backend.config_migration import _migrate_water_heater_fields

        config = {
            "config_version": 2,
            "input_sensors": {
                "water_power": "sensor.boiler_power",
                "water_heater_consumption": "",
            },
            "executor": {
                "water_heater": {
                    "target_entity": "",
                }
            },
            "water_heaters": [
                {
                    "id": "main_tank",
                    "sensor": "sensor.existing_power",  # Already set
                    "energy_sensor": "",
                    "target_entity": "",
                }
            ],
        }

        result, changed = _migrate_water_heater_fields(config)

        assert changed is True  # Still changed because old keys are removed
        # Existing value should be preserved
        assert result["water_heaters"][0]["sensor"] == "sensor.existing_power"
        # Old key should still be removed
        assert "water_power" not in result["input_sensors"]

    def test_migrate_no_water_heaters(self):
        """Config with no water_heaters array should not crash."""
        from backend.config_migration import _migrate_water_heater_fields

        config = {
            "config_version": 2,
            "input_sensors": {
                "water_power": "sensor.boiler_power",
            },
        }

        result, changed = _migrate_water_heater_fields(config)

        # Should not crash, no changes made
        assert changed is False
        assert "input_sensors" in result

    def test_migrate_empty_water_heaters(self):
        """Config with empty water_heaters array should not crash."""
        from backend.config_migration import _migrate_water_heater_fields

        config = {
            "config_version": 2,
            "input_sensors": {
                "water_power": "sensor.boiler_power",
            },
            "water_heaters": [],
        }

        result, changed = _migrate_water_heater_fields(config)

        # Should not crash, no changes made to array
        assert changed is False
        assert result["water_heaters"] == []


class TestRemoveEnergySensorFields:
    """Tests for _remove_energy_sensor_fields migration step."""

    def test_removes_energy_sensor_from_ev_chargers(self):
        """energy_sensor is removed from all ev_chargers[] items."""
        from backend.config_migration import _remove_energy_sensor_fields

        config = {
            "ev_chargers": [
                {"id": "ev1", "sensor": "sensor.ev_power", "energy_sensor": "sensor.ev_energy"},
                {"id": "ev2", "sensor": "sensor.ev2_power", "energy_sensor": "sensor.ev2_energy"},
            ],
        }

        result, changed = _remove_energy_sensor_fields(config)

        assert changed is True
        assert "energy_sensor" not in result["ev_chargers"][0]
        assert "energy_sensor" not in result["ev_chargers"][1]
        assert result["ev_chargers"][0]["sensor"] == "sensor.ev_power"

    def test_removes_energy_sensor_from_water_heaters(self):
        """energy_sensor is removed from all water_heaters[] items."""
        from backend.config_migration import _remove_energy_sensor_fields

        config = {
            "water_heaters": [
                {"id": "wh1", "sensor": "sensor.wh_power", "energy_sensor": "sensor.wh_energy"},
            ],
        }

        result, changed = _remove_energy_sensor_fields(config)

        assert changed is True
        assert "energy_sensor" not in result["water_heaters"][0]
        assert result["water_heaters"][0]["sensor"] == "sensor.wh_power"

    def test_other_fields_untouched(self):
        """Other fields on the item are preserved."""
        from backend.config_migration import _remove_energy_sensor_fields

        config = {
            "ev_chargers": [
                {
                    "id": "ev1",
                    "name": "My EV",
                    "enabled": True,
                    "sensor": "sensor.ev",
                    "energy_sensor": "sensor.ev_energy",
                    "soc_sensor": "sensor.ev_soc",
                },
            ],
        }

        result, changed = _remove_energy_sensor_fields(config)

        assert changed is True
        item = result["ev_chargers"][0]
        assert item["id"] == "ev1"
        assert item["name"] == "My EV"
        assert item["enabled"] is True
        assert item["sensor"] == "sensor.ev"
        assert item["soc_sensor"] == "sensor.ev_soc"
        assert "energy_sensor" not in item

    def test_idempotent_no_error_if_field_absent(self):
        """No error if energy_sensor already absent; changed=False."""
        from backend.config_migration import _remove_energy_sensor_fields

        config = {
            "ev_chargers": [{"id": "ev1", "sensor": "sensor.ev"}],
            "water_heaters": [{"id": "wh1", "sensor": "sensor.wh"}],
        }

        result, changed = _remove_energy_sensor_fields(config)

        assert changed is False
        assert result["ev_chargers"][0] == {"id": "ev1", "sensor": "sensor.ev"}

    def test_no_arrays_no_error(self):
        """Config without ev_chargers or water_heaters doesn't crash."""
        from backend.config_migration import _remove_energy_sensor_fields

        config = {"system": {"has_battery": True}}

        _, changed = _remove_energy_sensor_fields(config)

        assert changed is False


class TestMigrateEvChargerFields:
    """Tests for _migrate_ev_charger_fields: moves global EV settings into ev_chargers[0]."""

    def _base_config(self, extra_charger_fields=None):
        charger = {"id": "main", "enabled": True, "name": "My EV"}
        if extra_charger_fields:
            charger.update(extra_charger_fields)
        return {
            "ev_chargers": [charger],
        }

    def test_departure_time_migrated_to_first_enabled_charger(self):
        from backend.config_migration import _migrate_ev_charger_fields

        config = self._base_config()
        config["ev_departure_time"] = "07:30"

        result, changed = _migrate_ev_charger_fields(config)

        assert changed is True
        assert result["ev_chargers"][0]["departure_time"] == "07:30"

    def test_switch_entity_migrated_from_executor_ev_charger(self):
        from backend.config_migration import _migrate_ev_charger_fields

        config = self._base_config()
        config["executor"] = {"ev_charger": {"switch_entity": "switch.tesla"}}

        result, changed = _migrate_ev_charger_fields(config)

        assert changed is True
        assert result["ev_chargers"][0]["switch_entity"] == "switch.tesla"

    def test_replan_on_plugin_migrated(self):
        from backend.config_migration import _migrate_ev_charger_fields

        config = self._base_config()
        config["executor"] = {"ev_charger": {"replan_on_plugin": True}}

        result, changed = _migrate_ev_charger_fields(config)

        assert changed is True
        assert result["ev_chargers"][0]["replan_on_plugin"] is True

    def test_replan_on_unplug_migrated(self):
        from backend.config_migration import _migrate_ev_charger_fields

        config = self._base_config()
        config["executor"] = {"ev_charger": {"replan_on_unplug": True}}

        result, changed = _migrate_ev_charger_fields(config)

        assert changed is True
        assert result["ev_chargers"][0]["replan_on_unplug"] is True

    def test_idempotent_departure_time_not_overwritten(self):
        from backend.config_migration import _migrate_ev_charger_fields

        config = self._base_config(extra_charger_fields={"departure_time": "08:00"})
        config["ev_departure_time"] = "07:30"

        result, _ = _migrate_ev_charger_fields(config)

        # departure_time already present — should NOT be overwritten
        assert result["ev_chargers"][0]["departure_time"] == "08:00"

    def test_idempotent_switch_entity_not_overwritten(self):
        from backend.config_migration import _migrate_ev_charger_fields

        config = self._base_config(extra_charger_fields={"switch_entity": "switch.existing"})
        config["executor"] = {"ev_charger": {"switch_entity": "switch.old"}}

        result, _ = _migrate_ev_charger_fields(config)

        assert result["ev_chargers"][0]["switch_entity"] == "switch.existing"

    def test_no_op_when_already_migrated(self):
        from backend.config_migration import _migrate_ev_charger_fields

        config = self._base_config(
            extra_charger_fields={
                "departure_time": "07:00",
                "switch_entity": "switch.ev",
                "replan_on_plugin": True,
                "replan_on_unplug": False,
            }
        )
        # No old-style fields present either
        _, changed = _migrate_ev_charger_fields(config)

        assert changed is False

    def test_no_enabled_charger_returns_unchanged(self):
        from backend.config_migration import _migrate_ev_charger_fields

        config = {
            "ev_chargers": [{"id": "main", "enabled": False, "name": "My EV"}],
            "ev_departure_time": "07:00",
            "executor": {"ev_charger": {"switch_entity": "switch.ev"}},
        }

        result, changed = _migrate_ev_charger_fields(config)

        assert changed is False
        # The disabled charger should not have departure_time added
        assert "departure_time" not in result["ev_chargers"][0]

    def test_empty_ev_chargers_returns_unchanged(self):
        from backend.config_migration import _migrate_ev_charger_fields

        config = {
            "ev_chargers": [],
            "ev_departure_time": "07:00",
        }

        _, changed = _migrate_ev_charger_fields(config)

        assert changed is False


class TestMigrateLegacyEvChargerCurrentStub:
    """universal-load-balancing 1.4: executor.ev_charger (control_entity/control_mode/
    max_current_a/enabled_entity) is mapped onto ev_chargers[0] and the whole
    block is removed."""

    def test_stub_present_migrates_and_is_removed(self):
        from backend.config_migration import _migrate_ev_charger_fields, remove_deprecated_keys

        config = {
            "ev_chargers": [{"id": "main", "enabled": True, "name": "My EV"}],
            "executor": {
                "ev_charger": {
                    "control_entity": "number.goe_current",
                    "control_mode": "current",
                    "max_current_a": 32,
                    "enabled_entity": "binary_sensor.goe_enabled",
                }
            },
        }

        config, migrated = _migrate_ev_charger_fields(config)
        assert migrated is True
        assert config["ev_chargers"][0]["current_entity"] == "number.goe_current"
        assert config["ev_chargers"][0]["max_current_a"] == 32
        assert config["ev_chargers"][0]["type"] == "current"

        config, removed = remove_deprecated_keys(config)
        assert removed is True
        assert "ev_charger" not in config["executor"]

    def test_stub_absent_no_changes(self):
        from backend.config_migration import _migrate_ev_charger_fields, remove_deprecated_keys

        config = {
            "ev_chargers": [{"id": "main", "enabled": True, "name": "My EV"}],
            "executor": {"enabled": True},
        }

        config, migrated = _migrate_ev_charger_fields(config)
        assert migrated is False

        config, removed = remove_deprecated_keys(config)
        assert removed is False
        assert "ev_charger" not in config["executor"]

    def test_does_not_overwrite_already_configured_current_entity(self):
        from backend.config_migration import _migrate_ev_charger_fields

        config = {
            "ev_chargers": [
                {
                    "id": "main",
                    "enabled": True,
                    "current_entity": "number.new_current",
                    "max_current_a": 16,
                }
            ],
            "executor": {
                "ev_charger": {
                    "control_entity": "number.legacy_current",
                    "max_current_a": 32,
                }
            },
        }

        config, _ = _migrate_ev_charger_fields(config)

        assert config["ev_chargers"][0]["current_entity"] == "number.new_current"
        assert config["ev_chargers"][0]["max_current_a"] == 16


# ===========================================================================
# Tests 4.1 – 4.7: config-migration-hardening
# ===========================================================================


class TestUISaveRoutesAtomicWriter:
    """4.1 – UI save uses _write_config; never opens config.yaml in truncating 'w' mode."""

    @pytest.mark.asyncio
    async def test_save_calls_write_config_not_open_w(self, tmp_path, monkeypatch):
        from pathlib import Path as _Path

        from ruamel.yaml import YAML

        import backend.api.routers.config as config_router

        yaml_loader = YAML()

        config_file = tmp_path / "config.yaml"
        default_file = tmp_path / "config.default.yaml"

        base_config = {
            "config_version": 2,
            "timezone": "Europe/London",
            "system": {
                "system_id": "test",
                "inverter_profile": "test",
                "has_solar": False,
                "has_battery": False,
            },
            "battery": {},
            "executor": {},
            "input_sensors": {},
        }

        with config_file.open("w") as f:
            yaml_loader.dump(base_config, f)
        with default_file.open("w") as f:
            yaml_loader.dump(base_config, f)

        write_config_calls: list = []
        # Track whether config.yaml is opened in raw "w" mode *before* _write_config is reached.
        # We spy on Path.open; _write_config is mocked out so the only "w" opens that
        # could happen are from the old direct-write code path that must no longer exist.
        raw_open_w_calls: list = []
        real_open = _Path.open

        def spy_open(self, mode="r", **kwargs):
            # Flag any "w" mode open on the config file that is NOT from our mock.
            if mode == "w" and self == config_file:
                # Check call stack: if _write_config mock hasn't been called yet but a "w"
                # open happens, that means the old direct-write path is being used.
                if not write_config_calls:
                    raw_open_w_calls.append(self)
            return real_open(self, mode, **kwargs)

        monkeypatch.setattr(_Path, "open", spy_open)

        def mock_write_config(path, data, yaml_instance, **kwargs):
            write_config_calls.append((path, data))
            return True

        monkeypatch.setattr(
            config_router,
            "Path",
            lambda p: tmp_path / p if p in ["config.yaml", "config.default.yaml"] else _Path(p),
        )
        monkeypatch.setattr(config_router, "write_config", mock_write_config)
        monkeypatch.setattr(config_router, "get_executor_instance", lambda: None)
        monkeypatch.setattr(config_router, "_validate_config_for_save", lambda x, *_: [])

        await config_router.save_config({"timezone": "Europe/Stockholm"})

        assert len(write_config_calls) == 1, "_write_config should have been called exactly once"
        assert len(raw_open_w_calls) == 0, (
            "config.yaml must not be opened in truncating 'w' mode before _write_config is called"
        )


class TestUISaveCreatesBackup:
    """4.2 – UI save triggers a timestamped backup before writing."""

    @pytest.mark.asyncio
    async def test_save_calls_create_timestamped_backup(self, tmp_path, monkeypatch):
        from pathlib import Path as _Path

        from ruamel.yaml import YAML

        import backend.api.routers.config as config_router
        import backend.config_migration as cm

        yaml_loader = YAML()

        config_file = tmp_path / "config.yaml"
        default_file = tmp_path / "config.default.yaml"

        base_config = {
            "config_version": 2,
            "timezone": "Europe/London",
            "system": {
                "system_id": "test",
                "inverter_profile": "test",
                "has_solar": False,
                "has_battery": False,
            },
            "battery": {},
            "executor": {},
            "input_sensors": {},
        }

        with config_file.open("w") as f:
            yaml_loader.dump(base_config, f)
        with default_file.open("w") as f:
            yaml_loader.dump(base_config, f)

        backup_calls: list = []

        real_create_backup = cm.create_timestamped_backup

        def mock_backup(path, **kwargs):
            backup_calls.append(path)
            return real_create_backup(path, **kwargs)

        monkeypatch.setattr(cm, "create_timestamped_backup", mock_backup)
        # config_router imports write_config from cm at module load time, so patch cm directly.
        # _write_config calls create_timestamped_backup via the cm module namespace.

        monkeypatch.setattr(
            config_router,
            "Path",
            lambda p: tmp_path / p if p in ["config.yaml", "config.default.yaml"] else _Path(p),
        )
        monkeypatch.setattr(config_router, "get_executor_instance", lambda: None)
        monkeypatch.setattr(config_router, "_validate_config_for_save", lambda x, *_: [])

        await config_router.save_config({"timezone": "Europe/Stockholm"})

        assert len(backup_calls) >= 1, "create_timestamped_backup should be called during save"


class TestUISaveAbortedReturns500:
    """4.3 – If _write_config returns False (aborted), HTTP 500 is returned.

    The critical scenario: _write_config aborts silently (validation failure),
    the old non-empty config.yaml stays on disk unchanged, but the endpoint must
    still return an error — not success. This tests the return-value check, not a
    file-size check.
    """

    @pytest.mark.asyncio
    async def test_silent_write_abort_returns_500(self, tmp_path, monkeypatch):
        from pathlib import Path as _Path

        from fastapi import HTTPException
        from ruamel.yaml import YAML

        import backend.api.routers.config as config_router

        yaml_loader = YAML()

        config_file = tmp_path / "config.yaml"
        default_file = tmp_path / "config.default.yaml"

        base_config = {
            "config_version": 2,
            "timezone": "Europe/London",
            "system": {
                "system_id": "test",
                "inverter_profile": "test",
                "has_solar": False,
                "has_battery": False,
            },
            "battery": {},
            "executor": {},
            "input_sensors": {},
        }

        with config_file.open("w") as f:
            yaml_loader.dump(base_config, f)
        with default_file.open("w") as f:
            yaml_loader.dump(base_config, f)

        def aborted_write_config(path, data, yaml_instance, **kwargs):
            # Simulate _write_config aborting (e.g. internal validation failure):
            # the file is NOT updated and the old non-empty file remains in place.
            # Return False so the caller detects the abort via the return value.
            return False

        monkeypatch.setattr(
            config_router,
            "Path",
            lambda p: tmp_path / p if p in ["config.yaml", "config.default.yaml"] else _Path(p),
        )
        monkeypatch.setattr(config_router, "write_config", aborted_write_config)
        monkeypatch.setattr(config_router, "get_executor_instance", lambda: None)
        monkeypatch.setattr(config_router, "_validate_config_for_save", lambda x, *_: [])

        with pytest.raises(HTTPException) as exc_info:
            await config_router.save_config({"timezone": "Europe/Stockholm"})

        assert exc_info.value.status_code == 500
        # The old file must still be intact — abort must not truncate it.
        assert config_file.stat().st_size > 0


class TestBindMountExdevPath:
    """4.4 – EXDEV on first replace is retried atomically; shutil.copy2 is NOT called."""

    def test_exdev_retry_does_not_call_copy2(self, tmp_path, monkeypatch):
        import errno as _errno
        import shutil as _shutil

        from ruamel.yaml import YAML

        from backend.config_migration import _write_config

        yaml_instance = YAML()
        yaml_instance.preserve_quotes = True
        yaml_instance.width = 4096

        config_file = tmp_path / "config.yaml"
        config_file.write_text("system:\n  inverter_profile: test\n", encoding="utf-8")

        config_data = {
            "config_version": 2,
            "system": {
                "system_id": "test",
                "inverter_profile": "test",
                "has_solar": False,
                "has_battery": False,
            },
            "battery": {},
            "executor": {},
            "input_sensors": {},
        }

        replace_call_count = [0]
        real_replace = config_file.__class__.replace

        def patched_replace(self, target):
            replace_call_count[0] += 1
            if replace_call_count[0] == 1:
                raise OSError(_errno.EXDEV, "cross-device link")
            return real_replace(self, target)

        copy2_calls: list = []
        real_copy2 = _shutil.copy2

        def spy_copy2(src, dst, **kwargs):
            copy2_calls.append((src, dst))
            return real_copy2(src, dst, **kwargs)

        import backend.config_migration as cm

        monkeypatch.setattr(cm.Path, "replace", patched_replace)
        monkeypatch.setattr(cm.shutil, "copy2", spy_copy2)

        _write_config(config_file, config_data, yaml_instance, strict_validation=False)

        # The retry should have succeeded atomically — copy2 must NOT have been called
        # for the config itself (it may be called for the .bak backup, so filter by target).
        config_copy2_calls = [call for call in copy2_calls if str(call[1]) == str(config_file)]
        assert len(config_copy2_calls) == 0, (
            "shutil.copy2 should not be used when atomic replace succeeds on retry"
        )


class TestMigrateConfigVersionSet:
    """4.5 – migrate_config() sets config_version: 2 when the key is absent, even without template."""

    @pytest.mark.asyncio
    async def test_config_version_set_when_missing_no_template(self, tmp_path, monkeypatch):
        from pathlib import Path as _Path

        from ruamel.yaml import YAML

        import backend.config_migration as cm

        yaml_loader = YAML()
        config_file = tmp_path / "config.yaml"

        # Minimal config with no config_version key and no deprecated keys.
        # strict_validation=False so structure check passes without full schema.
        config_without_version = {
            "system": {"system_id": "test", "inverter_profile": "test"},
            "battery": {},
            "executor": {},
            "input_sensors": {},
        }

        with config_file.open("w") as f:
            yaml_loader.dump(config_without_version, f)

        # Do NOT create config.default.yaml so the template-merge branch is skipped.
        monkeypatch.setattr(
            cm,
            "Path",
            lambda p: tmp_path / p if p in ["config.yaml", "config.default.yaml"] else _Path(p),
        )

        written_configs: list = []

        def capture_write(path, data, yaml_instance, **kwargs):
            written_configs.append(dict(data))

        monkeypatch.setattr(cm, "_write_config", capture_write)

        await cm.migrate_config(strict_validation=False)

        assert len(written_configs) == 1, "_write_config should be called once (version was set)"
        assert written_configs[0].get("config_version") == cm.CURRENT_CONFIG_VERSION, (
            f"Expected config_version={cm.CURRENT_CONFIG_VERSION}, "
            f"got {written_configs[0].get('config_version')}"
        )


class TestConfigVersionNotDowngraded:
    """4.6 – migrate_config() never downgrades a config_version that is already higher."""

    @pytest.mark.asyncio
    async def test_higher_version_preserved(self, tmp_path, monkeypatch):
        from pathlib import Path as _Path

        from ruamel.yaml import YAML

        import backend.config_migration as cm

        yaml_loader = YAML()
        config_file = tmp_path / "config.yaml"
        default_file = tmp_path / "config.default.yaml"

        future_version = 99
        config_v99 = {
            "config_version": future_version,
            "system": {
                "system_id": "test",
                "inverter_profile": "test",
                "has_solar": False,
                "has_battery": True,
            },
            "battery": {"min_soc_percent": 20},
            "executor": {},
            "input_sensors": {},
        }

        with config_file.open("w") as f:
            yaml_loader.dump(config_v99, f)
        with default_file.open("w") as f:
            yaml_loader.dump(config_v99, f)

        monkeypatch.setattr(
            cm,
            "Path",
            lambda p: tmp_path / p if p in ["config.yaml", "config.default.yaml"] else _Path(p),
        )

        written_configs: list = []

        def capture_write(path, data, yaml_instance, **kwargs):
            written_configs.append(dict(data))

        monkeypatch.setattr(cm, "_write_config", capture_write)

        await cm.migrate_config(strict_validation=False)

        # Whether or not _write_config is called (structure may or may not change),
        # config_version must never be reduced to CURRENT_CONFIG_VERSION.
        for written in written_configs:
            assert written.get("config_version") == future_version, (
                f"config_version was downgraded: expected {future_version}, "
                f"got {written.get('config_version')}"
            )

        # Also verify the in-memory value was not downgraded by reading it from the file
        # or confirming that if nothing was written, the file still has version 99.
        if not written_configs:
            with config_file.open() as f:
                saved = yaml_loader.load(f)
            assert saved["config_version"] == future_version


class TestMigrateConfigIdempotentV2:
    """4.7 – A clean v2 config produces no file write (idempotency)."""

    @pytest.mark.asyncio
    async def test_clean_v2_no_write(self, tmp_path, monkeypatch):
        """config_version=2 with no deprecated keys must not trigger _write_config."""
        from pathlib import Path as _Path

        from ruamel.yaml import YAML

        import backend.config_migration as cm

        yaml_loader = YAML()
        config_file = tmp_path / "config.yaml"
        default_file = tmp_path / "config.default.yaml"

        clean_v2 = {
            "config_version": 2,
            "system": {
                "system_id": "test",
                "inverter_profile": "test",
                "has_solar": False,
                "has_battery": True,
            },
            "battery": {"min_soc_percent": 20},
            "executor": {},
            "input_sensors": {},
        }

        with config_file.open("w") as f:
            yaml_loader.dump(clean_v2, f)
        with default_file.open("w") as f:
            yaml_loader.dump(clean_v2, f)

        monkeypatch.setattr(
            cm,
            "Path",
            lambda p: tmp_path / p if p in ["config.yaml", "config.default.yaml"] else _Path(p),
        )

        write_calls: list = []

        def mock_write(*args, **kwargs):
            write_calls.append(args)

        monkeypatch.setattr(cm, "_write_config", mock_write)

        await cm.migrate_config(strict_validation=False)

        assert len(write_calls) == 0, (
            f"_write_config was called {len(write_calls)} time(s) for a clean v2 config "
            f"with no deprecated keys — it should be idempotent"
        )


class TestPostWriteVerificationFailureReturns500:
    """post-write verify: _verify_written_config returning False propagates as HTTP 500."""

    @pytest.mark.asyncio
    async def test_verify_failure_returns_500(self, tmp_path, monkeypatch):
        """If _verify_written_config returns False, _write_config returns False,
        and save_config() must raise HTTPException(500)."""
        from pathlib import Path as _Path

        from fastapi import HTTPException
        from ruamel.yaml import YAML

        import backend.api.routers.config as config_router

        yaml_loader = YAML()
        config_file = tmp_path / "config.yaml"

        base_config = {
            "config_version": 2,
            "timezone": "Europe/London",
            "system": {
                "system_id": "test",
                "inverter_profile": "test",
                "has_solar": False,
                "has_battery": False,
            },
            "battery": {},
            "executor": {},
            "input_sensors": {},
        }
        with config_file.open("w") as f:
            yaml_loader.dump(base_config, f)

        def failing_write_config(path, data, yaml_instance, **kwargs):
            # Simulate _write_config returning False because post-write verification failed.
            return False

        monkeypatch.setattr(
            config_router,
            "Path",
            lambda p: tmp_path / p if p in ["config.yaml", "config.default.yaml"] else _Path(p),
        )
        monkeypatch.setattr(config_router, "write_config", failing_write_config)
        monkeypatch.setattr(config_router, "get_executor_instance", lambda: None)
        monkeypatch.setattr(config_router, "_validate_config_for_save", lambda x, *_: [])

        with pytest.raises(HTTPException) as exc_info:
            await config_router.save_config({"timezone": "Europe/Stockholm"})

        assert exc_info.value.status_code == 500


class TestBackupRetentionPruning:
    """Backups are retention-pruned: oldest files beyond max_backups are removed."""

    def test_old_backups_pruned(self, tmp_path):
        """create_timestamped_backup prunes files beyond max_backups, keeping the newest."""
        import time

        from backend.config_migration import create_timestamped_backup

        config_file = tmp_path / "config.yaml"
        config_file.write_text("content: original\n")

        backup_dir = tmp_path / ".darkstar_backups"
        backup_dir.mkdir()

        # Pre-seed 5 old backup files with distinct mtimes so ordering is deterministic.
        import os as _os

        old_backups = []
        for i in range(5):
            b = backup_dir / f"config.yaml_2024010{i}_120000.bak"
            b.write_text(f"old backup {i}")
            # Stagger mtime so oldest has the smallest mtime.
            _os.utime(b, (1_000_000 + i, 1_000_000 + i))
            old_backups.append(b)

        import backend.config_migration as cm

        # Patch _get_persistent_backup_dir to return our tmp backup_dir.
        monkeypatch = None  # use direct patch via attribute swap
        original_fn = cm._get_persistent_backup_dir
        cm._get_persistent_backup_dir = lambda _path: backup_dir
        try:
            create_timestamped_backup(config_file, max_backups=4)
        finally:
            cm._get_persistent_backup_dir = original_fn

        remaining = sorted(backup_dir.glob("config.yaml_*.bak"))
        assert len(remaining) == 4, f"Expected 4 backups after pruning, got {len(remaining)}"
        # The oldest backup (index 0, lowest mtime) must have been removed.
        assert not old_backups[0].exists(), "Oldest backup should have been pruned"
        # The newest pre-seeded backup and the new one must survive.
        assert old_backups[-1].exists(), "Most recent old backup should survive"


class TestMigrateExcessPvSinkToPriority:
    """excess-pv-priority-dispatch 1.4: executor.excess_pv.sink -> priority[]."""

    def test_water_heater_boost_migrated(self):
        from backend.config_migration import _migrate_excess_pv_sink_to_priority

        config = {"executor": {"excess_pv": {"sink": "water_heater_boost"}}}
        result, changed = _migrate_excess_pv_sink_to_priority(config)
        assert changed
        excess_pv = result["executor"]["excess_pv"]
        assert "sink" not in excess_pv
        assert excess_pv["priority"] == [{"type": "water_heater_boost"}]

    def test_custom_entity_migrated_with_fields(self):
        from backend.config_migration import _migrate_excess_pv_sink_to_priority

        config = {
            "executor": {
                "excess_pv": {
                    "sink": "custom_entity",
                    "custom_entity": {
                        "entity": "switch.pool_pump",
                        "on_value": "1",
                        "off_value": "0",
                        "power_kw": 2.5,
                    },
                }
            }
        }
        result, changed = _migrate_excess_pv_sink_to_priority(config)
        assert changed
        excess_pv = result["executor"]["excess_pv"]
        assert "sink" not in excess_pv
        assert "custom_entity" not in excess_pv
        assert excess_pv["priority"] == [
            {
                "type": "custom_entity",
                "entity": "switch.pool_pump",
                "on_value": "1",
                "off_value": "0",
                "power_kw": 2.5,
            }
        ]

    def test_disabled_migrated_to_empty_priority(self):
        from backend.config_migration import _migrate_excess_pv_sink_to_priority

        config = {"executor": {"excess_pv": {"sink": "disabled"}}}
        result, changed = _migrate_excess_pv_sink_to_priority(config)
        assert changed
        excess_pv = result["executor"]["excess_pv"]
        assert "sink" not in excess_pv
        assert excess_pv["priority"] == []

    def test_no_sink_key_no_change(self):
        from backend.config_migration import _migrate_excess_pv_sink_to_priority

        config = {"executor": {"excess_pv": {"priority": [{"type": "ev", "charger_id": "x"}]}}}
        result, changed = _migrate_excess_pv_sink_to_priority(config)
        assert not changed
        assert result["executor"]["excess_pv"]["priority"] == [{"type": "ev", "charger_id": "x"}]

    def test_idempotent_second_run_no_op(self):
        from backend.config_migration import _migrate_excess_pv_sink_to_priority

        config = {"executor": {"excess_pv": {"sink": "water_heater_boost"}}}
        result, changed_once = _migrate_excess_pv_sink_to_priority(config)
        assert changed_once
        result, changed_twice = _migrate_excess_pv_sink_to_priority(result)
        assert not changed_twice
        assert result["executor"]["excess_pv"]["priority"] == [{"type": "water_heater_boost"}]

    def test_no_excess_pv_section_no_error(self):
        from backend.config_migration import _migrate_excess_pv_sink_to_priority

        config = {"executor": {}}
        result, changed = _migrate_excess_pv_sink_to_priority(config)
        assert not changed
        assert result == {"executor": {}}

    def test_existing_priority_wins_over_sink(self):
        """If a user has already set both (partial migration or manual edit),
        the existing priority[] is preserved and only 'sink'/'custom_entity' are dropped."""
        from backend.config_migration import _migrate_excess_pv_sink_to_priority

        config = {
            "executor": {
                "excess_pv": {
                    "sink": "custom_entity",
                    "priority": [{"type": "ev", "charger_id": "main_ev"}],
                }
            }
        }
        result, changed = _migrate_excess_pv_sink_to_priority(config)
        assert changed
        excess_pv = result["executor"]["excess_pv"]
        assert "sink" not in excess_pv
        assert excess_pv["priority"] == [{"type": "ev", "charger_id": "main_ev"}]
