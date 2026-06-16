"""
Test ARC15 Kepler Adapter Integration

Tests for the Kepler adapter's support of the new entity-centric config structure
with multiple water heaters and EV chargers.
"""

import pandas as pd
import pytz

from planner.solver.adapter import (
    _get_config_version,
    build_ev_charger_inputs,
    build_water_heater_inputs,
    config_to_kepler_config,
    planner_to_kepler_input,
)


class TestConfigVersionDetection:
    """Test config format version detection."""

    def test_detects_version_1_by_default(self):
        """Should default to version 1 when no config_version field."""
        config = {"battery": {"capacity_kwh": 13.5}}
        assert _get_config_version(config) == 1

    def test_detects_version_2_explicitly(self):
        """Should detect explicit version 2."""
        config = {"config_version": 2, "battery": {"capacity_kwh": 13.5}}
        assert _get_config_version(config) == 2

    def test_detects_version_as_int(self):
        """Should handle string version and convert to int."""
        config = {"config_version": "2"}
        assert _get_config_version(config) == 2


class TestBuildWaterHeaterInputs:
    """Test build_water_heater_inputs per-device config builder (task 1.6)."""

    def test_empty_array_returns_empty_list(self):
        """Empty water_heaters array returns empty list."""
        result = build_water_heater_inputs([])
        assert result == []

    def test_single_heater_built_correctly(self):
        """Single enabled heater builds correct WaterHeaterInput."""
        heaters = [
            {
                "id": "main",
                "enabled": True,
                "power_kw": 3.0,
                "min_kwh_per_day": 6.0,
                "max_hours_between_heating": 8.0,
                "water_min_spacing_hours": 4.0,
            }
        ]
        result = build_water_heater_inputs(heaters)
        assert len(result) == 1
        assert result[0].id == "main"
        assert result[0].power_kw == 3.0
        assert result[0].min_kwh_per_day == 6.0
        assert result[0].max_hours_between_heating == 8.0
        assert result[0].min_spacing_hours == 4.0

    def test_disabled_heaters_excluded(self):
        """Disabled water heaters are not included."""
        heaters = [
            {"id": "main", "enabled": True, "power_kw": 3.0, "min_kwh_per_day": 6.0},
            {"id": "backup", "enabled": False, "power_kw": 2.0, "min_kwh_per_day": 4.0},
        ]
        result = build_water_heater_inputs(heaters)
        assert len(result) == 1
        assert result[0].id == "main"

    def test_zero_power_heater_excluded(self):
        """Heater with power_kw = 0 is excluded (no variables created)."""
        heaters = [
            {"id": "main", "enabled": True, "power_kw": 0.0, "min_kwh_per_day": 6.0},
        ]
        result = build_water_heater_inputs(heaters)
        assert result == []

    def test_two_heaters_independent_configs(self):
        """Two heaters with different power ratings get independent configs."""
        heaters = [
            {
                "id": "wh1",
                "enabled": True,
                "power_kw": 3.0,
                "min_kwh_per_day": 6.0,
                "water_min_spacing_hours": 4.0,
            },
            {
                "id": "wh2",
                "enabled": True,
                "power_kw": 2.0,
                "min_kwh_per_day": 3.0,
                "water_min_spacing_hours": 2.0,
            },
        ]
        result = build_water_heater_inputs(heaters)
        assert len(result) == 2
        wh1 = next(r for r in result if r.id == "wh1")
        wh2 = next(r for r in result if r.id == "wh2")
        assert wh1.power_kw == 3.0
        assert wh2.power_kw == 2.0
        assert wh1.min_spacing_hours == 4.0
        assert wh2.min_spacing_hours == 2.0

    def test_enable_top_ups_false_zeros_spacing(self):
        """When enable_top_ups=False globally, spacing is zeroed for all heaters."""
        heaters = [
            {
                "id": "wh1",
                "enabled": True,
                "power_kw": 3.0,
                "min_kwh_per_day": 6.0,
                "water_min_spacing_hours": 4.0,
            },
        ]
        global_cfg = {"enable_top_ups": False}
        result = build_water_heater_inputs(heaters, global_cfg)
        assert result[0].min_spacing_hours == 0.0

    def test_per_device_state_applied(self):
        """Per-device state sets heated_today_kwh and force_on_slots."""
        heaters = [
            {"id": "wh1", "enabled": True, "power_kw": 3.0, "min_kwh_per_day": 6.0},
        ]
        states = [
            {"id": "wh1", "heated_today_kwh": 3.0, "force_on_slots": [0, 1, 2]},
        ]
        result = build_water_heater_inputs(heaters, water_heater_states=states)
        assert result[0].heated_today_kwh == 3.0
        assert result[0].force_on_slots == [0, 1, 2]

    def test_global_settings_passed_as_scalars(self):
        """Global settings like comfort penalties remain scalar in KeplerConfig."""
        from planner.solver.adapter import config_to_kepler_config

        config = {
            "config_version": 2,
            "battery": {"capacity_kwh": 13.5, "max_charge_a": 100, "max_discharge_a": 100},
            "prices": {
                "import": [{"price": 0.5, "start_time": "2024-01-01T00:00:00+00:00"}],
                "export": [{"price": 0.1, "start_time": "2024-01-01T00:00:00+00:00"}],
            },
            "water_heaters": [
                {"id": "wh1", "enabled": True, "power_kw": 3.0, "min_kwh_per_day": 6.0},
            ],
            "water_heating": {"comfort_level": 3, "defer_up_to_hours": 2.0},
        }
        import pytz

        tz = pytz.timezone("Europe/Stockholm")
        import pandas as pd

        now = pd.Timestamp.now(tz=tz)
        slot_starts = [now]
        kepler_cfg = config_to_kepler_config(config, slot_starts)
        # Per-device list populated
        assert len(kepler_cfg.water_heaters) == 1
        assert kepler_cfg.water_heaters[0].id == "wh1"
        # Global penalties are scalar
        assert kepler_cfg.defer_up_to_hours == 2.0


