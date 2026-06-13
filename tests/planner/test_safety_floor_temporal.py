"""
Unit tests for the temporal safety floor calculation.
Tests the new temporal deficit approach to safety floor calculation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd
import pytest
import pytz

from planner.strategy.s_index import calculate_safety_floor, calculate_temporal_deficit


def build_test_df(
    load_kwh: float = 30.0,
    pv_kwh: float = 10.0,
    days: int = 2,
    tz_name: str = "Europe/Stockholm",
    start_offset_days: int = 0,
):
    """Build a test DataFrame with forecast data."""
    tz = pytz.timezone(tz_name)
    today = datetime.now(tz).date()

    slots = []
    for _day_offset in range(start_offset_days, start_offset_days + days):
        for _hour in range(24):
            for _quarter in range(4):
                # Distribute load/pv evenly across slots
                slots_per_day = 96
                slots.append(
                    {
                        "load_forecast_kwh": load_kwh / slots_per_day,
                        "pv_forecast_kwh": pv_kwh / slots_per_day,
                    }
                )

    index = pd.date_range(
        start=tz.localize(
            datetime(today.year, today.month, today.day) + timedelta(days=start_offset_days)
        ),
        periods=len(slots),
        freq="15min",
    )
    return pd.DataFrame(slots, index=index)


def build_spring_scenario_df(tz_name: str = "Europe/Stockholm"):
    """
    Build a spring scenario DataFrame with:
    - Daytime: High PV, moderate load (surplus)
    - Nighttime: Zero PV, moderate load (deficit)
    - Aggregate: PV > Load (surplus)
    - Temporal: Overnight deficit exists
    """
    tz = pytz.timezone(tz_name)
    today = datetime.now(tz).date()

    slots = []
    # Build 2 days of data
    for _day_offset in range(2):
        for hour in range(24):
            for _quarter in range(4):
                # Daytime (06:00-18:00): High PV generation, low load
                if 6 <= hour < 18:
                    load = 0.3  # Low load during day (people at work)
                    pv = 2.5  # High PV during day (12 hours of generation)
                else:
                    load = 1.2  # Higher load at night (heating, cooking)
                    pv = 0.0  # No PV at night

                slots.append(
                    {
                        "load_forecast_kwh": load / 4,  # Per 15min slot
                        "pv_forecast_kwh": pv / 4,
                    }
                )

    index = pd.date_range(
        start=tz.localize(datetime(today.year, today.month, today.day)),
        periods=len(slots),
        freq="15min",
    )
    return pd.DataFrame(slots, index=index)


class TestCalculateTemporalDeficit:
    """Tests for the temporal deficit calculation."""

    def test_temporal_deficit_basic(self):
        """Temporal deficit should sum max(0, load - pv) per slot."""
        df = pd.DataFrame(
            {
                "load_forecast_kwh": [1.0, 2.0, 0.5, 1.5],
                "pv_forecast_kwh": [0.5, 1.0, 1.0, 0.0],
            }
        )

        deficit = calculate_temporal_deficit(df)

        # Expected: max(0, 1-0.5) + max(0, 2-1) + max(0, 0.5-1) + max(0, 1.5-0)
        # = 0.5 + 1.0 + 0 + 1.5 = 3.0
        assert deficit == pytest.approx(3.0)

    def test_temporal_deficit_empty_df(self):
        """Empty DataFrame should return 0 deficit."""
        df = pd.DataFrame({"load_forecast_kwh": [], "pv_forecast_kwh": []})
        deficit = calculate_temporal_deficit(df)
        assert deficit == 0.0

    def test_temporal_deficit_pv_surplus(self):
        """When PV > Load in all slots, deficit should be 0."""
        df = pd.DataFrame(
            {
                "load_forecast_kwh": [1.0, 2.0, 1.0],
                "pv_forecast_kwh": [2.0, 3.0, 1.5],
            }
        )

        deficit = calculate_temporal_deficit(df)
        assert deficit == 0.0


class TestCalculateSafetyFloor:
    """Tests for the safety floor calculation with temporal deficit."""

    def test_safety_floor_basic(self):
        """Basic safety floor calculation."""
        df = build_test_df(load_kwh=30.0, pv_kwh=10.0)

        battery_cfg = {"capacity_kwh": 34.2, "min_soc_percent": 12.0}
        s_index_cfg = {"risk_appetite": 3, "max_safety_buffer_percent": 20.0}

        floor_kwh, debug = calculate_safety_floor(df, battery_cfg, s_index_cfg, "Europe/Stockholm")

        # Should be above min_soc
        min_soc_kwh = 0.12 * 34.2
        assert floor_kwh > min_soc_kwh
        assert debug["method"] == "temporal_deficit"
        assert "temporal_deficit_kwh" in debug

    def test_safety_floor_spring_no_collapse(self):
        """
        Spring scenario: Aggregate PV surplus but overnight deficit.
        Safety floor should NOT collapse to min_soc.
        """
        df = build_spring_scenario_df()

        battery_cfg = {"capacity_kwh": 34.2, "min_soc_percent": 12.0}
        s_index_cfg = {"risk_appetite": 3, "max_safety_buffer_percent": 20.0}

        # Aggregate check: total PV > total load
        total_load = df["load_forecast_kwh"].sum()
        total_pv = df["pv_forecast_kwh"].sum()
        assert total_pv > total_load, "Test setup: should have aggregate PV surplus"

        floor_kwh, _debug = calculate_safety_floor(df, battery_cfg, s_index_cfg, "Europe/Stockholm")

        min_soc_kwh = 0.12 * 34.2

        # Safety floor should be significantly above min_soc due to temporal deficit
        assert floor_kwh > min_soc_kwh + 3.4, (
            f"Spring safety floor ({floor_kwh:.2f} kWh) should be > min_soc + 10% "
            f"({min_soc_kwh + 3.4:.2f} kWh) due to overnight deficit"
        )

    def test_safety_floor_risk_levels_different(self):
        """Different risk levels should produce different safety floors."""
        df = build_test_df(load_kwh=40.0, pv_kwh=5.0)  # High deficit scenario

        battery_cfg = {"capacity_kwh": 34.2, "min_soc_percent": 12.0}

        results = {}
        for risk in [1, 3, 5]:
            s_index_cfg = {"risk_appetite": risk, "max_safety_buffer_percent": 50.0}
            floor_kwh, _ = calculate_safety_floor(df, battery_cfg, s_index_cfg, "Europe/Stockholm")
            results[risk] = floor_kwh

        # Risk 1 (Safety) > Risk 3 (Neutral) > Risk 5 (Gambler)
        assert results[1] > results[3], f"Risk 1 ({results[1]}) should > Risk 3 ({results[3]})"
        assert results[3] > results[5], f"Risk 3 ({results[3]}) should > Risk 5 ({results[5]})"

    def test_safety_floor_gambler_returns_min_soc(self):
        """Risk level 5 (Gambler) should return min_soc as floor."""
        df = build_test_df(load_kwh=30.0, pv_kwh=10.0)

        battery_cfg = {"capacity_kwh": 34.2, "min_soc_percent": 12.0}
        s_index_cfg = {"risk_appetite": 5, "max_safety_buffer_percent": 20.0}

        floor_kwh, _debug = calculate_safety_floor(df, battery_cfg, s_index_cfg, "Europe/Stockholm")

        min_soc_kwh = 0.12 * 34.2

        # Gambler mode: 0% margin, 0% minimum buffer
        assert floor_kwh == pytest.approx(min_soc_kwh, abs=0.01)

    def test_safety_floor_with_extended_forecast(self, caplog):
        """Extended forecast beyond price horizon should be used."""
        # Price horizon: first 24h
        price_df = build_test_df(load_kwh=20.0, pv_kwh=10.0, days=1)

        # Extended forecast: 48h (includes 24h beyond price horizon)
        full_forecast_df = build_test_df(load_kwh=20.0, pv_kwh=10.0, days=2)

        price_horizon_end = price_df.index[-1]

        battery_cfg = {"capacity_kwh": 34.2, "min_soc_percent": 12.0}
        s_index_cfg = {"risk_appetite": 3, "max_safety_buffer_percent": 20.0}

        caplog.set_level(logging.WARNING, logger="darkstar.planner")
        _floor_kwh, debug = calculate_safety_floor(
            price_df,
            battery_cfg,
            s_index_cfg,
            "Europe/Stockholm",
            full_forecast_df=full_forecast_df,
            price_horizon_end=price_horizon_end,
        )

        # Should be using extended data
        assert debug["using_extended_data"] is True
        assert debug["temporal_deficit_kwh"] > 0
        assert "Extended forecast data unavailable or insufficient" not in caplog.text

    def test_safety_floor_fallback_warning(self, caplog):
        """Missing extended forecast should trigger fallback with warning."""
        df = build_test_df(load_kwh=30.0, pv_kwh=10.0, days=1)

        battery_cfg = {"capacity_kwh": 34.2, "min_soc_percent": 12.0}
        s_index_cfg = {"risk_appetite": 3, "max_safety_buffer_percent": 20.0}

        price_horizon_end = df.index[-1]

        # Don't provide full_forecast_df - should trigger fallback
        caplog.set_level(logging.WARNING, logger="darkstar.planner")
        _floor_kwh, debug = calculate_safety_floor(
            df,
            battery_cfg,
            s_index_cfg,
            "Europe/Stockholm",
            full_forecast_df=None,
            price_horizon_end=price_horizon_end,
        )

        assert debug["fallback_warning"] is True
        assert debug["using_extended_data"] is False
        assert "Extended forecast data unavailable or insufficient" in caplog.text

    def test_safety_floor_short_horizon_winter_extended_deficit_capped(self):
        """Short price horizon should reserve overnight deficit, capped by max buffer."""
        tz = pytz.timezone("Europe/Stockholm")
        today = datetime.now(tz).date()
        price_start = tz.localize(datetime(today.year, today.month, today.day, 12, 0))
        price_index = pd.date_range(start=price_start, periods=4, freq="15min")
        price_df = pd.DataFrame(
            {
                "load_forecast_kwh": [0.1] * len(price_index),
                "pv_forecast_kwh": [0.0] * len(price_index),
            },
            index=price_index,
        )

        full_index = pd.date_range(start=price_start, periods=4 + 96, freq="15min")
        full_forecast_df = pd.DataFrame(
            {
                "load_forecast_kwh": [0.4] * len(full_index),
                "pv_forecast_kwh": [0.0] * len(full_index),
                "temperature_c": [-12.0] * len(full_index),
            },
            index=full_index,
        )
        battery_cfg = {"capacity_kwh": 34.2, "min_soc_percent": 12.0}
        s_index_cfg = {"risk_appetite": 1, "max_safety_buffer_percent": 10.0}
        price_horizon_end = price_df.index[-1]

        floor_kwh, debug = calculate_safety_floor(
            price_df,
            battery_cfg,
            s_index_cfg,
            "Europe/Stockholm",
            full_forecast_df=full_forecast_df,
            price_horizon_end=price_horizon_end,
        )

        min_soc_kwh = 0.12 * 34.2
        max_allowed = min_soc_kwh + (0.10 * 34.2)
        assert debug["using_extended_data"] is True
        assert debug["temporal_deficit_kwh"] > 30.0
        assert floor_kwh == pytest.approx(max_allowed, abs=0.01)

    def test_safety_floor_max_buffer_cap(self):
        """max_safety_buffer_pct should cap the safety floor."""
        # High deficit scenario
        df = build_test_df(load_kwh=100.0, pv_kwh=5.0)

        battery_cfg = {"capacity_kwh": 34.2, "min_soc_percent": 12.0}
        s_index_cfg = {"risk_appetite": 1, "max_safety_buffer_percent": 10.0}  # Low cap

        floor_kwh, _debug = calculate_safety_floor(df, battery_cfg, s_index_cfg, "Europe/Stockholm")

        # Max buffer = 10% of 34.2 = 3.42 kWh above min_soc
        min_soc_kwh = 0.12 * 34.2
        max_allowed = min_soc_kwh + (0.10 * 34.2)

        assert floor_kwh <= max_allowed + 0.01, (
            f"Floor ({floor_kwh:.2f}) should be capped at {max_allowed:.2f} "
            f"(10% of capacity above min_soc)"
        )

    def test_safety_floor_price_horizon_expansion(self):
        """
        Price horizon expansion at 13:00 should shift look-ahead window.
        When prices extend to tomorrow midnight, safety floor should look
        24h beyond that (day after tomorrow's overnight).
        """
        tz = pytz.timezone("Europe/Stockholm")
        today = datetime.now(tz).date()
        tomorrow = today + timedelta(days=1)

        # Simulate midday planning (13:00) with prices to tomorrow midnight
        # Price horizon: today 13:00 to tomorrow 23:45
        price_start = tz.localize(datetime(today.year, today.month, today.day, 13, 0))
        price_end = tz.localize(datetime(tomorrow.year, tomorrow.month, tomorrow.day, 23, 45))
        price_index = pd.date_range(start=price_start, end=price_end, freq="15min")
        price_df = pd.DataFrame(
            {
                "load_forecast_kwh": [0.5] * len(price_index),
                "pv_forecast_kwh": [0.0] * len(price_index),
            },
            index=price_index,
        )

        # Extended forecast: 72h to cover beyond price horizon
        full_forecast_index = pd.date_range(
            start=tz.localize(datetime(today.year, today.month, today.day)),
            periods=96 * 3,  # 3 days of 15min slots
            freq="15min",
        )
        full_forecast_df = pd.DataFrame(
            {
                "load_forecast_kwh": [0.5] * len(full_forecast_index),
                "pv_forecast_kwh": [0.0] * len(full_forecast_index),
            },
            index=full_forecast_index,
        )

        battery_cfg = {"capacity_kwh": 34.2, "min_soc_percent": 12.0}
        s_index_cfg = {"risk_appetite": 3, "max_safety_buffer_percent": 20.0}

        _floor_kwh, debug = calculate_safety_floor(
            price_df,
            battery_cfg,
            s_index_cfg,
            "Europe/Stockholm",
            full_forecast_df=full_forecast_df,
            price_horizon_end=price_end,
        )

        # Look-ahead should start at price_end and extend 24h
        expected_lookahead_start = price_end
        expected_lookahead_end = price_end + timedelta(hours=24)

        assert debug["lookahead_start"] == str(expected_lookahead_start)
        assert debug["lookahead_end"] == str(expected_lookahead_end)

        # Should have a meaningful deficit (load with no PV)
        assert debug["temporal_deficit_kwh"] > 0


class TestSafetyFloorMinimumBuffer:
    """Tests that verify minimum floor per risk level works correctly."""

    def test_minimum_buffer_risk_1(self):
        """Risk 1 should have minimum 25% buffer above min_soc."""
        df = build_test_df(load_kwh=0.0, pv_kwh=0.0)  # No load, no PV

        battery_cfg = {"capacity_kwh": 34.2, "min_soc_percent": 12.0}
        s_index_cfg = {"risk_appetite": 1, "max_safety_buffer_percent": 50.0}

        floor_kwh, _debug = calculate_safety_floor(df, battery_cfg, s_index_cfg, "Europe/Stockholm")

        min_soc_kwh = 0.12 * 34.2
        expected_min_buffer = 0.25 * 34.2  # Risk 1: 25% minimum

        assert floor_kwh >= min_soc_kwh + expected_min_buffer - 0.1, (
            f"Risk 1 floor ({floor_kwh:.2f}) should be >= min_soc + 25% buffer"
        )

    def test_minimum_buffer_risk_3(self):
        """Risk 3 should have minimum 10% buffer above min_soc."""
        df = build_test_df(load_kwh=0.0, pv_kwh=0.0)  # No load, no PV

        battery_cfg = {"capacity_kwh": 34.2, "min_soc_percent": 12.0}
        s_index_cfg = {"risk_appetite": 3, "max_safety_buffer_percent": 50.0}

        floor_kwh, _debug = calculate_safety_floor(df, battery_cfg, s_index_cfg, "Europe/Stockholm")

        min_soc_kwh = 0.12 * 34.2
        expected_min_buffer = 0.10 * 34.2  # Risk 3: 10% minimum

        assert floor_kwh >= min_soc_kwh + expected_min_buffer - 0.1, (
            f"Risk 3 floor ({floor_kwh:.2f}) should be >= min_soc + 10% buffer"
        )

    def test_minimum_buffer_risk_5_zero(self):
        """Risk 5 should have 0% minimum buffer."""
        df = build_test_df(load_kwh=0.0, pv_kwh=0.0)

        battery_cfg = {"capacity_kwh": 34.2, "min_soc_percent": 12.0}
        s_index_cfg = {"risk_appetite": 5, "max_safety_buffer_percent": 20.0}

        floor_kwh, _debug = calculate_safety_floor(df, battery_cfg, s_index_cfg, "Europe/Stockholm")

        min_soc_kwh = 0.12 * 34.2
        assert floor_kwh == pytest.approx(min_soc_kwh, abs=0.01)
