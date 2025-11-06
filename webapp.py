import json
import os
import shutil
import sqlite3
from datetime import datetime

import pandas as pd
import pytz
import yaml
from flask import Flask, jsonify, render_template, request
import pymysql
import subprocess

from planner import HeliosPlanner, dataframe_to_json_response, simulate_schedule
from db_writer import write_schedule_to_db
from inputs import (
    get_all_input_data,
    _get_load_profile_from_ha,
    get_home_assistant_sensor_float,
    load_home_assistant_config,
)
from learning import get_learning_engine

app = Flask(__name__)

THEME_DIR = os.path.join(os.path.dirname(__file__), "themes")


def _parse_legacy_theme_format(text: str) -> dict:
    """Parse simple key/value themes with `palette = index=#hex` lines."""
    palette = [None] * 16
    data = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if "=" in line:
            key, value = line.split("=", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            continue

        key = key.strip()
        value = value.strip()

        if key.lower() == "palette":
            if "=" in value:
                idx_str, color = value.split("=", 1)
                idx = int(idx_str.strip())
                color = color.strip()
            else:
                # Allow sequential palette entries without explicit index.
                try:
                    idx = palette.index(None)
                except ValueError as exc:
                    raise ValueError("Too many palette entries") from exc
                color = value

            if idx < 0 or idx > 15:
                raise ValueError(f"Palette index {idx} out of range 0-15")
            palette[idx] = color
        else:
            data[key.lower().replace("-", "_")] = value

    if any(swatch is None for swatch in palette):
        raise ValueError("Palette must define 16 colours (indices 0-15)")

    data["palette"] = palette
    return data


def _normalise_theme(name: str, raw_data: dict) -> dict:
    """Ensure theme dictionaries contain the expected keys."""
    if not isinstance(raw_data, dict):
        raise ValueError("Theme data must be a mapping")

    palette = raw_data.get("palette")
    if not isinstance(palette, (list, tuple)) or len(palette) != 16:
        raise ValueError("Palette must contain exactly 16 colours")

    def _clean_colour(value, key):
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        value = value.strip()
        if not value.startswith("#"):
            raise ValueError(f"{key} must be a hex colour starting with #")
        return value

    palette = [_clean_colour(colour, f"palette[{idx}]") for idx, colour in enumerate(palette)]
    foreground = _clean_colour(raw_data.get("foreground", "#ffffff"), "foreground")
    background = _clean_colour(raw_data.get("background", "#000000"), "background")

    return {
        "name": name,
        "foreground": foreground,
        "background": background,
        "palette": palette,
    }


def _load_theme_file(path: str) -> dict:
    """Load a single theme file supporting JSON, YAML, and legacy key/value formats."""
    with open(path, "r") as handle:
        text = handle.read()

    filename = os.path.basename(path)
    try:

        if filename.lower().endswith(".json"):
            raw_data = json.loads(text)
        elif filename.lower().endswith((".yaml", ".yml")):
            raw_data = yaml.safe_load(text)
        else:
            raw_data = _parse_legacy_theme_format(text)
    except Exception as exc:
        raise ValueError(f"Failed to parse theme '{filename}': {exc}") from exc

    return _normalise_theme(os.path.splitext(filename)[0] or filename, raw_data)


def load_themes(theme_dir: str = THEME_DIR) -> dict:
    """Scan the themes directory and load all available themes."""
    themes = {}
    if not os.path.isdir(theme_dir):
        return themes

    for entry in sorted(os.listdir(theme_dir)):
        path = os.path.join(theme_dir, entry)
        if not os.path.isfile(path):
            continue
        try:
            theme = _load_theme_file(path)
        except Exception as exc:
            # Skip invalid themes but log to stdout for operator visibility.
            print(f"[theme] Skipping '{entry}': {exc}")
            continue
        themes[theme["name"]] = theme
    return themes


AVAILABLE_THEMES = load_themes()


def get_current_theme_name() -> str:
    """Return the theme stored in config.yaml if available."""
    try:
        with open("config.yaml", "r") as handle:
            config = yaml.safe_load(handle) or {}
    except FileNotFoundError:
        config = {}
    ui_section = config.get("ui", {})
    selected = ui_section.get("theme")
    if selected in AVAILABLE_THEMES:
        return selected
    return next(iter(AVAILABLE_THEMES.keys()), None)

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/themes', methods=['GET'])
def list_themes():
    """Return all available themes and the currently selected theme."""
    global AVAILABLE_THEMES
    AVAILABLE_THEMES = load_themes()
    current_name = get_current_theme_name()
    accent_index = None
    try:
        with open("config.yaml", "r") as handle:
            config = yaml.safe_load(handle) or {}
            accent_index = config.get("ui", {}).get("theme_accent_index")
    except FileNotFoundError:
        pass
    try:
        accent_index = int(accent_index)
    except (TypeError, ValueError):
        accent_index = None
    return jsonify({
        "current": current_name,
        "accent_index": accent_index,
        "themes": list(AVAILABLE_THEMES.values()),
    })


@app.route('/api/theme', methods=['POST'])
def select_theme():
    """Persist a selected theme to config.yaml."""
    global AVAILABLE_THEMES
    AVAILABLE_THEMES = load_themes()

    payload = request.get_json(silent=True) or {}
    theme_name = payload.get("theme")
    if theme_name not in AVAILABLE_THEMES:
        return jsonify({"error": f"Theme '{theme_name}' not found"}), 404
    accent_index = payload.get("accent_index")
    try:
        accent_index = int(accent_index) if accent_index is not None else None
    except (TypeError, ValueError):
        accent_index = None
    if accent_index is not None and not 0 <= accent_index <= 15:
        return jsonify({"error": "accent_index must be between 0 and 15"}), 400

    try:
        with open("config.yaml", "r") as handle:
            config = yaml.safe_load(handle) or {}
    except FileNotFoundError:
        config = {}

    ui_section = config.setdefault("ui", {})
    ui_section["theme"] = theme_name
    if accent_index is not None:
        ui_section["theme_accent_index"] = accent_index

    with open("config.yaml", "w") as handle:
        yaml.safe_dump(config, handle, default_flow_style=False)

    return jsonify({
        "status": "success",
        "current": theme_name,
        "accent_index": accent_index,
        "theme": AVAILABLE_THEMES[theme_name],
    })


@app.route('/api/schedule')
def get_schedule():
    with open('schedule.json', 'r') as f:
        data = json.load(f)
    
    # Add price overlay for historical slots if missing
    if 'schedule' in data:
        # Build price map using same logic as /api/db/current_schedule
        price_map = {}
        try:
            from inputs import get_nordpool_data
            price_slots = get_nordpool_data('config.yaml')
            tz = pytz.timezone('Europe/Stockholm')
            for p in price_slots:
                st = p['start_time']
                if st.tzinfo is None:
                    st_local_naive = tz.localize(st).replace(tzinfo=None)
                else:
                    st_local_naive = st.astimezone(tz).replace(tzinfo=None)
                price_map[st_local_naive] = float(p.get('import_price_sek_kwh') or 0.0)
        except Exception as exc:
            print(f"[api/schedule] price overlay unavailable: {exc}")
        
        # Overlay prices for slots that don't have them
        for slot in data['schedule']:
            if 'import_price_sek_kwh' not in slot:
                try:
                    start_str = slot.get('start_time')
                    if start_str:
                        start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                        local_naive = start if start.tzinfo is None else start.astimezone(tz).replace(tzinfo=None)
                        price = price_map.get(local_naive)
                        if price is not None:
                            slot['import_price_sek_kwh'] = round(price, 4)
                except Exception:
                    pass
    
    return jsonify(data)


def _load_yaml(path: str) -> dict:
    try:
        with open(path, 'r') as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def _db_connect_from_secrets():
    secrets = _load_yaml('secrets.yaml')
    db = secrets.get('mariadb', {})
    if not db:
        raise RuntimeError('MariaDB credentials not found in secrets.yaml')
    return pymysql.connect(
        host=db.get('host', '127.0.0.1'),
        port=int(db.get('port', 3306)),
        user=db.get('user'),
        password=db.get('password'),
        database=db.get('database'),
        charset='utf8mb4',
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


@app.route('/api/status', methods=['GET'])
def planner_status():
    """Return last plan info from local schedule.json and MariaDB plan_history if available."""
    status = {
        'local': None,
        'db': None,
        'current_soc': None,
    }
    # Local schedule.json
    try:
        with open('schedule.json', 'r') as f:
            payload = json.load(f)
        meta = payload.get('meta', {})
        status['local'] = {
            'planned_at': meta.get('planned_at'),
            'planner_version': meta.get('planner_version'),
        }
    except Exception:
        pass
    
    # Current SoC from Home Assistant
    try:
        from inputs import get_initial_state
        initial_state = get_initial_state()
        if initial_state and 'battery_soc_percent' in initial_state:
            status['current_soc'] = {
                'value': initial_state['battery_soc_percent'],
                'timestamp': datetime.now().isoformat(),
                'source': 'home_assistant'
            }
    except Exception:
        pass

    # Database last plan
    try:
        with _db_connect_from_secrets() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT planned_at, planner_version FROM plan_history ORDER BY planned_at DESC LIMIT 1"
                )
                row = cur.fetchone()
                if row:
                    status['db'] = {
                        'planned_at': row.get('planned_at').isoformat() if row.get('planned_at') else None,
                        'planner_version': row.get('planner_version'),
                    }
    except Exception as exc:
        status['db'] = {'error': str(exc)}

    return jsonify(status)


@app.route('/api/db/current_schedule', methods=['GET'])
def db_current_schedule():
    """Return the current_schedule from MariaDB in the same shape used by the UI."""
    try:
        config = _load_yaml('config.yaml')
        resolution_minutes = int(config.get('nordpool', {}).get('resolution_minutes', 15))
        tz_name = config.get('timezone', 'Europe/Stockholm')
        tz = pytz.timezone(tz_name)

        with _db_connect_from_secrets() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT slot_number, slot_start, charge_kw, export_kw, water_kw,
                           planned_load_kwh, planned_pv_kwh,
                           soc_target, soc_projected, classification, planner_version
                    FROM current_schedule
                    ORDER BY slot_number ASC
                    """
                )
                rows = cur.fetchall() or []

        # Build a price map keyed by local naive start time so DB rows get price overlays
        price_map = {}
        try:
            from inputs import get_nordpool_data
            price_slots = get_nordpool_data('config.yaml')
            for p in price_slots:
                st = p['start_time']
                if st.tzinfo is None:
                    st_local_naive = tz.localize(st).replace(tzinfo=None)
                else:
                    st_local_naive = st.astimezone(tz).replace(tzinfo=None)
                price_map[st_local_naive] = float(p.get('import_price_sek_kwh') or 0.0)
        except Exception as exc:
            print(f"[api/db/current_schedule] price overlay unavailable: {exc}")

        schedule = []
        for r in rows:
            start = r['slot_start']
            # slot_start is DATETIME; compute end_time from resolution
            try:
                end = start + pd.Timedelta(minutes=resolution_minutes)
            except Exception:
                # Fallback if not datetime (string), try parse
                start_dt = datetime.fromisoformat(str(start))
                end = start_dt + pd.Timedelta(minutes=resolution_minutes)
                start = start_dt

            record = {
                'slot_number': r.get('slot_number'),
                'start_time': start.isoformat(),
                'end_time': end.isoformat(),
                'battery_charge_kw': round(float(r.get('charge_kw') or 0.0), 2),
                # DB stores export in kW; UI expects export_kwh (15-min → kWh = kW/4)
                'export_kwh': round(float(r.get('export_kw') or 0.0) / 4.0, 4),
                'water_heating_kw': round(float(r.get('water_kw') or 0.0), 2),
                'load_forecast_kwh': round(float(r.get('planned_load_kwh') or 0.0), 4),
                'pv_forecast_kwh': round(float(r.get('planned_pv_kwh') or 0.0), 4),
                'soc_target_percent': round(float(r.get('soc_target') or 0.0), 2),
                'projected_soc_percent': round(float(r.get('soc_projected') or 0.0), 2),
                'classification': str(r.get('classification') or 'hold').lower(),
            }
            # Overlay import price if available
            try:
                local_naive = start if start.tzinfo is None else start.astimezone(tz).replace(tzinfo=None)
                price = price_map.get(local_naive)
                if price is not None:
                    record['import_price_sek_kwh'] = round(price, 4)
            except Exception:
                pass
            schedule.append(record)

        meta = {
            'source': 'mariadb',
            'planner_version': rows[0]['planner_version'] if rows else None,
        }
        return jsonify({'schedule': schedule, 'meta': meta})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/db/push_current', methods=['POST'])
def db_push_current():
    """Write the current local schedule.json to MariaDB regardless of automation toggles."""
    try:
        config = _load_yaml('config.yaml')
        secrets = _load_yaml('secrets.yaml')
        # Determine a sensible planner_version fallback for when meta is missing
        fallback_version = config.get('version')
        if not fallback_version:
            try:
                # Prefer tags, else short SHA; mark dirty if needed
                fallback_version = subprocess.check_output(
                    ['git', 'describe', '--tags', '--always', '--dirty'],
                    stderr=subprocess.DEVNULL
                ).decode().strip()
            except Exception:
                fallback_version = 'dev'

        inserted = write_schedule_to_db('schedule.json', fallback_version, config, secrets)
        return jsonify({'status': 'success', 'rows': inserted})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/schedule/save', methods=['POST'])
def save_schedule_json():
    """Persist a provided schedule payload to schedule.json with meta, preserving historical slots."""
    try:
        payload = request.get_json(silent=True) or {}
        manual_schedule = payload.get('schedule') if isinstance(payload, dict) else None
        if manual_schedule is None and isinstance(payload, list):
            manual_schedule = payload
        if not isinstance(manual_schedule, list):
            return jsonify({'status': 'error', 'error': 'Invalid schedule payload'}), 400

        # Preserve historical slots from database (same logic as planner.py Rev 19)
        try:
            from db_writer import get_preserved_slots
            import pytz
            
            tz = pytz.timezone('Europe/Stockholm')
            now = datetime.now(tz)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Load secrets for DB access
            secrets = _load_yaml('secrets.yaml')
            existing_past_slots = get_preserved_slots(today_start, now, secrets)
            
            # Fix slot number conflicts: ensure manual slots continue from max historical slot number
            max_historical_slot = 0
            if existing_past_slots:
                max_historical_slot = max(slot.get('slot_number', 0) for slot in existing_past_slots)
            
            # Reassign slot numbers for manual records to continue from historical max
            for i, record in enumerate(manual_schedule):
                record['slot_number'] = max_historical_slot + i + 1
            
            # Merge: preserved past + manual (same as planner.py)
            merged_schedule = existing_past_slots + manual_schedule
            
        except Exception as e:
            print(f"[webapp] Warning: Could not preserve historical slots for manual changes: {e}")
            # Fallback to manual schedule only if preservation fails
            merged_schedule = manual_schedule

        # Build meta with version + timestamp
        try:
            version = subprocess.check_output(
                ['git', 'describe', '--tags', '--always', '--dirty'],
                stderr=subprocess.DEVNULL
            ).decode().strip()
        except Exception:
            version = 'dev'

        out = {
            'schedule': merged_schedule,
            'meta': {
                'planned_at': datetime.now().isoformat(),
                'planner_version': version,
            }
        }
        with open('schedule.json', 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500

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
            if slot.get('pv_forecast_kwh') is not None:
                pv_dates.add(d)
            if slot.get('load_forecast_kwh') is not None:
                load_dates.add(d)

        debug = data.get('debug', {})
        s_index = debug.get('s_index', {})
        considered_days = s_index.get('considered_days')

        forecast_meta = data.get('meta', {}).get('forecast', {})

        return jsonify({
            'total_days_in_schedule': len(dates),
            'days_list': sorted(list(dates)),
            'pv_days_schedule': len(pv_dates),
            'load_days_schedule': len(load_dates),
            'pv_forecast_days': forecast_meta.get('pv_forecast_days'),
            'weather_forecast_days': forecast_meta.get('weather_forecast_days'),
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
                "source": "home_assistant",
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
                        "source": "sqlite",
                        "water_kwh_today": round(float(row[0]), 2)
                    })

        return jsonify({"source": "unknown", "water_kwh_today": None})
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
        df['manual_action'] = None
        
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
            elif action in ('Hold', 'Export'):
                # No direct power assignment, but tag manual intent
                pass

            if action:
                df.loc[mask, 'manual_action'] = action

        # Step D: Run the simulation
        print("Running simulation with the user's manual plan...")
        simulated_df = simulate_schedule(df, config_data, initial_state)
        print("Simulation completed successfully.")

        # Step E: Persist and return the full, simulated result
        json_response = dataframe_to_json_response(simulated_df)
        # Save immediately so subsequent actions and DB push see the updated plan
        try:
            version = subprocess.check_output(
                ['git', 'describe', '--tags', '--always', '--dirty'],
                stderr=subprocess.DEVNULL
            ).decode().strip()
        except Exception:
            version = 'dev'
        with open('schedule.json', 'w', encoding='utf-8') as f:
            json.dump({
                'schedule': json_response,
                'meta': {
                    'planned_at': datetime.now().isoformat(),
                    'planner_version': version,
                }
            }, f, ensure_ascii=False, indent=2)

        return jsonify({"schedule": json_response})

    except Exception as e:
        # This is the critical error handling that was missing
        import traceback
        print("---! SIMULATION FAILED !---")
        print(traceback.format_exc())
        return jsonify({"status": "error", "message": f"Simulation failed: {str(e)}"}), 500


@app.route('/api/learning/status', methods=['GET'])
def learning_status():
    """Return learning engine status and metrics."""
    try:
        engine = get_learning_engine()
        status = engine.get_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/learning/changes', methods=['GET'])
def learning_changes():
    """Return recent learning configuration changes."""
    try:
        engine = get_learning_engine()
        
        # Get recent config changes
        with sqlite3.connect(engine.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, created_at, reason, applied, metrics_json
                FROM config_versions
                ORDER BY created_at DESC
                LIMIT 10
            """)
            
            changes = []
            for row in cursor.fetchall():
                change = {
                    'id': row[0],
                    'created_at': row[1],
                    'reason': row[2],
                    'applied': bool(row[3]),
                    'metrics': json.loads(row[4]) if row[4] else None
                }
                changes.append(change)
        
        return jsonify({'changes': changes})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/learning/run', methods=['POST'])
