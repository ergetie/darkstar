"""load-balancer-coordinated-ramping: engine wiring of the phase sign
convention, measured voltage, shed-load restore power, water heater minimum
on/off times and the diagnostics trace accessor."""

from datetime import datetime, timedelta

import pytest
import pytz

from executor.config import (
    BalancedLoadConfig,
    BalancedLoadType,
    EVChargerDeviceConfig,
    WaterHeaterDeviceConfig,
)
from executor.override import SystemState
from tests.executor.test_load_balancer_wiring import (  # noqa: F401 (fixtures)
    make_engine,
    temp_db,
    temp_schedule,
)

NOW = pytz.UTC.localize(datetime(2026, 10, 21, 12, 0, 0))


def _iso_ago(seconds: float) -> str:
    return (datetime.now(pytz.UTC) - timedelta(seconds=seconds)).isoformat()


def _phase(value: float, unit: str = "A", ago: float = 1.0) -> dict:
    return {
        "state": str(value),
        "attributes": {"unit_of_measurement": unit},
        "last_updated": _iso_ago(ago),
        "last_reported": _iso_ago(ago),
    }


class TestPhaseSignConvention:
    @pytest.mark.asyncio
    async def test_export_phase_counts_as_zero_amps(self, temp_schedule, temp_db):
        engine = make_engine(
            temp_schedule,
            temp_db,
            load_balancing_enabled=True,
            grid_currents={},
            state_overrides={
                "sensor.grid_l1": _phase(12.0),
                "sensor.grid_l2": _phase(-5.0),
                "sensor.grid_l3": _phase(7.0),
            },
        )
        state = await engine._gather_system_state()
        assert state.grid_current_a == {1: 12.0, 2: 0.0, 3: 7.0}
        assert state.grid_export_phases == [2]

    @pytest.mark.asyncio
    async def test_inverted_sensor_import_negative(self, temp_schedule, temp_db):
        engine = make_engine(
            temp_schedule,
            temp_db,
            load_balancing_enabled=True,
            grid_currents={},
            state_overrides={
                "sensor.grid_l1": _phase(-12.0),
                "sensor.grid_l2": _phase(3.0),
                "sensor.grid_l3": _phase(-7.0),
            },
        )
        engine.config.load_balancing.phase_sign = "import_negative"
        state = await engine._gather_system_state()
        assert state.grid_current_a == {1: 12.0, 2: 0.0, 3: 7.0}
        assert state.grid_export_phases == [2]

    @pytest.mark.asyncio
    async def test_negative_power_reading_counts_as_zero(self, temp_schedule, temp_db):
        engine = make_engine(
            temp_schedule,
            temp_db,
            load_balancing_enabled=True,
            grid_currents={},
            state_overrides={
                "sensor.grid_l1": _phase(-2300.0, "W"),
                "sensor.grid_l2": _phase(2300.0, "W"),
                "sensor.grid_l3": _phase(0.0, "W"),
            },
        )
        state = await engine._gather_system_state()
        assert state.grid_current_a[1] == 0.0
        assert state.grid_current_a[2] == pytest.approx(10.0)

    def test_persistent_export_while_charging_warns_once(self, temp_schedule, temp_db, caplog):
        engine = make_engine(temp_schedule, temp_db, load_balancing_enabled=True)
        state = SystemState(grid_export_phases=[2])
        with caplog.at_level("WARNING", logger="executor.engine"):
            engine._warn_persistent_export_phase(state, NOW, charging=True)
            assert "phase_sign" not in caplog.text
            later = NOW + timedelta(seconds=engine._PHASE_EXPORT_WARN_S)
            engine._warn_persistent_export_phase(state, later, charging=True)
            engine._warn_persistent_export_phase(state, later + timedelta(seconds=5), charging=True)
        assert caplog.text.count("phase_sign") == 1

    def test_export_while_idle_does_not_warn(self, temp_schedule, temp_db, caplog):
        engine = make_engine(temp_schedule, temp_db, load_balancing_enabled=True)
        state = SystemState(grid_export_phases=[2])
        with caplog.at_level("WARNING", logger="executor.engine"):
            engine._warn_persistent_export_phase(state, NOW, charging=False)
            engine._warn_persistent_export_phase(
                state, NOW + timedelta(seconds=600), charging=False
            )
        assert "phase_sign" not in caplog.text


