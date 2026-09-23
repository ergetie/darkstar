"""ev-measured-draw-baseline: measured EV draw, effective baseline, and its use
by surplus feedback, the load balancer and the status payload."""

import contextlib
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine

from backend.learning.models import Base
from executor.config import EVChargerDeviceConfig, ExecutorConfig, LoadBalancingConfig
from executor.engine import EV_DRAW_SETTLE_S, EVChargerState, ExecutorEngine
from executor.ev_surplus import EVSurplusController, PhaseModeController
from executor.load_balancer import EVBalancerInput, EVBalancerOutput, LoadBalancer

NOW = datetime(2026, 9, 23, 12, 0, 0)
SETTLED = NOW - timedelta(seconds=60)


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


def charger(**overrides) -> EVChargerDeviceConfig:
    params = {
        "id": "goe",
        "type": "current",
        "current_entity": "number.goe_current",
        "switch_entity": "select.goe_frc",
        "min_current_a": 6,
        "max_current_a": 16,
        "phases": [1, 2, 3],
    }
    params.update(overrides)
    return EVChargerDeviceConfig(**params)


def make_engine(temp_schedule, temp_db, charger_cfg: EVChargerDeviceConfig) -> ExecutorEngine:
    with patch("executor.engine.load_executor_config") as mock_config:
        mock_config.return_value = ExecutorConfig(
            schedule_path=temp_schedule,
            timezone="Europe/Stockholm",
            ev_chargers=[charger_cfg],
        )
        with patch("executor.engine.load_yaml") as mock_yaml:
            mock_yaml.return_value = {}
            with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                eng = ExecutorEngine("config.yaml")
                eng._has_ev_charger = True
                return eng


def set_ev_power(eng: ExecutorEngine, charger_id: str, kw: float, healthy: bool = True) -> None:
    load = MagicMock(current_power_kw=kw, is_healthy=healthy)
    eng._load_disaggregator = MagicMock()
    eng._load_disaggregator.get_load_by_id = MagicMock(
        side_effect=lambda lid: load if lid == charger_id else None
    )


class TestMeasuredDraw:
    """4.1: source order per-phase sensors -> total power -> None."""

    @pytest.mark.asyncio
    async def test_total_power_three_phase(self, temp_schedule, temp_db):
        eng = make_engine(temp_schedule, temp_db, charger())
        eng.ha_client = AsyncMock()
        set_ev_power(eng, "goe", 6.9)
        dev_state = EVChargerState()

        await eng._update_ev_measured_draw(
            eng.config.ev_chargers[0], dev_state, PhaseModeController()
        )

        assert dev_state.measured_draw_a == pytest.approx(10.0)

    @pytest.mark.asyncio
    async def test_per_phase_sensors_take_precedence(self, temp_schedule, temp_db):
        cfg = charger(
            phase_sensor_l1="sensor.l1", phase_sensor_l2="sensor.l2", phase_sensor_l3="sensor.l3"
        )
        eng = make_engine(temp_schedule, temp_db, cfg)
        readings = {"sensor.l1": "9", "sensor.l2": "10", "sensor.l3": "9.5"}
        eng.ha_client = AsyncMock()
        eng.ha_client.get_state = AsyncMock(
            side_effect=lambda e: {
                "state": readings[e],
                "attributes": {"unit_of_measurement": "A"},
            }
        )
        set_ev_power(eng, "goe", 11.0)
        dev_state = EVChargerState()

        await eng._update_ev_measured_draw(cfg, dev_state, PhaseModeController())

        assert dev_state.measured_draw_a == pytest.approx(10.0)
        assert dev_state.active_phases == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_per_phase_watts_converted(self, temp_schedule, temp_db):
        cfg = charger(phase_sensor_l1="sensor.l1")
        eng = make_engine(temp_schedule, temp_db, cfg)
        eng.ha_client = AsyncMock()
        eng.ha_client.get_state = AsyncMock(
            return_value={"state": "2300", "attributes": {"unit_of_measurement": "W"}}
        )
        dev_state = EVChargerState()

        await eng._update_ev_measured_draw(cfg, dev_state, PhaseModeController())

        assert dev_state.measured_draw_a == pytest.approx(10.0)

    @pytest.mark.asyncio
    async def test_sensor_unavailable_is_none(self, temp_schedule, temp_db):
        eng = make_engine(temp_schedule, temp_db, charger())
        eng.ha_client = AsyncMock()
        set_ev_power(eng, "goe", 0.0, healthy=False)
        dev_state = EVChargerState(measured_draw_a=8.0)

        await eng._update_ev_measured_draw(
            eng.config.ev_chargers[0], dev_state, PhaseModeController()
        )

        assert dev_state.measured_draw_a is None

    @pytest.mark.asyncio
    async def test_fail_safe_is_none(self, temp_schedule, temp_db):
        eng = make_engine(temp_schedule, temp_db, charger())
        eng.ha_client = AsyncMock()
        set_ev_power(eng, "goe", 6.9)
        eng._ev_power_fetch_failed = True
        dev_state = EVChargerState()

        await eng._update_ev_measured_draw(
            eng.config.ev_chargers[0], dev_state, PhaseModeController()
        )

        assert dev_state.measured_draw_a is None


