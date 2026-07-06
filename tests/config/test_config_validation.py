from backend.api.routers.config import _validate_config_for_save


def test_validate_config_executor_entities_required_when_enabled():
    config = {
        "executor": {"enabled": True, "inverter": {}},
        "system": {"has_battery": True},
        "input_sensors": {},
    }
    issues = _validate_config_for_save(config)

    # REV UI23: Missing required entities now return warnings instead of errors
    # to allow incremental configuration across tabs
    warning_messages = [i["message"] for i in issues if i["severity"] == "warning"]
    assert any("work_mode" in m for m in warning_messages)
    assert any("grid_charging_enable" in m for m in warning_messages)
    assert any("battery_soc" in m for m in warning_messages)


def test_validate_config_executor_entities_not_required_when_disabled():
    config = {
        "executor": {"enabled": False, "inverter": {}},
        "system": {"has_battery": True},
        "input_sensors": {},
    }
    issues = _validate_config_for_save(config)

    # Should NOT have errors for missing executor entities if disabled
    # (But might still have battery capacity error if has_battery is True)
    error_messages = [i["message"] for i in issues if i["severity"] == "error"]
    assert not any("executor.inverter.work_mode" in m for m in error_messages)
    assert not any("executor.inverter.grid_charging_enable" in m for m in error_messages)
    # input_sensors.battery_soc might still be considered critical for other things?
    # Current implementation in _validate_config_for_save only checks them if executor is enabled.
    assert not any("input_sensors.battery_soc" in m for m in error_messages)


def test_validate_config_battery_capacity_required():
    config = {
        "executor": {"enabled": False},
        "system": {"has_battery": True},
        "battery": {"capacity_kwh": 0},
    }
    issues = _validate_config_for_save(config)
    assert any(
        "Battery enabled but capacity not configured" in i["message"]
        for i in issues
        if i["severity"] == "error"
    )


def test_validate_config_valid_config_no_issues():
    config = {
        "executor": {
            "enabled": True,
            "inverter": {
                "work_mode": "select.inverter_work_mode",
                "grid_charging_enable": "switch.inverter_grid_charging",
                "soc_target": "number.soc_target",
            },
        },
        "system": {"has_battery": True, "location": {"latitude": 59.3, "longitude": 18.1}},
        "battery": {"capacity_kwh": 10.0},
        "input_sensors": {"battery_soc": "sensor.battery_soc"},
    }
    issues = _validate_config_for_save(config)
    errors = [i for i in issues if i["severity"] == "error"]
    assert len(errors) == 0


def test_validate_config_battery_entities_not_required_if_no_battery():
    config = {
        "executor": {"enabled": True, "inverter": {}},
        "system": {"has_battery": False},
        "input_sensors": {},
        # Provide valid non-battery config to avoid other errors
        "battery": {"capacity_kwh": 0},
    }
    issues = _validate_config_for_save(config)

    # Should NOT have errors for missing battery entities
    error_messages = [i["message"] for i in issues if i["severity"] == "error"]
    assert not any("executor.inverter.work_mode" in m for m in error_messages)
    assert not any("executor.inverter.grid_charging_enable" in m for m in error_messages)
    assert not any("input_sensors.battery_soc" in m for m in error_messages)


def test_validate_config_fronius_success():
    """Verify Fronius config validates without grid_charging_entity."""
    config = {
        "executor": {
            "enabled": True,
            "inverter": {
                "work_mode": "select.mode",
                "max_charge_power": "number.max_charge",
                "max_discharge_power": "number.max_discharge",
                "minimum_reserve": "number.reserve",
                "grid_charge_power": "number.charge_power",
                "soc_target": "input_number.target",
            },
        },
        "system": {
            "has_battery": True,
            "inverter_profile": "fronius",
            "location": {"latitude": 59.3, "longitude": 18.1},
        },
        "input_sensors": {"battery_soc": "sensor.soc"},
        "battery": {"capacity_kwh": 10},
        "water_heating": {},
    }
    issues = _validate_config_for_save(config)
    errors = [i for i in issues if i["severity"] == "error"]
    assert len(errors) == 0, f"Found errors: {errors}"


