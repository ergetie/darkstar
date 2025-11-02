from datetime import datetime
import json
import os
import shutil
import sqlite3

import pandas as pd
import pytz
import yaml
from flask import Flask, jsonify, render_template, request

from planner import HeliosPlanner, dataframe_to_json_response, simulate_schedule
from inputs import (
    get_all_input_data,
    _get_load_profile_from_ha,
    get_home_assistant_sensor_float,
    load_home_assistant_config,
)

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/schedule')
def get_schedule():
    with open('schedule.json', 'r') as f:
        data = json.load(f)
    return jsonify(data)

@app.route('/api/config', methods=['GET'])
def get_config():
    with open('config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    return jsonify(config)

@app.route('/api/initial_state', methods=['GET'])
def get_initial_state():
    try:
        from inputs import get_initial_state
        initial_state = get_initial_state()
        return jsonify(initial_state)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/save', methods=['POST'])
def save_config():
    # Load current config first
    with open('config.yaml', 'r') as f:
        current_config = yaml.safe_load(f)
    
    # Get the new config data from the request
    new_config = request.get_json()
    
    # Deep merge the new config into the current config
    def deep_merge(current, new):
        for key, value in new.items():
            if key in current and isinstance(current[key], dict) and isinstance(value, dict):
                deep_merge(current[key], value)
            else:
                current[key] = value
        return current
    
    merged_config = deep_merge(current_config, new_config)
    
    # Ensure critical defaults are preserved
    if 'nordpool' not in merged_config:
        merged_config['nordpool'] = {}
    if 'resolution_minutes' not in merged_config['nordpool']:
        merged_config['nordpool']['resolution_minutes'] = 15
    if 'price_area' not in merged_config['nordpool']:
        merged_config['nordpool']['price_area'] = 'SE4'
    if 'currency' not in merged_config['nordpool']:
        merged_config['nordpool']['currency'] = 'SEK'
    
    with open('config.yaml', 'w') as f:
        yaml.dump(merged_config, f, default_flow_style=False)
    return jsonify({'status': 'success'})

@app.route('/api/config/reset', methods=['POST'])
def reset_config():
    shutil.copy('config.default.yaml', 'config.yaml')
    return jsonify({'status': 'success'})

@app.route('/api/run_planner', methods=['POST'])
def run_planner():
    try:
        input_data = get_all_input_data()
        planner = HeliosPlanner("config.yaml")
        planner.generate_schedule(input_data)
        return jsonify({"status": "success", "message": "Planner run completed successfully."})
    except Exception as e:
        return jsonify({"status": "error", "message": f"An error occurred: {str(e)}"}), 500

@app.route('/api/ha/average', methods=['GET'])
def ha_average():
    try:
        with open('config.yaml', 'r') as f:
            config = yaml.safe_load(f)
        profile = _get_load_profile_from_ha(config)
        daily_kwh = round(sum(profile), 2)
        avg_kw = round(daily_kwh / 24.0, 2)
        return jsonify({"daily_kwh": daily_kwh, "average_load_kw": avg_kw})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/forecast/horizon', methods=['GET'])
def forecast_horizon():
    """Return information about the forecast horizon based on current schedule.json."""
    try:
        with open('schedule.json', 'r') as f:
            data = json.load(f)
        schedule = data.get('schedule', [])
        tz = pytz.timezone('Europe/Stockholm')
        dates = set()
        pv_dates = set()
        load_dates = set()
        for slot in schedule:
            dt = datetime.fromisoformat(slot['start_time'])
            if dt.tzinfo is None:
                dt = tz.localize(dt)
            else:
                dt = dt.astimezone(tz)
            d = dt.date().isoformat()
            dates.add(d)
            if (slot.get('pv_forecast_kwh') or 0) is not None:
                pv_dates.add(d)
            if (slot.get('load_forecast_kwh') or 0) is not None:
                load_dates.add(d)

        debug = data.get('debug', {})
        s_index = debug.get('s_index', {})
        considered_days = s_index.get('considered_days')

        return jsonify({
            'total_days_in_schedule': len(dates),
            'days_list': sorted(list(dates)),
            'pv_days': len(pv_dates),
            'load_days': len(load_dates),
            's_index_considered_days': considered_days,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/ha/water_today', methods=['GET'])
def ha_water_today():
    """Return today's water heater energy usage from HA or sqlite fallback."""
    try:
        ha_config = load_home_assistant_config()
        entity_id = ha_config.get('water_heater_daily_entity_id', 'sensor.vvb_energy_daily')
        ha_value = get_home_assistant_sensor_float(entity_id) if entity_id else None

        if ha_value is not None:
            return jsonify({
                "water_kwh_today": round(ha_value, 2)
            })

        with open('config.yaml', 'r') as f:
            config = yaml.safe_load(f)

        learning_cfg = config.get('learning', {})
        sqlite_path = learning_cfg.get('sqlite_path', 'data/planner_learning.db')
        timezone_name = config.get('timezone', 'Europe/Stockholm')
        tz = pytz.timezone(timezone_name)
        today_key = datetime.now(tz).date().isoformat()

        if os.path.exists(sqlite_path):
            with sqlite3.connect(sqlite_path) as conn:
                cur = conn.execute(
                    "SELECT used_kwh FROM daily_water WHERE date = ?",
                    (today_key,),
                )
                row = cur.fetchone()
                if row and row[0] is not None:
                    return jsonify({
                        "water_kwh_today": round(float(row[0]), 2)
                    })

        return jsonify({"water_kwh_today": None})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.route('/api/simulate', methods=['POST'])
def simulate():
    print("--- SIMULATION ENDPOINT TRIGGERED ---")
    try:
        # Step A: Get a base DataFrame with all necessary data
        input_data = get_all_input_data()
        
        # Load config manually
        with open('config.yaml', 'r') as f:
            config_data = yaml.safe_load(f)
            
        initial_state = input_data['initial_state']
        
        # Create the full DataFrame
        planner = HeliosPlanner("config.yaml") # Create a temporary planner to use its methods
        df = planner._prepare_data_frame(input_data)
        df = planner._pass_0_apply_safety_margins(df) # Apply safety margins
        df = planner._pass_1_identify_windows(df) # Identify cheap windows (creates is_cheap column)

        # Step B: Clear the schedule-related columns to create a clean slate
        df['charge_kw'] = 0.0
        df['water_heating_kw'] = 0.0
        
        # Step C: "Paint" the user's manual plan onto the DataFrame
        manual_plan = request.get_json()
        print(f"Received manual plan with {len(manual_plan)} items.")

        for item in manual_plan:
            action = item.get('content')
            start_time = pd.to_datetime(item.get('start'))
            end_time = pd.to_datetime(item.get('end'))

            if start_time.tzinfo is None:
                start_time = start_time.tz_localize(config_data['timezone'])
            else:
                start_time = start_time.tz_convert(config_data['timezone'])

            if end_time.tzinfo is None:
                end_time = end_time.tz_localize(config_data['timezone'])
            else:
                end_time = end_time.tz_convert(config_data['timezone'])

            # Find the rows in the DataFrame that fall within this action's time range
            mask = (df.index >= start_time) & (df.index < end_time)
            
            if action == 'Charge':
                df.loc[mask, 'charge_kw'] = config_data['system']['battery']['max_charge_power_kw']
            elif action == 'Water Heating':
                df.loc[mask, 'water_heating_kw'] = config_data['water_heating'].get('power_kw', 3.0)

        # Step D: Run the simulation
        print("Running simulation with the user's manual plan...")
        simulated_df = simulate_schedule(df, config_data, initial_state)
        print("Simulation completed successfully.")

        # Step E: Return the full, simulated result
        json_response = dataframe_to_json_response(simulated_df)
        
        return jsonify({"schedule": json_response})

    except Exception as e:
        # This is the critical error handling that was missing
        import traceback
        print("---! SIMULATION FAILED !---")
        print(traceback.format_exc())
        return jsonify({"status": "error", "message": f"Simulation failed: {str(e)}"}), 500