class TestBuildEvChargerInputs:
    """Test build_ev_charger_inputs per-device config builder (task 2.6)."""

    def test_empty_array_returns_empty_list(self):
        """Empty ev_chargers config returns empty list."""
        result = build_ev_charger_inputs([])
        assert result == []

    def test_disabled_chargers_excluded(self):
        """Disabled chargers are filtered out."""
        chargers = [
            {"id": "tesla", "enabled": True, "max_power_kw": 11.0, "battery_capacity_kwh": 82.0},
            {"id": "fiat", "enabled": False, "max_power_kw": 7.4, "battery_capacity_kwh": 42.0},
        ]
        result = build_ev_charger_inputs(chargers)
        assert len(result) == 1
        assert result[0].id == "tesla"

    def test_per_device_configs_built_correctly(self):
        """Per-device configs use correct fields from config."""
        chargers = [
            {
                "id": "tesla",
                "enabled": True,
                "max_power_kw": 11.0,
                "battery_capacity_kwh": 82.0,
                "penalty_levels": [
                    {"max_soc": 80.0, "penalty_sek": 0.5},
                ],
            }
        ]
        result = build_ev_charger_inputs(chargers)
        assert len(result) == 1
        ev = result[0]
        assert ev.id == "tesla"
        assert ev.max_power_kw == 11.0
        assert ev.battery_capacity_kwh == 82.0
        assert len(ev.incentive_buckets) == 1
        assert ev.incentive_buckets[0].threshold_soc == 80.0

    def test_unplugged_charger_included_in_config(self):
        """Unplugged chargers are included but flagged as not plugged in."""
        chargers = [
            {"id": "main", "enabled": True, "max_power_kw": 7.4, "battery_capacity_kwh": 40.0}
        ]
        # No HA state provided → defaults: not plugged in
        result = build_ev_charger_inputs(chargers, ev_charger_states=None)
        assert len(result) == 1
        assert result[0].plugged_in is False

    def test_ha_state_applied_per_device(self):
        """HA state is applied to the correct charger by ID."""
        chargers = [
            {
                "id": "charger_a",
                "enabled": True,
                "max_power_kw": 11.0,
                "battery_capacity_kwh": 82.0,
            },
            {"id": "charger_b", "enabled": True, "max_power_kw": 7.4, "battery_capacity_kwh": 40.0},
        ]
        states = [
            {"id": "charger_a", "soc_percent": 75.0, "plugged_in": True},
            {"id": "charger_b", "soc_percent": 20.0, "plugged_in": False},
        ]
        result = build_ev_charger_inputs(chargers, ev_charger_states=states)
        a = next(r for r in result if r.id == "charger_a")
        b = next(r for r in result if r.id == "charger_b")
        assert a.current_soc_percent == 75.0
        assert a.plugged_in is True
        assert b.current_soc_percent == 20.0
        assert b.plugged_in is False

    def test_charger_without_id_is_skipped(self):
        """Chargers without id field are skipped."""
        chargers = [
            {"enabled": True, "max_power_kw": 7.4},  # No id
            {"id": "charger_b", "enabled": True, "max_power_kw": 7.4},
        ]
        result = build_ev_charger_inputs(chargers)
        assert len(result) == 1
        assert result[0].id == "charger_b"