class TestMeasuredVoltage:
    @pytest.mark.asyncio
    async def test_fresh_voltage_is_exposed_stale_one_is_not(self, temp_schedule, temp_db):
        engine = make_engine(
            temp_schedule,
            temp_db,
            load_balancing_enabled=True,
            grid_currents={},
            extra_input_sensors={
                "grid_voltage_l1": "sensor.v1",
                "grid_voltage_l2": "sensor.v2",
            },
            state_overrides={
                "sensor.v1": {
                    "state": "236",
                    "attributes": {"unit_of_measurement": "V"},
                    "last_reported": _iso_ago(2),
                },
                "sensor.v2": {
                    "state": "238",
                    "attributes": {"unit_of_measurement": "V"},
                    "last_reported": _iso_ago(120),
                },
            },
        )
        state = await engine._gather_system_state()
        assert state.grid_voltage_v == {1: 236.0}


class TestShedLoadPower:
    def _engine(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, load_balancing_enabled=True)
        engine.config.water_heater_devices = [
            WaterHeaterDeviceConfig(id="tank", power_kw=3.1, target_entity="switch.tank")
        ]
        engine.config.ev_chargers.append(
            EVChargerDeviceConfig(id="wallbox", type="binary", rated_power_kw=7.4)
        )
        return engine

    def test_custom_live_sensor_wins(self, temp_schedule, temp_db):
        engine = self._engine(temp_schedule, temp_db)
        load = BalancedLoadConfig(
            device_type=BalancedLoadType.CUSTOM_ENTITY,
            device_id="pump",
            phases=[1],
            power_kw=1.0,
            power_sensor="sensor.pump_w",
        )
        state = SystemState(shed_load_power_w={"pump": 1800.0})
        assert engine._resolve_shed_load_power(load, state) == (1800.0, "sensor")

    def test_idle_sensor_falls_back_to_configured(self, temp_schedule, temp_db):
        engine = self._engine(temp_schedule, temp_db)
        load = BalancedLoadConfig(
            device_type=BalancedLoadType.CUSTOM_ENTITY,
            device_id="pump",
            phases=[1],
            power_kw=1.0,
            power_sensor="sensor.pump_w",
        )
        state = SystemState(shed_load_power_w={"pump": 3.0})  # off: reads ~0 W
        assert engine._resolve_shed_load_power(load, state) == (1000.0, "configured")

    def test_custom_without_any_power_is_worst_case(self, temp_schedule, temp_db):
        engine = self._engine(temp_schedule, temp_db)
        load = BalancedLoadConfig(
            device_type=BalancedLoadType.CUSTOM_ENTITY, device_id="pump", phases=[1]
        )
        assert engine._resolve_shed_load_power(load, SystemState()) == (None, "worst_case")

    def test_water_heater_uses_its_configured_power(self, temp_schedule, temp_db):
        engine = self._engine(temp_schedule, temp_db)
        load = BalancedLoadConfig(
            device_type=BalancedLoadType.WATER_HEATER, device_id="tank", phases=[1]
        )
        assert engine._resolve_shed_load_power(load, SystemState()) == (3100.0, "configured")

    def test_binary_charger_uses_rated_power(self, temp_schedule, temp_db):
        engine = self._engine(temp_schedule, temp_db)
        load = BalancedLoadConfig(
            device_type=BalancedLoadType.EV_CHARGER, device_id="wallbox", phases=[1, 2, 3]
        )
        assert engine._resolve_shed_load_power(load, SystemState()) == (7400.0, "configured")

    def test_binary_charger_without_rated_power_is_worst_case(self, temp_schedule, temp_db):
        engine = self._engine(temp_schedule, temp_db)
        load = BalancedLoadConfig(
            device_type=BalancedLoadType.EV_CHARGER, device_id="unknown", phases=[1]
        )
        assert engine._resolve_shed_load_power(load, SystemState()) == (None, "worst_case")


class TestWaterHeaterMinTimes:
    def _engine(self, temp_schedule, temp_db, min_on=300, min_off=300):
        engine = make_engine(temp_schedule, temp_db, load_balancing_enabled=True)
        engine.config.load_balancing.loads = [
            BalancedLoadConfig(
                device_type=BalancedLoadType.WATER_HEATER,
                device_id="tank",
                phases=[1],
                min_on_s=min_on,
                min_off_s=min_off,
            )
        ]
        return engine

    def test_plan_switch_off_waits_for_min_on_time(self, temp_schedule, temp_db):
        engine = self._engine(temp_schedule, temp_db)
        off = engine.config.water_heater.temp_off
        assert engine._apply_water_heater_min_times("tank", 60, NOW) == 60
        # Plan wants off 100 s after switching on: held at the on temperature.
        held = engine._apply_water_heater_min_times("tank", off, NOW + timedelta(seconds=100))
        assert held == 60
        released = engine._apply_water_heater_min_times("tank", off, NOW + timedelta(seconds=301))
        assert released == off

    def test_plan_switch_on_waits_for_min_off_time(self, temp_schedule, temp_db):
        engine = self._engine(temp_schedule, temp_db)
        off = engine.config.water_heater.temp_off
        engine._apply_water_heater_min_times("tank", off, NOW)
        held = engine._apply_water_heater_min_times("tank", 60, NOW + timedelta(seconds=100))
        assert held == off
        assert engine._apply_water_heater_min_times("tank", 60, NOW + timedelta(seconds=301)) == 60

    def test_overload_shed_is_never_delayed(self, temp_schedule, temp_db):
        engine = self._engine(temp_schedule, temp_db)
        engine._apply_water_heater_min_times("tank", 60, NOW)
        # The shed path records the off state without consulting min_on_s...
        engine._note_water_heater_switch("tank", False, NOW + timedelta(seconds=5))
        off = engine.config.water_heater.temp_off
        # ...and the min_off clock of the restore starts from the shed.
        held = engine._apply_water_heater_min_times("tank", 60, NOW + timedelta(seconds=60))
        assert held == off

    def test_heater_outside_the_balancer_is_untouched(self, temp_schedule, temp_db):
        engine = self._engine(temp_schedule, temp_db)
        engine.config.load_balancing.loads = []
        off = engine.config.water_heater.temp_off
        engine._apply_water_heater_min_times("tank", 60, NOW)
        assert engine._apply_water_heater_min_times("tank", off, NOW + timedelta(seconds=1)) == off


