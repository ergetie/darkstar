"""
Tests for the Inverter Profile System v2

Tests profile loading, validation, parsing for v2 schema profiles.
These tests exercise profiles directly from disk using the v2 YAML format.
"""

from typing import ClassVar

import pytest

from executor.config import ControllerConfig, InverterConfig
from executor.controller import make_decision
from executor.override import SlotPlan, SystemState
from executor.profiles import InverterProfile, list_profiles, load_profile

PROFILE_NAMES = ["deye", "sungrow", "fronius", "generic"]


class TestProfileV2Loading:
    """Test v2 profile YAML loading from disk."""

    @pytest.mark.parametrize("profile_name", PROFILE_NAMES)
    def test_load_profile_from_disk(self, profile_name):
        """Test that all profiles load successfully from disk."""
        profile = load_profile(profile_name)
        assert profile is not None
        assert isinstance(profile, InverterProfile)

    @pytest.mark.parametrize("profile_name", PROFILE_NAMES)
    def test_profile_has_schema_version_2(self, profile_name):
        """All profiles must have schema_version == 2."""
        profile = load_profile(profile_name)
        assert profile.metadata.schema_version == 2

    @pytest.mark.parametrize("profile_name", PROFILE_NAMES)
    def test_profile_has_metadata(self, profile_name):
        """Profile must have valid metadata."""
        profile = load_profile(profile_name)
        assert profile.metadata.name == profile_name
        assert profile.metadata.version is not None
        assert profile.metadata.description is not None

    @pytest.mark.parametrize("profile_name", PROFILE_NAMES)
    def test_profile_has_supported_brands(self, profile_name):
        """Profile must list supported brands."""
        profile = load_profile(profile_name)
        assert profile.metadata.supported_brands is not None
        assert len(profile.metadata.supported_brands) > 0


class TestProfileV2Modes:
    """Test v2 profile mode structure."""

    REQUIRED_MODES: ClassVar = ["charge", "export", "self_consumption", "idle"]

    @pytest.mark.parametrize("profile_name", PROFILE_NAMES)
    def test_profile_has_4_required_modes(self, profile_name):
        """All profiles must have 4 required modes."""
        profile = load_profile(profile_name)
        for mode_name in self.REQUIRED_MODES:
            assert mode_name in profile.modes, f"Profile {profile_name} missing mode: {mode_name}"

    @pytest.mark.parametrize("profile_name", PROFILE_NAMES)
    @pytest.mark.parametrize("mode_name", REQUIRED_MODES)
    def test_mode_has_actions(self, profile_name, mode_name):
        """Each mode must have actions list."""
        profile = load_profile(profile_name)
        mode = profile.get_mode(mode_name)
        assert mode.actions is not None
        assert isinstance(mode.actions, list)

    @pytest.mark.parametrize("profile_name", PROFILE_NAMES)
    @pytest.mark.parametrize("mode_name", REQUIRED_MODES)
    def test_mode_has_description(self, profile_name, mode_name):
        """Each mode must have a description."""
        profile = load_profile(profile_name)
        mode = profile.get_mode(mode_name)
        assert mode.description is not None
        assert len(mode.description) > 0

    def test_deye_self_consumption_has_max_charge_current(self):
        """Deye self_consumption mode must include max_charge_current action.

        This enables PV surplus export while charging battery by limiting
        charge current. Excess PV beyond the limit exports to grid when
        Solar Sell is enabled.
        """
        profile = load_profile("deye")
        mode = profile.get_mode("self_consumption")

        # Find max_charge_current action
        charge_actions = [a for a in mode.actions if a.entity == "max_charge_current"]
        assert len(charge_actions) == 1, "self_consumption must have max_charge_current action"

        action = charge_actions[0]
        assert action.value == "{{charge_value}}", (
            "max_charge_current must use {{charge_value}} template"
        )

    def test_deye_zero_export_pv_charge_writes_max_charge(self):
        """A planned PV charge without export writes the configured max charge current."""
        profile = load_profile("deye")
        config = ControllerConfig()
        slot = SlotPlan(charge_kw=2.0, grid_charge_kw=0.0, export_kw=0.0, discharge_kw=0.0)

        decision = make_decision(
            slot,
            SystemState(current_soc_percent=50),
            None,
            config,
            InverterConfig(),
            None,
            None,
            profile,
        )

        assert decision.mode_intent == "self_consumption"
        assert decision.charge_value == config.max_charge_a
        assert decision.write_charge_current is True


