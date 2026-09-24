"""Tests for universal-load-balancing: EV current-type actuation (Section 2 & 3)."""

import contextlib
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz
from sqlalchemy import create_engine

from backend.learning.models import Base
from executor.actions import ActionResult
from executor.config import EVChargerDeviceConfig, ExecutorConfig
from executor.engine import EVChargerState, ExecutorEngine
from executor.override import SlotPlan


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
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    yield db_path
    with contextlib.suppress(OSError):
        Path(db_path).unlink()


def make_current_engine(temp_schedule, temp_db, charger: EVChargerDeviceConfig) -> ExecutorEngine:
    with patch("executor.engine.load_executor_config") as mock_config:
        mock_config.return_value = ExecutorConfig(
            schedule_path=temp_schedule,
            timezone="Europe/Stockholm",
            ev_chargers=[charger],
        )
        with patch("executor.engine.load_yaml") as mock_yaml:
            mock_yaml.return_value = {}
            with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                eng = ExecutorEngine("config.yaml")
                eng._has_ev_charger = True
                return eng


def make_slot(ev_kw: float) -> SlotPlan:
    return SlotPlan(
        charge_kw=0.0,
        discharge_kw=0.0,
        export_kw=0.0,
        load_kw=0.0,
        water_kw=0.0,
        ev_charging_kw=ev_kw,
        soc_target=50,
        soc_projected=50,
        ev_charger_plans={"goe": ev_kw},
    )


GOE_SWITCH = "select.goe_frc"


def goe_charger(**overrides) -> EVChargerDeviceConfig:
    """go-e style select-controlled current charger."""
    params = {
        "id": "goe",
        "type": "current",
        "current_entity": "number.goe_current",
        "switch_entity": GOE_SWITCH,
        "charge_enabled_value": "charge",
        "charge_disabled_value": "dont_charge",
        "min_current_a": 6,
        "max_current_a": 16,
        "phases": [1, 2, 3],
    }
    params.update(overrides)
    return EVChargerDeviceConfig(**params)


def make_dispatcher(
    current_success: bool = True,
    current_skipped: bool = False,
    switch_success: bool = True,
    switch_skipped: bool = False,
    error: str | None = None,
) -> AsyncMock:
    """Dispatcher double returning real ActionResults for both EV writes."""

    async def set_current(entity_id, amps):
        return ActionResult(
            action_type="ev_charge_current",
            success=current_success,
            message="ok" if current_success else f"Failed to set {entity_id} to {amps}A",
            entity_id=entity_id,
            new_value=amps,
            skipped=current_skipped,
            error_details=None if current_success else error,
        )

    async def set_switch(entity_id, turn_on, charging_kw=0.0, *, enabled_value, disabled_value):
        return ActionResult(
            action_type="ev_charge_start" if turn_on else "ev_charge_stop",
            success=switch_success,
            message="ok" if switch_success else "Failed",
            entity_id=entity_id,
            new_value=enabled_value if turn_on else disabled_value,
            skipped=switch_skipped,
            error_details=None if switch_success else error,
        )

    dispatcher = AsyncMock()
    dispatcher.set_ev_charger_current = AsyncMock(side_effect=set_current)
    dispatcher.set_ev_charger_switch = AsyncMock(side_effect=set_switch)
    return dispatcher


def switch_calls(dispatcher: AsyncMock) -> list[tuple[str, bool]]:
    return [
        (c.args[0], c.kwargs["turn_on"]) for c in dispatcher.set_ev_charger_switch.call_args_list
    ]


