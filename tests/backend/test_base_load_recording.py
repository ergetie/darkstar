"""Base-load integrity on the write path: isolation, coverage, inactive devices, store merge."""

import ast
import asyncio
import inspect
import logging
import sqlite3
from datetime import timedelta

import pandas as pd
import pytest
import pytz

import backend.core.slot_energy as slot_energy_module
from backend.core.ha_client import parse_power_states
from backend.core.slot_energy import (
    MIN_COVERAGE_SHARE,
    BaseLoadIsolation,
    SlotEnergySources,
    build_slot_sources,
    compute_slot_energy,
    isolate_base_load,
    slot_base_load_flag,
)
from backend.core.water_heating import NOISE_FLOOR_KW, normalize_active_power_kw
from backend.learning.models import Base
from backend.learning.store import LearningStore
from tests.backend.test_recorder_slot_energy import base_config, constant, record, series
from tests.backend.test_slot_energy_gaps import BASE, SLOT, SOURCES, _backfill_engine, _states

WATER_ENV = {
    "system": {"has_water_heater": True},
    "water_heaters": [{"id": "wh1", "enabled": True, "sensor": "sensor.wh"}],
}


def _water_config(**overrides):
    return base_config(**(WATER_ENV | overrides))


class TestNoiseFloor:
    def test_constant_is_pinned(self):
        assert NOISE_FLOOR_KW == 0.010

    @pytest.mark.parametrize(
        ("value", "unit", "cutoff", "expected"),
        [
            (0.001, "kW", 0.0, 0.0),
            (1, "W", 0.0, 0.0),
            (9, "W", 0.0, 0.0),
            (10, "W", 0.0, 0.010),
            (0.010, "kW", 0.0, 0.010),
            (100, "W", 0.0, 0.1),
            (99, "W", 0.10, 0.0),
            (100, "W", 0.10, 0.1),
            (0.00001, "MW", 0.0, 0.010),
            (0.06, "kW", 0.10, 0.0),
        ],
    )
    def test_effective_cutoff(self, value, unit, cutoff, expected):
        assert normalize_active_power_kw(value, unit, cutoff) == pytest.approx(expected)

    def test_non_heater_sensors_are_not_filtered(self):
        assert normalize_active_power_kw(0.005, "kW") == pytest.approx(0.005)
        assert normalize_active_power_kw(-0.5, "kW") == pytest.approx(-0.5)

    def test_history_and_snapshot_paths_agree(self):
        sources = build_slot_sources(_water_config())
        for watts in (1, 9, 10, 2000):
            states = _states([(0, str(watts / 1000))])
            series_ = {"sensor.wh": parse_power_states(states)}
            energy = compute_slot_energy(sources, series_, BASE, BASE + SLOT)
            snapshot = normalize_active_power_kw(watts / 1000, "kW", 0.0)
            assert energy.water["sensor.wh"] == pytest.approx(snapshot * 0.25)

    @pytest.mark.asyncio
    async def test_recorder_ignores_stray_watts(self):
        history = {
            "sensor.load": constant("sensor.load", 0.5),
            "sensor.wh": constant("sensor.wh", 0.002),
        }
        record_, _ = await record(_water_config(), history)
        assert record_["water_kwh"] == 0.0
        assert record_["load_kwh"] == pytest.approx(0.125)
        assert "base_load" not in record_["quality_flags"]