class TestWaterHeaterValidation:
    """Test water_heaters[] array validation (ARC15)."""

    def test_valid_water_heater_new_format(self):
        config = {
            "config_version": 2,
            "system": {"has_water_heater": True, "has_battery": False, "has_ev_charger": False},
            "water_heaters": [
                {
                    "id": "main_tank",
                    "name": "Main Water Heater",
                    "enabled": True,
                    "power_kw": 3.0,
                    "min_kwh_per_day": 6.0,
                    "sensor": "sensor.vvb_power",
                    "type": "binary",
                }
            ],
        }
        issues = _validate_config_for_save(config)
        water_heater_errors = [
            i for i in issues if i["severity"] == "error" and "water heater" in i["message"].lower()
        ]
        assert len(water_heater_errors) == 0

    def test_water_heater_missing_id(self):
        config = {
            "config_version": 2,
            "system": {"has_water_heater": True, "has_battery": False, "has_ev_charger": False},
            "water_heaters": [{"name": "Main Water Heater", "power_kw": 3.0}],
        }
        issues = _validate_config_for_save(config)
        errors = [i for i in issues if i["severity"] == "error"]
        assert any("missing required field 'id'" in e["message"] for e in errors)

    def test_water_heater_duplicate_id(self):
        config = {
            "config_version": 2,
            "system": {"has_water_heater": True, "has_battery": False, "has_ev_charger": False},
            "water_heaters": [
                {"id": "main_tank", "name": "Water Heater 1", "power_kw": 3.0},
                {"id": "main_tank", "name": "Water Heater 2", "power_kw": 3.0},
            ],
        }
        issues = _validate_config_for_save(config)
        errors = [i for i in issues if i["severity"] == "error"]
        assert any("Duplicate water heater ID" in e["message"] for e in errors)


class TestEVChargerValidation:
    """Test ev_chargers[] array validation (ARC15)."""

    def test_valid_ev_charger_new_format(self):
        config = {
            "config_version": 2,
            "system": {"has_ev_charger": True, "has_battery": False, "has_water_heater": False},
            "ev_chargers": [
                {
                    "id": "tesla",
                    "name": "Tesla Model 3",
                    "enabled": True,
                    "max_power_kw": 11.0,
                    "battery_capacity_kwh": 82.0,
                    "sensor": "sensor.tesla_power",
                    "type": "variable",
                    "nominal_power_kw": 11.0,
                }
            ],
        }
        issues = _validate_config_for_save(config)
        ev_errors = [
            i for i in issues if i["severity"] == "error" and "ev charger" in i["message"].lower()
        ]
        assert len(ev_errors) == 0

    def test_ev_departure_time_valid(self):
        for time_str in ["07:00", "23:30", "00:00", "12:59", "7:00"]:
            config = {
                "config_version": 2,
                "system": {"has_ev_charger": True, "has_battery": False, "has_water_heater": False},
                "ev_chargers": [
                    {
                        "id": "tesla",
                        "name": "Tesla",
                        "max_power_kw": 11.0,
                        "battery_capacity_kwh": 82.0,
                    }
                ],
                "ev_departure_time": time_str,
            }
            issues = _validate_config_for_save(config)
            errors = [
                i
                for i in issues
                if i["severity"] == "error" and "departure time" in i["message"].lower()
            ]
            assert len(errors) == 0

    def test_ev_departure_time_invalid(self):
        for time_str in ["25:00", "12:60", "7:00 AM", "invalid"]:
            config = {
                "config_version": 2,
                "system": {"has_ev_charger": True, "has_battery": False, "has_water_heater": False},
                "ev_chargers": [
                    {
                        "id": "tesla",
                        "name": "Tesla",
                        "max_power_kw": 11.0,
                        "battery_capacity_kwh": 82.0,
                    }
                ],
                "ev_departure_time": time_str,
            }
            issues = _validate_config_for_save(config)
            errors = [
                i
                for i in issues
                if i["severity"] == "error" and "departure time" in i["message"].lower()
            ]
            assert len(errors) == 1