class TestEffectiveBaseline:
    """4.2: max(min_current_a, min(setpoint, measured)) once settled."""

    cfg = charger()

    def _baseline(self, setpoint, measured, changed_at=SETTLED):
        state = EVChargerState(
            current_setpoint_a=setpoint, measured_draw_a=measured, setpoint_changed_at=changed_at
        )
        return ExecutorEngine._effective_baseline_a(self.cfg, state, NOW)

    def test_car_below_setpoint(self):
        assert self._baseline(16, 10.0) == 10

    def test_inside_settle_window_uses_setpoint(self):
        changed_at = NOW - timedelta(seconds=EV_DRAW_SETTLE_S - 20)
        assert self._baseline(6, 0.0, changed_at) == 6

    def test_measurement_above_setpoint_never_raises(self):
        assert self._baseline(10, 10.4) == 10

    def test_no_measurement_uses_setpoint(self):
        assert self._baseline(16, None) == 16

    def test_below_floor_clamps_to_min_current(self):
        assert self._baseline(16, 3.0) == 6

    def test_not_charging_is_none(self):
        assert self._baseline(None, 10.0) is None


def surplus_tick(ctrl, surplus_kw, setpoint, baseline=None):
    return ctrl.tick(
        now=NOW,
        surplus_kw=surplus_kw,
        deadband_kw=0.2,
        current_setpoint_a=setpoint,
        min_current_a=6,
        max_current_a=16,
        active_phase_count=3,
        increase_step_a=1,
        resume_delay_s=120,
        resume_margin_percent=90,
        phase_switch_can_lower_floor=False,
        baseline_a=baseline,
    )


class TestSurplusUsesBaseline:
    """4.3: reductions act on the actual draw."""

    def test_reduction_from_measured_draw(self):
        result = surplus_tick(EVSurplusController(), -2.07, setpoint=16, baseline=10)
        assert result.target_a == 7

    def test_without_measurement_unchanged(self):
        result = surplus_tick(EVSurplusController(), -2.07, setpoint=16)
        assert result.target_a == 13

    def test_deadband_holds_commanded_setpoint(self):
        result = surplus_tick(EVSurplusController(), 0.1, setpoint=16, baseline=10)
        assert result.target_a == 16

    @pytest.mark.asyncio
    async def test_engine_passes_effective_baseline(self, temp_schedule, temp_db):
        eng = make_engine(temp_schedule, temp_db, charger())
        eng.ha_client = AsyncMock()
        set_ev_power(eng, "goe", 6.9)  # 10 A on 3 phases
        eng._ev_charger_states["goe"] = EVChargerState(
            current_setpoint_a=16, setpoint_changed_at=SETTLED
        )
        eng.config.excess_pv.priority = [
            MagicMock(type="ev", charger_id="goe", surplus_deadband_kw=0.2)
        ]
        slot = MagicMock(ev_surplus_kw={"goe": 1.0}, ev_charger_plans={})
        state = MagicMock(current_export_kw=0.0, current_import_kw=2.07)

        await eng._update_ev_surplus_and_phase_mode(state, slot, NOW)

        assert eng._ev_surplus_targets["goe"] == 7


