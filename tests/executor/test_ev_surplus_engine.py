"""excess-pv-priority-dispatch 3.9: engine-level EV surplus / custom-entity /
phase-mode / source-isolation integration tests, mirroring the full-tick
pattern established by test_load_balancer_wiring.py.
"""

import contextlib
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytz
from sqlalchemy import create_engine

from backend.learning.models import Base
from executor.actions import ActionDispatcher, HAClient
from executor.config import (
    ControllerConfig,
    EVChargerDeviceConfig,
    ExcessPVConfig,
    ExcessPVSinkEntry,
    ExecutorConfig,
    InverterConfig,
    LoadBalancingConfig,
    NotificationConfig,
    WaterHeaterConfig,
)
from executor.engine import ExecutorEngine
from executor.ev_surplus import PhaseModeController


@pytest.fixture
def temp_schedule():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        schedule_path = f.name
    yield schedule_path
    with contextlib.suppress(OSError):
        Path(schedule_path).unlink()


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(db_engine)
    yield db_path
    with contextlib.suppress(OSError):
        Path(db_path).unlink()


def make_schedule(slots: list, timezone: str = "Europe/Stockholm") -> dict:
    return {
        "schedule": slots,
        "meta": {"generated_at": datetime.now(pytz.timezone(timezone)).isoformat()},
    }


def make_surplus_slot(
    start: datetime,
    charger_id: str,
    surplus_kw: float,
    custom_entity_active: dict | None = None,
) -> dict:
    end = start + timedelta(minutes=15)
    return {
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "end_time_kepler": end.isoformat(),
        "battery_charge_kw": 0,
        "battery_discharge_kw": 0,
        "export_kwh": 0,
        "water_heating_kw": 0,
        "soc_target_percent": 50,
        "projected_soc_percent": 50,
        "ev_charging_kw": 0,
        "ev_chargers": {},
        "ev_surplus_kw": {charger_id: surplus_kw},
        "custom_entity_active": custom_entity_active or {},
    }


def make_engine(
    temp_schedule,
    temp_db,
    *,
    excess_pv_priority: list,
    load_balancing_enabled: bool = False,
    grid_currents=None,
    export_kw: float = 0.0,
    import_kw: float = 0.0,
    charger_current_setpoint: int | None = 0,
):
    charger = EVChargerDeviceConfig(
        id="goe",
        type="current",
        current_entity="number.goe_current",
        min_current_a=6,
        max_current_a=16,
        phases=[1, 2, 3],
    )
    load_balancing = LoadBalancingConfig(
        enabled=load_balancing_enabled,
        main_fuse_a=20,
        resume_delay_s=120,
        resume_margin_percent=90,
        increase_step_a=1,
        sensor_stale_after_s=30,
        loads=[],
    )
    config = ExecutorConfig(
        enabled=True,
        schedule_path=temp_schedule,
        timezone="Europe/Stockholm",
        inverter=InverterConfig(),
        water_heater=WaterHeaterConfig(),
        notifications=NotificationConfig(),
        controller=ControllerConfig(),
        ev_chargers=[charger],
        load_balancing=load_balancing,
        excess_pv=ExcessPVConfig(priority=excess_pv_priority),
    )

    from unittest.mock import patch

    with patch("executor.engine.load_executor_config", return_value=config):
        input_sensors = {
            "grid_import_power": "sensor.grid_import",
            "grid_export_power": "sensor.grid_export",
        }
        if grid_currents is not None:
            input_sensors.update(
                {
                    "grid_current_l1": "sensor.grid_l1",
                    "grid_current_l2": "sensor.grid_l2",
                    "grid_current_l3": "sensor.grid_l3",
                }
            )
        full_config = {
            "system": {"grid_meter_type": "dual"},
            "input_sensors": input_sensors,
        }
        with patch("executor.engine.load_yaml", return_value=full_config):
            with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                engine = ExecutorEngine("config.yaml")

    engine._has_ev_charger = True

    mock_ha = MagicMock(spec=HAClient)

    grid_currents = grid_currents or {}

    async def fake_get_state_value(entity_id):
        if entity_id == "sensor.grid_import":
            return str(import_kw * 1000)
        if entity_id == "sensor.grid_export":
            return str(export_kw * 1000)
        if "soc" in entity_id:
            return "50"
        if entity_id == "number.goe_current":
            return str(charger_current_setpoint if charger_current_setpoint is not None else 0)
        if entity_id == "select.goe_phase_mode":
            return "3"
        if entity_id.startswith("switch."):
            return "unavailable"  # force writes; avoid accidental "0.0" == "0" skip-match
        return "0.0"

    def _phase_state(value: float) -> dict:
        return {
            "state": str(value),
            "attributes": {"unit_of_measurement": "A"},
            "last_updated": datetime.now(pytz.UTC).isoformat(),
        }

    async def fake_get_state(entity_id):
        if entity_id == "sensor.grid_l1":
            return _phase_state(grid_currents.get(1, 5.0))
        if entity_id == "sensor.grid_l2":
            return _phase_state(grid_currents.get(2, 5.0))
        if entity_id == "sensor.grid_l3":
            return _phase_state(grid_currents.get(3, 5.0))
        return None

    mock_ha.get_state_value = AsyncMock(side_effect=fake_get_state_value)
    mock_ha.get_state = AsyncMock(side_effect=fake_get_state)
    mock_ha.set_number = AsyncMock(return_value=True)
    mock_ha.set_switch = AsyncMock(return_value=True)
    mock_ha.set_select_option = AsyncMock(return_value=True)
    mock_ha.set_input_number = AsyncMock(return_value=True)
    engine.ha_client = mock_ha
    engine.dispatcher = ActionDispatcher(mock_ha, config, shadow_mode=False)

    return engine