class TestTraceAccessor:
    def test_trace_snapshot_is_exposed_for_diagnostics(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, load_balancing_enabled=True)
        assert engine.get_balancer_trace() == []
        engine._load_balancer.tick(
            NOW,
            {1: 5.0, 2: 5.0, 3: 5.0},
            {1: NOW, 2: NOW, 3: NOW},
            [],
        )
        assert len(engine.get_balancer_trace()) == 1


@pytest.mark.asyncio
async def test_sustained_balancer_constraint_never_requests_replan(temp_schedule, temp_db):
    import json
    from pathlib import Path
    from unittest.mock import AsyncMock, MagicMock, patch
    from executor.engine import EVChargerState
    from tests.executor.test_load_balancer_e2e_dry_run import _FakeDateTime
    from tests.executor.test_load_balancer_wiring import make_ev_slot, make_schedule

    engine = make_engine(
        temp_schedule, temp_db, load_balancing_enabled=True, grid_currents={1: 24, 2: 5, 3: 5}
    )
    engine._request_balancer_replan = MagicMock()
    engine._track_soc_deviation = MagicMock()
    for seconds in (0, 600, 1800, 3605):
        now = NOW + timedelta(seconds=seconds)
        _FakeDateTime._current = now
        Path(temp_schedule).write_text(json.dumps(make_schedule([make_ev_slot(now, "goe", 11.0)])))
        engine._gather_system_state = AsyncMock(
            return_value=SystemState(
                soc_available=True,
                current_soc_percent=50,
                grid_current_a={1: 24, 2: 5, 3: 5},
                grid_current_updated_at={1: now, 2: now, 3: now},
            )
        )
        engine._ev_charger_states["goe"] = EVChargerState(
            charging_active=True, current_setpoint_a=6
        )
        with patch("executor.engine.datetime", _FakeDateTime):
            await engine.run_once()
        assert engine._last_balancer_status.ev_outputs[0].target_a is None
    engine._request_balancer_replan.assert_not_called()


def test_unplanned_custom_start_still_uses_shared_room(temp_schedule, temp_db):
    engine = make_engine(temp_schedule, temp_db, load_balancing_enabled=True)
    engine.config.load_balancing.resume_delay_s = 0
    engine.config.load_balancing.loads = [
        BalancedLoadConfig(
            device_type=BalancedLoadType.CUSTOM_ENTITY,
            device_id="pump",
            entity="switch.pump",
            phases=[1],
            power_kw=2.3,
            min_off_s=0,
        )
    ]
    state = SystemState(
        grid_current_a={1: 15, 2: 5, 3: 5},
        grid_current_updated_at={p: NOW for p in (1, 2, 3)},
        shed_load_on={"pump": False},
    )
    first = engine._run_load_balancer(state, None, NOW)
    assert first.shed_outputs[0].shed
    state.grid_current_a[1] = 5
    later = NOW + timedelta(seconds=5)
    state.grid_current_updated_at = {p: later for p in (1, 2, 3)}
    restored = engine._run_load_balancer(state, None, later)
    assert not restored.shed_outputs[0].shed
    assert engine._load_balancer._ledger.pending_a(1) == pytest.approx(10)


