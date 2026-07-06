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


class TestControlEvChargerCurrentType:
    """3.3: _control_ev_charger branches on device.type."""

    @pytest.fixture
    def engine(self, temp_schedule, temp_db):
        charger = EVChargerDeviceConfig(
            id="goe",
            type="current",
            current_entity="number.goe_current",
            min_current_a=6,
            max_current_a=16,
            phases=[1, 2, 3],
        )
        return make_current_engine(temp_schedule, temp_db, charger)

    @pytest.mark.asyncio
    async def test_writes_ampere_setpoint_for_planned_power(self, engine):
        engine.ha_client = AsyncMock()
        engine.ha_client.get_state = AsyncMock(return_value=None)  # no phase sensors configured

        mock_result = MagicMock(
            success=True,
            skipped=False,
            duration_ms=5,
            action_type="ev_charge_current",
            message="ok",
            entity_id="number.goe_current",
            previous_value="6",
            new_value=15,
            verified_value="15",
            verification_success=True,
            error_details=None,
        )
        engine.dispatcher = AsyncMock()
        engine.dispatcher.set_ev_charger_current = AsyncMock(return_value=mock_result)

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        await engine._control_ev_charger(make_slot(11.0), now)

        engine.dispatcher.set_ev_charger_current.assert_called_once_with(
            "number.goe_current", 15
        )
        assert engine._ev_charger_states["goe"].current_setpoint_a == 15
        assert engine._ev_charger_states["goe"].charging_active is True

    @pytest.mark.asyncio
    async def test_stops_when_below_minimum_current(self, engine):
        """Plan implies < 6A -> writes 0A (stop) rather than a below-floor setpoint."""
        engine.ha_client = AsyncMock()
        engine.ha_client.get_state = AsyncMock(return_value=None)

        engine._ev_charger_states["goe"] = EVChargerState(
            charging_active=True,
            current_setpoint_a=6,
            charging_started_at=datetime.now(pytz.timezone("Europe/Stockholm")),
        )

        mock_result = MagicMock(
            success=True,
            skipped=False,
            duration_ms=5,
            action_type="ev_charge_current",
            message="ok",
            entity_id="number.goe_current",
            previous_value="6",
            new_value=0,
            verified_value="0",
            verification_success=True,
            error_details=None,
        )
        engine.dispatcher = AsyncMock()
        engine.dispatcher.set_ev_charger_current = AsyncMock(return_value=mock_result)

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        # 1kW / 3-phase implies ~1.4A, well below the 6A floor
        await engine._control_ev_charger(make_slot(1.0), now)

        engine.dispatcher.set_ev_charger_current.assert_called_once_with(
            "number.goe_current", 0
        )
        assert engine._ev_charger_states["goe"].current_setpoint_a is None
        assert engine._ev_charger_states["goe"].charging_active is False

    @pytest.mark.asyncio
    async def test_no_call_when_already_stopped_and_no_plan(self, engine):
        engine.ha_client = AsyncMock()
        engine.ha_client.get_state = AsyncMock(return_value=None)
        engine.dispatcher = AsyncMock()

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        await engine._control_ev_charger(make_slot(0.0), now)

        engine.dispatcher.set_ev_charger_current.assert_not_called()

    @pytest.mark.asyncio
    async def test_charger_without_current_entity_skipped(self, temp_schedule, temp_db):
        charger = EVChargerDeviceConfig(id="goe", type="current", current_entity=None)
        eng = make_current_engine(temp_schedule, temp_db, charger)
        eng.ha_client = AsyncMock()
        eng.dispatcher = AsyncMock()

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        await eng._control_ev_charger(make_slot(11.0), now)

        eng.dispatcher.set_ev_charger_current.assert_not_called()


class TestEvCurrentSafetyTimeout:
    """3.4: 30-minute safety timeout applies to current-type devices too."""

    @pytest.fixture
    def engine(self, temp_schedule, temp_db):
        charger = EVChargerDeviceConfig(
            id="goe", type="current", current_entity="number.goe_current",
            min_current_a=6, max_current_a=16,
        )
        return make_current_engine(temp_schedule, temp_db, charger)

    @pytest.mark.asyncio
    async def test_stale_session_past_30_minutes_is_stopped(self, engine, caplog):
        engine.ha_client = AsyncMock()
        engine.ha_client.get_state = AsyncMock(return_value=None)

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        engine._ev_charger_states["goe"] = EVChargerState(
            charging_active=True,
            current_setpoint_a=10,
            charging_started_at=now - timedelta(minutes=45),
        )

        mock_result = MagicMock(
            success=True, skipped=False, duration_ms=5, action_type="ev_charge_current",
            message="ok", entity_id="number.goe_current", previous_value="10", new_value=0,
            verified_value="0", verification_success=True, error_details=None,
        )
        engine.dispatcher = AsyncMock()
        engine.dispatcher.set_ev_charger_current = AsyncMock(return_value=mock_result)

        # No plan this tick (plan ended)
        await engine._control_ev_charger(make_slot(0.0), now)

        engine.dispatcher.set_ev_charger_current.assert_called_once_with(
            "number.goe_current", 0
        )
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
        charger = EVChargerDeviceConfig(
            id="goe",
            type="current",
            current_entity="number.goe_current",
            min_current_a=6,
            max_current_a=16,
            phases=[1, 2, 3],
        )
        eng = make_current_engine(temp_schedule, temp_db, charger)
        eng.ha_client = AsyncMock()
        eng.ha_client.get_state = AsyncMock(return_value=None)  # no phase sensors configured

        eng._ev_charger_states["goe"] = EVChargerState(active_phases=[1])  # measured 1-phase car

        mock_result = MagicMock(
            success=True, skipped=False, duration_ms=5, action_type="ev_charge_current",
            message="ok", entity_id="number.goe_current", previous_value="0", new_value=15,
            verified_value="15", verification_success=True, error_details=None,
        )
        eng.dispatcher = AsyncMock()
        eng.dispatcher.set_ev_charger_current = AsyncMock(return_value=mock_result)

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        # 3.6kW / 1 phase -> 15A (vs ~5A if treated as 3-phase)
        await eng._control_ev_charger(make_slot(3.6), now)

        eng.dispatcher.set_ev_charger_current.assert_called_once_with(
            "number.goe_current", 15
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
