"""universal-load-balancing 6.1: ExecutorEngine.get_load_balancer_status() payload."""

from unittest.mock import MagicMock, patch

import pytest

from executor.config import ControllerConfig, EVChargerDeviceConfig, InverterConfig
from executor.engine import ExecutorEngine
from executor.load_balancer import EVBalancerOutput, LoadBalancerStatus, ShedLoadOutput


@pytest.fixture
def engine():
    with (
        patch("executor.engine.load_executor_config") as mock_load,
        patch("executor.engine.load_yaml") as mock_yaml,
        patch("executor.engine.ExecutionHistory"),
        patch("executor.engine.LoadDisaggregator"),
    ):
        mock_load.return_value = MagicMock(
            enabled=True,
            shadow_mode=False,
            timezone="Europe/Stockholm",
            controller=ControllerConfig(),
            inverter=InverterConfig(),
            water_heater=None,
            ev_chargers=[],
            load_balancing=MagicMock(
                enabled=False, main_fuse_a=None, loads=[], resume_margin_percent=90.0
            ),
        )
        mock_yaml.return_value = {
            "system": {"has_solar": True, "has_battery": True, "has_ev_charger": False},
            "ev_chargers": [],
            "water_heaters": [],
        }
        return ExecutorEngine()


class TestDisabledPayload:
    def test_no_status_yet_returns_disabled_shape(self, engine):
        payload = engine.get_load_balancer_status()

        assert payload["enabled"] is False
        assert payload["state"] == "disabled"
        assert payload["main_fuse_a"] is None
        assert payload["resume_margin_percent"] == 90.0
        assert payload["phase_current_a"] == {}
        assert payload["phase_headroom_a"] == {}
        assert payload["ev"] == []
        assert payload["shed"] == []

    def test_explicit_disabled_status(self, engine):
        engine._last_balancer_status = LoadBalancerStatus(
            enabled=False,
            state="disabled",
            reason="Load balancing disabled or unconfigured",
            main_fuse_a=None,
            phase_current_a={},
            phase_headroom_a={},
        )
        payload = engine.get_load_balancer_status()
        assert payload["enabled"] is False
        assert payload["state"] == "disabled"
        assert payload["resume_margin_percent"] == 90.0


class TestEnabledPayload:
    def test_all_fields_present_for_each_state(self, engine):
        for state in ("idle", "throttling", "shedding", "paused", "stale_fallback"):
            engine._last_balancer_status = LoadBalancerStatus(
                enabled=True,
                state=state,
                reason=f"reason for {state}",
                main_fuse_a=20,
                phase_current_a={1: 18.0, 2: 5.0, 3: 5.0},
                phase_headroom_a={1: 2.0, 2: 15.0, 3: 15.0},
                ev_outputs=[
                    EVBalancerOutput("goe", target_a=10, state=state, reason="ev reason")
                ],
                shed_outputs=[
                    ShedLoadOutput("wh", "water_heater", shed=(state == "shedding"), reason="")
                ],
            )
            engine._last_balancer_planned_targets = {"goe": 16}

            payload = engine.get_load_balancer_status()

            assert payload["enabled"] is True
            assert payload["state"] == state
            assert payload["reason"] == f"reason for {state}"
            assert payload["main_fuse_a"] == 20
            assert payload["resume_margin_percent"] == 90.0
            assert payload["phase_current_a"] == {1: 18.0, 2: 5.0, 3: 5.0}
            assert payload["phase_headroom_a"] == {1: 2.0, 2: 15.0, 3: 15.0}

            assert len(payload["ev"]) == 1
            ev = payload["ev"][0]
            assert ev["charger_id"] == "goe"
            assert ev["charger_name"] == "goe"  # no configured name -> falls back to id
            assert ev["setpoint_a"] == 10
            assert ev["planned_target_a"] == 16
            assert ev["state"] == state
            assert ev["reason"] == "ev reason"

            assert len(payload["shed"]) == 1
            shed = payload["shed"][0]
            assert shed["load_id"] == "wh"
            assert shed["device_type"] == "water_heater"
            assert shed["shed"] == (state == "shedding")

    def test_charger_name_resolved_from_config(self, engine):
        engine.config.ev_chargers = [
            EVChargerDeviceConfig(id="goe", name="Garage EV", type="current")
        ]
        engine._last_balancer_status = LoadBalancerStatus(
            enabled=True,
            state="throttling",
            reason="reason",
            main_fuse_a=20,
            phase_current_a={1: 18.0, 2: 5.0, 3: 5.0},
            phase_headroom_a={1: 2.0, 2: 15.0, 3: 15.0},
            ev_outputs=[EVBalancerOutput("goe", target_a=10, state="throttling", reason="")],
        )
        engine._last_balancer_planned_targets = {"goe": 16}

        payload = engine.get_load_balancer_status()
        assert payload["ev"][0]["charger_name"] == "Garage EV"