class TestEVChargerCurrentTypeValidation:
    """universal-load-balancing 1.6: type: current field validation replaces the
    old blanket 'not yet implemented' warning."""

    def _base_config(self, ev_overrides):
        ev = {
            "id": "goe",
            "name": "go-e Gemini",
            "max_power_kw": 11.0,
            "battery_capacity_kwh": 82.0,
        }
        ev.update(ev_overrides)
        return {
            "config_version": 2,
            "system": {"has_ev_charger": True, "has_battery": False, "has_water_heater": False},
            "ev_chargers": [ev],
        }

    def test_valid_current_type_no_warning(self):
        config = self._base_config(
            {
                "type": "current",
                "current_entity": "number.goe_current",
                "min_current_a": 6,
                "max_current_a": 16,
            }
        )
        issues = _validate_config_for_save(config)
        assert not any("uses unsupported type" in i["message"] for i in issues)
        assert not any("current_entity" in i["message"] for i in issues)
        assert not any("max_current_a" in i["message"] for i in issues)

    def test_current_type_without_current_entity_is_error(self):
        config = self._base_config({"type": "current", "max_current_a": 16})
        issues = _validate_config_for_save(config)
        errors = [i for i in issues if i["severity"] == "error"]
        assert any("current_entity" in e["message"] for e in errors)

    def test_current_type_without_max_current_a_is_error(self):
        config = self._base_config(
            {"type": "current", "current_entity": "number.goe_current"}
        )
        issues = _validate_config_for_save(config)
        errors = [i for i in issues if i["severity"] == "error"]
        assert any("max_current_a" in e["message"] for e in errors)

    def test_current_type_invalid_min_current_a_is_error(self):
        config = self._base_config(
            {
                "type": "current",
                "current_entity": "number.goe_current",
                "max_current_a": 16,
                "min_current_a": 0,
            }
        )
        issues = _validate_config_for_save(config)
        errors = [i for i in issues if i["severity"] == "error"]
        assert any("min_current_a" in e["message"] for e in errors)

    def test_unknown_type_still_warns(self):
        config = self._base_config({"type": "power"})
        issues = _validate_config_for_save(config)
        warnings = [i for i in issues if i["severity"] == "warning"]
        assert any("uses unsupported type" in w["message"] for w in warnings)


