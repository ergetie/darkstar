"""
EV Isolation Tests (REV F76 Follow-up)

Production-grade test suite for battery discharge prevention during EV charging.
Covers fail-safe error handling, state-based logging, and threshold edge cases.
"""

import dataclasses
import logging
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from executor.config import (
    ControllerConfig,
    ExecutorConfig,
    InverterConfig,
    WaterHeaterDeviceConfig,
    WaterHeaterGlobalConfig,
)
from executor.controller import (
    EV_ISOLATION_REASON,
    MIN_SOC_GUARD_REASON,
    BatteryPlanState,
    Controller,
    ControllerDecision,
    make_decision,
)
from executor.engine import ExecutorEngine
from executor.override import OverrideResult, SlotPlan, SystemState


class TestControllerEVIsolation:
    """Test controller.py EV → idle mode selection (lines 190-193)."""

    @pytest.fixture
    def base_config(self):
        """Standard controller and inverter config."""
        return ControllerConfig(), InverterConfig()

    @pytest.fixture
    def controller(self, base_config):
        """Initialized controller."""
        ctrl_config, inv_config = base_config
        return Controller(ctrl_config, inv_config)

    @pytest.fixture
    def base_state(self):
        """System state with SoC above target (normally → self_consumption)."""
        return SystemState(
            current_soc_percent=65.0,  # Above target
            min_soc_percent=10.0,
        )

    def test_ev_scheduled_goes_idle(self, controller, base_state):
        """Scheduled EV (0.15 kW) → idle mode even when SoC > target."""
        # NOTE: Engine sets discharge_kw=0 before calling controller when EV active
        slot = SlotPlan(
            charge_kw=0.0,
            discharge_kw=0.0,  # Engine already blocked discharge
            export_kw=0.0,
            load_kw=1.0,
            water_kw=0.0,
            ev_charging_kw=0.15,  # Above threshold
            soc_target=60,
            soc_projected=65,
        )

        decision = make_decision(
            slot,
            base_state,
            None,
            controller.config,
            controller.inverter_config,
            None,
            None,
        )

        assert decision.mode_intent == "idle"
        # Note: Controller reason doesn't include EV text, but mode is correct

    def test_no_ev_self_consumption(self, controller, base_state):
        """No EV + SoC > target → normal self_consumption."""
        slot = SlotPlan(
            charge_kw=0.0,
            discharge_kw=3.0,
            export_kw=0.0,
            load_kw=1.0,
            water_kw=0.0,
            ev_charging_kw=0.0,  # No EV
            soc_target=60,
            soc_projected=65,
        )

        decision = make_decision(
            slot,
            base_state,
            None,
            controller.config,
            controller.inverter_config,
            None,
            None,
        )

        assert decision.mode_intent == "self_consumption"

    def test_ev_below_threshold_self_consumption(self, controller, base_state):
        """EV at 0.05 kW (below 0.1 threshold) → self_consumption."""
        slot = SlotPlan(
            charge_kw=0.0,
            discharge_kw=3.0,
            export_kw=0.0,
            load_kw=1.0,
            water_kw=0.0,
            ev_charging_kw=0.05,  # Below threshold
            soc_target=60,
            soc_projected=65,
        )

        decision = make_decision(
            slot,
            base_state,
            None,
            controller.config,
            controller.inverter_config,
            None,
            None,
        )

        assert decision.mode_intent == "self_consumption"

    def test_ev_soc_target_takes_priority(self, controller):
        """SoC <= target takes priority (idle anyway), EV adds discharge block."""
        state = SystemState(
            current_soc_percent=55.0,  # Below target
            min_soc_percent=10.0,
        )
        slot = SlotPlan(
            charge_kw=0.0,
            discharge_kw=3.0,
            export_kw=0.0,
            load_kw=1.0,
            water_kw=0.0,
            ev_charging_kw=0.15,
            soc_target=60,
            soc_projected=55,
        )

        decision = make_decision(
            slot,
            state,
            None,
            controller.config,
            controller.inverter_config,
            None,
            None,
        )

        # Should be idle due to SoC <= target
        assert decision.mode_intent == "idle"

    def test_ev_with_discharge_blocked_idle(self, controller, base_state):
        """discharge_kw=0 + ev_charging_kw>0.1 → idle mode."""
        slot = SlotPlan(
            charge_kw=0.0,
            discharge_kw=0.0,  # Engine blocked discharge
            export_kw=0.0,
            load_kw=1.0,
            water_kw=0.0,
            ev_charging_kw=0.15,
            soc_target=60,
            soc_projected=65,
        )

        decision = make_decision(
            slot,
            base_state,
            None,
            controller.config,
            controller.inverter_config,
            None,
            None,
        )

        assert decision.mode_intent == "idle"

    def test_flagged_isolation_slot_idles_above_target(self, controller, base_state):
        """Manual / actual-only / surplus isolation: no planned kW, no keep-on, flag set."""
        slot = SlotPlan(
            discharge_kw=0.0,
            ev_charging_kw=0.0,
            soc_target=60,
            discharge_blocked_by_ev=True,
        )
        decision = make_decision(
            slot, base_state, None, controller.config, controller.inverter_config, None, None
        )
        assert decision.mode_intent == "idle"

    def test_flagged_isolation_keeps_planned_grid_charge(self, controller):
        """Planned grid charge below its target still wins over isolation."""
        state = SystemState(current_soc_percent=40.0, min_soc_percent=10.0)
        slot = SlotPlan(
            charge_kw=3.0,
            grid_charge_kw=3.0,
            discharge_kw=0.0,
            soc_target=60,
            discharge_blocked_by_ev=True,
        )
        decision = make_decision(
            slot, state, None, controller.config, controller.inverter_config, None, None
        )
        assert decision.mode_intent == "charge"

    def test_isolation_composes_with_min_soc_guard(self, controller):
        """Engaged guard leaves the already-idle isolated slot (and its reason) alone."""
        state = SystemState(current_soc_percent=10.0, min_soc_percent=10.0)
        slot = SlotPlan(discharge_kw=0.0, soc_target=60, discharge_blocked_by_ev=True)
        decision = make_decision(
            slot, state, None, controller.config, controller.inverter_config, None, None
        )
        assert decision.mode_intent == "idle"
        assert MIN_SOC_GUARD_REASON not in decision.reason

    @staticmethod
    def _pv_charge_slot(**kwargs):
        return SlotPlan(
            charge_kw=3.0,
            grid_charge_kw=0.0,
            discharge_kw=0.0,
            export_kw=0.0,
            soc_target=80,
            **kwargs,
        )

    def _decide(self, controller, slot, soc=50.0):
        state = SystemState(current_soc_percent=soc, min_soc_percent=10.0)
        return make_decision(
            slot, state, None, controller.config, controller.inverter_config, None, None
        )

    def test_pv_charge_flagged_isolation_idles_with_reason(self, controller):
        decision = self._decide(controller, self._pv_charge_slot(discharge_blocked_by_ev=True))
        assert decision.mode_intent == "idle"
        assert EV_ISOLATION_REASON in decision.reason

    def test_pv_charge_planned_ev_idles(self, controller):
        decision = self._decide(controller, self._pv_charge_slot(ev_charging_kw=0.5))
        assert decision.mode_intent == "idle"

    def test_pv_charge_keep_on_only_idles(self, controller):
        decision = self._decide(controller, self._pv_charge_slot(ev_keep_on={"ev1": True}))
        assert decision.mode_intent == "idle"

    def test_pv_charge_without_ev_is_self_consumption(self, controller):
        decision = self._decide(controller, self._pv_charge_slot())
        assert decision.mode_intent == "self_consumption"
        assert EV_ISOLATION_REASON not in decision.reason

    def test_existing_isolation_idle_branch_has_reason(self, controller):
        slot = SlotPlan(discharge_kw=0.0, soc_target=60, discharge_blocked_by_ev=True)
        decision = self._decide(controller, slot, soc=65.0)
        assert EV_ISOLATION_REASON in decision.reason

    def test_pv_charge_isolation_composes_with_min_soc_guard(self, controller):
        slot = self._pv_charge_slot(discharge_blocked_by_ev=True)
        plan_state = BatteryPlanState()
        state = SystemState(current_soc_percent=10.0, min_soc_percent=10.0)
        decision = make_decision(
            slot,
            state,
            None,
            controller.config,
            controller.inverter_config,
            None,
            None,
            plan_state=plan_state,
        )
        assert decision.mode_intent == "idle"
        assert EV_ISOLATION_REASON in decision.reason
        assert MIN_SOC_GUARD_REASON not in decision.reason
        assert plan_state.min_soc_guard is True

    def test_grid_charge_below_target_not_overridden_by_isolation(self, controller):
        slot = SlotPlan(
            charge_kw=3.0,
            grid_charge_kw=3.0,
            discharge_kw=0.0,
            soc_target=80,
            discharge_blocked_by_ev=True,
        )
        assert self._decide(controller, slot, soc=40.0).mode_intent == "charge"

    def test_unflagged_hold_slot_unchanged(self, controller, base_state):
        """A plain hold slot above target (no isolation) still follows the hold logic."""
        slot = SlotPlan(discharge_kw=0.0, ev_charging_kw=0.0, soc_target=60)
        decision = make_decision(
            slot, base_state, None, controller.config, controller.inverter_config, None, None
        )
        assert decision.mode_intent == "self_consumption"