def learning_run():
    """Trigger learning orchestration manually."""
    try:
        engine = get_learning_engine()
        from learning import NightlyOrchestrator
        
        orchestrator = NightlyOrchestrator(engine)
        result = orchestrator.run_nightly_job()
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/learning/loops', methods=['GET'])
def learning_loops():
    """Get status of individual learning loops."""
    try:
        engine = get_learning_engine()
        from learning import LearningLoops
        
        loops = LearningLoops(engine)
        
        # Test each loop
        results = {}
        
        # Forecast calibrator
        fc_result = loops.forecast_calibrator()
        results['forecast_calibrator'] = {
            'status': 'has_changes' if fc_result else 'no_changes',
            'result': fc_result
        }
        
        # Threshold tuner
        tt_result = loops.threshold_tuner()
        results['threshold_tuner'] = {
            'status': 'has_changes' if tt_result else 'no_changes',
            'result': tt_result
        }
        
        # S-index tuner
        si_result = loops.s_index_tuner()
        results['s_index_tuner'] = {
            'status': 'has_changes' if si_result else 'no_changes',
            'result': si_result
        }
        
        # Export guard tuner
        eg_result = loops.export_guard_tuner()
        results['export_guard_tuner'] = {
            'status': 'has_changes' if eg_result else 'no_changes',
            'result': eg_result
        }
        
        return jsonify(results)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/debug', methods=['GET'])
