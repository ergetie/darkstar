"""
Unit tests for the new calculate_target_soc_risk_factor function.
Tests that risk_appetite and PV deficit properly affect the target SOC.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest
import pytz

from planner.strategy.s_index import (
    calculate_target_soc_risk_factor,
    calculate_dynamic_target_soc,
)


def build_test_df(
    load_kwh: float = 30.0, pv_kwh: float = 10.0, days: int = 2, tz_name: str = "Europe/Stockholm"
):
    """Build a test DataFrame with forecast data."""
    tz = pytz.timezone(tz_name)
    today = datetime.now(tz).date()

    slots = []
    for day_offset in range(1, days + 1):
        target_date = today + timedelta(days=day_offset)
        for hour in range(24):
            for quarter in range(4):
                ts = tz.localize(
                    datetime(
                        target_date.year, target_date.month, target_date.day, hour, quarter * 15
                    )
                )
                # Distribute load/pv evenly across slots
                slots_per_day = 96
                slots.append(
                    {
                        "load_forecast_kwh": load_kwh / slots_per_day,
                        "pv_forecast_kwh": pv_kwh / slots_per_day,
                        "load_p90": (load_kwh * 1.2) / slots_per_day,
                        "load_p10": (load_kwh * 0.8) / slots_per_day,
                        "pv_p90": (pv_kwh * 1.3) / slots_per_day,
                        "pv_p10": (pv_kwh * 0.7) / slots_per_day,
                        "import_price_sek_kwh": 1.50,
                        "export_price_sek_kwh": 0.80,
                    }
                )

    index = pd.date_range(
        start=tz.localize(datetime(today.year, today.month, today.day) + timedelta(days=1)),
        periods=len(slots),
        freq="15min",
    )
    return pd.DataFrame(slots, index=index)


def test_target_soc_risk_appetite_affects_result():
    """Different risk_appetite values should produce different target SOCs."""
    df = build_test_df(load_kwh=30.0, pv_kwh=5.0)  # High deficit

    base_cfg = {
        "base_factor": 1.1,
        "max_factor": 1.5,
        "min_factor": 0.8,
        "pv_deficit_weight": 0.2,
        "temp_weight": 0.0,  # Disable temp to isolate risk_appetite effect
    }

    results = {}
    for appetite in [1, 3, 5]:
        cfg = {**base_cfg, "risk_appetite": appetite}
        factor, debug = calculate_target_soc_risk_factor(df, cfg, "Europe/Stockholm")
        results[appetite] = factor

    # Safety (1) should have highest factor (most buffer)
    # Gambler (5) should have lowest factor (least buffer)
    assert results[1] > results[3], f"Safety ({results[1]}) should > Neutral ({results[3]})"
    assert results[3] > results[5], f"Neutral ({results[3]}) should > Gambler ({results[5]})"


def test_target_soc_pv_deficit_increases_buffer():
    """Low PV vs high load should increase risk factor (more buffer)."""
    base_cfg = {
        "base_factor": 1.1,
        "max_factor": 1.5,
        "min_factor": 0.8,
        "pv_deficit_weight": 0.2,
        "temp_weight": 0.0,
        "risk_appetite": 3,  # Neutral
    }

    # High deficit: load >> PV
    df_deficit = build_test_df(load_kwh=30.0, pv_kwh=2.0)
    factor_deficit, debug_deficit = calculate_target_soc_risk_factor(
        df_deficit, base_cfg, "Europe/Stockholm"
    )

    # Low deficit: PV covers most of load
    df_surplus = build_test_df(load_kwh=30.0, pv_kwh=25.0)
    factor_surplus, debug_surplus = calculate_target_soc_risk_factor(
        df_surplus, base_cfg, "Europe/Stockholm"
    )

    assert (
        factor_deficit > factor_surplus
    ), f"High deficit ({factor_deficit}) should have higher factor than low deficit ({factor_surplus})"


def test_target_soc_gambler_can_go_below_baseline():
    """risk_appetite=5 with PV surplus should allow factor below base_factor."""
    cfg = {
        "base_factor": 1.1,
        "max_factor": 1.5,
        "min_factor": 0.8,
        "pv_deficit_weight": 0.2,
        "temp_weight": 0.0,
        "risk_appetite": 5,  # Gambler
    }

    # PV surplus: more PV than load
    df = build_test_df(load_kwh=20.0, pv_kwh=30.0)
    factor, debug = calculate_target_soc_risk_factor(df, cfg, "Europe/Stockholm")

    # With surplus and gambler mode, factor can drop below base_factor
    # The sigma adjustment should push it down
    assert (
        factor < cfg["base_factor"]
    ), f"Gambler mode with surplus should allow factor ({factor}) < base ({cfg['base_factor']})"


def test_target_soc_respects_min_factor():
    """Factor should never go below min_factor even in extreme gambler mode."""
    cfg = {
        "base_factor": 1.1,
        "max_factor": 1.5,
        "min_factor": 0.9,  # High floor
        "pv_deficit_weight": 0.3,
        "temp_weight": 0.0,
        "risk_appetite": 5,  # Gambler
    }

    # Extreme PV surplus
    df = build_test_df(load_kwh=10.0, pv_kwh=50.0)
    factor, debug = calculate_target_soc_risk_factor(df, cfg, "Europe/Stockholm")

    assert (
        factor >= cfg["min_factor"]
    ), f"Factor ({factor}) should respect min_factor ({cfg['min_factor']})"


def test_target_soc_respects_max_factor():
    """Factor should never exceed max_factor even in extreme safety mode."""
    cfg = {
        "base_factor": 1.2,
        "max_factor": 1.5,
        "min_factor": 0.8,
        "pv_deficit_weight": 0.5,  # High weight
        "temp_weight": 0.3,
        "temp_baseline_c": 20.0,
        "temp_cold_c": -10.0,
        "risk_appetite": 1,  # Safety
    }

    # Extreme deficit + cold temps would push factor very high
    df = build_test_df(load_kwh=50.0, pv_kwh=1.0)

    # Mock cold temperature
    def cold_temps(days, tz):
        return {1: -5.0, 2: -8.0}

    factor, debug = calculate_target_soc_risk_factor(df, cfg, "Europe/Stockholm", cold_temps)

    assert (
        factor <= cfg["max_factor"]
    ), f"Factor ({factor}) should not exceed max_factor ({cfg['max_factor']})"


def test_dynamic_target_soc_uses_risk_factor():
    """calculate_dynamic_target_soc should properly use the risk_factor."""
    battery_cfg = {
        "capacity_kwh": 34.2,
        "min_soc_percent": 12.0,
    }
    s_index_cfg = {
        "soc_scaling_factor": 50.0,
    }

    # Test with different risk factors
    for risk_factor, expected_min in [(1.0, 12.0), (1.2, 22.0), (1.5, 37.0)]:
        target_pct, target_kwh, debug = calculate_dynamic_target_soc(
            risk_factor, battery_cfg, s_index_cfg
        )

        expected_pct = 12.0 + max(0, (risk_factor - 1.0) * 50.0)
        assert (
            abs(target_pct - expected_pct) < 0.1
        ), f"For risk_factor={risk_factor}, expected {expected_pct}%, got {target_pct}%"