class TestKeplerConfigWithARC15:
    """Test full config_to_kepler_config with ARC15 structure."""

    def test_uses_legacy_format_when_no_new_arrays(self):
        """With no water_heaters/ev_chargers arrays, per-device lists are empty."""
        config = {
            "config_version": 1,
            "system": {"has_ev_charger": True},
            "battery": {"capacity_kwh": 13.5, "max_charge_a": 100, "max_discharge_a": 100},
            "water_heating": {
                "power_kw": 3.0,
                "min_kwh_per_day": 6.0,
                "comfort_level": 3,
            },
            "ev_charger": {
                "max_power_kw": 11.0,
                "battery_capacity_kwh": 82.0,
            },
        }

        kepler_cfg = config_to_kepler_config(config)

        # Legacy format produces no per-device water heaters
        assert kepler_cfg.water_heaters == []
        # Legacy format does not populate per-device ev_chargers
        assert kepler_cfg.ev_chargers == []

    def test_uses_new_format_when_config_version_2(self):
        """Should build per-device EVChargerInput list from water_heaters/ev_chargers arrays."""
        config = {
            "config_version": 2,
            "system": {"has_ev_charger": True},
            "battery": {"capacity_kwh": 13.5, "max_charge_a": 100, "max_discharge_a": 100},
            "water_heaters": [
                {
                    "id": "main",
                    "enabled": True,
                    "power_kw": 3.0,
                    "min_kwh_per_day": 6.0,
                    "comfort_level": 4,
                    "enable_top_ups": True,
                    "max_hours_between_heating": 6.0,
                    "min_spacing_hours": 4.0,
                },
                {
                    "id": "backup",
                    "enabled": True,
                    "power_kw": 2.0,
                    "min_kwh_per_day": 4.0,
                },
            ],
            "ev_chargers": [
                {
                    "id": "tesla",
                    "enabled": True,
                    "max_power_kw": 11.0,
                    "battery_capacity_kwh": 82.0,
                },
            ],
        }

        kepler_cfg = config_to_kepler_config(config)

        # Water heaters build two independent WaterHeaterInput objects
        assert len(kepler_cfg.water_heaters) == 2
        heater_ids = {wh.id for wh in kepler_cfg.water_heaters}
        assert heater_ids == {"main", "backup"}
        main = next(wh for wh in kepler_cfg.water_heaters if wh.id == "main")
        backup = next(wh for wh in kepler_cfg.water_heaters if wh.id == "backup")
        assert main.power_kw == 3.0
        assert backup.power_kw == 2.0

        # EV charger should produce one EVChargerInput
        assert len(kepler_cfg.ev_chargers) == 1
        assert kepler_cfg.ev_chargers[0].id == "tesla"
        assert kepler_cfg.ev_chargers[0].max_power_kw == 11.0
        assert kepler_cfg.ev_chargers[0].battery_capacity_kwh == 82.0

    def test_disables_water_heating_when_all_disabled(self):
        """Should disable water heating when all heaters are disabled."""
        config = {
            "config_version": 2,
            "system": {},
            "battery": {"capacity_kwh": 13.5, "max_charge_a": 100, "max_discharge_a": 100},
            "water_heaters": [
                {"id": "main", "enabled": False, "power_kw": 3.0, "min_kwh_per_day": 6.0},
            ],
            "ev_chargers": [],
        }

        kepler_cfg = config_to_kepler_config(config)

        # All disabled → empty water_heaters list
        assert kepler_cfg.water_heaters == []

    def test_disables_ev_when_all_disabled(self):
        """Should produce empty ev_chargers list when all chargers are disabled."""
        config = {
            "config_version": 2,
            "system": {"has_ev_charger": True},
            "battery": {"capacity_kwh": 13.5, "max_charge_a": 100, "max_discharge_a": 100},
            "water_heaters": [],
            "ev_chargers": [
                {
                    "id": "tesla",
                    "enabled": False,
                    "max_power_kw": 11.0,
                    "battery_capacity_kwh": 82.0,
                },
            ],
        }

        kepler_cfg = config_to_kepler_config(config)

        assert kepler_cfg.ev_chargers == []

    def test_backward_compatibility_with_legacy_config(self):
        """Should work with old config format without new arrays."""
        config = {
            # No config_version field
            "system": {"has_ev_charger": True},
            "battery": {"capacity_kwh": 13.5, "max_charge_a": 100, "max_discharge_a": 100},
            "water_heating": {
                "power_kw": 3.0,
                "min_kwh_per_day": 6.0,
                "comfort_level": 3,
                "enable_top_ups": True,
                "max_hours_between_heating": 8.0,
                "min_spacing_hours": 5.0,
            },
            "ev_charger": {
                "max_power_kw": 11.0,
                "battery_capacity_kwh": 82.0,
            },
        }

        kepler_cfg = config_to_kepler_config(config)

        # Legacy format produces no per-device water heaters (no water_heaters array in config)
        assert kepler_cfg.water_heaters == []
        # Legacy ev_charger section does not populate ev_chargers (needs config_version>=2)
        assert kepler_cfg.ev_chargers == []

    def test_max_inverter_ac_kw_mapping_from_config(self):
        """Should map system.inverter.max_ac_power_kw to KeplerConfig.max_inverter_ac_kw."""
        config = {
            "config_version": 2,
            "system": {
                "inverter": {
                    "max_ac_power_kw": 10.0,
                    "max_dc_input_kw": 12.0,
                }
            },
            "battery": {
                "capacity_kwh": 10.0,
                "min_soc_percent": 10.0,
                "max_soc_percent": 100.0,
                "max_charge_a": 100.0,
                "max_discharge_a": 100.0,
                "nominal_voltage_v": 48.0,
                "charge_efficiency": 0.95,
            },
        }

        kepler_cfg = config_to_kepler_config(config)

        assert kepler_cfg.max_inverter_ac_kw == 10.0, (
            f"max_inverter_ac_kw should be 10.0, got {kepler_cfg.max_inverter_ac_kw}"
        )

    def test_max_inverter_ac_kw_none_when_not_configured(self):
        """Should set max_inverter_ac_kw to None when not configured."""
        config = {
            "config_version": 2,
            "system": {},
            "battery": {
                "capacity_kwh": 10.0,
                "min_soc_percent": 10.0,
                "max_soc_percent": 100.0,
                "max_charge_a": 100.0,
                "max_discharge_a": 100.0,
                "nominal_voltage_v": 48.0,
                "charge_efficiency": 0.95,
            },
        }

        kepler_cfg = config_to_kepler_config(config)

        assert kepler_cfg.max_inverter_ac_kw is None, (
            f"max_inverter_ac_kw should be None when not configured, got {kepler_cfg.max_inverter_ac_kw}"
        )

    def test_wear_cost_override_is_clamped_to_cycle_cost_floor(self):
        config = {
            "config_version": 2,
            "system": {},
            "battery": {
                "capacity_kwh": 10.0,
                "max_charge_a": 100.0,
                "max_discharge_a": 100.0,
                "nominal_voltage_v": 48.0,
            },
            "battery_economics": {"battery_cycle_cost_kwh": 0.2},
        }

        kepler_cfg = config_to_kepler_config(
            config,
            overrides={"kepler": {"wear_cost_sek_per_kwh": 0.0}},
        )

        assert kepler_cfg.wear_cost_sek_per_kwh == 0.2

    def test_wear_cost_override_above_cycle_cost_floor_is_preserved(self):
        config = {
            "config_version": 2,
            "system": {},
            "battery": {
                "capacity_kwh": 10.0,
                "max_charge_a": 100.0,
                "max_discharge_a": 100.0,
                "nominal_voltage_v": 48.0,
            },
            "battery_economics": {"battery_cycle_cost_kwh": 0.2},
        }

        kepler_cfg = config_to_kepler_config(
            config,
            overrides={"kepler": {"wear_cost_sek_per_kwh": 1.0}},
        )

        assert kepler_cfg.wear_cost_sek_per_kwh == 1.0

    def test_wear_cost_floor_applies_to_root_level_config_value(self):
        config = {
            "config_version": 2,
            "system": {},
            "battery": {
                "capacity_kwh": 10.0,
                "max_charge_a": 100.0,
                "max_discharge_a": 100.0,
                "nominal_voltage_v": 48.0,
            },
            "battery_economics": {"battery_cycle_cost_kwh": 0.2},
            "wear_cost_sek_per_kwh": 0.05,
        }

        kepler_cfg = config_to_kepler_config(config)

        assert kepler_cfg.wear_cost_sek_per_kwh >= config["battery_economics"]["battery_cycle_cost_kwh"]