def debug_data():
    """Return comprehensive planner debug data from schedule.json."""
    try:
        with open('schedule.json', 'r') as f:
            data = json.load(f)
        
        debug_section = data.get('debug', {})
        if not debug_section:
            return jsonify({"error": "No debug data available. Enable debug mode in config.yaml with enable_planner_debug: true"}), 404
        
        return jsonify(debug_section)
        
    except FileNotFoundError:
        return jsonify({"error": "schedule.json not found. Run the planner first."}), 404




@app.route('/api/history/soc', methods=['GET'])
def historic_soc():
    """Return historic SoC data for today from learning database."""
    try:
        date_param = request.args.get('date', 'today')
        
        # Determine target date
        if date_param == 'today':
            target_date = datetime.now(pytz.timezone('Europe/Stockholm')).date()
        else:
            try:
                target_date = datetime.strptime(date_param, '%Y-%m-%d').date()
            except ValueError:
                return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD or "today"'}), 400
        
        # Get learning engine and query historic SoC data
        engine = get_learning_engine()
        
        with sqlite3.connect(engine.db_path) as conn:
            query = """
                SELECT slot_start, soc_end_percent, quality_flags
                FROM slot_observations
                WHERE DATE(slot_start) = ?
                  AND soc_end_percent IS NOT NULL
                ORDER BY slot_start ASC
            """
            rows = conn.execute(query, (target_date.isoformat(),)).fetchall()
        
        if not rows:
            return jsonify({
                'date': target_date.isoformat(),
                'slots': [],
                'message': 'No historical SoC data available for this date'
            })
        
        # Convert to JSON format
        slots = []
        for row in rows:
            slots.append({
                'timestamp': row[0],
                'soc_percent': row[1],
                'quality_flags': row[2] or ''
            })
        
        return jsonify({
            'date': target_date.isoformat(),
            'slots': slots,
            'count': len(slots)
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to fetch historical SoC data: {str(e)}'}), 500


def record_observation_from_current_state():
    """Record current system state as observation for learning engine."""
    try:
        from learning import get_learning_engine
        import pandas as pd
        from datetime import datetime, timedelta
        import pytz
        
        engine = get_learning_engine()
        if not engine.learning_config.get('enable', False):
            return  # Learning disabled
        
        # Get current time in local timezone
        tz = pytz.timezone(engine.config.get('timezone', 'Europe/Stockholm'))
        now = datetime.now(tz)
        
        # Get current system state
        try:
            from inputs import get_initial_state
            initial_state = get_initial_state()
            
            if not initial_state:
                return  # No data available
            
            # Create observation record
            current_slot_start = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
            current_slot_end = current_slot_start + timedelta(minutes=15)
            
            # Check if observation already exists for this slot
            with sqlite3.connect(engine.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*) FROM slot_observations 
                    WHERE slot_start = ? AND soc_end_percent IS NOT NULL
                """, (current_slot_start.isoformat(),))
                existing_count = cursor.fetchone()[0]
                
                if existing_count > 0:
                    print(f"[learning] Observation already exists for slot {current_slot_start.isoformat()}")
                    return  # Skip if already recorded
                
            observation = {
                'slot_start': current_slot_start.isoformat(),
                'slot_end': current_slot_end.isoformat(),
                'import_kwh': 0.0,
                'export_kwh': 0.0,
                'pv_kwh': 0.0,
                'load_kwh': 0.0,
                'water_kwh': 0.0,
                'batt_charge_kwh': 0.0,
                'batt_discharge_kwh': 0.0,
                'soc_start_percent': initial_state.get('battery_soc_percent', 0),
                'soc_end_percent': initial_state.get('battery_soc_percent', 0),
                'import_price_sek_kwh': 0.0,
                'export_price_sek_kwh': 0.0,
                'quality_flags': 'auto_recorded'
            }
            
            # Create DataFrame and store observation
            observations_df = pd.DataFrame([observation])
            engine.store_slot_observations(observations_df)
            print(f"[learning] Recorded observation for slot {current_slot_start.isoformat()}: {initial_state.get('battery_soc_percent', 0)}%")
            
            print(f"[learning] Recorded observation for slot {current_slot_start.isoformat()}")
            
        except Exception as e:
            print(f"[learning] Failed to record observation: {e}")
            
    except Exception as e:
        print(f"[learning] Error in record_observation_from_current_state: {e}")


@app.route('/api/learning/record_observation', methods=['POST'])
def record_observation():
    """Trigger observation recording from current system state."""
    try:
        record_observation_from_current_state()
        return jsonify({'status': 'success', 'message': 'Observation recorded'})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500

# Set up automatic observation recording
import threading

def setup_auto_observation_recording():
    """Set up automatic observation recording every 15 minutes."""
    def record_observation_loop():
        while True:
            try:
                record_observation_from_current_state()
            except Exception as e:
                print(f"[auto-observation] Error in recording loop: {e}")
            # Sleep for 15 minutes (900 seconds)
            import time
            time.sleep(900)
    
    # Start the recording thread
    recording_thread = threading.Thread(target=record_observation_loop, daemon=True)
    recording_thread.start()
    print("[auto-observation] Started automatic observation recording thread")

@app.route('/debug-log', methods=['POST'])
def debug_log():
    """Receive debug logs from browser for troubleshooting."""
    try:
        data = request.get_json()
        message = data.get('message', '')
        timestamp = data.get('timestamp', '')
        
        # Log to console and file
        log_message = f"[Browser Debug] {timestamp}: {message}"
        print(log_message)
        
        # Also append to debug log file
        with open('browser_debug.log', 'a') as f:
            f.write(log_message + '\n')
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Start automatic recording when webapp starts
setup_auto_observation_recording()
