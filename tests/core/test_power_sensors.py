"""sensor-unit-overrides: unit resolver, power sensor registry, unit_needed, drift guards."""

import ast
import logging
from pathlib import Path
from typing import ClassVar
from unittest.mock import AsyncMock, patch

import pytest

from backend.core import ha_client, power_sensors
from backend.core.ha_client import (
    ResolvedUnit,
    get_ha_sensor_kw_normalized,
    get_sensor_unit_overrides,
    normalize_power_for_entity,
    parse_power_states,
    resolve_power_unit,
)
from backend.core.power_sensors import POWER_SENSOR_PATHS, compute_unit_needed

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _fresh_warnings():
    ha_client._unitless_warned.clear()
    yield
    ha_client._unitless_warned.clear()


class TestResolver:
    @pytest.mark.parametrize(
        ("reported", "override", "unit", "source"),
        [
            ("W", "kW", "W", "reported"),  # reported wins over override
            ("kW", "W", "kW", "reported"),
            ("MW", None, "MW", "reported"),
            (None, "W", "W", "override"),
            ("", "kW", "kW", "override"),
            ("  ", "W", "W", "override"),
            (None, None, "kW", "assumed"),
            ("", None, "kW", "assumed"),
        ],
    )
    def test_matrix(self, reported, override, unit, source):
        overrides = {"sensor.x": override} if override else {}
        assert resolve_power_unit("sensor.x", reported, overrides) == ResolvedUnit(unit, source)

    def test_override_for_another_entity_is_ignored(self):
        assert resolve_power_unit("sensor.x", None, {"sensor.y": "W"}).source == "assumed"

    @pytest.mark.parametrize(
        ("value", "reported", "override", "expected"),
        [
            (1500, "W", None, 1.5),
            (1.5, "kW", None, 1.5),
            (2, "MW", None, 2000.0),
            (1500, None, "W", 1.5),
            (1500, None, None, 1500.0),  # unitless without override is read as kW
            (1500, "kW", "W", 1500.0),
            (1500, "W", "kW", 1.5),
        ],
    )
    def test_normalize(self, value, reported, override, expected):
        overrides = {"sensor.x": override} if override else {}
        assert normalize_power_for_entity(value, "sensor.x", reported, overrides) == expected

    def test_unitless_warns_once_per_entity_with_the_fix(self, caplog):
        with caplog.at_level(logging.WARNING, logger="darkstar.core.ha_client"):
            for _ in range(3):
                resolve_power_unit("sensor.x", None, {})
            resolve_power_unit("sensor.y", None, {})
            resolve_power_unit("sensor.z", None, {"sensor.z": "W"})
            resolve_power_unit("sensor.q", None, {}, warn_unitless=False)
        messages = [r.getMessage() for r in caplog.records]
        assert len(messages) == 2
        assert "sensor.x" in messages[0]
        assert "assuming kW. Set its unit in Settings" in messages[0]

    def test_overrides_accessor_follows_the_config_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert get_sensor_unit_overrides() == {}
        config = tmp_path / "config.yaml"
        config.write_text("sensor_unit_overrides:\n  sensor.a: W\n  sensor.b: MW\n")
        assert get_sensor_unit_overrides() == {"sensor.a": "W"}
        config.write_text("sensor_unit_overrides:\n  sensor.c: kW\n")
        import os

        os.utime(config, ns=(1, config.stat().st_mtime_ns + 5_000_000))
        assert get_sensor_unit_overrides() == {"sensor.c": "kW"}


class TestCallers:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("attributes", "overrides", "expected"),
        [
            ({}, {}, 1200.0),
            ({}, {"sensor.x": "W"}, 1.2),
            ({"unit_of_measurement": "W"}, {"sensor.x": "kW"}, 1.2),
        ],
    )
    async def test_get_ha_sensor_kw_normalized(self, attributes, overrides, expected):
        state = {"state": "1200", "attributes": attributes}
        with (
            patch.object(ha_client, "get_ha_entity_state", AsyncMock(return_value=state)),
            patch.object(ha_client, "get_sensor_unit_overrides", return_value=overrides),
        ):
            assert await get_ha_sensor_kw_normalized("sensor.x") == pytest.approx(expected)

    @pytest.mark.asyncio
    async def test_unitless_warning_logged_once(self, caplog):
        state = {"state": "5", "attributes": {}}
        with (
            patch.object(ha_client, "get_ha_entity_state", AsyncMock(return_value=state)),
            patch.object(ha_client, "get_sensor_unit_overrides", return_value={}),
            caplog.at_level(logging.WARNING, logger="darkstar.core.ha_client"),
        ):
            for _ in range(3):
                await get_ha_sensor_kw_normalized("sensor.x")
        assert len([r for r in caplog.records if "sensor.x" in r.getMessage()]) == 1

    def test_history_override_and_propagated_unit(self):
        def state(value, minute, unit=None):
            return {
                "state": value,
                "last_changed": f"2026-01-01T00:{minute:02d}:00+00:00",
                "attributes": {"unit_of_measurement": unit} if unit else {},
            }

        unitless = [state("1000", 0), state("2000", 5)]
        assert [v for _, v in parse_power_states(unitless, "sensor.x", {})] == [1000.0, 2000.0]
        assert [v for _, v in parse_power_states(unitless, "sensor.x", {"sensor.x": "W"})] == [
            1.0,
            2.0,
        ]
        propagated = [state("unavailable", 0, "W"), state("1000", 5), state("2000", 10)]
        assert [v for _, v in parse_power_states(propagated, "sensor.x", {"sensor.x": "kW"})] == [
            None,
            1.0,
            2.0,
        ]


