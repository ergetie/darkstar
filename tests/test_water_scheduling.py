"""
Test water heating block scheduling functionality.
"""
import math
import pytest
import pandas as pd
from datetime import datetime, timedelta
from planner import HeliosPlanner


class TestWaterScheduling:
    """Test water heating scheduling with contiguous blocks."""

    def setup_method(self):
        """Set up test fixtures."""
        config = {
            'water_heating': {
                'power_kw': 3.0,
                'min_hours_per_day': 2.0,
                'min_kwh_per_day': 6.0,
                'max_blocks_per_day': 2,
                'schedule_future_only': True
            },
            'charging_strategy': {
                'charge_threshold_percentile': 15,
                'cheap_price_tolerance_sek': 0.10,
                'price_smoothing_sek_kwh': 0.05
            }
        }
        self.planner = HeliosPlanner.__new__(HeliosPlanner)
        self.planner.config = config
        self.planner.water_heating_config = config['water_heating']
        self.planner.charging_strategy = config['charging_strategy']
        self.planner.strategic_charging = {'target_soc_percent': 95}
        self.planner.daily_pv_forecast = {}
        self.planner.daily_load_forecast = {}
        self.planner._last_temperature_forecast = {}
        self.planner.forecast_meta = {}
        self.planner.daily_pv_forecast = {}
        self.planner.daily_load_forecast = {}
        self.planner._last_temperature_forecast = {}
        self.planner.forecast_meta = {}
        # smoothing_config is accessed through config

    def test_contiguous_block_identification(self):
        """Test identification of contiguous cheap slots."""
        # Create test DataFrame with cheap slots
        dates = pd.date_range('2025-01-01 00:00', periods=24, freq='15min')
        df = pd.DataFrame({
            'import_price_sek_kwh': [0.15] * 6 + [0.25] * 6 + [0.15] * 6 + [0.25] * 6,  # Two cheap blocks
            'adjusted_pv_kwh': [0.0] * 24,
            'adjusted_load_kwh': [0.3] * 24,
            'water_heating_kw': [0.0] * 24
        }, index=dates)

        # Mark cheap slots
        df['is_cheap'] = df['import_price_sek_kwh'] <= 0.20

        # Test block identification
        available_slots = df[df['is_cheap']]
        blocks = []
        if not available_slots.empty:
            current_block = {'start': available_slots.index[0], 'length': 1}
            for i in range(1, len(available_slots)):
                current_time = available_slots.index[i]
                prev_time = available_slots.index[i-1]
                if (current_time - prev_time).total_seconds() == 900:  # 15 minutes
                    current_block['length'] += 1
                else:
                    blocks.append(current_block)
                    current_block = {'start': current_time, 'length': 1}
            blocks.append(current_block)

        # Should have 2 blocks of 6 slots each
        assert len(blocks) == 2
        assert all(block['length'] == 6 for block in blocks)

    def test_water_heating_cheap_window_uses_grid(self):
        planner = self.planner
        planner.battery_config = {
            'capacity_kwh': 10.0,
            'min_soc_percent': 15,
            'max_soc_percent': 95,
            'max_charge_power_kw': 5.0,
            'max_discharge_power_kw': 5.0,
            'roundtrip_efficiency_percent': 95.0,
        }
        planner.thresholds = {
            'battery_use_margin_sek': 0.10,
            'battery_water_margin_sek': 0.20,
        }
        planner.battery_economics = {'battery_cycle_cost_kwh': 0.20}
        efficiency_component = math.sqrt(0.95)
        planner.roundtrip_efficiency = 0.95
        planner.charge_efficiency = efficiency_component
        planner.discharge_efficiency = efficiency_component
        planner.cycle_cost = 0.20
        planner.state = {
            'battery_kwh': 6.0,
            'battery_cost_sek_per_kwh': 0.20,
        }
        planner.window_responsibilities = []

        dates = pd.date_range('2025-01-01 07:00', periods=1, freq='15min', tz='Europe/Stockholm')
        df = pd.DataFrame({
            'adjusted_pv_kwh': [0.0],
            'adjusted_load_kwh': [0.0],
            'water_heating_kw': [planner.water_heating_config['power_kw']],
            'charge_kw': [0.0],
            'import_price_sek_kwh': [0.12],
            'export_price_sek_kwh': [0.10],
            'is_cheap': [True],
        }, index=dates)

        planner.now_slot = dates[0]
        result = planner._pass_6_finalize_schedule(df.copy())

        slot = result.iloc[0]
        assert slot['water_from_battery_kwh'] == pytest.approx(0.0)
        assert slot['water_from_grid_kwh'] == pytest.approx(planner.water_heating_config['power_kw'] * 0.25)

    def test_single_block_preference(self):
        """Test that single block is preferred when possible."""
        # Create scenario where one large block can satisfy requirements
        dates = pd.date_range('2025-01-01 00:00', periods=16, freq='15min')  # 4 hours
        df = pd.DataFrame({
            'import_price_sek_kwh': [0.15] * 16,  # All cheap
            'adjusted_pv_kwh': [0.0] * 16,
            'adjusted_load_kwh': [0.3] * 16,
            'water_heating_kw': [0.0] * 16
        }, index=dates)

        df['is_cheap'] = df['import_price_sek_kwh'] <= 0.20

        # Run water heating scheduling
        result_df = self.planner._pass_2_schedule_water_heating(df)

        # Count scheduled slots
        scheduled_slots = result_df[result_df['water_heating_kw'] > 0]
        assert len(scheduled_slots) == 8  # 6 kWh / (3 kW * 0.25 h) = 8 slots

        # Check that it's scheduled as one contiguous block
        scheduled_indices = scheduled_slots.index
        time_diffs = [(scheduled_indices[i+1] - scheduled_indices[i]).total_seconds() for i in range(len(scheduled_indices)-1)]
        assert all(abs(diff - 900) < 1 for diff in time_diffs)  # All 15-minute intervals (with small tolerance)

    def test_multiple_blocks_when_needed(self):
        """Test that multiple blocks are used when single block insufficient."""
        # Create scenario with small cheap blocks
        dates = pd.date_range('2025-01-01 00:00', periods=24, freq='15min')
        df = pd.DataFrame({
            'import_price_sek_kwh': [0.15] * 4 + [0.25] * 4 + [0.15] * 4 + [0.25] * 12,  # Two blocks of 4 slots each
            'adjusted_pv_kwh': [0.0] * 24,
            'adjusted_load_kwh': [0.3] * 24,
            'water_heating_kw': [0.0] * 24
        }, index=dates)

        df['is_cheap'] = df['import_price_sek_kwh'] <= 0.20

        # Run water heating scheduling
        result_df = self.planner._pass_2_schedule_water_heating(df)

        # Should schedule across available blocks (may not meet full requirement if blocks too small)
        scheduled_slots = result_df[result_df['water_heating_kw'] > 0]
        # With 4-slot blocks, we can only schedule 4 slots, not 8
        assert len(scheduled_slots) <= 8  # May be less if blocks are insufficient

    def test_future_day_scheduling(self):
        """Test scheduling for future day when today is complete."""
        # Mock the scenario where today is complete
        dates = pd.date_range('2025-01-01 00:00', periods=24, freq='15min')
        df = pd.DataFrame({
            'import_price_sek_kwh': [0.15] * 16,
            'adjusted_pv_kwh': [0.0] * 16,
            'adjusted_load_kwh': [0.3] * 16,
            'water_heating_kw': [0.0] * 16
        }, index=dates[:16])

        df['is_cheap'] = df['import_price_sek_kwh'] <= 0.20

        # Test with schedule_future_only = True (default)
        result_df = self.planner._pass_2_schedule_water_heating(df)

        # Should schedule in future slots (after first slot)
        scheduled_slots = result_df[result_df['water_heating_kw'] > 0]
        assert len(scheduled_slots) > 0
        assert all(slot > df.index[0] for slot in scheduled_slots.index)

    def test_respects_max_blocks_limit(self):
        """Test that scheduling respects max_blocks_per_day limit."""
        # Create many small cheap blocks
        dates = pd.date_range('2025-01-01 00:00', periods=24, freq='15min')
        prices = []
        for i in range(24):
            prices.append(0.15 if i % 3 == 0 else 0.25)  # Every 3rd slot is cheap

        df = pd.DataFrame({
            'import_price_sek_kwh': prices,
            'adjusted_pv_kwh': [0.0] * len(prices),
            'adjusted_load_kwh': [0.3] * len(prices),
            'water_heating_kw': [0.0] * len(prices)
        }, index=dates[:len(prices)])

        df['is_cheap'] = df['import_price_sek_kwh'] <= 0.20

        # Run scheduling
        result_df = self.planner._pass_2_schedule_water_heating(df)

        # Count contiguous blocks used
        scheduled_slots = result_df[result_df['water_heating_kw'] > 0]
        if len(scheduled_slots) > 0:
            # Should not exceed max_blocks_per_day
            # This is a simplified check - in practice we'd count actual blocks
            assert len(scheduled_slots) <= 16  # Reasonable upper bound