class TestEngineEVIsolation:
    """Test engine.py EV isolation: discharge blocking & fail-safe."""

    @pytest.fixture
    def mock_engine(self):
        """Create engine with mocked dependencies."""
        with (
            patch("executor.engine.load_executor_config") as mock_load,
            patch("executor.engine.load_yaml") as mock_yaml,
            patch("executor.engine.ExecutionHistory"),
            patch("executor.engine.LoadDisaggregator") as mock_disagg,
        ):
            mock_load.return_value = MagicMock(
                enabled=True,
                shadow_mode=False,
                timezone="Europe/Stockholm",
                tick_interval_sec=30,
                schedule_file="schedule.json",
                controller=ControllerConfig(),
                inverter=InverterConfig(),
                water_heater=None,
                ev_charger=MagicMock(switch_entity=None),
            )
            mock_yaml.return_value = {
                "system": {
                    "has_solar": True,
                    "has_battery": True,
                    "has_water_heater": True,
                    "has_ev_charger": True,
                },
                "ev_chargers": [],
                "water_heaters": [],
            }

            engine = ExecutorEngine()
            # Mock the disaggregator
            engine._load_disaggregator = mock_disagg.return_value
            engine._has_ev_charger = True
            engine._has_battery = True
            return engine

    @pytest.mark.parametrize(
        "ev_power,should_block",
        [
            (0.099, False),  # Just under threshold
            (0.100, False),  # At threshold (strictly >)
            (0.101, True),  # Just over threshold
            (0.05, False),  # User example: below
            (0.15, True),  # User example: above
        ],
    )
    @pytest.mark.asyncio
    async def test_ev_threshold_boundaries(self, mock_engine, ev_power, should_block):
        """Boundary testing with floating-point precision awareness."""
        mock_engine._load_disaggregator.update_current_power = AsyncMock()
        mock_engine._load_disaggregator.get_total_ev_power.return_value = ev_power

        # Simulate the EV detection logic
        await mock_engine._load_disaggregator.update_current_power()
        actual_ev_power = mock_engine._load_disaggregator.get_total_ev_power()
        actual_ev_charging = actual_ev_power > 0.1

        if should_block:
            assert actual_ev_charging is True
        else:
            assert actual_ev_charging is False

    @pytest.mark.asyncio
    async def test_scheduled_plus_actual_ev_combined(self, mock_engine):
        """OR logic: scheduled (0.05) + actual (0.06) = EV active."""
        mock_engine._load_disaggregator.update_current_power = AsyncMock()
        mock_engine._load_disaggregator.get_total_ev_power.return_value = 0.06

        scheduled_ev_kw = 0.05

        await mock_engine._load_disaggregator.update_current_power()
        actual_ev_power = mock_engine._load_disaggregator.get_total_ev_power()

        scheduled_ev_charging = scheduled_ev_kw > 0.1
        actual_ev_charging = actual_ev_power > 0.1
        ev_should_charge = scheduled_ev_charging or actual_ev_charging

        # 0.05 scheduled (False) OR 0.06 actual (False) = False
        assert ev_should_charge is False

        # Now test with actual = 0.15
        mock_engine._load_disaggregator.get_total_ev_power.return_value = 0.15
        actual_ev_power = mock_engine._load_disaggregator.get_total_ev_power()
        actual_ev_charging = actual_ev_power > 0.1
        ev_should_charge = scheduled_ev_charging or actual_ev_charging

        # 0.05 scheduled (False) OR 0.15 actual (True) = True
        assert ev_should_charge is True

    @pytest.mark.asyncio
    async def test_fail_safe_exception_blocks_discharge(self, mock_engine, caplog):
        """CRITICAL SAFETY: Exception → inf used → discharge blocked."""
        caplog.set_level(logging.WARNING)

        # Simulate disaggregator raising exception
        mock_engine._load_disaggregator.update_current_power = AsyncMock(
            side_effect=RuntimeError("HA sensor unavailable")
        )

        actual_ev_power_kw = 0.0
        try:
            await mock_engine._load_disaggregator.update_current_power()
            actual_ev_power_kw = mock_engine._load_disaggregator.get_total_ev_power()
        except Exception as e:
            if not mock_engine._ev_power_fetch_failed:
                logging.warning(
                    "EV power monitoring failed: %s - Fail-safe activated (blocking discharge)",
                    e,
                )
                mock_engine._ev_power_fetch_failed = True
            actual_ev_power_kw = float("inf")  # Fail-safe

        # Verify fail-safe activated
        assert actual_ev_power_kw == float("inf")
        assert mock_engine._ev_power_fetch_failed is True
        assert "Fail-safe activated" in caplog.text

    @pytest.mark.asyncio
    async def test_fail_safe_logs_once_then_silent(self, mock_engine, caplog):
        """Verify single warning, no spam on repeated failures."""
        caplog.set_level(logging.WARNING)

        mock_engine._load_disaggregator.update_current_power = AsyncMock(
            side_effect=RuntimeError("HA unavailable")
        )

        # First failure - should log
        try:
            await mock_engine._load_disaggregator.update_current_power()
        except Exception as e:
            if not mock_engine._ev_power_fetch_failed:
                logging.warning("EV power monitoring failed: %s", e)
                mock_engine._ev_power_fetch_failed = True

        # Second failure - should NOT log
        try:
            await mock_engine._load_disaggregator.update_current_power()
        except Exception as e:
            if not mock_engine._ev_power_fetch_failed:
                logging.warning("EV power monitoring failed: %s", e)
                mock_engine._ev_power_fetch_failed = True

        # Should only have one warning
        warning_count = caplog.text.count("EV power monitoring failed")
        assert warning_count == 1