CONFIG = {
    "system": {
        "has_battery": True,
        "has_solar": True,
        "has_ev_charger": True,
        "has_water_heater": True,
        "grid_meter_type": "net",
    },
    "input_sensors": {
        "pv_power": "sensor.pv",
        "load_power": "sensor.load",
        "battery_power": "sensor.batt",
        "grid_power": "sensor.grid",
        "grid_import_power": "sensor.imp",
        "grid_export_power": "sensor.exp",
    },
    "ev_chargers": [
        {
            "enabled": True,
            "sensor": "sensor.ev",
            "phase_sensor_l1": "sensor.ev_l1",
        },
        {"enabled": False, "sensor": "sensor.ev_off"},
    ],
    "water_heaters": [{"enabled": True, "sensor": "sensor.wh"}],
    "load_balancing": {
        "loads": [
            {"device_type": "custom_entity", "power_sensor": "sensor.shed"},
            {"device_type": "water_heater", "power_sensor": "sensor.ignored"},
        ]
    },
}


def _states(unit=None, **units):
    names = {
        "sensor.pv",
        "sensor.load",
        "sensor.batt",
        "sensor.grid",
        "sensor.imp",
        "sensor.exp",
        "sensor.ev",
        "sensor.ev_l1",
        "sensor.ev_off",
        "sensor.wh",
        "sensor.shed",
        "sensor.ignored",
    }
    return {n: {"state": "100", "unit_of_measurement": units.get(n, unit)} for n in names}


class TestRegistry:
    def test_each_pattern_expands_against_a_sample_config(self):
        found = {
            (key, path, entity)
            for key, path, entity in power_sensors.referenced_power_sensors(CONFIG)
        }
        assert found == {
            ("pv_power", "input_sensors.pv_power", "sensor.pv"),
            ("load_power", "input_sensors.load_power", "sensor.load"),
            ("battery_power", "input_sensors.battery_power", "sensor.batt"),
            ("grid_power", "input_sensors.grid_power", "sensor.grid"),
            ("ev_power", "ev_chargers.0.sensor", "sensor.ev"),
            ("ev_phase_power", "ev_chargers.0.phase_sensor_l1", "sensor.ev_l1"),
            ("water_power", "water_heaters.0.sensor", "sensor.wh"),
            ("load_device_power", "load_balancing.loads.0.power_sensor", "sensor.shed"),
        }

    def test_inactive_entries_are_included_on_request(self):
        everything = power_sensors.referenced_entity_ids(CONFIG, active_only=False)
        assert {"sensor.ev_off", "sensor.imp", "sensor.exp"} <= everything
        assert "sensor.ignored" not in everything

    def test_dual_meter_swaps_grid_roles(self):
        config = {**CONFIG, "system": {**CONFIG["system"], "grid_meter_type": "dual"}}
        entities = power_sensors.referenced_entity_ids(config)
        assert {"sensor.imp", "sensor.exp"} <= entities
        assert "sensor.grid" not in entities

    def test_features_switched_off_are_not_referenced(self):
        system = {**CONFIG["system"], "has_solar": False, "has_ev_charger": False}
        entities = power_sensors.referenced_entity_ids({**CONFIG, "system": system})
        assert "sensor.pv" not in entities
        assert "sensor.ev" not in entities