class TestIsolation:
    def test_exact_zero_is_not_a_clamp(self):
        assert isolate_base_load(1.0, 0.25, 0.75) == BaseLoadIsolation(0.0, False)

    def test_negative_is_clamped(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = isolate_base_load(0.20, 0.0, 0.75)
        assert result == BaseLoadIsolation(0.0, True)
        assert sum("Negative base load" in r.message for r in caplog.records) == 1

    def test_no_deferrable_load_passes_through(self):
        assert isolate_base_load(0.3, 0.0, 0.0) == BaseLoadIsolation(0.3, False)

    def test_subtraction(self):
        result = isolate_base_load(6.0, 2.0, 0.75)
        assert result.kwh == pytest.approx(3.25)
        assert not result.clamped


class TestCoverage:
    def test_constant_is_pinned(self):
        assert MIN_COVERAGE_SHARE == 0.95

    def _energy(self, wh_points, load_points=((0, "3.0"),)):
        series_ = {
            "sensor.load": parse_power_states(_states(list(load_points))),
            "sensor.wh": parse_power_states(_states(list(wh_points))),
        }
        return compute_slot_energy(SOURCES, series_, BASE, BASE + SLOT)

    def test_full_coverage(self):
        energy = self._energy([(0, "2.0")])
        assert energy.water_coverage["sensor.wh"] == pytest.approx(1.0)
        assert energy.load_coverage == pytest.approx(1.0)
        assert slot_base_load_flag(SOURCES, energy, False) is None

    def test_ten_of_fifteen_minutes_flags_the_device_only(self):
        energy = self._energy([(300, "2.0")])
        assert energy.water["sensor.wh"] == pytest.approx(2.0 * 600 / 3600)
        assert energy.water_coverage["sensor.wh"] == pytest.approx(600 / 900)
        assert slot_base_load_flag(SOURCES, energy, False) == {
            "reliable": False,
            "reasons": ["device_partial_coverage"],
        }

    def test_total_load_partial_coverage(self):
        energy = self._energy([(0, "2.0")], load_points=[(300, "3.0")])
        assert energy.load_coverage == pytest.approx(600 / 900)
        flag = slot_base_load_flag(SOURCES, energy, False)
        assert flag is not None
        assert flag["reasons"] == ["load_partial_coverage"]

    @pytest.mark.parametrize(
        ("gap_seconds", "flagged"), [(45, False), (46, True), (60, True)]
    )
    def test_boundary_at_ninety_five_percent(self, gap_seconds, flagged):
        energy = self._energy([(gap_seconds, "2.0")])
        assert (slot_base_load_flag(SOURCES, energy, False) is not None) is flagged

    def test_gap_marker_in_the_middle(self):
        energy = self._energy([(0, "2.0"), (300, "unavailable"), (600, "2.0")])
        assert energy.water_coverage["sensor.wh"] == pytest.approx(600 / 900)
        assert slot_base_load_flag(SOURCES, energy, False) is not None

    def test_absent_sensor_is_not_a_second_flag(self):
        energy = self._energy([])
        assert energy.water["sensor.wh"] is None
        assert slot_base_load_flag(SOURCES, energy, False) is None


class TestInactiveDevices:
    @pytest.mark.parametrize(
        "config",
        [
            base_config(
                system={"has_water_heater": False},
                water_heaters=[{"id": "wh1", "enabled": True, "sensor": "sensor.wh"}],
            ),
            base_config(
                system={"has_water_heater": True},
                water_heaters=[{"id": "wh1", "enabled": False, "sensor": "sensor.wh"}],
            ),
        ],
    )
    def test_water_sensors_are_watched_in_the_one_batch(self, config):
        sources = build_slot_sources(config)
        assert sources.water_heaters == ()
        assert "sensor.wh" in sources.entity_ids()
        assert sources.inactive_water_heaters == (("wh1", "sensor.wh"),)

    def test_ev_sensor_is_watched_when_the_feature_is_off(self):
        sources = build_slot_sources(
            base_config(
                system={"has_ev_charger": False},
                ev_chargers=[{"id": "ev1", "enabled": True, "sensor": "sensor.ev"}],
            )
        )
        assert sources.ev_chargers == ()
        assert "sensor.ev" in sources.entity_ids()

    def test_sensorless_or_absent_devices_add_nothing(self):
        sources = build_slot_sources(
            base_config(water_heaters=[{"id": "wh1", "enabled": False}], ev_chargers=[])
        )
        assert sources.inactive_water_heaters == ()
        assert sources.inactive_ev_chargers == ()

    def test_active_sensor_is_not_also_inactive(self):
        sources = build_slot_sources(
            _water_config(
                water_heaters=[
                    {"id": "a", "enabled": True, "sensor": "sensor.wh"},
                    {"id": "b", "enabled": False, "sensor": "sensor.wh"},
                ]
            )
        )
        assert sources.inactive_water_heaters == ()

    @pytest.mark.asyncio
    async def test_excluded_heater_with_live_sensor_flags_the_slot(self, caplog):
        slot_energy_module._inactive_warned.clear()
        config = base_config(
            system={"has_water_heater": False},
            water_heaters=[{"id": "wh1", "enabled": True, "sensor": "sensor.wh"}],
        )
        history = {
            "sensor.load": constant("sensor.load", 3.0),
            "sensor.wh": constant("sensor.wh", 2.0),
        }
        with caplog.at_level(logging.WARNING):
            first, history_mock = await record(config, history)
            await record(config, history)
        assert history_mock.await_count == 1
        assert first["water_kwh"] == 0.0
        assert first["quality_flags"]["base_load"] == {
            "reliable": False,
            "reasons": ["inactive_device_drawing_power"],
        }
        components = first["quality_flags"]["recording"]["components"]
        assert components["water"]["method"] == "disabled_zero"
        # Demand stays exact: load still contains the heater energy.
        assert components["load"]["method"] == "derived_history"
        warnings = [r.message for r in caplog.records if "sensor.wh" in r.message]
        assert len(warnings) == 1
        assert "system.has_water_heater" in warnings[0]

    @pytest.mark.asyncio
    async def test_excluded_heater_idle_or_unavailable_is_not_flagged(self):
        config = base_config(
            system={"has_water_heater": False},
            water_heaters=[{"id": "wh1", "enabled": True, "sensor": "sensor.wh"}],
        )
        idle = {"sensor.wh": constant("sensor.wh", 0.003)}
        for history in (idle, {}):
            record_, _ = await record(config, history | {"sensor.load": constant("sensor.load", 1)})
            assert "base_load" not in record_["quality_flags"]


class TestRecorderFlags:
    @pytest.mark.asyncio
    async def test_clamp_flags_and_makes_load_unknown(self, caplog):
        history = {
            "sensor.load": constant("sensor.load", 0.8),
            "sensor.wh": constant("sensor.wh", 3.0),
        }
        with caplog.at_level(logging.WARNING):
            record_, _ = await record(_water_config(), history)
        assert record_["load_kwh"] == 0.0
        assert record_["quality_flags"]["base_load"] == {
            "reliable": False,
            "reasons": ["negative_after_subtraction"],
        }
        assert record_["quality_flags"]["recording"]["components"]["load"]["method"] == "unknown"
        assert sum("Negative base load" in r.message for r in caplog.records) == 1

    @pytest.mark.asyncio
    async def test_exact_zero_is_not_flagged(self):
        history = {
            "sensor.load": constant("sensor.load", 3.0),
            "sensor.wh": constant("sensor.wh", 3.0),
        }
        record_, _ = await record(_water_config(), history)
        assert record_["load_kwh"] == 0.0
        assert "base_load" not in record_["quality_flags"]

    @pytest.mark.asyncio
    async def test_device_partial_coverage_keeps_value_method_and_demand(self):
        history = {
            "sensor.load": constant("sensor.load", 3.0),
            "sensor.wh": series("sensor.wh", [(300, 2.0)]),
        }
        record_, _ = await record(_water_config(), history)
        assert record_["water_kwh"] == pytest.approx(2.0 * 600 / 3600)
        flags = record_["quality_flags"]
        assert flags["base_load"]["reasons"] == ["device_partial_coverage"]
        components = flags["recording"]["components"]
        assert components["water"]["method"] == "power_history"
        assert components["load"]["method"] == "derived_history"

    @pytest.mark.asyncio
    async def test_load_partial_coverage_makes_load_unknown(self):
        history = {"sensor.load": series("sensor.load", [(300, 3.0)])}
        record_, _ = await record(base_config(), history)
        flags = record_["quality_flags"]
        assert flags["base_load"]["reasons"] == ["load_partial_coverage"]
        assert flags["recording"]["components"]["load"]["method"] == "unknown"

    @pytest.mark.asyncio
    async def test_unavailable_device_sensor_gets_no_second_flag(self):
        history = {"sensor.load": constant("sensor.load", 3.0)}
        record_, _ = await record(_water_config(), history, snapshots={})
        flags = record_["quality_flags"]
        assert "base_load" not in flags

    @pytest.mark.asyncio
    async def test_reliable_slot_has_no_flag(self):
        record_, _ = await record(base_config(), {"sensor.load": constant("sensor.load", 1.0)})
        assert "base_load" not in record_["quality_flags"]


class TestBackfillMatchesLive:
    def _flags(self, history):
        engine = _backfill_engine()
        records = engine.integrate_slots(SOURCES, None, history, [BASE])
        return records[0]["quality_flags"], records[0]

    def test_clamp(self):
        flags, record_ = self._flags(
            {"sensor.load": _states([(0, "0.8")]), "sensor.wh": _states([(0, "3.0")])}
        )
        assert flags["base_load"] == {"reliable": False, "reasons": ["negative_after_subtraction"]}
        assert flags["recording"]["components"]["load"]["method"] == "unknown"
        assert record_["load_kwh"] == 0.0

    def test_device_partial_coverage(self):
        flags, _ = self._flags(
            {"sensor.load": _states([(0, "3.0")]), "sensor.wh": _states([(300, "2.0")])}
        )
        assert flags["base_load"]["reasons"] == ["device_partial_coverage"]
        assert flags["recording"]["components"]["load"]["method"] == "derived_history"

    def test_load_partial_coverage(self):
        flags, _ = self._flags(
            {"sensor.load": _states([(300, "3.0")]), "sensor.wh": _states([(0, "0.0")])}
        )
        assert flags["base_load"]["reasons"] == ["load_partial_coverage"]
        assert flags["recording"]["components"]["load"]["method"] == "unknown"

    def test_inactive_device(self):
        engine = _backfill_engine()
        engine.config["system"]["has_water_heater"] = False
        sources = build_slot_sources(engine.config)
        history = {"sensor.load": _states([(0, "3.0")]), "sensor.wh": _states([(0, "2.0")])}
        records = engine.integrate_slots(sources, None, history, [BASE])
        assert records[0]["quality_flags"]["base_load"]["reasons"] == [
            "inactive_device_drawing_power"
        ]

    def test_reliable(self):
        flags, _ = self._flags(
            {"sensor.load": _states([(0, "3.0")]), "sensor.wh": _states([(0, "1.0")])}
        )
        assert "base_load" not in flags

    @pytest.mark.asyncio
    async def test_live_and_backfill_agree_on_the_flag(self):
        history = {
            "sensor.load": constant("sensor.load", 0.8),
            "sensor.wh": constant("sensor.wh", 3.0),
        }
        live, _ = await record(_water_config(), history)
        flags, _ = self._flags(
            {"sensor.load": _states([(0, "0.8")]), "sensor.wh": _states([(0, "3.0")])}
        )
        assert live["quality_flags"]["base_load"] == flags["base_load"]


def test_load_is_only_integrated_from_power_history():
    """No cumulative energy counter feeds total load: sources hold power sensors only."""
    sources = build_slot_sources(base_config())
    assert sources.load == "sensor.load"
    assert all("energy" not in entity for entity in sources.entity_ids())
    tree = ast.parse(inspect.getsource(slot_energy_module))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert not {"cumulative", "total_load_consumption"} & names
    assert "total_load_consumption" not in inspect.getsource(slot_energy_module)


# --- store merge -------------------------------------------------------------


def _row(slot_start, load_kwh, *, flag, owner="recorder", source="recorder"):
    flags = {
        "source": source,
        "recording": {
            "schema_version": 1,
            "semantics": "slot-energy-v1",
            "boundary_fingerprint": "a" * 64,
            "algorithm": "power-history-step-zoh-v1",
            "components": {"load": {"method": "derived_history", "owner": owner}},
            "soc": {"source": "live", "owner": owner},
        },
    }
    if flag is not None:
        flags["base_load"] = flag
    return {
        "slot_start": slot_start,
        "slot_end": slot_start + timedelta(minutes=15),
        "pv_kwh": 0.0,
        "load_kwh": load_kwh,
        "import_kwh": 0.0,
        "export_kwh": 0.0,
        "water_kwh": 0.0,
        "ev_charging_kwh": 0.0,
        "quality_flags": flags,
    }


def _stored_flags(db_path, slot_start):
    import json

    with sqlite3.connect(db_path) as conn:
        raw = conn.execute(
            "SELECT quality_flags FROM slot_observations WHERE slot_start = ?",
            (slot_start.astimezone(pytz.UTC).isoformat(),),
        ).fetchone()
    return json.loads(raw[0])


FLAG = {"reliable": False, "reasons": ["negative_after_subtraction"]}


def test_store_keeps_replaces_and_never_lets_backfill_clear_the_flag(tmp_path):
    asyncio.run(_store_scenario(tmp_path))


async def _store_scenario(tmp_path):
    db = str(tmp_path / "learning.db")
    store = LearningStore(db, pytz.UTC)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    slot = BASE.astimezone(pytz.UTC)

    # new row: the flag is stored
    await store.store_slot_observations(pd.DataFrame([_row(slot, 0.0, flag=FLAG)]))
    assert _stored_flags(db, slot)["base_load"] == FLAG

    # a backfill that cannot replace the recorder's load keeps the recorder's flag
    await store.store_slot_observations(
        pd.DataFrame([_row(slot, 0.4, flag=None, owner="backfill", source="backfill")]),
        authoritative=False,
    )
    assert _stored_flags(db, slot)["base_load"] == FLAG

    # a reliable recorder rewrite clears it
    await store.store_slot_observations(pd.DataFrame([_row(slot, 0.4, flag=None)]))
    assert "base_load" not in _stored_flags(db, slot)

    # and a later flagged rewrite sets it again
    await store.store_slot_observations(pd.DataFrame([_row(slot, 0.0, flag=FLAG)]))
    assert _stored_flags(db, slot)["base_load"] == FLAG
    await store.close()
