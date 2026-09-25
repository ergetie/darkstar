"""
Tests for ev-manual-charge: per-charger "charge now to target SoC" in the executor.

Covers set/clear/status + validation, persistence (restart resume, goal fields
untouched), the shared should-be-on predicate at every decision site, safety
precedence (balancer throttle, binary shed, force_stop), and automatic end
conditions with the follow-up replan request.
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

from backend.core import ev_state
from backend.learning.models import Base
from executor.config import EVChargerDeviceConfig, ExecutorConfig, LoadBalancingConfig
from executor.engine import EV_MANUAL_CHARGE_STATE_KEY, ExecutorEngine, ManualCharge
from executor.override import SlotPlan, SystemState

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
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    yield db_path
    with contextlib.suppress(OSError):
        Path(db_path).unlink()


def binary_charger(charger_id: str = "ev1", **overrides) -> EVChargerDeviceConfig:
    params = {
        "id": charger_id,
        "switch_entity": f"switch.{charger_id}",
        "soc_sensor": f"sensor.{charger_id}_soc",
        "plug_sensor": f"binary_sensor.{charger_id}_plug",
    }
    params.update(overrides)
    return EVChargerDeviceConfig(**params)


def current_charger(charger_id: str = "goe", **overrides) -> EVChargerDeviceConfig:
    params = {
        "id": charger_id,
        "type": "current",
        "current_entity": f"number.{charger_id}_current",
        "switch_entity": f"switch.{charger_id}_allow",
        "min_current_a": 6,
        "max_current_a": 16,
        "phases": [1, 2, 3],
        "soc_sensor": f"sensor.{charger_id}_soc",
        "plug_sensor": f"binary_sensor.{charger_id}_plug",
    }
    params.update(overrides)
    return EVChargerDeviceConfig(**params)


def make_engine(temp_schedule, temp_db, chargers, load_balancing=None) -> ExecutorEngine:
    with patch("executor.engine.load_executor_config") as mock_config:
        mock_config.return_value = ExecutorConfig(
            schedule_path=temp_schedule,
            timezone="Europe/Stockholm",
            ev_chargers=chargers,
            load_balancing=load_balancing or LoadBalancingConfig(),
        )
        with patch("executor.engine.load_yaml") as mock_yaml:
            mock_yaml.return_value = {}
            with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                eng = ExecutorEngine("config.yaml")
                eng._has_ev_charger = True
                return eng


def ok_result(**kwargs) -> MagicMock:
    defaults = {
        "success": True,
        "skipped": False,
        "duration_ms": 5,
        "action_type": "switch",
        "message": "ok",
        "entity_id": "x",
        "previous_value": None,
        "new_value": None,
        "verified_value": None,
        "verification_success": True,
        "error_details": None,
    }
    defaults.update(kwargs)
    return MagicMock(**defaults)


def start(engine, charger_id="ev1", target=80, current_a=None, soc=49.0, plug="plugged"):
    return engine.set_ev_manual_charge(
        charger_id, target, current_a, current_soc_percent=soc, plug_state=plug
    )


@pytest.fixture(autouse=True)
def no_ws_emit():
    with patch("backend.core.websockets.ws_manager") as ws:
        yield ws


class TestSetClearStatus:
    def test_start_sets_active_status(self, temp_schedule, temp_db, no_ws_emit):
        engine = make_engine(temp_schedule, temp_db, [binary_charger()])

        result = start(engine)

        assert result["success"] is True
        status = engine.get_ev_manual_charge_status()
        assert status["ev1"]["target_soc"] == 80
        assert status["ev1"]["current_a"] is None
        no_ws_emit.emit_sync.assert_called_with("ev_manual_charge_updated", {"chargers": status})

    def test_clear_ends_and_requests_replan(self, temp_schedule, temp_db, no_ws_emit):
        engine = make_engine(temp_schedule, temp_db, [binary_charger()])
        start(engine)

        result = engine.clear_ev_manual_charge("ev1")

        assert result == {"success": True, "was_active": True}
        assert engine.get_ev_manual_charge_status() == {}
        assert engine._ev_manual_replan_pending is True
        no_ws_emit.emit_sync.assert_called_with("ev_manual_charge_updated", {"chargers": {}})

    def test_clear_inactive_is_noop(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, [binary_charger()])
        assert engine.clear_ev_manual_charge("ev1") == {"success": True, "was_active": False}
        assert engine._ev_manual_replan_pending is False

    def test_user_current_on_current_charger(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, [current_charger()])
        start(engine, "goe", current_a=10)
        assert engine.get_ev_manual_charge_status()["goe"]["current_a"] == 10


class TestValidation:
    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"charger_id": "nope"}, "Unknown or disabled"),
            ({"target": 0}, "between 1 and 100"),
            ({"target": 101}, "between 1 and 100"),
            ({"plug": "unplugged"}, "not connected"),
            ({"plug": "unknown"}, "plug state is unknown"),
            ({"soc": None}, "SoC is unknown"),
            ({"soc": 82.0}, "already reached"),
            ({"soc": 80.0}, "already reached"),
            ({"current_a": 10}, "current-type"),
        ],
    )
    def test_binary_rejections(self, temp_schedule, temp_db, kwargs, message):
        engine = make_engine(temp_schedule, temp_db, [binary_charger()])
        with pytest.raises(ValueError, match=message):
            start(engine, **kwargs)
        assert engine.get_ev_manual_charge_status() == {}

    @pytest.mark.parametrize("current_a", [5, 17])
    def test_current_out_of_range_rejected(self, temp_schedule, temp_db, current_a):
        engine = make_engine(temp_schedule, temp_db, [current_charger()])
        with pytest.raises(ValueError, match="between 6 and 16 A"):
            start(engine, "goe", current_a=current_a)

    def test_externally_controlled_rejected(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, [binary_charger(switch_entity=None)])
        with pytest.raises(ValueError, match="not controlled by Darkstar"):
            start(engine)


class TestPersistence:
    def test_restart_resumes_manual_charge(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, [current_charger()])
        start(engine, "goe", target=80, current_a=10)
        started_at = engine.get_ev_manual_charge_status()["goe"]["started_at"]

        restarted = make_engine(temp_schedule, temp_db, [current_charger()])

        status = restarted.get_ev_manual_charge_status()["goe"]
        assert status["target_soc"] == 80
        assert status["current_a"] == 10
        assert status["started_at"] == started_at

    def test_goal_fields_untouched(self, temp_schedule, temp_db):
        goal = {
            "target_soc_percent": 80,
            "ready_by": "07:00",
            "repeat": "daily",
            "keep_on_after_target": True,
        }
        ev_state.write_ev_state({"ev1": dict(goal)})
        engine = make_engine(temp_schedule, temp_db, [binary_charger()])

        start(engine, target=60)
        during = ev_state.read_ev_state()["ev1"]
        assert {k: during[k] for k in goal} == goal
        assert during[EV_MANUAL_CHARGE_STATE_KEY]["target_soc"] == 60

        engine.clear_ev_manual_charge("ev1")
        assert ev_state.read_ev_state()["ev1"] == goal

    def test_clear_without_goal_removes_entry(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, [binary_charger()])
        start(engine)
        engine.clear_ev_manual_charge("ev1")
        assert ev_state.read_ev_state() == {}

    def test_unknown_charger_and_malformed_entries_ignored(self, temp_schedule, temp_db):
        ev_state.write_ev_state(
            {
                "gone": {EV_MANUAL_CHARGE_STATE_KEY: {"target_soc": 80, "started_at": "x"}},
                "ev1": {EV_MANUAL_CHARGE_STATE_KEY: {"target_soc": "bad"}},
            }
        )
        engine = make_engine(temp_schedule, temp_db, [binary_charger()])
        assert engine.get_ev_manual_charge_status() == {}


class TestKeepsChargerOn:
    @pytest.mark.asyncio
    async def test_binary_on_with_zero_kw_plan(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, [binary_charger()])
        start(engine)
        engine.ha_client = AsyncMock()
        engine.ha_client.get_state_value = AsyncMock(return_value="off")
        engine.dispatcher = AsyncMock()
        engine.dispatcher.set_ev_charger_switch = AsyncMock(return_value=ok_result())

        await engine._control_ev_charger(SlotPlan(ev_charger_plans={"ev1": 0.0}), datetime.now(TZ))

        assert engine.dispatcher.set_ev_charger_switch.call_args.kwargs["turn_on"] is True

    @pytest.mark.asyncio
    async def test_binary_on_without_any_slot(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, [binary_charger()])
        start(engine)
        assert engine._charger_should_be_on(None, "ev1") is True

    @pytest.mark.asyncio
    async def test_other_charger_follows_plan(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, [binary_charger("ev1"), binary_charger("ev2")])
        start(engine, "ev1")
        engine.ha_client = AsyncMock()
        engine.ha_client.get_state_value = AsyncMock(return_value="off")
        engine.dispatcher = AsyncMock()
        engine.dispatcher.set_ev_charger_switch = AsyncMock(return_value=ok_result())

        slot = SlotPlan(ev_charger_plans={"ev1": 0.0, "ev2": 0.0})
        await engine._control_ev_charger(slot, datetime.now(TZ))

        entities = [c.args[0] for c in engine.dispatcher.set_ev_charger_switch.call_args_list]
        assert entities == ["switch.ev1"]

    @pytest.mark.asyncio
    async def test_current_charger_at_max_without_balancer(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, [current_charger()])
        start(engine, "goe")
        engine.ha_client = AsyncMock()
        engine.ha_client.get_state = AsyncMock(return_value=None)
        engine.dispatcher = AsyncMock()
        engine.dispatcher.set_ev_charger_current = AsyncMock(return_value=ok_result())
        engine.dispatcher.set_ev_charger_switch = AsyncMock(return_value=ok_result())

        await engine._control_ev_charger(SlotPlan(ev_charger_plans={"goe": 0.0}), datetime.now(TZ))

        engine.dispatcher.set_ev_charger_current.assert_called_once_with("number.goe_current", 16)

    @pytest.mark.asyncio
    async def test_current_charger_at_user_amps_without_balancer(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, [current_charger()])
        start(engine, "goe", current_a=10)
        engine.ha_client = AsyncMock()
        engine.ha_client.get_state = AsyncMock(return_value=None)
        engine.dispatcher = AsyncMock()
        engine.dispatcher.set_ev_charger_current = AsyncMock(return_value=ok_result())
        engine.dispatcher.set_ev_charger_switch = AsyncMock(return_value=ok_result())

        await engine._control_ev_charger(SlotPlan(ev_charger_plans={"goe": 0.0}), datetime.now(TZ))

        engine.dispatcher.set_ev_charger_current.assert_called_once_with("number.goe_current", 10)

    def test_balancer_input_uses_manual_current_over_surplus(self, temp_schedule, temp_db):
        engine = make_engine(
            temp_schedule,
            temp_db,
            [current_charger()],
            load_balancing=LoadBalancingConfig(enabled=True, main_fuse_a=32),
        )
        start(engine, "goe", current_a=12)
        engine._ev_surplus_targets = {"goe": 6}  # would lower it — must be ignored
        now = datetime.now(TZ)
        state = SystemState(
            grid_current_a={1: 0.0, 2: 0.0, 3: 0.0},
            grid_current_updated_at={1: now, 2: now, 3: now},
        )

        engine._run_load_balancer(state, SlotPlan(ev_charger_plans={"goe": 0.0}), now)

        assert engine._last_balancer_planned_targets["goe"] == 12

    @pytest.mark.asyncio
    async def test_surplus_targeting_skipped_while_manual(self, temp_schedule, temp_db):
        from executor.config import ExcessPVConfig, ExcessPVSinkEntry

        engine = make_engine(temp_schedule, temp_db, [current_charger()])
        engine.config.excess_pv = ExcessPVConfig(
            priority=[ExcessPVSinkEntry(type="ev", charger_id="goe")]
        )
        engine.ha_client = AsyncMock()
        engine.ha_client.get_state = AsyncMock(return_value=None)
        start(engine, "goe")

        slot = SlotPlan(ev_charger_plans={"goe": 0.0}, ev_surplus_kw={"goe": 3.0})
        await engine._update_ev_surplus_and_phase_mode(
            SystemState(current_export_kw=3.0), slot, datetime.now(TZ)
        )

        assert "goe" not in engine._ev_surplus_targets


class TestSafetyPrecedence:
    def test_balancer_throttles_and_manual_stays_active(self, temp_schedule, temp_db):
        engine = make_engine(
            temp_schedule,
            temp_db,
            [current_charger()],
            load_balancing=LoadBalancingConfig(enabled=True, main_fuse_a=32),
        )
        start(engine, "goe")
        now = datetime.now(TZ)
        state = SystemState(
            grid_current_a={1: 22.0, 2: 22.0, 3: 22.0},
            grid_current_updated_at={1: now, 2: now, 3: now},
        )

        status = engine._run_load_balancer(state, SlotPlan(), now)

        out = status.ev_outputs[0]
        assert out.target_a is None or out.target_a <= 10
        assert "goe" in engine.get_ev_manual_charge_status()

    @pytest.mark.asyncio
    async def test_binary_shed_switches_off_while_active(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, [binary_charger()])
        start(engine)
        engine.ha_client = AsyncMock()
        engine.ha_client.get_state_value = AsyncMock(return_value="on")
        engine.dispatcher = AsyncMock()
        engine.dispatcher.set_ev_charger_switch = AsyncMock(return_value=ok_result())

        await engine._control_ev_charger(
            SlotPlan(), datetime.now(TZ), shed_binary_charger_ids={"ev1"}
        )
        assert engine.dispatcher.set_ev_charger_switch.call_args.kwargs["turn_on"] is False
        assert "ev1" in engine.get_ev_manual_charge_status()

        # Restored: shed released → back on, manual charge still active.
        engine.ha_client.get_state_value = AsyncMock(return_value="off")
        await engine._control_ev_charger(SlotPlan(), datetime.now(TZ))
        assert engine.dispatcher.set_ev_charger_switch.call_args.kwargs["turn_on"] is True

    @pytest.mark.asyncio
    async def test_force_stop_wins(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, [binary_charger()])
        start(engine)
        engine.ha_client = AsyncMock()
        engine.ha_client.get_state_value = AsyncMock(return_value="on")
        engine.dispatcher = AsyncMock()
        engine.dispatcher.set_ev_charger_switch = AsyncMock(return_value=ok_result())

        await engine._control_ev_charger(SlotPlan(), datetime.now(TZ), force_stop=True)

        assert engine.dispatcher.set_ev_charger_switch.call_args.kwargs["turn_on"] is False
        assert "ev1" in engine.get_ev_manual_charge_status()


    @pytest.mark.asyncio
    async def test_manual_override_skips_ev_writes(self, temp_schedule, temp_db):
        """Executor pause via manual override (skip_writes) still prevents charging."""
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump({"schedule": []}, f)
        engine = make_engine(temp_schedule, temp_db, [binary_charger()])
        start(engine)
        engine.ha_client = ha_states({"sensor.ev1_soc": "50", "binary_sensor.ev1_plug": "on"})
        engine.dispatcher = AsyncMock()

        with (
            patch.object(
                engine,
                "_gather_system_state",
                AsyncMock(return_value=SystemState(manual_override_active=True)),
            ),
            patch.object(engine, "_control_ev_charger", AsyncMock()) as control,
        ):
            await engine.run_once()

        control.assert_not_awaited()
        assert "ev1" in engine.get_ev_manual_charge_status()


def ha_states(values: dict[str, str | None]) -> AsyncMock:
    client = AsyncMock()
    client.get_state_value = AsyncMock(side_effect=lambda entity: values.get(entity))
    return client


class TestEndConditions:
    @pytest.mark.asyncio
    async def test_target_reached_ends_and_replans(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, [binary_charger()])
        start(engine, target=80)
        engine.ha_client = ha_states({"sensor.ev1_soc": "80", "binary_sensor.ev1_plug": "on"})
        now = datetime.now(TZ)

        await engine._check_ev_manual_charge_end(now)

        assert engine.get_ev_manual_charge_status() == {}
        assert engine._charger_should_be_on(SlotPlan(ev_charger_plans={"ev1": 0.0}), "ev1") is False
        with patch.object(engine, "_request_balancer_replan") as replan:
            engine._maybe_request_ev_manual_replan(now)
        replan.assert_called_once()
        assert engine._ev_manual_replan_pending is False

    @pytest.mark.asyncio
    async def test_replan_rate_limited(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, [binary_charger()])
        now = datetime.now(TZ)
        engine._last_balancer_replan_at = now - timedelta(minutes=1)
        engine._ev_manual_replan_pending = True
        with patch.object(engine, "_request_balancer_replan") as replan:
            engine._maybe_request_ev_manual_replan(now)
        replan.assert_not_called()

    @pytest.mark.asyncio
    async def test_below_target_keeps_charging(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, [binary_charger()])
        start(engine, target=80)
        engine.ha_client = ha_states({"sensor.ev1_soc": "79.5", "binary_sensor.ev1_plug": "on"})

        await engine._check_ev_manual_charge_end(datetime.now(TZ))

        assert "ev1" in engine.get_ev_manual_charge_status()

    @pytest.mark.asyncio
    async def test_unplugged_ends(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, [binary_charger()])
        start(engine)
        engine.ha_client = ha_states({"sensor.ev1_soc": "50", "binary_sensor.ev1_plug": "off"})

        await engine._check_ev_manual_charge_end(datetime.now(TZ))

        assert engine.get_ev_manual_charge_status() == {}

    @pytest.mark.asyncio
    async def test_disconnected_ends(self, temp_schedule, temp_db):
        engine = make_engine(
            temp_schedule, temp_db, [binary_charger(plugged_in_states="connected")]
        )
        start(engine)
        engine.ha_client = ha_states(
            {"sensor.ev1_soc": "50", "binary_sensor.ev1_plug": "disconnected"}
        )

        await engine._check_ev_manual_charge_end(datetime.now(TZ))

        assert engine.get_ev_manual_charge_status() == {}

    @pytest.mark.asyncio
    async def test_unavailable_plug_keeps_charging(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, [binary_charger()])
        start(engine)
        engine.ha_client = ha_states({"sensor.ev1_soc": "50", "binary_sensor.ev1_plug": "unavailable"})

        await engine._check_ev_manual_charge_end(datetime.now(TZ))

        assert "ev1" in engine.get_ev_manual_charge_status()

    @pytest.mark.asyncio
    async def test_target_reached_with_unavailable_plug_ends(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, [binary_charger()])
        start(engine, target=80)
        engine.ha_client = ha_states({"sensor.ev1_soc": "81", "binary_sensor.ev1_plug": "unavailable"})

        await engine._check_ev_manual_charge_end(datetime.now(TZ))

        assert engine.get_ev_manual_charge_status() == {}

    @pytest.mark.asyncio
    async def test_unavailable_soc_and_plug_keep_charging(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, [binary_charger()])
        start(engine)
        engine.ha_client = ha_states(
            {"sensor.ev1_soc": "unavailable", "binary_sensor.ev1_plug": "unavailable"}
        )

        await engine._check_ev_manual_charge_end(datetime.now(TZ))

        assert "ev1" in engine.get_ev_manual_charge_status()

    @pytest.mark.asyncio
    async def test_24h_timeout_ends(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, [binary_charger()])
        start(engine)
        engine.ha_client = ha_states({"sensor.ev1_soc": "unavailable"})

        await engine._check_ev_manual_charge_end(datetime.now(TZ) + timedelta(hours=24))

        assert engine.get_ev_manual_charge_status() == {}


def test_manual_charge_round_trip():
    manual = ManualCharge(target_soc=80, current_a=None, started_at=datetime.now(TZ))
    assert ManualCharge.from_dict(json.loads(json.dumps(manual.to_dict()))) == manual