@pytest.mark.asyncio
async def test_surplus_charging_dispatches_amps_without_balancer(temp_schedule, temp_db):
    """Surplus-eligible slot with the fuse balancer disabled still dispatches
    a feedback-computed amp target (task 3.3's fallback path)."""
    engine = make_engine(
        temp_schedule,
        temp_db,
        excess_pv_priority=[ExcessPVSinkEntry(type="ev", charger_id="goe")],
        load_balancing_enabled=False,
        export_kw=6.0,  # enough to clear the 6A/3-phase floor immediately
        charger_current_setpoint=None,
    )

    tz = pytz.timezone("Europe/Stockholm")
    now = datetime.now(tz)
    slot_start = now - timedelta(minutes=5)
    schedule = make_schedule([make_surplus_slot(slot_start, "goe", 5.0)])
    with Path(temp_schedule).open("w", encoding="utf-8") as f:
        json.dump(schedule, f)

    await engine.run_once()

    # Not currently charging + surplus (floor(6000/(230*3))=8A) clears the 6A
    # floor -> starts directly at the floor (no 0 -> floor ramp), matching the
    # fuse balancer's own "resume at floor" convention.
    engine.ha_client.set_number.assert_any_call("number.goe_current", 6.0)


@pytest.mark.asyncio
async def test_balancer_cap_clamps_surplus_proposal(temp_schedule, temp_db):
    """Even when surplus alone would justify a higher amp target, the fuse
    balancer's cap is authoritative (task 3.3)."""
    from executor.engine import EVChargerState

    engine = make_engine(
        temp_schedule,
        temp_db,
        excess_pv_priority=[ExcessPVSinkEntry(type="ev", charger_id="goe")],
        load_balancing_enabled=True,
        grid_currents={1: 26.0, 2: 5.0, 3: 5.0},  # L1 headroom = 20-26 = -6A
        export_kw=10.0,  # huge surplus, would want to ramp up a lot
        charger_current_setpoint=16,
    )

    tz = pytz.timezone("Europe/Stockholm")
    now = datetime.now(tz)
    slot_start = now - timedelta(minutes=5)
    schedule = make_schedule([make_surplus_slot(slot_start, "goe", 5.0)])
    with Path(temp_schedule).open("w", encoding="utf-8") as f:
        json.dump(schedule, f)

    engine._ev_charger_states["goe"] = EVChargerState(
        charging_active=True, current_setpoint_a=16, charging_started_at=now
    )

    await engine.run_once()

    assert engine._last_balancer_status.state != "disabled"
    calls = [
        c.args
        for c in engine.ha_client.set_number.call_args_list
        if c.args[0] == "number.goe_current"
    ]
    assert calls, "expected a write to number.goe_current"
    commanded = calls[-1][1]
    assert commanded <= 10.0  # 16A + (-6A headroom) = 10A, well below the surplus's own proposal