class TestSurplusModeFields:
    """excess-pv-priority-dispatch 4.1: additive surplus-mode status fields."""

    def test_surplus_fields_default_absent(self, engine):
        payload = engine.get_load_balancer_status()
        assert payload["measured_surplus_kw"] is None
        assert payload["ev"] == []

    def test_surplus_charger_surfaces_even_when_balancer_disabled(self, engine):
        """Fuse balancer disabled, but a surplus-eligible charger must still
        appear in the status payload (design D7)."""
        engine._last_measured_surplus_kw = 2.5
        engine._ev_surplus_status = {"goe": {"state": "charging", "reason": "within floor"}}
        engine._ev_charger_states["goe"] = MagicMock(current_setpoint_a=8)

        payload = engine.get_load_balancer_status()

        assert payload["enabled"] is False
        assert payload["measured_surplus_kw"] == 2.5
        assert len(payload["ev"]) == 1
        ev = payload["ev"][0]
        assert ev["charger_id"] == "goe"
        assert ev["surplus_mode"] is True
        assert ev["surplus_state"] == "charging"
        assert ev["surplus_reason"] == "within floor"
        assert ev["setpoint_a"] == 8
        assert ev["paused"] is False

    def test_paused_surplus_charger_flagged(self, engine):
        engine._ev_surplus_status = {"goe": {"state": "paused", "reason": "insufficient surplus"}}

        payload = engine.get_load_balancer_status()

        assert payload["ev"][0]["paused"] is True

    def test_phase_mode_reported(self, engine):
        from executor.ev_surplus import PhaseModeController

        ctrl = PhaseModeController()
        ctrl.commanded_mode = 1
        engine._ev_phase_controllers = {"goe": ctrl}

        payload = engine.get_load_balancer_status()

        assert payload["ev"][0]["charger_id"] == "goe"
        assert payload["ev"][0]["phase_mode"] == 1
        assert payload["ev"][0]["surplus_mode"] is False

    def test_balancer_output_and_surplus_fields_coexist(self, engine):
        """When the fuse balancer IS enabled and also throttling a
        surplus-eligible charger, both sets of fields are present together."""
        engine._last_balancer_status = LoadBalancerStatus(
            enabled=True,
            state="throttling",
            reason="reason",
            main_fuse_a=20,
            phase_current_a={1: 18.0, 2: 5.0, 3: 5.0},
            phase_headroom_a={1: 2.0, 2: 15.0, 3: 15.0},
            ev_outputs=[EVBalancerOutput("goe", target_a=7, state="throttling", reason="capped")],
        )
        engine._ev_surplus_status = {"goe": {"state": "charging", "reason": "within floor"}}

        payload = engine.get_load_balancer_status()

        assert len(payload["ev"]) == 1
        ev = payload["ev"][0]
        assert ev["setpoint_a"] == 7  # balancer output wins over dev_state
        assert ev["state"] == "throttling"
        assert ev["surplus_mode"] is True
        assert ev["surplus_state"] == "charging"