class TestLoadBalancingValidation:
    """universal-load-balancing 1.5: startup validation with actionable errors."""

    def _base_config(self, load_balancing, **extra):
        config = {
            "config_version": 2,
            "system": {"has_battery": False, "has_water_heater": False, "has_ev_charger": False},
            "load_balancing": load_balancing,
        }
        config.update(extra)
        return config

    def test_disabled_produces_no_load_balancing_issues(self):
        config = self._base_config({"enabled": False})
        issues = _validate_config_for_save(config)
        assert not any("load_balancing" in i["message"] for i in issues)

    def test_missing_main_fuse_a_is_error(self):
        config = self._base_config(
            {
                "enabled": True,
                "loads": [{"device_type": "custom_entity", "device_id": "pump", "phases": [1]}],
            }
        )
        config["input_sensors"] = {
            "grid_current_l1": "sensor.l1",
            "grid_current_l2": "sensor.l2",
            "grid_current_l3": "sensor.l3",
        }
        issues = _validate_config_for_save(config)
        errors = [i for i in issues if i["severity"] == "error"]
        assert any("system.grid.main_fuse_a" in e["message"] for e in errors)

    def test_main_fuse_a_too_large_is_error(self):
        config = self._base_config({"enabled": True, "loads": []})
        config["system"]["grid"] = {"main_fuse_a": 200}
        issues = _validate_config_for_save(config)
        errors = [i for i in issues if i["severity"] == "error"]
        assert any("system.grid.main_fuse_a" in e["message"] for e in errors)

    def test_missing_phase_sensor_is_error(self):
        config = self._base_config(
            {
                "enabled": True,
                "loads": [{"device_type": "custom_entity", "device_id": "pump", "phases": [1]}],
            }
        )
        config["system"]["grid"] = {"main_fuse_a": 20}
        config["input_sensors"] = {
            "grid_current_l1": "sensor.l1",
            "grid_current_l3": "sensor.l3",
        }
        issues = _validate_config_for_save(config)
        errors = [i for i in issues if i["severity"] == "error"]
        assert any("input_sensors.grid_current_l2" in e["message"] for e in errors)

    def test_empty_loads_is_error(self):
        config = self._base_config({"enabled": True, "loads": []})
        config["system"]["grid"] = {"main_fuse_a": 20}
        config["input_sensors"] = {
            "grid_current_l1": "sensor.l1",
            "grid_current_l2": "sensor.l2",
            "grid_current_l3": "sensor.l3",
        }
        issues = _validate_config_for_save(config)
        errors = [i for i in issues if i["severity"] == "error"]
        assert any("load_balancing.loads" in e["message"] for e in errors)

    def test_load_references_unknown_ev_charger_is_error(self):
        config = self._base_config(
            {
                "enabled": True,
                "loads": [{"device_type": "ev_charger", "device_id": "ghost", "phases": [1]}],
            }
        )
        config["system"]["grid"] = {"main_fuse_a": 20}
        config["input_sensors"] = {
            "grid_current_l1": "sensor.l1",
            "grid_current_l2": "sensor.l2",
            "grid_current_l3": "sensor.l3",
        }
        config["ev_chargers"] = [{"id": "real_ev"}]
        issues = _validate_config_for_save(config)
        errors = [i for i in issues if i["severity"] == "error"]
        assert any(
            "references unknown EV charger id" in e["message"] and "ghost" in e["message"]
            for e in errors
        )

    def test_load_with_empty_phases_is_error(self):
        config = self._base_config(
            {
                "enabled": True,
                "loads": [{"device_type": "custom_entity", "device_id": "pump", "phases": []}],
            }
        )
        config["system"]["grid"] = {"main_fuse_a": 20}
        config["input_sensors"] = {
            "grid_current_l1": "sensor.l1",
            "grid_current_l2": "sensor.l2",
            "grid_current_l3": "sensor.l3",
        }
        issues = _validate_config_for_save(config)
        errors = [i for i in issues if i["severity"] == "error"]
        assert any("empty phases list" in e["message"] for e in errors)

    def test_fully_valid_config_has_no_load_balancing_errors(self):
        config = self._base_config(
            {
                "enabled": True,
                "loads": [{"device_type": "water_heater", "device_id": "main_tank", "phases": [2]}],
            }
        )
        config["system"]["grid"] = {"main_fuse_a": 20}
        config["input_sensors"] = {
            "grid_current_l1": "sensor.l1",
            "grid_current_l2": "sensor.l2",
            "grid_current_l3": "sensor.l3",
        }
        config["water_heaters"] = [{"id": "main_tank"}]
        issues = _validate_config_for_save(config)
        errors = [i for i in issues if i["severity"] == "error"]
        assert not any("load_balancing" in e["message"] or "grid_current" in e["message"] or "main_fuse_a" in e["message"] for e in errors)