class TestControlEvChargerCurrentType:
    """Current-type chargers start/stop via switch_entity; never write 0 A."""

    @pytest.fixture
    def engine(self, temp_schedule, temp_db):
        eng = make_current_engine(temp_schedule, temp_db, goe_charger())
        eng.ha_client = AsyncMock()
        eng.ha_client.get_state = AsyncMock(return_value=None)  # no phase sensors configured
        return eng

    @pytest.mark.asyncio
    async def test_start_writes_amps_then_enables_switch(self, engine):
        engine.dispatcher = make_dispatcher()
        calls = MagicMock()
        calls.attach_mock(engine.dispatcher.set_ev_charger_current, "amps")
        calls.attach_mock(engine.dispatcher.set_ev_charger_switch, "switch")

        now = datetime.now(pytz.timezone("Europe/Stockholm"))
        await engine._control_ev_charger(make_slot(11.0), now)

        engine.dispatcher.set_ev_charger_current.assert_called_once_with(
            "number.goe_current", 16
        )
        call = engine.dispatcher.set_ev_charger_switch.call_args
        assert call.args[0] == GOE_SWITCH
        assert call.kwargs["turn_on"] is True
        assert call.kwargs["enabled_value"] == "charge"
        assert [c[0] for c in calls.mock_calls] == ["amps", "switch"]
        state = engine._ev_charger_states["goe"]
        assert state.current_setpoint_a == 16
        assert state.charging_active is True

    @pytest.mark.asyncio
    async def test_unchanged_setpoint_is_checked_against_ha(self, engine):
        """Setpoint and switch are both re-checked against HA every tick; when HA
        already holds the targets the dispatcher skips and nothing is recorded."""
        engine.dispatcher = make_dispatcher(current_skipped=True, switch_skipped=True)
        now = datetime.now(pytz.timezone("Europe/Stockholm"))
        engine._ev_charger_states["goe"] = EVChargerState(
            charging_active=True, current_setpoint_a=16, charging_started_at=now
        )

        with patch.object(engine.history, "log_execution") as log_execution:
            await engine._control_ev_charger(make_slot(11.0), now)

        engine.dispatcher.set_ev_charger_current.assert_called_once_with(
            "number.goe_current", 16
        )
        assert switch_calls(engine.dispatcher) == [(GOE_SWITCH, True)]
        log_execution.assert_not_called()

    @pytest.mark.asyncio
    async def test_external_amps_change_is_corrected(self, engine):
        """HA holds a different amps value than last sent (e.g. changed in the
        go-e app): the setpoint is written again even though memory says 16 A."""
        engine.dispatcher = make_dispatcher(switch_skipped=True)  # current not skipped
        now = datetime.now(pytz.timezone("Europe/Stockholm"))
        engine._ev_charger_states["goe"] = EVChargerState(
            charging_active=True, current_setpoint_a=16, charging_started_at=now
        )

        await engine._control_ev_charger(make_slot(11.0), now)

        engine.dispatcher.set_ev_charger_current.assert_called_once_with(
            "number.goe_current", 16
        )
        assert engine._ev_charger_states["goe"].current_setpoint_a == 16

    @pytest.mark.asyncio
    async def test_external_dont_charge_is_corrected(self, engine):
        """Charging desired, switch reads dont_charge: the switch is re-enabled."""
        engine.dispatcher = make_dispatcher()  # not skipped -> HA held a different value
        now = datetime.now(pytz.timezone("Europe/Stockholm"))
        engine._ev_charger_states["goe"] = EVChargerState(
            charging_active=True, current_setpoint_a=16, charging_started_at=now
        )

        await engine._control_ev_charger(make_slot(11.0), now)

        assert switch_calls(engine.dispatcher) == [(GOE_SWITCH, True)]
        assert engine.dispatcher.set_ev_charger_switch.call_args.kwargs["enabled_value"] == (
            "charge"
        )

    @pytest.mark.asyncio
    async def test_below_minimum_pauses_via_switch(self, engine):
        """Plan implies < 6A -> switch set to dont_charge; no number.set_value."""
        engine.dispatcher = make_dispatcher()
        now = datetime.now(pytz.timezone("Europe/Stockholm"))
        engine._ev_charger_states["goe"] = EVChargerState(
            charging_active=True, current_setpoint_a=6, charging_started_at=now
        )

        # 1kW / 3-phase implies ~1.4A, well below the 6A floor
        await engine._control_ev_charger(make_slot(1.0), now)

        engine.dispatcher.set_ev_charger_current.assert_not_called()
        assert switch_calls(engine.dispatcher) == [(GOE_SWITCH, False)]
        assert engine.dispatcher.set_ev_charger_switch.call_args.kwargs["disabled_value"] == (
            "dont_charge"
        )
        state = engine._ev_charger_states["goe"]
        assert state.current_setpoint_a is None
        assert state.charging_active is False

    @pytest.mark.asyncio
    async def test_plan_end_stops_via_switch_without_amps(self, engine):
        engine.dispatcher = make_dispatcher()
        now = datetime.now(pytz.timezone("Europe/Stockholm"))
        engine._ev_charger_states["goe"] = EVChargerState(
            charging_active=True, current_setpoint_a=10, charging_started_at=now
        )

        await engine._control_ev_charger(make_slot(0.0), now)

        engine.dispatcher.set_ev_charger_current.assert_not_called()
        assert switch_calls(engine.dispatcher) == [(GOE_SWITCH, False)]

    @pytest.mark.asyncio
    async def test_balancer_pause_stops_via_switch(self, engine):
        engine.dispatcher = make_dispatcher()
        now = datetime.now(pytz.timezone("Europe/Stockholm"))
        engine._ev_charger_states["goe"] = EVChargerState(
            charging_active=True, current_setpoint_a=10, charging_started_at=now
        )

        await engine._control_ev_charger(make_slot(11.0), now, balancer_ev_targets={"goe": None})

        engine.dispatcher.set_ev_charger_current.assert_not_called()
        assert switch_calls(engine.dispatcher) == [(GOE_SWITCH, False)]

    @pytest.mark.asyncio
    async def test_force_stop_uses_switch(self, engine):
        engine.dispatcher = make_dispatcher()
        now = datetime.now(pytz.timezone("Europe/Stockholm"))
        engine._ev_charger_states["goe"] = EVChargerState(
            charging_active=True, current_setpoint_a=10, charging_started_at=now
        )

        await engine._control_ev_charger(make_slot(11.0), now, force_stop=True)

        engine.dispatcher.set_ev_charger_current.assert_not_called()
        assert switch_calls(engine.dispatcher) == [(GOE_SWITCH, False)]

    @pytest.mark.asyncio
    async def test_already_stopped_makes_no_write(self, engine):
        """Idle charger: the stop is an idempotent switch check, never an amps write."""
        engine.dispatcher = make_dispatcher(switch_skipped=True)
        now = datetime.now(pytz.timezone("Europe/Stockholm"))

        await engine._control_ev_charger(make_slot(0.0), now)

        engine.dispatcher.set_ev_charger_current.assert_not_called()
        assert switch_calls(engine.dispatcher) == [(GOE_SWITCH, False)]

    @pytest.mark.asyncio
    async def test_switch_like_entity_uses_on_off(self, temp_schedule, temp_db):
        eng = make_current_engine(
            temp_schedule, temp_db, goe_charger(switch_entity="switch.goe_allow")
        )
        eng.ha_client = AsyncMock()
        eng.ha_client.get_state = AsyncMock(return_value=None)
        eng.dispatcher = make_dispatcher()
        now = datetime.now(pytz.timezone("Europe/Stockholm"))

        await eng._control_ev_charger(make_slot(11.0), now)

        assert switch_calls(eng.dispatcher) == [("switch.goe_allow", True)]

    @pytest.mark.asyncio
    async def test_charger_without_current_entity_skipped(self, temp_schedule, temp_db):
        eng = make_current_engine(temp_schedule, temp_db, goe_charger(current_entity=None))
        eng.ha_client = AsyncMock()
        eng.dispatcher = make_dispatcher()

        now = datetime.now(pytz.timezone("Europe/Stockholm"))
        await eng._control_ev_charger(make_slot(11.0), now)

        eng.dispatcher.set_ev_charger_current.assert_not_called()
        eng.dispatcher.set_ev_charger_switch.assert_not_called()