class TestProfileV2EntityValidation:
    """Test v2 profile entity validation."""

    VALID_DOMAINS: ClassVar = {"select", "number", "switch", "input_number", "sensor"}
    VALID_CATEGORIES: ClassVar = {"system", "battery"}

    @pytest.mark.parametrize("profile_name", PROFILE_NAMES)
    def test_all_entity_domains_are_valid(self, profile_name):
        """All entity domains must be valid."""
        profile = load_profile(profile_name)
        for key, entity in profile.entities.items():
            assert entity.domain in self.VALID_DOMAINS, f"Invalid domain {entity.domain} for {key}"

    @pytest.mark.parametrize("profile_name", PROFILE_NAMES)
    def test_all_entity_categories_are_valid(self, profile_name):
        """All entity categories must be valid."""
        profile = load_profile(profile_name)
        for key, entity in profile.entities.items():
            assert entity.category in self.VALID_CATEGORIES, (
                f"Invalid category {entity.category} for {key}"
            )

    @pytest.mark.parametrize("profile_name", PROFILE_NAMES)
    def test_all_mode_actions_reference_valid_entity_keys(self, profile_name):
        """All mode actions must reference valid entity keys."""
        profile = load_profile(profile_name)
        for mode_name in profile.modes:
            mode = profile.get_mode(mode_name)
            for action in mode.actions:
                assert action.entity in profile.entities, (
                    f"Invalid entity key {action.entity} in mode {mode_name}"
                )


class TestProfileV2DynamicTemplates:
    """Test v2 profile dynamic template validation."""

    VALID_TEMPLATES: ClassVar = {
        "{{charge_value}}",
        "{{discharge_value}}",
        "{{soc_target}}",
        "{{export_power_w}}",
        "{{export_with_load_w}}",
        "{{max_charge}}",
        "{{max_discharge}}",
        "true",
        "false",
    }

    @pytest.mark.parametrize("profile_name", PROFILE_NAMES)
    def test_all_dynamic_templates_are_valid(self, profile_name):
        """All dynamic templates must be valid."""
        profile = load_profile(profile_name)
        for mode_name in profile.modes:
            mode = profile.get_mode(mode_name)
            for action in mode.actions:
                value = action.value
                if isinstance(value, str) and "{{" in value:
                    assert value in self.VALID_TEMPLATES, (
                        f"Invalid template {value} in mode {mode_name}"
                    )


class TestProfileV2Roundtrip:
    """Test profile roundtrip: YAML -> dataclass -> validation."""

    @pytest.mark.parametrize("profile_name", PROFILE_NAMES)
    def test_profile_roundtrip(self, profile_name):
        """Profile can be parsed from YAML and re-serialized."""
        profile = load_profile(profile_name)

        assert profile.metadata.name == profile_name
        assert profile.metadata.schema_version == 2
        assert len(profile.modes) >= 4
        assert len(profile.entities) > 0

    @pytest.mark.parametrize("profile_name", PROFILE_NAMES)
    def test_profile_validation_passes(self, profile_name):
        """Parsed profile should pass validation."""
        profile = load_profile(profile_name)
        is_valid, errors = profile.validate()
        assert is_valid, f"Validation errors: {errors}"


class TestProfileV2ListProfiles:
    """Test profile listing."""

    def test_list_profiles_returns_all_4(self):
        """list_profiles should return all 4 profiles."""
        profiles = list_profiles()
        assert len(profiles) == 4
        names = [p["name"] for p in profiles]
        for name in PROFILE_NAMES:
            assert name in names

    def test_list_profiles_sorted(self):
        """list_profiles should return sorted list."""
        profiles = list_profiles()
        names = [p["name"] for p in profiles]
        assert names == sorted(names)