class TestLoadBalancingPowerSensorValidation:
    """load-balancing-power-sensors: unit recognition, type: current rejection
    from loads[], dynamically-throttled charger satisfying the "at least one
    balanced load" rule, and charger_priority reference validation."""

    def _base_config(self, load_balancing, **extra):
        config = {
            "config_version": 2,
            "system": {
                "has_battery": False,
                "has_water_heater": False,
                "has_ev_charger": False,
                "grid": {"main_fuse_a": 20},
            },
            "input_sensors": {
                "grid_current_l1": "sensor.l1",
                "grid_current_l2": "sensor.l2",
                "grid_current_l3": "sensor.l3",
            },
            "load_balancing": load_balancing,
        }
        config.update(extra)
        return config

    def test_unrecognized_unit_is_error(self):
        config = self._base_config({"enabled": True, "loads": []})
        config["ev_chargers"] = [{"id": "goe", "type": "current"}]
        phase_units = {"sensor.l1": {"unit_of_measurement": "lux", "device_class": ""}}
        issues = _validate_config_for_save(config, phase_units)
        errors = [i for i in issues if i["severity"] == "error"]
        assert any(
            "grid_current_l1" in e["message"] and "lux" in e["message"] for e in errors
        )

    def test_recognized_power_unit_is_not_an_error(self):
        config = self._base_config({"enabled": True, "loads": []})
        config["ev_chargers"] = [{"id": "goe", "type": "current"}]
        phase_units = {
            "sensor.l1": {"unit_of_measurement": "W", "device_class": "power"},
            "sensor.l2": {"unit_of_measurement": "A", "device_class": "current"},
            "sensor.l3": {"unit_of_measurement": "kW", "device_class": "power"},
        }
        issues = _validate_config_for_save(config, phase_units)
        errors = [i for i in issues if i["severity"] == "error"]
        assert not any("unrecognized unit" in e["message"] for e in errors)

    def test_no_phase_sensor_units_available_skips_unit_check(self):
        # Simulates HA being unreachable at validation time (best-effort check).
        config = self._base_config({"enabled": True, "loads": []})
        config["ev_chargers"] = [{"id": "goe", "type": "current"}]
        issues = _validate_config_for_save(config, {})
        errors = [i for i in issues if i["severity"] == "error"]
        assert not any("unrecognized unit" in e["message"] for e in errors)

    def test_type_current_charger_in_loads_is_error(self):
        config = self._base_config(
            {
                "enabled": True,
                "loads": [{"device_type": "ev_charger", "device_id": "goe", "phases": [1]}],
            }
        )
        config["ev_chargers"] = [{"id": "goe", "type": "current"}]
        issues = _validate_config_for_save(config)
        errors = [i for i in issues if i["severity"] == "error"]
        assert any(
            "type: current" in e["message"] and "goe" in e["message"] for e in errors
        )

    def test_type_binary_charger_in_loads_is_still_allowed(self):
        config = self._base_config(
            {
                "enabled": True,
                "loads": [{"device_type": "ev_charger", "device_id": "goe", "phases": [1]}],
            }
        )
        config["ev_chargers"] = [{"id": "goe", "type": "binary"}]
        issues = _validate_config_for_save(config)
        errors = [i for i in issues if i["severity"] == "error"]
        assert not any("type: current" in e["message"] for e in errors)

    def test_dynamically_throttled_charger_alone_satisfies_at_least_one_load(self):
        config = self._base_config({"enabled": True, "loads": []})
        config["ev_chargers"] = [{"id": "goe", "type": "current"}]
        issues = _validate_config_for_save(config)
        errors = [i for i in issues if i["severity"] == "error"]
        assert not any("load_balancing.loads is empty" in e["message"] for e in errors)

    def test_empty_loads_and_no_current_charger_is_still_error(self):
        config = self._base_config({"enabled": True, "loads": []})
        config["ev_chargers"] = [{"id": "goe", "type": "binary"}]
        issues = _validate_config_for_save(config)
        errors = [i for i in issues if i["severity"] == "error"]
        assert any("load_balancing.loads is empty" in e["message"] for e in errors)

    def test_charger_priority_referencing_non_current_charger_is_warning(self):
        config = self._base_config(
            {"enabled": True, "loads": [], "charger_priority": {"goe": 1, "ghost": 2}}
        )
        config["ev_chargers"] = [{"id": "goe", "type": "current"}]
        issues = _validate_config_for_save(config)
        warnings = [i for i in issues if i["severity"] == "warning"]
        assert any("ghost" in w["message"] for w in warnings)
        assert not any("goe" in w["message"] for w in warnings)


class TestBackwardCompatibility:
    """Test backward compatibility (ARC15)."""

    def test_legacy_water_heater_format(self):
        config = {
            "config_version": 1,
            "system": {"has_water_heater": True, "has_battery": False, "has_ev_charger": False},
            "water_heating": {"power_kw": 3.0, "min_kwh_per_day": 6.0},
            "deferrable_loads": [
                {
                    "id": "water_heater",
                    "name": "Water Heater",
                    "type": "binary",
                    "nominal_power_kw": 3.0,
                }
            ],
        }
        issues = _validate_config_for_save(config)
        water_heater_errors = [
            i for i in issues if i["severity"] == "error" and "water heater" in i["message"].lower()
        ]
        assert len(water_heater_errors) == 0


