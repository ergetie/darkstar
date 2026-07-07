"""
Unit tests for Module 3: price-aware S-Index safety floor.

Covers:
- ``calculate_price_floor_addon()`` (proximity-weighted spread, risk scaling,
  insufficient-data fallbacks, cheap-period asymmetry).
- ``calculate_safety_floor()`` Layer 2 integration (two-tier architecture,
  additive-only clamp, 80% capacity cap, backward compatibility, strategy event
  logging).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest
import pytz

from planner.strategy.s_index import (
    PRICE_PROXIMITY_HALF_LIFE_DAYS,
    RISK_PRICE_KW_FRACTION,
    calculate_price_floor_addon,
    calculate_safety_floor,
)


def _weight(d: int) -> float:
    return 0.5 ** ((d - 1) / PRICE_PROXIMITY_HALF_LIFE_DAYS)


def build_test_df(
    load_kwh: float = 30.0,
    pv_kwh: float = 10.0,
    days: int = 2,
    tz_name: str = "Europe/Stockholm",
    start_offset_days: int = 0,
) -> pd.DataFrame:
    tz = pytz.timezone(tz_name)
    today = datetime.now(tz).date()

    slots = []
    for _day_offset in range(start_offset_days, start_offset_days + days):
        for _hour in range(24):
            for _quarter in range(4):
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


BATTERY_CFG = {"capacity_kwh": 10.0, "min_soc_percent": 10.0}
S_INDEX_CFG = {"risk_appetite": 3, "max_safety_buffer_percent": 50.0}


class TestCalculatePriceFloorAddon:
    """Unit tests for ``calculate_price_floor_addon()``."""

    def test_rising_prices_at_d1_full_weight(self):
        addon, debug = calculate_price_floor_addon({1: 3.0}, 1.0, 10.0, 3)
        # spread = 2.0, weight = 1.0, fraction = 0.10 → 10.0 × 2.0 × 1.0 × 0.10 = 2.0
        assert addon == pytest.approx(2.0, abs=1e-9)
        assert debug["price_adjustment_active"] is True
        assert debug["driving_day_offset"] == 1
        assert debug["proximity_weight"] == pytest.approx(1.0)
        assert debug["raw_spread_sek"] == pytest.approx(2.0)
        assert debug["price_spread_sek"] == pytest.approx(2.0)
        assert debug["peak_upcoming_spot_sek"] == pytest.approx(3.0)
        assert debug["trailing_avg_spot_sek"] == pytest.approx(1.0)
        assert debug["price_reserve_fraction"] == pytest.approx(0.10)

    def test_proximity_damping_d3(self):
        addon, debug = calculate_price_floor_addon({3: 3.0}, 1.0, 10.0, 3)
        # spread = 2.0, weight = 0.5 → 10.0 × 1.0 × 0.10 = 1.0
        assert addon == pytest.approx(1.0, abs=1e-9)
        assert debug["driving_day_offset"] == 3
        assert debug["proximity_weight"] == pytest.approx(_weight(3))

    def test_proximity_damping_d7(self):
        addon, debug = calculate_price_floor_addon({7: 3.0}, 1.0, 10.0, 3)
        # spread = 2.0, weight = 0.125 → 10.0 × 0.25 × 0.10 = 0.25
        assert addon == pytest.approx(0.25, abs=1e-9)
        assert debug["driving_day_offset"] == 7
        assert debug["proximity_weight"] == pytest.approx(0.125)

    def test_ramp_strictly_increases_as_spike_approaches(self):
        spread = 2.0
        addons = [
            calculate_price_floor_addon({d: 1.0 + spread}, 1.0, 10.0, 3)[0]
            for d in (6, 4, 2, 1)
        ]
        assert addons[0] < addons[1] < addons[2] < addons[3]
        assert addons[3] == pytest.approx(2.0, abs=1e-9)  # full weight at D+1

    def test_weighted_peak_selection_far_spike_can_still_win(self):
        addon, debug = calculate_price_floor_addon({1: 1.5, 5: 5.0}, 1.0, 10.0, 3)
        # D+1: weighted = 0.5 × 1.0 = 0.5; D+5: weighted = 4.0 × 0.25 = 1.0
        assert debug["driving_day_offset"] == 5
        assert debug["price_spread_sek"] == pytest.approx(1.0)
        assert debug["raw_spread_sek"] == pytest.approx(4.0)
        assert addon == pytest.approx(10.0 * 1.0 * 0.10, abs=1e-9)

    def test_cheap_period_yields_negative_addon(self):
        addon, debug = calculate_price_floor_addon({1: 0.5}, 1.5, 10.0, 3)
        # spread = -1.0, weight = 1.0 → 10.0 × -1.0 × 0.10 = -1.0
        assert addon == pytest.approx(-1.0, abs=1e-9)
        assert debug["price_adjustment_active"] is True
        assert debug["driving_day_offset"] == 1

    def test_insufficient_forecast_data_empty(self):
        addon, debug = calculate_price_floor_addon({}, 1.0, 10.0, 3)
        assert addon == 0.0
        assert debug["price_adjustment_active"] is False
        assert debug["price_adjustment_reason"] == "insufficient_forecast_data"

    def test_insufficient_historical_data_none(self):
        addon, debug = calculate_price_floor_addon({1: 3.0}, None, 10.0, 3)
        assert addon == 0.0
        assert debug["price_adjustment_active"] is False
        assert debug["price_adjustment_reason"] == "insufficient_historical_data"

    def test_insufficient_historical_data_zero(self):
        addon, debug = calculate_price_floor_addon({1: 3.0}, 0.0, 10.0, 3)
        assert addon == 0.0
        assert debug["price_adjustment_active"] is False
        assert debug["price_adjustment_reason"] == "insufficient_historical_data"

    def test_risk_scaling_proportional(self):
        upcoming = {1: 3.0}
        trailing = 1.0
        cap = 10.0
        addon_r1, _ = calculate_price_floor_addon(upcoming, trailing, cap, 1)
        addon_r5, _ = calculate_price_floor_addon(upcoming, trailing, cap, 5)
        # Risk 1: 10 × 2.0 × 1.0 × 0.15 = 3.0; Risk 5: 10 × 2.0 × 1.0 × 0.02 = 0.4
        assert addon_r1 == pytest.approx(3.0, abs=1e-9)
        assert addon_r5 == pytest.approx(0.4, abs=1e-9)
        assert RISK_PRICE_KW_FRACTION[1] / RISK_PRICE_KW_FRACTION[5] == pytest.approx(addon_r1 / addon_r5)

    def test_no_adjustment_when_prices_at_average(self):
        # spec.md:24-26 — every upcoming day's daily avg spot equals the trailing
        # average → zero spread → zero addon. Floor would be unchanged.
        addon, debug = calculate_price_floor_addon({1: 1.5, 3: 1.5, 7: 1.5}, 1.5, 10.0, 3)
        assert addon == pytest.approx(0.0, abs=1e-9)
        assert debug["price_adjustment_active"] is True
        assert debug["price_spread_sek"] == pytest.approx(0.0)
        assert debug["driving_day_offset"] == 1  # highest weight wins on ties

    def test_uniformly_high_week_drives_d1(self):
        # spec.md:66-68 — all days D+1..D+7 equally elevated → D+1 (highest weight)
        # is the driving day and the signal equals D+1's full spread.
        elevated = {d: 3.0 for d in range(1, 8)}
        addon, debug = calculate_price_floor_addon(elevated, 1.0, 10.0, 3)
        assert debug["driving_day_offset"] == 1
        assert debug["proximity_weight"] == pytest.approx(1.0)
        assert debug["raw_spread_sek"] == pytest.approx(2.0)
        assert debug["price_spread_sek"] == pytest.approx(2.0)
        assert addon == pytest.approx(10.0 * 2.0 * 1.0 * 0.10, abs=1e-9)

    def test_near_spike_outweighs_far_equal_spike(self):
        # spec.md:62-64 — same raw spread at D+2 and D+6 → D+2 wins
        # (weight 0.71 > 0.18).
        addon, debug = calculate_price_floor_addon({2: 3.0, 6: 3.0}, 1.0, 10.0, 3)
        assert debug["driving_day_offset"] == 2
        assert debug["proximity_weight"] == pytest.approx(_weight(2))
        assert debug["price_spread_sek"] == pytest.approx(2.0 * _weight(2))


class TestSafetyFloorPriceIntegration:
    """Integration tests for ``calculate_safety_floor()`` with price data (Layer 2)."""

    def _baseline_floor(self, df: pd.DataFrame, battery_cfg: dict[str, Any], s_index_cfg: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        return calculate_safety_floor(df, battery_cfg, s_index_cfg, "Europe/Stockholm")

    def test_two_tier_floor_increase(self):
        df = build_test_df(load_kwh=30.0, pv_kwh=10.0)
        baseline, base_debug = self._baseline_floor(df, BATTERY_CFG, S_INDEX_CFG)

        addon, _ = calculate_price_floor_addon({1: 3.0}, 1.0, 10.0, 3)
        floor, debug = calculate_safety_floor(
            df,
            BATTERY_CFG,
            S_INDEX_CFG,
            "Europe/Stockholm",
            upcoming_daily_avg_spots={1: 3.0},
            trailing_avg_spot=1.0,
        )
        # Final floor should exceed the Layer 1 baseline by the additive (positive) addon.
        assert floor == pytest.approx(baseline + addon, abs=1e-6)
        assert floor > baseline
        assert debug["price_adjustment_active"] is True
        assert debug["price_addon_applied_kwh"] == pytest.approx(addon, abs=1e-6)
        assert debug["final_floor_kwh"] == pytest.approx(floor, abs=1e-2)

    def test_cheap_period_asymmetry_clamps_to_zero_effect(self):
        df = build_test_df(load_kwh=30.0, pv_kwh=10.0)
        baseline, _ = self._baseline_floor(df, BATTERY_CFG, S_INDEX_CFG)

        floor, debug = calculate_safety_floor(
            df,
            BATTERY_CFG,
            S_INDEX_CFG,
            "Europe/Stockholm",
            upcoming_daily_avg_spots={1: 0.5},
            trailing_avg_spot=1.5,
        )
        assert floor == pytest.approx(baseline, abs=1e-6)
        # Computed addon is negative (visible) but effective change is zero.
        assert debug["price_addon_kwh"] < 0
        assert debug["price_addon_applied_kwh"] == pytest.approx(0.0, abs=1e-9)
        assert debug["price_adjustment_active"] is True

    def test_80_pct_capacity_cap_enforced(self):
        # Tiny max_safety_buffer so the Layer 1 floor is well below 80% capacity,
        # and a large positive spread that would push the floor above 80%.
        capacity = 10.0
        cfg = {"risk_appetite": 1, "max_safety_buffer_percent": 5.0}
        battery_cfg = {"capacity_kwh": capacity, "min_soc_percent": 10.0}
        df = build_test_df(load_kwh=1.0, pv_kwh=0.0)

        # Spread large enough that addon alone would exceed 0.80 × capacity.
        # capacity × spread × weight × fraction = 10 × 5.0 × 1.0 × 0.15 = 7.5
        # baseline floor ~ 1.0 + 0.05×10 = 1.5; 1.5 + 7.5 = 9.0 > 8.0 (80%)
        upcoming = {1: 6.0}
        trailing = 1.0
        floor, debug = calculate_safety_floor(
            df,
            battery_cfg,
            cfg,
            "Europe/Stockholm",
            upcoming_daily_avg_spots=upcoming,
            trailing_avg_spot=trailing,
        )
        assert floor <= 0.80 * capacity + 1e-6
        assert floor == pytest.approx(0.80 * capacity, abs=1e-6)
        assert debug["final_floor_kwh"] == pytest.approx(0.80 * capacity, abs=1e-2)

    def test_extreme_negative_addon_never_below_layer1(self):
        df = build_test_df(load_kwh=30.0, pv_kwh=10.0)
        baseline, _ = self._baseline_floor(df, BATTERY_CFG, S_INDEX_CFG)

        floor, debug = calculate_safety_floor(
            df,
            BATTERY_CFG,
            S_INDEX_CFG,
            "Europe/Stockholm",
            upcoming_daily_avg_spots={1: 0.0},  # spread = -1.5
            trailing_avg_spot=1.5,
        )
        # Floor must equal the Layer 1 baseline (NOT clamp down toward min_soc_kwh).
        assert floor == pytest.approx(baseline, abs=1e-6)
        assert floor > BATTERY_CFG["capacity_kwh"] * (BATTERY_CFG["min_soc_percent"] / 100.0)
        assert debug["price_addon_applied_kwh"] == pytest.approx(0.0, abs=1e-9)

    def test_backward_compatibility_no_price_params(self):
        df = build_test_df(load_kwh=30.0, pv_kwh=10.0)
        baseline, base_debug = self._baseline_floor(df, BATTERY_CFG, S_INDEX_CFG)

        floor, debug = calculate_safety_floor(df, BATTERY_CFG, S_INDEX_CFG, "Europe/Stockholm")
        assert floor == pytest.approx(baseline, abs=1e-9)
        assert debug["price_adjustment_active"] is False
        assert debug["price_adjustment_reason"] == "disabled_or_no_data"
        # Layer 1 debug keys unchanged.
        assert debug["method"] == "temporal_deficit"
        assert "temporal_deficit_kwh" in debug

    def test_disabled_when_upcoming_is_none(self):
        df = build_test_df(load_kwh=30.0, pv_kwh=10.0)
        baseline, _ = self._baseline_floor(df, BATTERY_CFG, S_INDEX_CFG)

        floor, debug = calculate_safety_floor(
            df,
            BATTERY_CFG,
            S_INDEX_CFG,
            "Europe/Stockholm",
            upcoming_daily_avg_spots=None,
            trailing_avg_spot=1.0,
        )
        assert floor == pytest.approx(baseline, abs=1e-9)
        assert debug["price_adjustment_active"] is False
        assert debug["price_adjustment_reason"] == "disabled_or_no_data"

    def test_no_strategy_event_on_negative_addon(self):
        df = build_test_df(load_kwh=30.0, pv_kwh=10.0)
        with patch(
            "backend.strategy.history.append_strategy_event"
        ) as mock_event:
            floor, debug = calculate_safety_floor(
                df,
                BATTERY_CFG,
                S_INDEX_CFG,
                "Europe/Stockholm",
                upcoming_daily_avg_spots={1: 0.5},
                trailing_avg_spot=1.5,
            )
            mock_event.assert_not_called()
        assert debug["price_addon_kwh"] < 0
        assert debug["price_addon_applied_kwh"] == pytest.approx(0.0, abs=1e-9)

    def test_strategy_event_logged_on_significant_increase(self):
        df = build_test_df(load_kwh=30.0, pv_kwh=10.0)
        # Use risk 1 with a 3.0 spread → addon = 10 × 2.0 × 1.0 × 0.15 = 3.0 ≥ 0.5
        with patch(
            "backend.strategy.history.append_strategy_event"
        ) as mock_event:
            calculate_safety_floor(
                df,
                BATTERY_CFG,
                {"risk_appetite": 1, "max_safety_buffer_percent": 50.0},
                "Europe/Stockholm",
                upcoming_daily_avg_spots={1: 3.0},
                trailing_avg_spot=1.0,
            )
            mock_event.assert_called_once()
            kwargs = mock_event.call_args.kwargs
            assert kwargs["event_type"] == "STRATEGY_CHANGE"
            details = kwargs["details"]
            assert "price_spread_sek" in details
            assert "price_addon_kwh" in details
            assert "peak_upcoming_spot_sek" in details
            assert details["price_addon_kwh"] >= 0.5

    def test_no_strategy_event_on_trivial_positive_addon(self):
        df = build_test_df(load_kwh=30.0, pv_kwh=10.0)
        # Tiny spread: 10 × 0.05 × 1.0 × 0.10 = 0.05 kWh (< 0.5 threshold)
        with patch(
            "backend.strategy.history.append_strategy_event"
        ) as mock_event:
            calculate_safety_floor(
                df,
                BATTERY_CFG,
                S_INDEX_CFG,
                "Europe/Stockholm",
                upcoming_daily_avg_spots={1: 1.05},
                trailing_avg_spot=1.0,
            )
            mock_event.assert_not_called()
