"""
Tests for per-day water heating scheduling logic.
"""

from __future__ import annotations

import math
from datetime import timedelta

import pandas as pd

from planner import HeliosPlanner


class TestWaterHeatingScheduling:
    """Validate water heating scheduling across today and tomorrow."""

    def setup_method(self):
        config = {
            "timezone": "Europe/Stockholm",
            "water_heating": {
                "power_kw": 3.0,
                "min_hours_per_day": 2.0,
                "min_kwh_per_day": 6.0,
                "max_blocks_per_day": 2,
                "block_consolidation_tolerance_sek": 0.1,
                "consolidation_max_gap_slots": 1,
                "schedule_future_only": True,
                "defer_up_to_hours": 3,
                "plan_days_ahead": 1,
            },
            "charging_strategy": {
                "charge_threshold_percentile": 15,
                "cheap_price_tolerance_sek": 0.10,
                "price_smoothing_sek_kwh": 0.05,
            },
            "learning": {
                "enable": False,
                "sqlite_path": "data/planner_learning_test.db",
            },
            "nordpool": {"resolution_minutes": 15},
        }

        planner = HeliosPlanner.__new__(HeliosPlanner)
        planner.config = config
        planner.timezone = config["timezone"]
        planner.water_heating_config = config["water_heating"]
        planner.charging_strategy = config["charging_strategy"]
        planner.learning_config = config["learning"]
        planner.strategic_charging = {"target_soc_percent": 95}
        planner.daily_pv_forecast = {}
        planner.daily_load_forecast = {}
        planner._last_temperature_forecast = {}
        planner.forecast_meta = {}
        planner.battery_config = {
            "capacity_kwh": 10.0,
            "min_soc_percent": 15,
            "max_soc_percent": 95,
            "max_charge_power_kw": 5.0,
            "max_discharge_power_kw": 5.0,
            "roundtrip_efficiency_percent": 95.0,
        }

        self.planner = planner
        self.slot_energy = config["water_heating"]["power_kw"] * 0.25  # 15-minute slots
        self.slot_minutes = config["nordpool"]["resolution_minutes"]

    def _count_water_blocks(self, scheduled_slots: pd.Series, slot_duration_minutes=15) -> int:
        """Count contiguous water-heating blocks based on the configured cadence."""
        block_count = 0
        previous_slot = None
        slot_duration = pd.Timedelta(minutes=slot_duration_minutes)
        for slot_time in scheduled_slots.index:
            if previous_slot is None or (slot_time - previous_slot) > slot_duration:
                block_count += 1
            previous_slot = slot_time
        return block_count

    def _build_frame(self, start: str = "2025-01-01 00:00", periods: int = 192) -> pd.DataFrame:
        """Create baseline dataframe covering today + tomorrow (48h)."""
        index = pd.date_range(start, periods=periods, freq="15min", tz="Europe/Stockholm")
        df = pd.DataFrame(
            {
                "import_price_sek_kwh": [0.25] * periods,
                "adjusted_pv_kwh": [0.0] * periods,
                "adjusted_load_kwh": [0.3] * periods,
                "water_heating_kw": [0.0] * periods,
            },
            index=index,
        )
        df["is_cheap"] = False
        return df

    def _min_hour_slots(self) -> int:
        min_hours = self.planner.water_heating_config.get("min_hours_per_day", 0.0)
        if min_hours <= 0:
            return 0
        return max(1, math.ceil(min_hours * 60.0 / self.slot_minutes))

    def test_today_schedules_remaining_requirement(self):
        """Planner should cover only the remaining energy needed for today."""
        df = self._build_frame(periods=96)  # today only
        df.loc[df.index[16:32], "is_cheap"] = True  # 4 hours cheap window mid-day

        planner = self.planner
        planner.now_slot = df.index[0]
        planner._get_daily_water_usage_kwh = lambda _: 3.0  # already consumed 3 kWh

        result = planner._pass_2_schedule_water_heating(df)

        scheduled = result[result["water_heating_kw"] > 0]
        expected_slots = self._min_hour_slots()
        assert len(scheduled) == expected_slots
        assert scheduled.index.min() >= df.index[1]  # respects future-only rule

    def test_skip_today_when_requirement_met(self):
        """No scheduling when today's requirement already satisfied."""
        df = self._build_frame(periods=96)
        df.loc[df.index[20:40], "is_cheap"] = True

        planner = self.planner
        planner.now_slot = df.index[0]
        planner._get_daily_water_usage_kwh = lambda _: 7.0  # already met min_kwh

        result = planner._pass_2_schedule_water_heating(df)
        assert (result["water_heating_kw"] == 0.0).all()

    def test_home_assistant_sensor_prevents_todays_water_heating(self):
        """HA sensor exceeds min_kwh and no extra slots should be scheduled."""
        df = self._build_frame(periods=96)
        df.loc[df.index[20:40], "is_cheap"] = True

        planner = self.planner
        planner.now_slot = df.index[0]
        planner._home_assistant_water_today = 6.5
        planner._home_assistant_water_checked = True

        result = planner._pass_2_schedule_water_heating(df)
        assert (result["water_heating_kw"] == 0.0).all()

    def test_schedule_tomorrow_when_prices_known(self):
        """Planner schedules tomorrow when today satisfied and prices published."""
        df = self._build_frame()  # 48-hour horizon
        today = df.index[0].normalize()
        tomorrow_start = today + timedelta(days=1)

        today_mask = (df.index >= today) & (df.index < tomorrow_start)
        tomorrow_mask = (df.index >= tomorrow_start) & (
            df.index < tomorrow_start + timedelta(days=1)
        )

        df.loc[today_mask, "is_cheap"] = False
        hour_mask = (df.index.hour >= 1) & (df.index.hour <= 4)
        df.loc[tomorrow_mask & hour_mask, "is_cheap"] = True  # cheap window tomorrow

        planner = self.planner
        planner.now_slot = df.index[0]
        planner._get_daily_water_usage_kwh = lambda date: 6.0 if date.day == today.day else 0.0

        result = planner._pass_2_schedule_water_heating(df)
        scheduled = result[result["water_heating_kw"] > 0]
        assert not scheduled.empty
        assert scheduled.index.min() >= tomorrow_start
        assert scheduled.index.max() < tomorrow_start + timedelta(days=1, hours=3)

    def test_water_heating_blocks_respect_tolerance_and_block_limit(self):
        """Segments within tolerance should saturate max blocks without exceeding them."""
        df = self._build_frame()
        first_block = df.index[12:16]
        second_block = df.index[18:22]

        df.loc[first_block, "is_cheap"] = True
        df.loc[second_block, "is_cheap"] = True
        df.loc[first_block, "import_price_sek_kwh"] = 0.20
        df.loc[second_block, "import_price_sek_kwh"] = 0.23

        planner = self.planner
        planner.now_slot = df.index[0]
        planner._home_assistant_water_today = 0.0
        planner._home_assistant_water_checked = True

        result = planner._pass_2_schedule_water_heating(df)
        scheduled = result[result["water_heating_kw"] > 0]
        assert len(scheduled) == math.ceil(6.0 / self.slot_energy)
        assert (
            self._count_water_blocks(scheduled)
            <= planner.water_heating_config["max_blocks_per_day"]
        )

    def test_should_schedule_more_slots_when_energy_shortfall_exceeds_hours(self):
        """If the HA energy deficiency is greater than the hourly minimum,
        schedule the extra slots."""
        df = self._build_frame()
        df.loc[df.index[10:70], "is_cheap"] = True  # wide cheap window

        planner = self.planner
        planner.now_slot = df.index[0]
        planner.water_heating_config["min_kwh_per_day"] = 10.0
        planner._home_assistant_water_today = 0.0
        planner._home_assistant_water_checked = True

        result = planner._pass_2_schedule_water_heating(df)
        scheduled = result[result["water_heating_kw"] > 0]
        expected_slots = math.ceil(10.0 / self.slot_energy)
        assert len(scheduled) == expected_slots
        assert (
            self._count_water_blocks(scheduled)
            <= planner.water_heating_config["max_blocks_per_day"]
        )

    def test_skip_tomorrow_when_prices_unknown(self):
        """Planner should skip tomorrow if the price horizon is incomplete."""
        df = self._build_frame(periods=120)  # less than 48h -> tomorrow incomplete
        today = df.index[0].normalize()
        tomorrow_start = today + timedelta(days=1)

        df.loc[(df.index >= today) & (df.index < today + timedelta(hours=6)), "is_cheap"] = True
        df.loc[(df.index >= tomorrow_start), "is_cheap"] = True

        planner = self.planner
        planner.now_slot = df.index[0]
        planner._get_daily_water_usage_kwh = lambda _: 6.0  # today satisfied

        result = planner._pass_2_schedule_water_heating(df)
        scheduled = result[result["water_heating_kw"] > 0]
        assert scheduled.empty