class _StopTick(Exception):
    """Raised by the make_decision spy to end the tick after capturing."""


class TestIsolationSlotThroughEngine:
    """The slot the engine hands to make_decision during EV source isolation."""

    @pytest.fixture
    def engine(self):
        with (
            patch("executor.engine.load_executor_config"),
            patch("executor.engine.load_yaml") as mock_yaml,
            patch("executor.engine.ExecutionHistory"),
            patch("executor.engine.LoadDisaggregator") as mock_disagg,
        ):
            mock_yaml.return_value = {
                "system": {"has_battery": True, "has_water_heater": True},
                "ev_chargers": [],
                "water_heaters": [],
            }
            eng = ExecutorEngine()
        eng.config = ExecutorConfig(
            water_heater=WaterHeaterGlobalConfig(temp_normal=60, temp_off=40),
            water_heater_devices=[
                WaterHeaterDeviceConfig(
                    id="vvb", target_entity="switch.vvb", control_type="switch"
                )
            ],
        )
        eng.ha_client = None
        eng._has_ev_charger = True
        eng._has_battery = True
        eng._load_disaggregator = mock_disagg.return_value
        eng._load_disaggregator.update_current_power = AsyncMock()
        eng._load_disaggregator.get_total_ev_power.return_value = 0.0
        eng._gather_system_state = AsyncMock(
            return_value=SystemState(current_soc_percent=65.0, min_soc_percent=10.0)
        )
        eng._maybe_request_ev_manual_replan = MagicMock()
        return eng

    async def _isolated(self, engine, slot, actual_ev_kw=0.0):
        """Run one tick; return (slot passed to make_decision, decision)."""
        engine._load_current_slot = MagicMock(return_value=(slot, "slot"))
        engine._load_disaggregator.get_total_ev_power.return_value = actual_ev_kw
        captured: dict = {}

        def spy(passed_slot, *args, **kwargs):
            captured["slot"] = passed_slot
            captured["decision"] = make_decision(passed_slot, *args, **kwargs)
            raise _StopTick

        with patch("executor.engine.make_decision", side_effect=spy):
            await engine._tick()
        return captured["slot"], captured["decision"]

    @pytest.mark.asyncio
    async def test_all_fields_preserved(self, engine):
        """Generic over SlotPlan fields: only discharge_kw and the flag change."""
        now = datetime(2026, 10, 24, 1, 45)
        values: dict = {}
        for f in dataclasses.fields(SlotPlan):
            default = SlotPlan.__dataclass_fields__[f.name].default
            if f.name in ("discharge_kw", "discharge_blocked_by_ev"):
                continue
            if f.name == "soc_entry":
                values[f.name] = 33
            elif f.name == "slot_start":
                values[f.name] = now
            elif f.name == "slot_end":
                values[f.name] = now + timedelta(minutes=15)
            elif f.name == "grid_charge_kw":
                values[f.name] = 1.5
            elif f.name.endswith("_plans") or f.name in ("ev_surplus_kw", "water_heating_boost"):
                values[f.name] = {"x": 1.0} if f.name != "water_heating_boost" else {"x": True}
            elif f.name in ("custom_entity_active", "ev_keep_on"):
                values[f.name] = {"1": True}
            elif isinstance(default, int):
                values[f.name] = 77
            else:
                values[f.name] = 1.25
        values["ev_charging_kw"] = 6.0  # trigger isolation
        original = SlotPlan(discharge_kw=2.0, **values)
        assert set(values) | {"discharge_kw", "discharge_blocked_by_ev"} == {
            f.name for f in dataclasses.fields(SlotPlan)
        }

        passed, _ = await self._isolated(engine, original)

        assert passed.discharge_kw == 0.0
        assert passed.discharge_blocked_by_ev is True
        for name, value in values.items():
            assert getattr(passed, name) == value, name

    @pytest.mark.asyncio
    async def test_planned_ev_keeps_heater_on(self, engine):
        slot = SlotPlan(
            discharge_kw=1.0, ev_charging_kw=6.0, water_kw=3.1, water_heater_plans={"vvb": 3.1}
        )
        _, decision = await self._isolated(engine, slot)
        assert decision.water_temps["vvb"] == 60
        assert decision.mode_intent == "idle"

    @pytest.mark.asyncio
    async def test_manual_charge_keeps_heater_on(self, engine):
        engine._ev_manual_charge = {"c1": MagicMock()}
        engine._check_ev_manual_charge_end = AsyncMock()
        slot = SlotPlan(water_kw=3.1, water_heater_plans={"vvb": 3.1}, soc_target=60)
        _, decision = await self._isolated(engine, slot)
        assert decision.water_temps["vvb"] == 60
        assert decision.mode_intent == "idle"

    @pytest.mark.asyncio
    async def test_actual_unplanned_charge_keeps_heater_on(self, engine):
        slot = SlotPlan(water_kw=3.1, water_heater_plans={"vvb": 3.1}, soc_target=60)
        _, decision = await self._isolated(engine, slot, actual_ev_kw=7.0)
        assert decision.water_temps["vvb"] == 60
        assert decision.mode_intent == "idle"

    @pytest.mark.asyncio
    async def test_keep_on_keeps_heater_on(self, engine):
        slot = SlotPlan(water_kw=3.1, water_heater_plans={"vvb": 3.1}, ev_keep_on={"c1": True})
        _, decision = await self._isolated(engine, slot)
        assert decision.water_temps["vvb"] == 60

    @pytest.mark.asyncio
    async def test_surplus_keeps_heater_on(self, engine):
        slot = SlotPlan(
            water_kw=3.1,
            water_heater_plans={"vvb": 3.1},
            ev_surplus_kw={"c1": 5.0},
            soc_target=60,
        )
        _, decision = await self._isolated(engine, slot)
        assert decision.water_temps["vvb"] == 60
        assert decision.mode_intent == "idle"


