"""
Unit tests for SoC target signal generation and manual action semantics.
"""

from __future__ import annotations

import math
import pandas as pd
import pytest

from archive.legacy_mpc import HeliosPlanner


def build_planner() -> HeliosPlanner:
    planner = HeliosPlanner.__new__(HeliosPlanner)
    planner.config = {
        "timezone": "Europe/Stockholm",
        "arbitrage": {
            "enable_export": True,
            "export_profit_margin_sek": 0.0,
            "export_percentile_threshold": 0,
            "enable_peak_only_export": False,
            "export_future_price_guard": False,
        },
        "decision_thresholds": {
            "battery_use_margin_sek": 0.0,
            "battery_water_margin_sek": 0.0,
        },
        "charging_strategy": {},
        "strategic_charging": {"target_soc_percent": 95},
        "water_heating": {"power_kw": 3.0},
        "battery_economics": {"battery_cycle_cost_kwh": 0.0},
        "manual_planning": {
            "charge_target_percent": 95,
            "export_target_percent": 35,
        },
    }
    planner.timezone = "Europe/Stockholm"
    planner.battery_config = {
        "capacity_kwh": 10.0,
        "min_soc_percent": 15.0,
        "max_soc_percent": 95.0,
        "max_charge_power_kw": 5.0,
        "max_discharge_power_kw": 5.0,
        "roundtrip_efficiency_percent": 95.0,
    }
    planner.thresholds = planner.config["decision_thresholds"]
    planner.charging_strategy = planner.config["charging_strategy"]
    planner.strategic_charging = planner.config["strategic_charging"]
    planner.water_heating_config = planner.config["water_heating"]
    planner.arbitrage_config = planner.config["arbitrage"]
    planner.battery_economics = planner.config["battery_economics"]
    planner.manual_planning = planner.config["manual_planning"]
    planner.daily_pv_forecast = {}
    planner.daily_load_forecast = {}
    planner._last_temperature_forecast = {}
    planner.forecast_meta = {}
    planner.window_responsibilities = []

    planner.learning_config = {"enable": False}
    planner.roundtrip_efficiency = 0.95
    efficiency_component = math.sqrt(planner.roundtrip_efficiency)
    planner.charge_efficiency = efficiency_component
    planner.discharge_efficiency = efficiency_component
    planner.cycle_cost = 0.0

    planner.state = {
        "battery_kwh": 9.0,
        "battery_cost_sek_per_kwh": 0.2,
    }
    return planner


def test_soc_target_rules_across_actions():
    planner = build_planner()

    index = pd.date_range("2025-02-01 00:00", periods=6, freq="15min", tz="Europe/Stockholm")
    df = pd.DataFrame(
        {
            "adjusted_pv_kwh": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "adjusted_load_kwh": [0.4, 0.2, 0.2, 0.3, 0.3, 0.1],
            "water_heating_kw": [0.0, 0.0, 0.0, 3.0, 3.0, 0.0],
            "charge_kw": [0.0, 2.0, 2.0, 0.0, 0.0, 0.0],
            "import_price_sek_kwh": [0.20, 0.18, 0.18, 0.16, 0.17, 0.80],
            "export_price_sek_kwh": [0.18, 0.20, 0.20, 0.19, 0.19, 1.20],
            "is_cheap": [False, True, True, True, True, False],
            "manual_action": [None, None, None, None, None, "Export"],
        },
        index=index,
    )

    planner.now_slot = index[0]
    result = planner._pass_6_finalize_schedule(df)
    entry_series = planner._slot_entry_soc_percent
    result = planner._apply_soc_target_percent(result)

    targets = result["soc_target_percent"]
    projected = result["projected_soc_percent"]

    # Slot 0: hold -> target equals entry
    assert pytest_approx(targets.iloc[0]) == pytest_approx(entry_series.iloc[0])

    # Charge block (slots 1-2): target equals final projected SoC of block (slot 2)
    charge_target = projected.iloc[2]
    assert pytest_approx(targets.iloc[1]) == pytest_approx(charge_target)
    assert pytest_approx(targets.iloc[2]) == pytest_approx(charge_target)

    # Water heating grid block (slots 3-4): target equals entry for block start
    block_entry = entry_series.iloc[3]
    assert pytest_approx(targets.iloc[3]) == pytest_approx(block_entry)
    assert pytest_approx(targets.iloc[4]) == pytest_approx(block_entry)

    # Export slot (5): manual export target clamps to configured manual target (35%)
    assert result.iloc[5]["action"] == "Export"
    assert pytest_approx(targets.iloc[5]) == pytest_approx(35.0)


def test_manual_hold_blocks_discharge():
    planner = build_planner()
    index = pd.date_range("2025-02-02 12:00", periods=1, freq="15min", tz="Europe/Stockholm")
    df = pd.DataFrame(
        {
            "adjusted_pv_kwh": [0.0],
            "adjusted_load_kwh": [1.5],  # deficit that would trigger discharge
            "water_heating_kw": [0.0],
            "charge_kw": [0.0],
            "import_price_sek_kwh": [0.90],
            "export_price_sek_kwh": [0.20],
            "is_cheap": [False],
            "manual_action": ["Hold"],
        },
        index=index,
    )

    planner.now_slot = index[0]
    result = planner._pass_6_finalize_schedule(df)
    assert result.iloc[0]["action"] == "Hold"
    assert pytest_approx(result.iloc[0]["battery_discharge_kw"]) == pytest_approx(0.0)


def test_manual_export_forces_action_even_if_not_profitable():
    planner = build_planner()
    index = pd.date_range("2025-02-02 14:00", periods=1, freq="15min", tz="Europe/Stockholm")
    df = pd.DataFrame(
        {
            "adjusted_pv_kwh": [0.0],
            "adjusted_load_kwh": [0.0],
            "water_heating_kw": [0.0],
            "charge_kw": [0.0],
            "import_price_sek_kwh": [0.10],  # low price -> export not profitable
            "export_price_sek_kwh": [0.12],
            "is_cheap": [True],
            "manual_action": ["Export"],
        },
        index=index,
    )

    planner.now_slot = index[0]
    result = planner._pass_6_finalize_schedule(df)
    slot = result.iloc[0]
    assert slot["action"] == "Export"
    assert slot["export_kwh"] > 0.0


def test_manual_export_forces_energy_to_target():
    planner = build_planner()
    index = pd.date_range("2025-02-03 08:00", periods=1, freq="15min", tz="Europe/Stockholm")
    df = pd.DataFrame(
        {
            "adjusted_pv_kwh": [0.0],
            "adjusted_load_kwh": [0.0],
            "water_heating_kw": [0.0],
            "charge_kw": [0.0],
            "import_price_sek_kwh": [
                0.30
            ],  # high enough but manual export should ignore profitability
            "export_price_sek_kwh": [0.20],
            "is_cheap": [False],
            "manual_action": ["Export"],
        },
        index=index,
    )

    planner.now_slot = index[0]
    result = planner._pass_6_finalize_schedule(df)
    slot = result.iloc[0]
    assert slot["action"] == "Export"
    # Manual export should push energy out up to discharge limit
    assert slot["export_kwh"] > 0.0
    # SoC should move downward from the original ~90% toward the manual export target
    projected_soc = slot["projected_soc_percent"]
    assert projected_soc < 90.0


def pytest_approx(value: float, tol: float = 1e-6) -> float:
    """Helper to round comparison tolerance."""
    return pytest.approx(value, abs=tol)