class TestEvCurrentSafetyTimeout:
    """3.4: 30-minute safety timeout applies to current-type devices too."""

    @pytest.mark.asyncio
    async def test_stale_session_past_30_minutes_is_stopped(
        self, temp_schedule, temp_db, caplog
    ):
        engine = make_current_engine(temp_schedule, temp_db, goe_charger())
        engine.ha_client = AsyncMock()
        engine.ha_client.get_state = AsyncMock(return_value=None)

        now = datetime.now(pytz.timezone("Europe/Stockholm"))
        engine._ev_charger_states["goe"] = EVChargerState(
            charging_active=True,
            current_setpoint_a=10,
            charging_started_at=now - timedelta(minutes=45),
        )
        engine.dispatcher = make_dispatcher()

        # No plan this tick (plan ended)
        await engine._control_ev_charger(make_slot(0.0), now)

        engine.dispatcher.set_ev_charger_current.assert_not_called()
        assert switch_calls(engine.dispatcher) == [(GOE_SWITCH, False)]
        assert any("safety timeout" in m for m in caplog.messages)


class TestEvActivePhaseMeasurement:
    """2.2: active_phases derived from the charger's own per-phase sensors."""

    @pytest.fixture
    def engine(self, temp_schedule, temp_db):
        charger = EVChargerDeviceConfig(
            id="goe",
            type="current",
            current_entity="number.goe_current",
            min_current_a=6,
            max_current_a=16,
            phases=[1, 2, 3],
            phase_sensor_l1="sensor.goe_l1",
            phase_sensor_l2="sensor.goe_l2",
            phase_sensor_l3="sensor.goe_l3",
        )
        return make_current_engine(temp_schedule, temp_db, charger)

    @pytest.mark.asyncio
    async def test_falls_back_to_configured_phases_before_measurement(self, engine):
        charger_cfg = engine.config.ev_chargers[0]
        dev_state = EVChargerState()
        engine.ha_client = AsyncMock()
        # No response yet this tick (simulate not measured)
        engine.ha_client.get_state = AsyncMock(return_value=None)

        await engine._update_ev_active_phases(charger_cfg, dev_state)

        assert dev_state.active_phases is None  # caller falls back to charger_cfg.phases

    @pytest.mark.asyncio
    async def test_single_phase_car_detected(self, engine):
        charger_cfg = engine.config.ev_chargers[0]
        dev_state = EVChargerState()
        engine.ha_client = AsyncMock()

        async def fake_get_state(entity):
            if entity == "sensor.goe_l1":
                return {"state": "10.0", "attributes": {"unit_of_measurement": "A"}}
            return {"state": "0.0", "attributes": {"unit_of_measurement": "A"}}

        engine.ha_client.get_state = AsyncMock(side_effect=fake_get_state)

        await engine._update_ev_active_phases(charger_cfg, dev_state)

        assert dev_state.active_phases == [1]

    @pytest.mark.asyncio
    async def test_three_phase_car_detected(self, engine):
        charger_cfg = engine.config.ev_chargers[0]
        dev_state = EVChargerState()
        engine.ha_client = AsyncMock()
        engine.ha_client.get_state = AsyncMock(
            return_value={"state": "10.0", "attributes": {"unit_of_measurement": "A"}}
        )

        await engine._update_ev_active_phases(charger_cfg, dev_state)

        assert dev_state.active_phases == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_momentary_zero_reading_does_not_blank_known_session(self, engine):
        charger_cfg = engine.config.ev_chargers[0]
        dev_state = EVChargerState(active_phases=[1, 2, 3])
        engine.ha_client = AsyncMock()
        engine.ha_client.get_state = AsyncMock(
            return_value={"state": "0.0", "attributes": {"unit_of_measurement": "A"}}
        )

        await engine._update_ev_active_phases(charger_cfg, dev_state)

        assert dev_state.active_phases == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_power_sensor_in_watts_uses_watt_threshold(self, engine):
        charger_cfg = engine.config.ev_chargers[0]
        dev_state = EVChargerState()
        engine.ha_client = AsyncMock()

        async def fake_get_state(entity):
            if entity == "sensor.goe_l1":
                return {"state": "2300", "attributes": {"unit_of_measurement": "W"}}
            return {"state": "50", "attributes": {"unit_of_measurement": "W"}}  # below 100W

        engine.ha_client.get_state = AsyncMock(side_effect=fake_get_state)

        await engine._update_ev_active_phases(charger_cfg, dev_state)

        assert dev_state.active_phases == [1]


