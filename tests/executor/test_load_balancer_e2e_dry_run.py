"""universal-load-balancing 8.2: scripted end-to-end dry run through the real
ExecutorEngine (shadow-mode style, HA fully mocked).

Drives a realistic timeline — stove spike, sustained overload beyond the EV
floor (shed), recovery (restore after delay), and a stale sensor — asserting
the exact setpoints/commands the pipeline emits at each tick match the spec
scenarios. Wall-clock is faked so delay-based anti-flap logic (120s) doesn't
require the test to actually sleep.
"""

import contextlib
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz
from sqlalchemy import create_engine

from backend.learning.models import Base
from executor.actions import ActionDispatcher, HAClient
from executor.config import (
    BalancedLoadConfig,
    BalancedLoadType,
    ControllerConfig,
    EVChargerDeviceConfig,
    ExecutorConfig,
    InverterConfig,
    LoadBalancingConfig,
    NotificationConfig,
    WaterHeaterConfig,
    WaterHeaterDeviceConfig,
)
from executor.engine import EVChargerState, ExecutorEngine

TZ = pytz.timezone("Europe/Stockholm")


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


class _FakeDateTime(datetime):
    """Lets the test advance executor._tick's wall-clock deterministically."""

    _current: datetime

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return cls._current.astimezone(tz) if tz else cls._current


def make_schedule(slots: list) -> dict:
    return {"schedule": slots, "meta": {"generated_at": datetime.now(pytz.UTC).isoformat()}}


def make_slot(start: datetime, ev_kw: float) -> dict:
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
        "ev_chargers": {"goe": ev_kw},
    }