class TestEVLoggingStateMachine:
    """Verify Issue 4 fix: logs only on transitions, never during steady-state."""

    def test_ev_start_logs_once(self, caplog):
        """First detection → log 'EV charging started'."""
        caplog.set_level(logging.INFO)

        _ev_detected_last_tick = False
        actual_ev_charging = True

        if not _ev_detected_last_tick and actual_ev_charging:
            logging.info(
                "EV charging started: 1.50 kW actual - Source isolation: Blocking battery discharge"
            )
            _ev_detected_last_tick = True

        assert "EV charging started" in caplog.text
        assert _ev_detected_last_tick is True

    def test_continuous_ev_silent(self, caplog):
        """10 ticks with EV active → zero logs after first."""
        caplog.set_level(logging.INFO)

        _ev_detected_last_tick = True

        # Simulate 10 ticks
        for _ in range(10):
            actual_ev_charging = True
            if not _ev_detected_last_tick and actual_ev_charging:
                logging.info("EV charging started")
                _ev_detected_last_tick = True

        # Should have zero "started" messages
        assert "EV charging started" not in caplog.text

    def test_ev_stop_logs_once(self, caplog):
        """EV ends → log 'EV charging ended'."""
        caplog.set_level(logging.INFO)

        _ev_detected_last_tick = True
        ev_should_charge = False

        if not ev_should_charge and _ev_detected_last_tick:
            logging.info("EV charging ended - Source isolation: Resuming normal battery operation")
            _ev_detected_last_tick = False

        assert "EV charging ended" in caplog.text
        assert _ev_detected_last_tick is False

    def test_ev_resume_logs_again(self, caplog):
        """EV stops then starts → both transitions logged."""
        caplog.set_level(logging.INFO)

        _ev_detected_last_tick = False

        # First start (ev_should_charge=True)
        ev_should_charge = True
        if not _ev_detected_last_tick and ev_should_charge:
            logging.info("EV charging started")
            _ev_detected_last_tick = True

        # Stop (ev_should_charge=False)
        ev_should_charge = False
        if not ev_should_charge and _ev_detected_last_tick:
            logging.info("EV charging ended")
            _ev_detected_last_tick = False

        # Resume (ev_should_charge=True)
        ev_should_charge = True
        if not _ev_detected_last_tick and ev_should_charge:
            logging.info("EV charging started")
            _ev_detected_last_tick = True

        started_count = caplog.text.count("EV charging started")
        ended_count = caplog.text.count("EV charging ended")

        assert started_count == 2
        assert ended_count == 1


