"""universal-load-balancing 6.1: ExecutorEngine.get_load_balancer_status() payload."""

from unittest.mock import MagicMock, patch

import pytest

from executor.config import ControllerConfig, InverterConfig
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
            assert ev["setpoint_a"] == 10
            assert ev["planned_target_a"] == 16
            assert ev["state"] == state
            assert ev["reason"] == "ev reason"

            assert len(payload["shed"]) == 1
            shed = payload["shed"][0]
            assert shed["load_id"] == "wh"
            assert shed["device_type"] == "water_heater"
            assert shed["shed"] == (state == "shedding")