@pytest.mark.asyncio
async def test_scripted_dry_run(temp_schedule, temp_db):
    charger = EVChargerDeviceConfig(
        id="goe",
        type="current",
        current_entity="number.goe_current",
        min_current_a=6,
        max_current_a=16,
        phases=[1, 2, 3],
    )
    water_heater = WaterHeaterDeviceConfig(
        id="main_tank", name="Main Tank", target_entity="input_number.water_heater_target"
    )
    load_balancing = LoadBalancingConfig(
        enabled=True,
        main_fuse_a=20,
        resume_delay_s=120,
        resume_margin_percent=90,
        increase_step_a=1,
        sensor_stale_after_s=30,
        loads=[
            BalancedLoadConfig(
                device_type=BalancedLoadType.WATER_HEATER,
                device_id="main_tank",
                phases=[2],
                priority=1,
            )
        ],
    )
    config = ExecutorConfig(
        enabled=True,
        schedule_path=temp_schedule,
        timezone="Europe/Stockholm",
        inverter=InverterConfig(),
        water_heater=WaterHeaterConfig(),
        water_heater_devices=[water_heater],
        notifications=NotificationConfig(),
        controller=ControllerConfig(),
        ev_chargers=[charger],
        load_balancing=load_balancing,
        has_water_heater=True,
    )

    t0 = TZ.localize(datetime(2026, 6, 1, 12, 0, 0))
    _FakeDateTime._current = t0

    with patch("executor.engine.load_executor_config", return_value=config):
        with patch(
            "executor.engine.load_yaml",
            return_value={
                "input_sensors": {
                    "grid_current_l1": "sensor.grid_l1",
                    "grid_current_l2": "sensor.grid_l2",
                    "grid_current_l3": "sensor.grid_l3",
                },
                "system": {"has_water_heater": True},
            },
        ):
            with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                engine = ExecutorEngine("config.yaml")

    engine._has_ev_charger = True
    engine._has_water_heater = True

    grid = {"1": 5.0, "2": 5.0, "3": 5.0}

    def phase_state(phase: str) -> dict:
        return {
            "state": str(grid[phase]),
            "attributes": {"unit_of_measurement": "A"},
            "last_updated": _FakeDateTime._current.isoformat(),
        }

    stale_phase: str | None = None

    async def fake_get_state(entity_id):
        mapping = {"sensor.grid_l1": "1", "sensor.grid_l2": "2", "sensor.grid_l3": "3"}
        phase = mapping.get(entity_id)
        if phase is None:
            return None
        if phase == stale_phase:
            # Freeze this sensor's last_updated far in the past
            return {
                "state": str(grid[phase]),
                "attributes": {"unit_of_measurement": "A"},
                "last_updated": (t0 - timedelta(hours=1)).isoformat(),
            }
        return phase_state(phase)

    async def fake_get_state_value(entity_id):
        if "water_heater_target" in entity_id:
            return "60"
        if entity_id == "number.goe_current":
            # Never coincidentally match a commanded target, so idempotent-skip
            # logic never masks a real write in this test.
            return "99"
        return "0"

    mock_ha = MagicMock(spec=HAClient)
    mock_ha.get_state = AsyncMock(side_effect=fake_get_state)
    mock_ha.get_state_value = AsyncMock(side_effect=fake_get_state_value)
    mock_ha.set_number = AsyncMock(return_value=True)
    mock_ha.set_input_number = AsyncMock(return_value=True)
    mock_ha.set_switch = AsyncMock(return_value=True)
    mock_ha.set_select_option = AsyncMock(return_value=True)
    engine.ha_client = mock_ha
    engine.dispatcher = ActionDispatcher(mock_ha, config, shadow_mode=False)

    slot_start = t0 - timedelta(minutes=5)
    with Path(temp_schedule).open("w", encoding="utf-8") as f:
        json.dump(make_schedule([make_slot(slot_start, 11.0)]), f)

    def goe_calls() -> list[float]:
        return [
            c.args[1]
            for c in mock_ha.set_number.call_args_list
            if c.args[0] == "number.goe_current"
        ]

    def water_heater_writes() -> list[float]:
        return [
            c.args[1]
            for c in mock_ha.set_input_number.call_args_list
            if c.args[0] == "input_number.water_heater_target"
        ]

    with patch("executor.engine.datetime", _FakeDateTime):
        # --- Stage 1: mid-session at 16A, stove spike hits (headroom -6) ---
        engine._ev_charger_states["goe"] = EVChargerState(
            charging_active=True, current_setpoint_a=16, charging_started_at=t0
        )
        grid["1"] = 26.0
        await engine.run_once()

        assert goe_calls(), "expected an EV setpoint write on the spike tick"
        assert goe_calls()[-1] <= 10.0
        assert engine._last_balancer_status.state == "throttling"

        # --- Stage 2: sustained overload beyond the EV floor -> pause + shed ---
        _FakeDateTime._current = t0 + timedelta(seconds=5)
        grid["2"] = 40.0  # water heater's phase, deeply over fuse
        mock_ha.set_number.reset_mock()
        mock_ha.set_input_number.reset_mock()
        await engine.run_once()

        assert engine._last_balancer_status.state in ("paused", "shedding")
        assert goe_calls() == [0.0]  # commanded stop
        assert water_heater_writes() == [40.0]  # config.water_heater.temp_off default

        # A couple more overloaded ticks confirm the shed holds (EV is fully
        # paused here too, so the summary state reports "paused" — shedding
        # is still active underneath, per shed_outputs)
        for i in range(2):
            _FakeDateTime._current = t0 + timedelta(seconds=10 + i * 5)
            mock_ha.set_input_number.reset_mock()
            await engine.run_once()
            assert engine._last_balancer_status.state in ("paused", "shedding")
            assert any(o.shed for o in engine._last_balancer_status.shed_outputs)

        # --- Stage 3: recovery — grid healthy again, wait out resume_delay_s ---
        grid["1"] = 5.0
        grid["2"] = 5.0
        _FakeDateTime._current = t0 + timedelta(seconds=30)
        mock_ha.set_number.reset_mock()
        mock_ha.set_input_number.reset_mock()
        await engine.run_once()
        # Too soon: still shed/paused
        assert engine._last_balancer_status.state in ("paused", "shedding")

        _FakeDateTime._current = t0 + timedelta(seconds=30 + 125)
        mock_ha.set_number.reset_mock()
        mock_ha.set_input_number.reset_mock()
        await engine.run_once()
        assert engine._last_balancer_status.state not in ("paused", "shedding")
        # Water heater restored — the balancer no longer reports it as shed
        # (its temperature happens to still be temp_off here too, since this
        # test's slot has no real water-heating demand configured)
        assert not any(o.shed for o in engine._last_balancer_status.shed_outputs)

        # --- Stage 4: stale sensor two-stage fail-safe ---
        engine._ev_charger_states["goe"] = EVChargerState(
            charging_active=True, current_setpoint_a=16, charging_started_at=_FakeDateTime._current
        )
        stale_phase = "1"
        t_stale_start = _FakeDateTime._current
        mock_ha.set_number.reset_mock()
        await engine.run_once()

        assert engine._last_balancer_status.state == "stale_fallback"
        assert goe_calls()[-1] == 6.0  # forced to the floor immediately

        _FakeDateTime._current = t_stale_start + timedelta(seconds=125)
        mock_ha.set_number.reset_mock()
        await engine.run_once()

        assert engine._last_balancer_status.state == "paused"
        assert goe_calls() == [0.0]  # stale beyond resume_delay_s -> stopped