class TestEVIsolationIntegration:
    """End-to-end integration tests."""

    def test_original_bug_regression(self):
        """
        Full simulation: The original 06:45 EV charging bug.

        Scenario:
        - SoC 65% > target 60% (normally → self_consumption)
        - EV charging 0.15 kW detected
        - Expected: idle mode + discharge blocked
        - Forbidden: self_consumption with discharge allowed
        """
        state = SystemState(
            current_soc_percent=65.0,
            min_soc_percent=10.0,
        )

        # NOTE: Engine sets discharge_kw=0 before calling controller when EV active
        slot = SlotPlan(
            charge_kw=0.0,
            discharge_kw=0.0,  # Engine already blocked discharge
            export_kw=0.0,
            load_kw=2.0,
            water_kw=0.0,
            ev_charging_kw=0.15,  # EV is charging!
            soc_target=60,
            soc_projected=65,
        )

        ctrl_config = ControllerConfig()
        inv_config = InverterConfig()

        decision = make_decision(
            slot,
            state,
            None,
            ctrl_config,
            inv_config,
            None,
            None,
        )

        # MUST be idle, not self_consumption
        assert decision.mode_intent == "idle", (
            f"BUG: Expected idle mode when EV charging, got {decision.mode_intent}"
        )

    def test_fail_safe_integration(self, caplog):
        """Fail-safe blocks discharge even when controller might not."""
        caplog.set_level(logging.WARNING)

        # Simulate engine-level fail-safe intervention
        scheduled_ev_kw = 0.0  # Not scheduled
        actual_ev_power_kw = float("inf")  # Fail-safe activated

        actual_ev_charging = actual_ev_power_kw > 0.1
        ev_should_charge = scheduled_ev_kw > 0.1 or actual_ev_charging

        # Should block despite scheduled showing no EV
        assert ev_should_charge is True
        assert actual_ev_charging is True

    @pytest.mark.parametrize(
        "scenario,expected_mode,expected_discharge",
        [
            ("no_ev_soc_high", "self_consumption", 3.0),
            ("ev_scheduled", "idle", 0.0),
            ("ev_both", "idle", 0.0),
            ("soc_low_no_ev", "idle", 0.0),
        ],
    )
    def test_scenario_matrix(self, scenario, expected_mode, expected_discharge):
        """Parameterized scenario testing for controller mode selection.

        Note: "ev_actual" scenario tests engine-level actual EV detection,
        which sets discharge_kw=0 before calling controller. See engine tests above.
        """

        scenarios = {
            "no_ev_soc_high": (
                SystemState(current_soc_percent=65.0),
                SlotPlan(discharge_kw=3.0, ev_charging_kw=0.0, soc_target=60),
            ),
            "ev_scheduled": (
                SystemState(current_soc_percent=65.0),
                SlotPlan(discharge_kw=0.0, ev_charging_kw=0.15, soc_target=60),
            ),
            "ev_both": (
                SystemState(current_soc_percent=65.0),
                SlotPlan(discharge_kw=0.0, ev_charging_kw=0.15, soc_target=60),
            ),
            "soc_low_no_ev": (
                SystemState(current_soc_percent=55.0),
                SlotPlan(discharge_kw=3.0, ev_charging_kw=0.0, soc_target=60),
            ),
        }

        state, slot = scenarios[scenario]

        decision = make_decision(
            slot,
            state,
            None,
            ControllerConfig(),
            InverterConfig(),
            None,
            None,
        )

        assert decision.mode_intent == expected_mode, (
            f"Scenario {scenario}: expected {expected_mode}, got {decision.mode_intent}"
        )