class TestProfileExecutionBehavior:
    """Test how the dispatcher behaves when using profiles (REV IP4)."""

    @pytest.fixture
    def mock_ha(self):
        from unittest.mock import MagicMock

        from executor.actions import HAClient

        return MagicMock(spec=HAClient)

    @pytest.fixture
    def base_config(self):
        from executor.config import ExecutorConfig

        config = ExecutorConfig()
        config.has_battery = True
        config.inverter.work_mode = "select.work_mode"
        config.inverter.max_charge_power = "number.pv_charge_limit"
        config.inverter.grid_charging_enable = "switch.grid_charge"
        config.inverter.grid_charge_power = "number.grid_charge_limit"
        return config

    @pytest.fixture
    def fronius_profile_mock(self):
        """Create a v2-style Fronius profile mock for dispatcher tests."""
        from unittest.mock import MagicMock

        from executor.profiles import EntityDefinition, ModeAction, ModeDefinition

        profile = MagicMock(spec=InverterProfile)

        charge_mode = ModeDefinition(
            description="Charge from grid",
            actions=[
                ModeAction(entity="work_mode", value="Charge from Grid"),
                ModeAction(entity="grid_charging_enable", value=True),
            ],
        )
        idle_mode = ModeDefinition(
            description="Block discharging",
            actions=[
                ModeAction(entity="work_mode", value="Block Discharging"),
            ],
        )

        profile.modes = {"charge": charge_mode, "idle": idle_mode}
        profile.metadata = MagicMock()
        profile.metadata.name = "fronius"

        profile.entities = {
            "work_mode": EntityDefinition(
                default_entity="select.work_mode",
                domain="select",
                category="system",
                description="Work mode select",
                required=True,
            ),
            "grid_charging_enable": EntityDefinition(
                default_entity="switch.grid_charge",
                domain="switch",
                category="system",
                description="Grid charging switch",
                required=False,
            ),
        }
        profile.behavior = MagicMock()
        profile.behavior.requires_mode_settling = False
        profile.behavior.mode_settling_ms = 0
        return profile

    @pytest.mark.asyncio
    async def test_action_skipping_in_charge_mode(self, mock_ha, base_config, fronius_profile_mock):
        """Verify that discharge and export limits are skipped in charge mode."""
        from executor.actions import ActionDispatcher
        from executor.controller import ControllerDecision

        dispatcher = ActionDispatcher(mock_ha, base_config, profile=fronius_profile_mock)
        base_config.inverter.max_discharge_power = "number.discharge_limit"
        base_config.inverter.grid_max_export_power = "number.export_limit"

        mock_ha.set_number.return_value = True
        mock_ha.set_select_option.return_value = True
        mock_ha.set_input_number.return_value = True

        decision = ControllerDecision(
            mode_intent="charge",
            charge_value=2000.0,
            discharge_value=5000.0,
            export_power_w=3000.0,
            soc_target=10,
            water_temp=40,
            write_charge_current=True,
            write_discharge_current=True,
            control_unit="W",
        )

        await dispatcher.execute(decision)

        for call in mock_ha.set_number.call_args_list:
            assert call.args[0] != "number.discharge_limit"
            assert call.args[0] != "number.export_limit"

    @pytest.mark.asyncio
    async def test_action_skipping_in_idle_mode(self, mock_ha, base_config, fronius_profile_mock):
        """Verify that discharge and export limits are skipped in idle/hold mode."""
        from executor.actions import ActionDispatcher
        from executor.controller import ControllerDecision

        dispatcher = ActionDispatcher(mock_ha, base_config, profile=fronius_profile_mock)
        base_config.inverter.max_discharge_power = "number.discharge_limit"

        mock_ha.set_number.return_value = True
        mock_ha.set_select_option.return_value = True
        mock_ha.set_input_number.return_value = True

        decision = ControllerDecision(
            mode_intent="idle",
            charge_value=0.0,
            discharge_value=5000.0,
            soc_target=10,
            water_temp=40,
            write_charge_current=False,
            write_discharge_current=True,
            control_unit="W",
        )

        await dispatcher.execute(decision)

        for call in mock_ha.set_number.call_args_list:
            assert call.args[0] != "number.discharge_limit"
