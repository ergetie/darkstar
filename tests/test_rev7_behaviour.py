import math
from datetime import timedelta

import pandas as pd
import pytest

from planner import HeliosPlanner


def _build_planner():
    planner = HeliosPlanner.__new__(HeliosPlanner)
    planner.timezone = 'Europe/Stockholm'
    planner.config = {
        'system': {
            'inverter': {'max_power_kw': 8.0},
            'grid': {'max_power_kw': 11.0},
        },
        'arbitrage': {
            'enable_export': True,
            'export_fees_sek_per_kwh': 0.0,
            'export_profit_margin_sek': 0.05,
            'protective_soc_strategy': 'gap_based',
            'fixed_protective_soc_percent': 15.0,
        },
        'learning': {'enable': False},
    }
    planner.battery_config = {
        'capacity_kwh': 10.0,
        'min_soc_percent': 10,
        'max_soc_percent': 50,
        'max_charge_power_kw': 5.0,
        'max_discharge_power_kw': 5.0,
        'roundtrip_efficiency_percent': 95.0,
    }
    planner.thresholds = {
        'battery_use_margin_sek': 0.10,
        'battery_water_margin_sek': 0.20,
    }
    planner.charging_strategy = {
        'charge_threshold_percentile': 15,
        'cheap_price_tolerance_sek': 0.10,
        'price_smoothing_sek_kwh': 0.05,
        'block_consolidation_tolerance_sek': 0.03,
        'consolidation_max_gap_slots': 0,
    }
    planner.strategic_charging = {'target_soc_percent': 95}
    planner.water_heating_config = {
        'power_kw': 3.0,
        'min_kwh_per_day': 6.0,
        'min_hours_per_day': 2.0,
        'max_blocks_per_day': 2,
        'schedule_future_only': True,
        'defer_up_to_hours': 3,
    }
    planner.learning_config = planner.config['learning']
    planner._learning_schema_initialized = False
    planner.window_responsibilities = []
    planner.daily_pv_forecast = {}
    planner.daily_load_forecast = {}
    planner._last_temperature_forecast = {}
    planner.forecast_meta = {}

    planner.roundtrip_efficiency = 0.95
    efficiency_component = math.sqrt(planner.roundtrip_efficiency)
    planner.charge_efficiency = efficiency_component
    planner.discharge_efficiency = efficiency_component
    planner.cycle_cost = 0.20
    planner._max_soc_warning_emitted = False
    return planner


def test_projected_soc_not_forced_below_max():
    planner = _build_planner()
    capacity = planner.battery_config['capacity_kwh']
    planner.battery_config['max_soc_percent'] = 55  # Set low max to expose previous clamp

    starting_soc_percent = 85.0
    planner.state = {
        'battery_kwh': capacity * (starting_soc_percent / 100.0),
        'battery_cost_sek_per_kwh': 0.20,
    }
    planner.window_responsibilities = []

    timestamps = pd.date_range('2025-01-01 00:00', periods=2, freq='15min', tz='Europe/Stockholm')
    planner.now_slot = timestamps[0]

    df = pd.DataFrame(
        {
            'adjusted_pv_kwh': [0.0, 0.0],
            'adjusted_load_kwh': [0.0, 0.0],
            'water_heating_kw': [0.0, 0.0],
            'charge_kw': [0.0, 0.0],
            'import_price_sek_kwh': [0.20, 0.22],
            'export_price_sek_kwh': [0.18, 0.18],
            'is_cheap': [False, False],
        },
        index=timestamps,
    )

    result = planner._pass_6_finalize_schedule(df.copy())
    projected_start = result['projected_soc_percent'].iloc[0]

    assert projected_start == pytest.approx(starting_soc_percent, rel=1e-4)


def test_water_heating_defers_into_next_day():
    planner = _build_planner()
    base_time = pd.Timestamp('2025-05-01 18:00', tz='Europe/Stockholm')
    timestamps = pd.date_range(base_time, periods=48, freq='15min')
    planner.now_slot = base_time

    prices = []
    is_cheap = []
    for ts in timestamps:
        if ts.date() == base_time.date():
            prices.append(0.30)
            is_cheap.append(False)
        else:
            prices.append(0.10)
            is_cheap.append(True)

    df = pd.DataFrame(
        {
            'adjusted_pv_kwh': [0.0] * len(timestamps),
            'adjusted_load_kwh': [0.0] * len(timestamps),
            'import_price_sek_kwh': prices,
            'is_cheap': is_cheap,
        },
        index=timestamps,
    )

    scheduled = planner._pass_2_schedule_water_heating(df.copy())
    future_slots = scheduled[scheduled.index.date > base_time.date()]
    assert (future_slots['water_heating_kw'] > 0).any()

    # With zero deferral we should not plan into tomorrow
    planner.water_heating_config['defer_up_to_hours'] = 0
    scheduled_same_day = planner._pass_2_schedule_water_heating(df.copy())
    future_same_day = scheduled_same_day[scheduled_same_day.index.date > base_time.date()]
    assert not (future_same_day['water_heating_kw'] > 0).any()


def test_charge_consolidation_forms_contiguous_block():
    planner = _build_planner()
    start = pd.Timestamp('2025-02-01 00:00', tz='Europe/Stockholm')
    timestamps = pd.date_range(start, periods=6, freq='15min')
    planner.now_slot = start

    prices = [0.10, 0.12, 0.11, 0.35, 0.09, 0.40]
    df = pd.DataFrame(
        {
            'adjusted_pv_kwh': [0.0] * len(timestamps),
            'adjusted_load_kwh': [0.0] * len(timestamps),
            'water_heating_kw': [0.0] * len(timestamps),
            'import_price_sek_kwh': prices,
            'is_cheap': [True] * len(timestamps),
        },
        index=timestamps,
    )

    total_required_kwh = 3.0  # With 5 kW max charge, this equates to roughly 0.6 h (~3 slots)
    planner.window_responsibilities = [
        {
            'window': {'start': timestamps[0], 'end': timestamps[-1]},
            'total_responsibility_kwh': total_required_kwh,
        }
    ]

    result = planner._pass_5_distribute_charging_in_windows(df.copy())
    charged_slots = [idx for idx in result.index if result.loc[idx, 'charge_kw'] > 0]

    assert charged_slots, "Expected at least one charged slot"
    first = charged_slots[0]
    last = charged_slots[-1]
    expected_span = timedelta(minutes=15 * (len(charged_slots) - 1))
    assert last - first == expected_span, "Charge slots should form a contiguous block"

    total_energy = sum(result.loc[idx, 'charge_kw'] * 0.25 for idx in charged_slots)
    assert total_energy == pytest.approx(total_required_kwh, rel=1e-6)