@pytest.mark.asyncio
@pytest.mark.parametrize("age,expected", [(2, (2300.0, "sensor")), (120, (1000.0, "configured"))])
async def test_custom_restore_ignores_stale_power_sensor(temp_schedule, temp_db, age, expected):
    engine = make_engine(
        temp_schedule,
        temp_db,
        load_balancing_enabled=True,
        state_overrides={"sensor.pump": _phase(2300, "W", ago=age)},
    )
    load = BalancedLoadConfig(
        device_type=BalancedLoadType.CUSTOM_ENTITY,
        device_id="pump",
        entity="switch.pump",
        phases=[1],
        power_sensor="sensor.pump",
        power_kw=1.0,
    )
    engine.config.load_balancing.loads = [load]
    state = await engine._gather_system_state()
    assert engine._resolve_shed_load_power(load, state) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "first_value,expected", [("off", False), ("on", True), ("unavailable", None)]
)
async def test_balanced_heater_states_are_per_device(temp_schedule, temp_db, first_value, expected):
    engine = make_engine(
        temp_schedule,
        temp_db,
        load_balancing_enabled=True,
        state_overrides={"switch.tank": first_value, "number.second": "20"},
    )
    engine.config.water_heater_devices = [
        WaterHeaterDeviceConfig(id="tank", target_entity="switch.tank", control_type="switch"),
        WaterHeaterDeviceConfig(id="second", target_entity="number.second"),
    ]
    engine.config.load_balancing.loads = [
        BalancedLoadConfig(device_type=BalancedLoadType.WATER_HEATER, device_id=key, phases=[1])
        for key in ("tank", "second")
    ]
    original_read = engine.ha_client.get_state_value.side_effect

    async def read(entity):
        if entity == "switch.tank":
            return first_value
        if entity == "number.second":
            return "20"
        return await original_read(entity)

    engine.ha_client.get_state_value.side_effect = read
    state = await engine._gather_system_state()
    assert (state.shed_load_on or {}).get("tank") is expected
    assert (state.shed_load_on or {}).get("second") is False


@pytest.mark.parametrize("on", [False, None])
def test_heater_initial_start_requires_shared_room(temp_schedule, temp_db, on):
    from executor.controller import ControllerDecision

    engine = make_engine(temp_schedule, temp_db, load_balancing_enabled=True)
    engine.config.load_balancing.resume_delay_s = 0
    engine.config.water_heater_devices = [
        WaterHeaterDeviceConfig(
            id="tank", target_entity="switch.tank", control_type="switch", power_kw=3.1
        )
    ]
    engine.config.load_balancing.loads = [
        BalancedLoadConfig(
            device_type=BalancedLoadType.WATER_HEATER, device_id="tank", phases=[1], min_off_s=0
        )
    ]
    state = SystemState(
        grid_current_a={1: 10, 2: 5, 3: 5},
        grid_current_updated_at={p: NOW for p in (1, 2, 3)},
        shed_load_on={"tank": on} if on is not None else None,
    )
    decision = ControllerDecision(mode_intent="idle", water_temps={"tank": 60})
    first = engine._run_load_balancer(state, None, NOW, decision)
    assert first.shed_outputs[0].shed
    later = NOW + timedelta(seconds=5)
    state.grid_current_a[1] = 0
    state.grid_current_updated_at = {p: later for p in (1, 2, 3)}
    restored = engine._run_load_balancer(state, None, later, decision)
    assert not restored.shed_outputs[0].shed
    assert engine._load_balancer._ledger.pending_a(1) > 13


@pytest.mark.asyncio
async def test_binary_charger_start_uses_shared_room(temp_schedule, temp_db):
    from executor.override import SlotPlan

    engine = make_engine(
        temp_schedule,
        temp_db,
        load_balancing_enabled=True,
        state_overrides={"switch.wallbox": "off"},
    )
    engine.config.ev_chargers = [
        EVChargerDeviceConfig(
            id="wallbox", type="binary", switch_entity="switch.wallbox", rated_power_kw=3.1
        )
    ]
    engine.config.load_balancing.resume_delay_s = 0
    engine.config.load_balancing.loads = [
        BalancedLoadConfig(
            device_type=BalancedLoadType.EV_CHARGER, device_id="wallbox", phases=[1], min_off_s=0
        )
    ]
    original_read = engine.ha_client.get_state_value.side_effect

    async def read(entity):
        return "off" if entity == "switch.wallbox" else await original_read(entity)

    engine.ha_client.get_state_value.side_effect = read
    state = await engine._gather_system_state()
    assert state.shed_load_on["wallbox"] is False
    state.grid_current_a = {1: 10, 2: 5, 3: 5}
    state.grid_current_updated_at = {p: NOW for p in (1, 2, 3)}
    slot = SlotPlan(ev_charger_plans={"wallbox": 3.1})
    assert engine._run_load_balancer(state, slot, NOW).shed_outputs[0].shed
    later = NOW + timedelta(seconds=5)
    state.grid_current_a[1] = 0
    state.grid_current_updated_at = {p: later for p in (1, 2, 3)}
    assert not engine._run_load_balancer(state, slot, later).shed_outputs[0].shed