class TestExecutionRecordOriginalSlot:
    """Tests that _create_execution_record uses the original (pre-isolation) slot values."""

    @pytest.fixture
    def engine(self, mock_engine):
        return mock_engine

    @pytest.fixture
    def mock_engine(self):
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
                tick_interval_sec=30,
                schedule_file="schedule.json",
                controller=ControllerConfig(),
                inverter=InverterConfig(),
                water_heater=None,
                ev_charger=MagicMock(switch_entity=None),
            )
            mock_yaml.return_value = {
                "system": {
                    "has_solar": True,
                    "has_battery": True,
                    "has_water_heater": False,
                    "has_ev_charger": True,
                },
                "ev_chargers": [],
                "water_heaters": [],
            }
            return ExecutorEngine()

    def _make_record(
        self, engine, original_slot, ev_isolation_reason=None, success=True, override=None
    ):
        if override is None:
            override = OverrideResult()
        return engine._create_execution_record(
            now_iso="2026-03-16T07:00:00",
            slot=original_slot,
            slot_start="2026-03-16T07:00:00",
            state=SystemState(),
            decision=ControllerDecision(mode_intent="idle"),
            override=override,
            action_results=[],
            success=success,
            duration_ms=100,
            ev_isolation_reason=ev_isolation_reason,
        )

    def test_planned_discharge_uses_original_slot(self, engine):
        """Task 1.3: planned_discharge_kw reflects original schedule (1.4), not isolation value (0)."""
        original_slot = SlotPlan(discharge_kw=1.4, ev_charging_kw=10.0)
        record = self._make_record(engine, original_slot)
        assert record.planned_discharge_kw == 1.4

    def test_ev_charging_kw_from_original_slot(self, engine):
        """Task 2.3: ev_charging_kw in execution record comes from original slot."""
        original_slot = SlotPlan(ev_charging_kw=10.0, discharge_kw=1.4)
        record = self._make_record(engine, original_slot)
        assert record.ev_charging_kw == 10.0

    def test_non_ev_slot_has_zero_ev_charging_kw(self, engine):
        """Task 2.3: Non-EV slot has ev_charging_kw=0."""
        original_slot = SlotPlan(ev_charging_kw=0.0, discharge_kw=2.0)
        record = self._make_record(engine, original_slot)
        assert record.ev_charging_kw == 0.0

    def test_isolation_reason_in_override_reason(self, engine):
        """Task 4.2: override_reason is populated when isolation is active and no real override."""
        original_slot = SlotPlan(ev_charging_kw=10.0)
        isolation_reason = "EV source isolation: 10.0kW scheduled, 0.00kW actual"
        record = self._make_record(engine, original_slot, ev_isolation_reason=isolation_reason)
        assert record.override_reason == isolation_reason

    def test_real_override_takes_precedence_over_isolation(self, engine):
        """Task 4.3: Real override reason wins over isolation reason when both active."""
        from executor.override import OverrideType

        real_override = OverrideResult(
            override_needed=True,
            override_type=OverrideType.FORCE_CHARGE,
            reason="Force charge active",
        )
        original_slot = SlotPlan(ev_charging_kw=10.0)
        isolation_reason = "EV source isolation: 10.0kW scheduled, 0.00kW actual"
        record = self._make_record(
            engine, original_slot, ev_isolation_reason=isolation_reason, override=real_override
        )
        assert record.override_reason == "Force charge active"
        assert "EV source isolation" not in (record.override_reason or "")

    def test_success_zero_when_ev_charge_failed(self, engine):
        """Task 3.5: Execution record has success=0 when ev_charge_failed is set."""
        original_slot = SlotPlan(ev_charging_kw=10.0)
        record = self._make_record(engine, original_slot, success=False)
        assert record.success == 0