class TestEvCurrentTypeUsesActivePhases:
    """kW->A translation uses measured active_phases, falling back to configured phases."""

    @pytest.mark.asyncio
    async def test_single_phase_measurement_changes_amps(self, temp_schedule, temp_db):
        eng = make_current_engine(temp_schedule, temp_db, goe_charger())
        eng.ha_client = AsyncMock()
        eng.ha_client.get_state = AsyncMock(return_value=None)  # no phase sensors configured

        eng._ev_charger_states["goe"] = EVChargerState(active_phases=[1])  # measured 1-phase car
        eng.dispatcher = make_dispatcher()

        now = datetime.now(pytz.timezone("Europe/Stockholm"))
        # 3.6kW / 1 phase -> 16A (ceil) (vs ~5A if treated as 3-phase)
        await eng._control_ev_charger(make_slot(3.6), now)

        eng.dispatcher.set_ev_charger_current.assert_called_once_with(
            "number.goe_current", 16
        )


class TestSourceIsolationWithCurrentControl:
    """3.4 / ev-current-control spec: source isolation is driven purely by
    measured EV power (LoadDisaggregator), which is charger-type-agnostic —
    a current-type charger actively drawing current blocks discharge exactly
    like a binary one, with no charger-type-specific code path involved."""

    @pytest.mark.asyncio
    async def test_active_current_type_session_blocks_discharge(self, temp_schedule, temp_db):
        charger = EVChargerDeviceConfig(
            id="goe", type="current", current_entity="number.goe_current",
            min_current_a=6, max_current_a=16,
        )
        eng = make_current_engine(temp_schedule, temp_db, charger)
        eng._has_battery = True

        # Charger is actively holding a setpoint (as _control_ev_charger_current would leave it)
        eng._ev_charger_states["goe"] = EVChargerState(charging_active=True, current_setpoint_a=10)

        # Measured actual EV power (independent of charger type) is what isolation checks
        actual_ev_power_kw = 2.3  # 10A * 230V
        scheduled_ev_charging = False  # no fresh plan this tick, e.g. balancer-driven
        actual_ev_charging = actual_ev_power_kw > 0.1
        ev_should_charge_block = scheduled_ev_charging or actual_ev_charging

        assert ev_should_charge_block is True