@pytest.mark.asyncio
async def test_ev_source_isolation_active_during_surplus_charging(temp_schedule, temp_db):
    """Surplus slots have ev_charging_kw=0, but discharge must still be
    blocked while surplus-eligible (task 3.4's isolation extension)."""
    engine = make_engine(
        temp_schedule,
        temp_db,
        excess_pv_priority=[ExcessPVSinkEntry(type="ev", charger_id="goe")],
        export_kw=3.0,
        charger_current_setpoint=None,
    )
    engine._has_battery = True

    tz = pytz.timezone("Europe/Stockholm")
    now = datetime.now(tz)
    slot_start = now - timedelta(minutes=5)
    schedule = make_schedule([make_surplus_slot(slot_start, "goe", 5.0)])
    with Path(temp_schedule).open("w", encoding="utf-8") as f:
        json.dump(schedule, f)

    await engine.run_once()

    # Source isolation activated even though ev_charging_kw was 0 this slot —
    # only ev_surplus_kw made it eligible.
    assert engine._ev_detected_last_tick is True


@pytest.mark.asyncio
async def test_two_custom_entities_toggle_independently(temp_schedule, temp_db):
    engine = make_engine(
        temp_schedule,
        temp_db,
        excess_pv_priority=[
            ExcessPVSinkEntry(type="custom_entity", entity="switch.pool_pump"),
            ExcessPVSinkEntry(type="custom_entity", entity="switch.sauna"),
        ],
    )

    tz = pytz.timezone("Europe/Stockholm")
    now = datetime.now(tz)
    slot_start = now - timedelta(minutes=5)
    schedule = make_schedule(
        [make_surplus_slot(slot_start, "goe", 0.0, custom_entity_active={"0": True, "1": False})]
    )
    with Path(temp_schedule).open("w", encoding="utf-8") as f:
        json.dump(schedule, f)

    await engine.run_once()

    engine.ha_client.set_switch.assert_any_call("switch.pool_pump", True)
    engine.ha_client.set_switch.assert_any_call("switch.sauna", False)


@pytest.mark.asyncio
async def test_custom_entity_slot_failure_fallback_forces_off(temp_schedule, temp_db):
    """No valid slot -> SLOT_FAILURE_FALLBACK -> every custom_entity forced off,
    regardless of what a (nonexistent) plan would have said."""
    engine = make_engine(
        temp_schedule,
        temp_db,
        excess_pv_priority=[
            ExcessPVSinkEntry(type="custom_entity", entity="switch.pool_pump"),
            ExcessPVSinkEntry(type="custom_entity", entity="switch.sauna"),
        ],
    )

    # No schedule written at all -> no valid slot -> fallback override
    with Path(temp_schedule).open("w", encoding="utf-8") as f:
        json.dump(make_schedule([]), f)

    await engine.run_once()

    engine.ha_client.set_switch.assert_any_call("switch.pool_pump", False)
    engine.ha_client.set_switch.assert_any_call("switch.sauna", False)


@pytest.mark.asyncio
async def test_non_surplus_slot_unaffected_by_ev_surplus_feature(temp_schedule, temp_db):
    """Regression guard (task 3.9h): a charger not referenced by any `ev`
    priority entry behaves exactly as scheduled charging always has."""
    engine = make_engine(
        temp_schedule,
        temp_db,
        excess_pv_priority=[],
        charger_current_setpoint=0,
    )

    tz = pytz.timezone("Europe/Stockholm")
    now = datetime.now(tz)
    slot_start = now - timedelta(minutes=5)
    end = slot_start + timedelta(minutes=15)
    schedule = make_schedule(
        [
            {
                "start_time": slot_start.isoformat(),
                "end_time": end.isoformat(),
                "end_time_kepler": end.isoformat(),
                "battery_charge_kw": 0,
                "battery_discharge_kw": 0,
                "export_kwh": 0,
                "water_heating_kw": 0,
                "soc_target_percent": 50,
                "projected_soc_percent": 50,
                "ev_chargers": {"goe": 11.0},
            }
        ]
    )
    with Path(temp_schedule).open("w", encoding="utf-8") as f:
        json.dump(schedule, f)

    await engine.run_once()

    # 11kW / 3-phase -> 15A, exactly as planned_kw_to_amps computes, unaffected
    # by the (empty) surplus feature.
    engine.ha_client.set_number.assert_any_call("number.goe_current", 15.0)
    assert engine._ev_surplus_targets == {}