def make_lb() -> LoadBalancer:
    return LoadBalancer(
        LoadBalancingConfig(
            enabled=True,
            main_fuse_a=20,
            resume_delay_s=120,
            resume_margin_percent=90,
            increase_step_a=1,
            sensor_stale_after_s=30,
        )
    )


class TestBalancerUsesBaseline:
    """4.4: reduction and pool relief computed from the effective draw."""

    def test_reduction_and_relief_from_measured_draw(self):
        lb = make_lb()
        # L1 at 24 A -> headroom -4 A. Car A: setpoint 16, drawing 10.
        ev_a = EVBalancerInput("a", [1], 16, 16, 6, 16, effective_draw_a=10)
        ev_b = EVBalancerInput("b", [1], 10, 10, 6, 16)
        grid = {1: 24.0, 2: 5.0, 3: 5.0}
        status = lb.tick(NOW, grid, dict.fromkeys((1, 2, 3), NOW), [ev_a, ev_b])

        out = {o.charger_id: o for o in status.ev_outputs}
        assert out["a"].target_a is not None and out["a"].target_a <= 6
        # Relief from A is 10 - 6 = 4 A, exactly covering the deficit: B untouched.
        assert out["b"].target_a == 10

    def test_relief_not_inflated_by_setpoint(self):
        lb = make_lb()
        # Headroom -2 A. A (setpoint 16, drawing 10) drops to 8 A: real relief
        # is 2 A, leaving 0 A for B, which must not start. Setpoint-based
        # accounting would claim 8 A relief and let B start at 6 A.
        ev_a = EVBalancerInput("a", [1], 16, 16, 6, 16, effective_draw_a=10)
        ev_b = EVBalancerInput("b", [1], None, 6, 6, 16)
        grid = {1: 22.0, 2: 5.0, 3: 5.0}
        status = lb.tick(NOW, grid, dict.fromkeys((1, 2, 3), NOW), [ev_a, ev_b])

        out = {o.charger_id: o for o in status.ev_outputs}
        assert out["a"].target_a == 8
        assert out["b"].target_a is None

    def test_default_effective_draw_is_setpoint(self):
        ev = EVBalancerInput("a", [1], 16, 16, 6, 16)
        assert ev.effective_draw_a == 16


class TestStatusPayload:
    """4.5 (backend half): measured_a per charger."""

    def test_measured_a_in_payload(self, temp_schedule, temp_db):
        eng = make_engine(temp_schedule, temp_db, charger())
        eng._last_balancer_status = MagicMock(
            enabled=False,
            reason="disabled",
            main_fuse_a=None,
            ev_outputs=[EVBalancerOutput("goe", 16, "idle")],
        )
        eng._ev_charger_states["goe"] = EVChargerState(current_setpoint_a=16, measured_draw_a=10.04)

        payload = eng.get_load_balancer_status()

        assert payload["ev"][0]["measured_a"] == 10.0

    def test_measured_a_null_without_measurement(self, temp_schedule, temp_db):
        eng = make_engine(temp_schedule, temp_db, charger())
        eng._last_balancer_status = MagicMock(
            enabled=False,
            reason="disabled",
            main_fuse_a=None,
            ev_outputs=[EVBalancerOutput("goe", 16, "idle")],
        )
        eng._ev_charger_states["goe"] = EVChargerState(current_setpoint_a=16)

        payload = eng.get_load_balancer_status()

        assert payload["ev"][0]["measured_a"] is None