class TestPreWriteValidation:
    """Test pre-write structural validation (F57)."""

    def test_validate_config_for_write_success(self):
        from backend.config_migration import validate_config_for_write

        config = {
            "config_version": 2,
            "system": {},
            "battery": {},
            "executor": {},
            "input_sensors": {},
        }
        assert validate_config_for_write(config) is True

    def test_validate_config_for_write_missing_section(self):
        from backend.config_migration import validate_config_for_write

        config = {"config_version": 2, "system": {}, "executor": {}, "input_sensors": {}}
        assert validate_config_for_write(config) is False

    def test_validate_config_for_write_deprecated_key(self):
        from backend.config_migration import validate_config_for_write

        config = {
            "config_version": 2,
            "system": {},
            "battery": {},
            "executor": {},
            "input_sensors": {},
            "deferrable_loads": [],
        }
        assert validate_config_for_write(config) is False


def test_validate_config_inverter_warnings_when_missing():
    """Should warn when inverter limits are missing and battery/solar are enabled."""
    config = {
        "executor": {"enabled": False},
        "system": {
            "has_battery": True,
            "has_solar": True,
            "inverter": {},  # Missing max_ac_power_kw and max_dc_input_kw
        },
        "battery": {"capacity_kwh": 10.0},
    }
    issues = _validate_config_for_save(config)

    # Should have warnings for missing inverter config
    warning_messages = [i["message"] for i in issues if i["severity"] == "warning"]
    assert any("Inverter AC power limit not configured" in m for m in warning_messages)
    assert any("Inverter DC input limit not configured" in m for m in warning_messages)


def test_validate_config_inverter_no_warning_when_configured():
    """Should not warn when inverter limits are configured."""
    config = {
        "executor": {"enabled": False},
        "system": {
            "has_battery": True,
            "has_solar": True,
            "inverter": {
                "max_ac_power_kw": 10.0,
                "max_dc_input_kw": 12.0,
            },
        },
        "battery": {"capacity_kwh": 10.0},
    }
    issues = _validate_config_for_save(config)

    # Should NOT have warnings for inverter config
    warning_messages = [i["message"] for i in issues if i["severity"] == "warning"]
    assert not any("Inverter AC power limit not configured" in m for m in warning_messages)
    assert not any("Inverter DC input limit not configured" in m for m in warning_messages)


def test_validate_config_inverter_both_warnings_with_solar():
    """Should warn about both AC and DC when solar is enabled (regardless of battery)."""
    config = {
        "executor": {"enabled": False},
        "system": {
            "has_battery": False,
            "has_solar": True,
            "inverter": {},  # Missing limits
        },
        "battery": {"capacity_kwh": 0},
    }
    issues = _validate_config_for_save(config)

    warning_messages = [i["message"] for i in issues if i["severity"] == "warning"]
    # AC power warning SHOULD appear (has solar - AC limit needed for PV export)
    assert any("Inverter AC power limit not configured" in m for m in warning_messages)
    # DC input warning SHOULD appear (has solar)
    assert any("Inverter DC input limit not configured" in m for m in warning_messages)


def test_validate_config_inverter_ac_only_warning_with_battery():
    """Should only warn about AC power when battery is enabled but solar is not."""
    config = {
        "executor": {"enabled": False},
        "system": {
            "has_battery": True,
            "has_solar": False,
            "inverter": {},  # Missing limits
        },
        "battery": {"capacity_kwh": 10.0},
    }
    issues = _validate_config_for_save(config)

    warning_messages = [i["message"] for i in issues if i["severity"] == "warning"]
    # AC power warning SHOULD appear (has battery)
    assert any("Inverter AC power limit not configured" in m for m in warning_messages)
    # DC input warning should NOT appear (no solar)
    assert not any("Inverter DC input limit not configured" in m for m in warning_messages)