class TestKeplerInputConversion:
    """Test planner_to_kepler_input function."""

    def test_converts_dataframe_to_kepler_input(self):
        """Should convert DataFrame with required columns to KeplerInput."""
        tz = pytz.UTC
        df = pd.DataFrame(
            {
                "load_forecast_kwh": [1.0, 2.0, 3.0],
                "pv_forecast_kwh": [0.5, 1.0, 1.5],
                "import_price_sek_kwh": [0.5, 0.6, 0.7],
                "export_price_sek_kwh": [0.4, 0.5, 0.6],
            },
            index=pd.date_range("2024-01-01 00:00", periods=3, freq="15min", tz=tz),
        )

        result = planner_to_kepler_input(df, initial_soc_kwh=5.0)

        assert len(result.slots) == 3
        assert result.initial_soc_kwh == 5.0
        assert result.slots[0].load_kwh == 1.0
        assert result.slots[0].pv_kwh == 0.5
        assert result.slots[0].import_price_sek_kwh == 0.5

    def test_handles_missing_export_price(self):
        """Should use import price when export price is missing."""
        tz = pytz.UTC
        df = pd.DataFrame(
            {
                "load_forecast_kwh": [1.0],
                "pv_forecast_kwh": [0.5],
                "import_price_sek_kwh": [0.5],
                # No export_price_sek_kwh
            },
            index=pd.date_range("2024-01-01 00:00", periods=1, freq="15min", tz=tz),
        )

        result = planner_to_kepler_input(df, initial_soc_kwh=5.0)

        assert result.slots[0].export_price_sek_kwh == 0.5  # Should equal import price

    def test_prefers_adjusted_forecasts(self):
        """Should prefer adjusted_load_kwh and adjusted_pv_kwh if available."""
        tz = pytz.UTC
        df = pd.DataFrame(
            {
                "load_forecast_kwh": [1.0],
                "pv_forecast_kwh": [0.5],
                "adjusted_load_kwh": [0.8],  # Should use this
                "adjusted_pv_kwh": [0.6],  # Should use this
                "import_price_sek_kwh": [0.5],
            },
            index=pd.date_range("2024-01-01 00:00", periods=1, freq="15min", tz=tz),
        )

        result = planner_to_kepler_input(df, initial_soc_kwh=5.0)

        assert result.slots[0].load_kwh == 0.8  # adjusted value
        assert result.slots[0].pv_kwh == 0.6  # adjusted value

    def test_pv_dc_clipping_with_max_dc_input_kw(self):
        """Should clip PV to max DC input capacity."""
        tz = pytz.UTC
        # Create a slot with 18kW average PV (4.5 kWh in 15min)
        df = pd.DataFrame(
            {
                "load_forecast_kwh": [1.0],
                "pv_forecast_kwh": [4.5],  # 18kW average
                "import_price_sek_kwh": [0.5],
            },
            index=pd.date_range("2024-01-01 12:00", periods=1, freq="15min", tz=tz),
        )

        # With max_dc_input_kw=12.0, max PV should be 3.0 kWh (12kW * 0.25h)
        result = planner_to_kepler_input(df, initial_soc_kwh=5.0, max_dc_input_kw=12.0)

        assert result.slots[0].pv_kwh == 3.0, (
            f"PV should be clipped to 3.0 kWh (12kW * 0.25h), got {result.slots[0].pv_kwh}"
        )

    def test_pv_no_clipping_when_none(self):
        """Should not clip PV when max_dc_input_kw is None."""
        tz = pytz.UTC
        df = pd.DataFrame(
            {
                "load_forecast_kwh": [1.0],
                "pv_forecast_kwh": [4.5],  # 18kW average
                "import_price_sek_kwh": [0.5],
            },
            index=pd.date_range("2024-01-01 12:00", periods=1, freq="15min", tz=tz),
        )

        result = planner_to_kepler_input(df, initial_soc_kwh=5.0, max_dc_input_kw=None)

        assert result.slots[0].pv_kwh == 4.5, (
            f"PV should not be clipped, expected 4.5 kWh, got {result.slots[0].pv_kwh}"
        )

    def test_pv_no_clipping_when_below_limit(self):
        """Should not clip PV when it's below the limit."""
        tz = pytz.UTC
        df = pd.DataFrame(
            {
                "load_forecast_kwh": [1.0],
                "pv_forecast_kwh": [2.0],  # 8kW average, below 12kW limit
                "import_price_sek_kwh": [0.5],
            },
            index=pd.date_range("2024-01-01 12:00", periods=1, freq="15min", tz=tz),
        )

        result = planner_to_kepler_input(df, initial_soc_kwh=5.0, max_dc_input_kw=12.0)

        assert result.slots[0].pv_kwh == 2.0, (
            f"PV should not be clipped, expected 2.0 kWh, got {result.slots[0].pv_kwh}"
        )
