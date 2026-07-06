"""universal-load-balancing 4.7: full-tick wiring of the load balancer.

Verifies the balancer is a true no-op when disabled (regression gate) and
that it actually changes the commanded EV setpoint when enabled.
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
    ExecutorConfig,
    InverterConfig,
    LoadBalancingConfig,
    NotificationConfig,
    WaterHeaterConfig,
)
from executor.engine import ExecutorEngine


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


def make_ev_slot(start: datetime, charger_id: str, ev_kw: float) -> dict:
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
        "ev_chargers": {charger_id: ev_kw},
    }


def make_engine(temp_schedule, temp_db, *, load_balancing_enabled: bool, grid_currents=None):
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
    )

    from unittest.mock import patch

    with patch("executor.engine.load_executor_config", return_value=config):
        input_sensors = {}
        if grid_currents is not None:
            input_sensors = {
                "grid_current_l1": "sensor.grid_l1",
                "grid_current_l2": "sensor.grid_l2",
                "grid_current_l3": "sensor.grid_l3",
            }
        with patch("executor.engine.load_yaml", return_value={"input_sensors": input_sensors}):
            with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                engine = ExecutorEngine("config.yaml")

    engine._has_ev_charger = True

    mock_ha = MagicMock(spec=HAClient)

    grid_currents = grid_currents or {}

    async def fake_get_state_value(entity_id):
        if "soc" in entity_id:
            return "50"
        if entity_id == "number.goe_current":
            return "0"
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
async def test_disabled_balancer_matches_unbalanced_target(temp_schedule, temp_db):
    """4.7 regression gate: disabled balancer produces the same EV setpoint as
    computing planned_kw_to_amps directly (byte-identical decision)."""
    engine = make_engine(temp_schedule, temp_db, load_balancing_enabled=False)

    tz = pytz.timezone("Europe/Stockholm")
    now = datetime.now(tz)
    slot_start = now - timedelta(minutes=5)
    schedule = make_schedule([make_ev_slot(slot_start, "goe", 11.0)])
    with Path(temp_schedule).open("w", encoding="utf-8") as f:
        json.dump(schedule, f)

    await engine.run_once()

    # 11kW / 3-phase -> 15A, exactly as planned_kw_to_amps computes with no cap
    engine.ha_client.set_number.assert_any_call("number.goe_current", 15.0)
    assert engine._last_balancer_status.state == "disabled"


@pytest.mark.asyncio
async def test_enabled_balancer_caps_setpoint_below_planned(temp_schedule, temp_db):
    """With load balancing enabled and L1 already near the fuse, an in-progress
    charging session must be reduced below the naive 15A planner target."""
    from executor.engine import EVChargerState

    engine = make_engine(
        temp_schedule,
        temp_db,
        load_balancing_enabled=True,
        grid_currents={1: 26.0, 2: 5.0, 3: 5.0},  # L1 headroom = 20-26 = -6
    )

    tz = pytz.timezone("Europe/Stockholm")
    now = datetime.now(tz)
    slot_start = now - timedelta(minutes=5)
    schedule = make_schedule([make_ev_slot(slot_start, "goe", 11.0)])
    with Path(temp_schedule).open("w", encoding="utf-8") as f:
        json.dump(schedule, f)

    # Charger already mid-session at 16A when the stove spike hits
    engine._ev_charger_states["goe"] = EVChargerState(
        charging_active=True, current_setpoint_a=16, charging_started_at=now
    )

    await engine.run_once()

    assert engine._last_balancer_status.state != "disabled"
    calls = [c.args for c in engine.ha_client.set_number.call_args_list if c.args[0] == "number.goe_current"]
    assert calls, "expected a write to number.goe_current"
    commanded = calls[-1][1]
    assert commanded <= 10.0  # 16A + (-6A headroom) = 10A per the decrease-side formula


@pytest.mark.asyncio
async def test_balancer_intervention_is_logged_with_reason_and_phase_currents(
    temp_schedule, temp_db
):
    """Spec scenario: 'Balancer intervention is always auditable' — a throttle
    transition is logged with the reason and per-phase currents, even though
    execution logging is otherwise throttled (5.2)."""
    from executor.engine import EVChargerState

    engine = make_engine(
        temp_schedule,
        temp_db,
        load_balancing_enabled=True,
        grid_currents={1: 26.0, 2: 5.0, 3: 5.0},
    )
    tz = pytz.timezone("Europe/Stockholm")
    now = datetime.now(tz)
    slot_start = now - timedelta(minutes=5)
    schedule = make_schedule([make_ev_slot(slot_start, "goe", 11.0)])
    with Path(temp_schedule).open("w", encoding="utf-8") as f:
        json.dump(schedule, f)

    engine._ev_charger_states["goe"] = EVChargerState(
        charging_active=True, current_setpoint_a=16, charging_started_at=now
    )

    await engine.run_once()

    history = engine.history.get_history()
    assert history, "expected an execution record to be logged"
    record = history[0]
    lb_actions = [a for a in record["action_results"] if a["type"] == "load_balancer"]
    assert lb_actions, "expected a load_balancer action_results entry"
    lb_action = lb_actions[0]
    assert lb_action["state"] == "throttling"
    assert lb_action["message"]
    assert lb_action["phase_current_a"] == {"1": 26.0, "2": 5.0, "3": 5.0}