class TestComputeUnitNeeded:
    def test_one_case_per_registry_path(self):
        needed = compute_unit_needed(CONFIG, _states())
        assert {n["settings_path"] for n in needed} == {
            "input_sensors.pv_power",
            "input_sensors.load_power",
            "input_sensors.battery_power",
            "input_sensors.grid_power",
            "ev_chargers.0.sensor",
            "water_heaters.0.sensor",
            "load_balancing.loads.0.power_sensor",
        }
        pv = next(n for n in needed if n["entity_id"] == "sensor.pv")
        assert pv == {
            "entity_id": "sensor.pv",
            "settings_path": "input_sensors.pv_power",
            "live_value": 100.0,
            "override": None,
        }

    def test_phase_sensors_are_never_listed(self):
        assert "sensor.ev_l1" not in {
            n["entity_id"] for n in compute_unit_needed(CONFIG, _states())
        }

    def test_unit_reported_is_not_listed(self):
        assert compute_unit_needed(CONFIG, _states("W")) == []

    def test_override_present_is_listed_with_its_value(self):
        config = {**CONFIG, "sensor_unit_overrides": {"sensor.pv": "W"}}
        overrides = {n["entity_id"]: n["override"] for n in compute_unit_needed(config, _states())}
        assert overrides["sensor.pv"] == "W"
        assert overrides["sensor.load"] is None

    def test_override_ignored_when_ha_reports_a_unit(self):
        config = {**CONFIG, "sensor_unit_overrides": {"sensor.pv": "W"}}
        assert compute_unit_needed(config, _states("kW")) == []

    @pytest.mark.parametrize("state", ["unavailable", "unknown", "abc", None, "nan"])
    def test_non_numeric_state_is_not_listed(self, state):
        states = _states()
        states["sensor.pv"]["state"] = state
        assert "sensor.pv" not in {n["entity_id"] for n in compute_unit_needed(CONFIG, states)}

    def test_missing_entity_is_not_listed(self):
        states = _states()
        del states["sensor.pv"]
        assert "sensor.pv" not in {n["entity_id"] for n in compute_unit_needed(CONFIG, states)}

    def test_entity_used_twice_is_listed_once(self):
        config = {
            **CONFIG,
            "input_sensors": {"pv_power": "sensor.same", "load_power": "sensor.same"},
        }
        states = {"sensor.same": {"state": "3", "unit_of_measurement": ""}}
        assert len(compute_unit_needed(config, states)) == 1

    def test_draft_selection_changes_the_list(self):
        draft = {**CONFIG, "input_sensors": {"pv_power": "sensor.other"}}
        states = {
            **_states("W"),
            "sensor.other": {"state": "1", "unit_of_measurement": None},
        }
        assert [n["entity_id"] for n in compute_unit_needed(draft, states)] == ["sensor.other"]


def _python_files(*roots):
    for root in roots:
        yield from (REPO_ROOT / root).rglob("*.py")


def _path_key_values():
    """Every ``path_key=`` argument in backend and executor, outside the registry module."""
    for file in _python_files("backend", "executor"):
        if file.name == "power_sensors.py":
            continue
        tree = ast.parse(file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "path_key":
                yield file, node.value


def _constant_names():
    return {
        name: getattr(power_sensors, name)
        for name in dir(power_sensors)
        if name.isupper()
        and isinstance(getattr(power_sensors, name), str)
        and getattr(power_sensors, name) in POWER_SENSOR_PATHS
    }


class TestDriftGuards:
    def test_every_path_key_passed_to_the_resolver_is_in_the_registry(self):
        constants = _constant_names()
        seen = 0
        for file, value in _path_key_values():
            seen += 1
            if isinstance(value, ast.Constant):
                assert value.value is None or value.value in POWER_SENSOR_PATHS, file
            elif isinstance(value, ast.Name | ast.Attribute):
                name = value.id if isinstance(value, ast.Name) else value.attr
                # A constant from the registry module, or a variable forwarding one.
                assert name in constants or name.islower(), (file, name)
        assert seen

    def test_every_registry_entry_has_a_caller(self):
        constants = _constant_names()
        referenced: set[str] = set()
        for file in _python_files("backend", "executor"):
            if file.name == "power_sensors.py":
                continue
            for node in ast.walk(ast.parse(file.read_text())):
                if isinstance(node, ast.Name) and node.id in constants:
                    referenced.add(constants[node.id])
        assert referenced == set(POWER_SENSOR_PATHS)

    def test_registry_keys_and_constants_agree(self):
        assert set(_constant_names().values()) == set(POWER_SENSOR_PATHS)
        for key, entry in POWER_SENSOR_PATHS.items():
            assert entry.path_key == key
            assert entry.patterns

    # Modules that read ``unit_of_measurement`` for something other than the unit
    # of a power reading to convert to kW. Anything else must use the resolver.
    NON_POWER_READS: ClassVar[set[str]] = {
        "backend/core/ha_client.py",  # the resolver's own inputs and history unit propagation
        "backend/core/ha_registry.py",  # discovery metadata
        "backend/core/readiness.py",  # reports HA's unit; unit_needed comes from the registry
        "backend/core/entity_matcher.py",  # entity suggestions
        "backend/api/routers/config.py",  # phase sensor unit classification (A or W/kW)
        "backend/api/routers/ha.py",  # entity metadata for the UI
        "backend/ha_socket.py",  # forwards entity metadata on state changes
        "backend/events.py",  # attribute allowlist for emitted entity changes
        "backend/api/routers/setup.py",  # passes the reported unit to compute_unit_needed
        "backend/core/water_progress.py",  # carries a reported unit across history states
        "executor/engine.py",  # grid phase sensor classification (A or W/kW) and EV phase
        "executor/load_balancer.py",  # phase sensor unit classification
    }

    def test_no_module_reads_power_units_outside_the_resolver(self):
        offenders = set()
        for file in _python_files("backend", "executor"):
            relative = file.relative_to(REPO_ROOT).as_posix()
            if relative in self.NON_POWER_READS or relative == "backend/core/power_sensors.py":
                continue
            if "unit_of_measurement" in file.read_text():
                offenders.add(relative)
        assert not offenders, f"read power units through resolve_power_unit instead: {offenders}"

    def test_no_inline_watt_conversion_in_converted_modules(self):
        for relative in ("backend/ha_socket.py", "backend/api/routers/system.py"):
            text = (REPO_ROOT / relative).read_text()
            assert '== "W"' not in text, relative