class TestActivePhaseCountResolution:
    """Task 3.6: commanded phase count, falling back to measured/configured."""

    def _engine(self):
        from executor.engine import EVChargerState, ExecutorEngine

        return ExecutorEngine.__new__(ExecutorEngine)

    def test_uses_commanded_mode_when_no_measurement(self):
        eng = self._engine()
        cfg = EVChargerDeviceConfig(id="goe", phase_switching_enabled=True, phases=[1, 2, 3])
        dev_state = __import__("executor.engine", fromlist=["EVChargerState"]).EVChargerState()
        ctrl = PhaseModeController()
        ctrl.commanded_mode = 1
        assert eng._resolve_active_phase_count(cfg, dev_state, ctrl) == 1

    def test_measured_overrides_commanded_when_fewer(self):
        eng = self._engine()
        cfg = EVChargerDeviceConfig(id="goe", phase_switching_enabled=True, phases=[1, 2, 3])
        dev_state = __import__("executor.engine", fromlist=["EVChargerState"]).EVChargerState(
            active_phases=[1]
        )
        ctrl = PhaseModeController()
        ctrl.commanded_mode = 3
        assert eng._resolve_active_phase_count(cfg, dev_state, ctrl) == 1

    def test_measured_ignored_when_not_fewer(self):
        eng = self._engine()
        cfg = EVChargerDeviceConfig(id="goe", phase_switching_enabled=True, phases=[1, 2, 3])
        dev_state = __import__("executor.engine", fromlist=["EVChargerState"]).EVChargerState(
            active_phases=[1, 2, 3]
        )
        ctrl = PhaseModeController()
        ctrl.commanded_mode = 1
        assert eng._resolve_active_phase_count(cfg, dev_state, ctrl) == 1

    def test_falls_back_to_configured_phases_when_switching_disabled(self):
        eng = self._engine()
        cfg = EVChargerDeviceConfig(id="goe", phase_switching_enabled=False, phases=[1, 2])
        dev_state = __import__("executor.engine", fromlist=["EVChargerState"]).EVChargerState()
        ctrl = PhaseModeController()
        ctrl.commanded_mode = 1  # irrelevant, switching disabled
        assert eng._resolve_active_phase_count(cfg, dev_state, ctrl) == 2


@pytest.mark.asyncio
async def test_gather_system_state_net_meter_grid_power(temp_schedule, temp_db):
    """Net-meter surplus tracking (design D3) needs current_import_kw /
    current_export_kw populated from the single bidirectional grid_power sensor."""
    from unittest.mock import patch

    charger = EVChargerDeviceConfig(id="goe", type="current")
    config = ExecutorConfig(
        enabled=True,
        schedule_path=temp_schedule,
        timezone="Europe/Stockholm",
        inverter=InverterConfig(),
        water_heater=WaterHeaterConfig(),
        notifications=NotificationConfig(),
        controller=ControllerConfig(),
        ev_chargers=[charger],
    )
    full_config = {
        "system": {"grid_meter_type": "net"},
        "input_sensors": {"grid_power": "sensor.grid_power"},
    }
    with patch("executor.engine.load_executor_config", return_value=config):
        with patch("executor.engine.load_yaml", return_value=full_config):
            with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                engine = ExecutorEngine("config.yaml")

    mock_ha = MagicMock(spec=HAClient)

    async def fake_get_state_value(entity_id):
        if entity_id == "sensor.grid_power":
            return "-2000"  # exporting 2kW (negative = export per repo convention)
        return "0"

    mock_ha.get_state_value = AsyncMock(side_effect=fake_get_state_value)
    mock_ha.get_state = AsyncMock(return_value=None)
    engine.ha_client = mock_ha

    state = await engine._gather_system_state()

    assert state.current_export_kw == pytest.approx(2.0)
    assert state.current_import_kw == 0.0
