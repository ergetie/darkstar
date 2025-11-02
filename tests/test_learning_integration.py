import json
import math
import os
import sqlite3

import pandas as pd
import pytest

from planner import HeliosPlanner


@pytest.fixture
def tmp_planner(tmp_path, monkeypatch):
    db_path = tmp_path / "planner_learning.db"
    schedule_dir = tmp_path / "output"
    schedule_dir.mkdir()
    monkeypatch.chdir(schedule_dir)

    config = {
        'learning': {
            'enable': True,
            'sqlite_path': str(db_path),
            'sync_interval_minutes': 5,
        },
        'debug': {
            'enable_planner_debug': True,
            'sample_size': 2,
        },
        'battery': {
            'capacity_kwh': 10.0,
            'min_soc_percent': 15,
            'max_soc_percent': 95,
            'roundtrip_efficiency_percent': 95.0,
            'max_charge_power_kw': 5.0,
            'max_discharge_power_kw': 5.0,
        },
        'battery_economics': {
            'battery_cycle_cost_kwh': 0.20,
        },
        'decision_thresholds': {
            'battery_use_margin_sek': 0.10,
            'battery_water_margin_sek': 0.20,
        },
        'arbitrage': {
            'enable_export': False,
        },
    }

    planner = HeliosPlanner.__new__(HeliosPlanner)
    planner.config = config
    planner.timezone = 'Europe/Stockholm'
    planner.battery_config = config['battery']
    planner.thresholds = config['decision_thresholds']
    planner.charging_strategy = {
        'charge_threshold_percentile': 15,
        'cheap_price_tolerance_sek': 0.1,
        'price_smoothing_sek_kwh': 0.05,
    }
    planner.strategic_charging = {}
    planner.water_heating_config = {'power_kw': 3.0, 'min_hours_per_day': 2.0}
    planner.battery_economics = config['battery_economics']
    planner.learning_config = config['learning']
    planner._learning_schema_initialized = False
    planner.daily_pv_forecast = {}
    planner.daily_load_forecast = {}
    planner._last_temperature_forecast = {}
    planner.forecast_meta = {}

    roundtrip_percent = planner.battery_config['roundtrip_efficiency_percent'] / 100.0
    efficiency_component = math.sqrt(roundtrip_percent)
    planner.roundtrip_efficiency = roundtrip_percent
    planner.charge_efficiency = efficiency_component
    planner.discharge_efficiency = efficiency_component
    planner.cycle_cost = config['battery_economics']['battery_cycle_cost_kwh']
    planner.state = {
        'battery_kwh': 5.0,
        'battery_cost_sek_per_kwh': 0.2,
    }

    return planner


def test_debug_payload_persisted(tmp_planner):
    dates = pd.date_range('2025-01-01', periods=2, freq='15min', tz='Europe/Stockholm')
    schedule_df = pd.DataFrame(
        {
            'end_time': dates + pd.Timedelta(minutes=15),
            'import_price_sek_kwh': [0.15, 0.35],
            'export_price_sek_kwh': [0.10, 0.40],
            'pv_forecast_kwh': [0.2, 0.1],
            'adjusted_pv_kwh': [0.2, 0.1],
            'adjusted_load_kwh': [0.3, 0.4],
            'is_cheap': [True, False],
            'water_heating_kw': [0.0, 0.0],
            'simulated_soc_kwh': [5.0, 5.0],
            'charge_kw': [0.0, 0.0],
            'action': ['Hold', 'Hold'],
            'projected_soc_kwh': [5.0, 5.0],
            'projected_soc_percent': [50.0, 50.0],
            'projected_battery_cost': [0.2, 0.2],
            'water_from_pv_kwh': [0.0, 0.0],
            'water_from_battery_kwh': [0.0, 0.0],
            'water_from_grid_kwh': [0.0, 0.0],
            'export_kwh': [0.0, 0.0],
            'export_revenue': [0.0, 0.0],
        },
        index=dates,
    )
    schedule_df.index.name = 'start_time'

    tmp_planner._save_schedule_to_json(schedule_df.copy())

    db_path = tmp_planner.learning_config['sqlite_path']
    assert os.path.exists(db_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT payload FROM planner_debug ORDER BY id DESC LIMIT 1").fetchone()
        assert row is not None
        payload = json.loads(row[0])
        assert 'metrics' in payload
        assert 'windows' in payload