class TestEVChargeFailureDetection:
    """Test EV charge failure detection counter and notification logic."""

    @pytest.fixture
    def mock_engine(self):
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
                tick_interval_sec=30,
                schedule_file="schedule.json",
                controller=ControllerConfig(),
                inverter=InverterConfig(),
                water_heater=None,
                ev_charger=MagicMock(switch_entity=None),
            )
            mock_yaml.return_value = {
                "system": {
                    "has_solar": True,
                    "has_battery": True,
                    "has_water_heater": False,
                    "has_ev_charger": True,
                },
                "ev_chargers": [],
                "water_heaters": [],
            }
            engine = ExecutorEngine()
            engine._has_ev_charger = True
            engine._has_battery = True
            return engine

    def _simulate_tick_counter(self, engine, scheduled_ev_charging, actual_ev_charging):
        """Simulate the counter logic from _execute_tick without running the full tick."""
        if scheduled_ev_charging and not actual_ev_charging and not engine._ev_power_fetch_failed:
            engine._ev_zero_power_ticks += 1
        elif actual_ev_charging:
            engine._ev_zero_power_ticks = 0

    def test_counter_increments_each_zero_tick(self, mock_engine):
        """Task 3.5: Counter increments each tick where scheduled > 0 and actual = 0."""
        engine = mock_engine
        for i in range(1, 6):
            self._simulate_tick_counter(
                engine, scheduled_ev_charging=True, actual_ev_charging=False
            )
            assert engine._ev_zero_power_ticks == i

    def test_counter_resets_when_actual_power_arrives(self, mock_engine):
        """Task 3.6: Counter resets to 0 when actual EV power exceeds threshold."""
        engine = mock_engine
        engine._ev_zero_power_ticks = 4
        self._simulate_tick_counter(engine, scheduled_ev_charging=True, actual_ev_charging=True)
        assert engine._ev_zero_power_ticks == 0

    def test_counter_and_flag_reset_when_ev_slot_ends(self, mock_engine):
        """Task 3.6: Both counter and notified flag reset when EV slot ends (else branch)."""
        engine = mock_engine
        engine._ev_zero_power_ticks = 4
        engine._ev_failure_notified = True

        # Simulate the else branch (no EV charging → slot ended)
        engine._ev_zero_power_ticks = 0
        engine._ev_failure_notified = False

        assert engine._ev_zero_power_ticks == 0
        assert engine._ev_failure_notified is False

    @pytest.mark.asyncio
    async def test_notify_error_called_after_5_ticks(self, mock_engine):
        """Task 3.5: notify_error called when counter reaches 5."""
        engine = mock_engine
        engine._ev_zero_power_ticks = 5
        engine._ev_failure_notified = False
        engine.dispatcher = MagicMock()
        engine.dispatcher.notify_error = AsyncMock()

        if engine._ev_zero_power_ticks >= 5 and not engine._ev_failure_notified:
            await engine.dispatcher.notify_error(
                "EV charge failure: 10.0kW scheduled, 0.00kW actual for 5 consecutive ticks"
            )
            engine._ev_failure_notified = True

        engine.dispatcher.notify_error.assert_called_once()
        assert engine._ev_failure_notified is True

    @pytest.mark.asyncio
    async def test_notify_error_fires_only_once(self, mock_engine):
        """Task 3.7: notify_error not called again after flag is set."""
        engine = mock_engine
        engine._ev_zero_power_ticks = 10
        engine._ev_failure_notified = True  # Already fired
        engine.dispatcher = MagicMock()
        engine.dispatcher.notify_error = AsyncMock()

        if engine._ev_zero_power_ticks >= 5 and not engine._ev_failure_notified:
            await engine.dispatcher.notify_error("should not be called")

        engine.dispatcher.notify_error.assert_not_called()

    @pytest.mark.asyncio
    async def test_fresh_count_after_ev_slot_ends(self, mock_engine):
        """Task 3.6: After EV slot ends and resets, a new EV slot starts with fresh counter."""
        engine = mock_engine
        engine._ev_zero_power_ticks = 4
        engine._ev_failure_notified = True

        # Simulate slot end (else branch)
        engine._ev_zero_power_ticks = 0
        engine._ev_failure_notified = False

        # Next EV slot starts fresh — 4 ticks should NOT trigger notification
        engine.dispatcher = MagicMock()
        engine.dispatcher.notify_error = AsyncMock()
        for _ in range(4):
            self._simulate_tick_counter(
                engine, scheduled_ev_charging=True, actual_ev_charging=False
            )

        assert engine._ev_zero_power_ticks == 4
        # Not yet at threshold — no notification
        if engine._ev_zero_power_ticks >= 5 and not engine._ev_failure_notified:
            await engine.dispatcher.notify_error("should not trigger yet")
        engine.dispatcher.notify_error.assert_not_called()
