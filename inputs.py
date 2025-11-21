from datetime import datetime, timedelta, date
import math
from typing import Any, Dict, Optional, List

import pytz
import requests
import yaml
from nordpool.elspot import Prices
from open_meteo_solar_forecast import OpenMeteoSolarForecast

from ml.api import get_forecast_slots


def load_home_assistant_config() -> Dict[str, Any]:
    """Read Home Assistant configuration from secrets.yaml."""
    try:
        with open("secrets.yaml", "r") as file:
            secrets = yaml.safe_load(file) or {}
    except FileNotFoundError:
        return {}
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"Warning: Could not load secrets.yaml: {exc}")
        return {}

    ha_config = secrets.get("home_assistant")
    if not isinstance(ha_config, dict):
        return {}
    return ha_config


def _make_ha_headers(token: str) -> Dict[str, str]:
    """Return headers for Home Assistant REST calls."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _load_yaml(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def _get_ha_entity_state(entity_id: str, *, timeout: int = 10) -> Optional[Dict[str, Any]]:
    """Fetch a single entity state from Home Assistant."""
    ha_config = load_home_assistant_config()
    url = ha_config.get("url")
    token = ha_config.get("token")

    if not url or not token or not entity_id:
        return None

    endpoint = f"{url.rstrip('/')}/api/states/{entity_id}"
    try:
        response = requests.get(endpoint, headers=_make_ha_headers(token), timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        print(f"Warning: Failed to fetch Home Assistant entity '{entity_id}': {exc}")
        return None


def get_home_assistant_sensor_float(entity_id: str, *, timeout: int = 10) -> Optional[float]:
    """Return the numeric state of a Home Assistant sensor if available."""
    state = _get_ha_entity_state(entity_id, timeout=timeout)
    if not state:
        return None

    raw_value = state.get("state")
    if raw_value in (None, "unknown", "unavailable"):
        return None

    try:
        return float(raw_value)
    except (TypeError, ValueError):
        print(f"Warning: Non-numeric value '{raw_value}' for Home Assistant entity '{entity_id}'")
        return None


def get_home_assistant_bool(entity_id: str, *, timeout: int = 10) -> bool:
    """Return True if entity is 'on', 'true', 'armed', etc."""
    state = _get_ha_entity_state(entity_id, timeout=timeout)
    if not state:
        return False

    raw = str(state.get("state", "")).lower()
    # Common 'on' states in Home Assistant
    true_states = {"on", "true", "yes", "1", "armed_away", "armed_home", "armed_night"}
    return raw in true_states


def get_nordpool_data(config_path="config.yaml"):
    """
    Fetch day-ahead electricity prices from Nordpool for the next 24-47 hours.

    Args:
        config_path (str): Path to the configuration YAML file

    Returns:
        list: List of dictionaries with keys:
            - start_time (datetime): Start time of the price slot (timezone-aware)
            - end_time (datetime): End time of the price slot (timezone-aware)
            - import_price_sek_kwh (float): Price in SEK per kWh
            - export_price_sek_kwh (float): Export price in SEK per kwh (estimated as 90% of import)
    """
    # Load configuration
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    nordpool_config = config.get("nordpool", {})
    price_area = nordpool_config.get("price_area", "SE4")
    currency = nordpool_config.get("currency", "SEK")
    resolution_minutes = nordpool_config.get("resolution_minutes", 60)

    # Initialize Nordpool Prices client with currency
    prices_client = Prices(currency)

    # Fetch today's prices
    try:
        today_data = prices_client.fetch(
            end_date=date.today(), areas=[price_area], resolution=resolution_minutes
        )
    except Exception:
        today_data = {}

    # Fetch tomorrow's prices safely
    try:
        tomorrow_data = prices_client.fetch(areas=[price_area], resolution=resolution_minutes)
    except Exception:
        tomorrow_data = {}

    # Combine data
    today_values = []
    if today_data and today_data.get("areas") and today_data["areas"].get(price_area):
        today_values = today_data["areas"][price_area].get("values", [])

    tomorrow_values = []
    if tomorrow_data and tomorrow_data.get("areas") and tomorrow_data["areas"].get(price_area):
        tomorrow_values = tomorrow_data["areas"][price_area].get("values", [])

    # Use only known market data (do not duplicate unknown future)
    all_entries = today_values + tomorrow_values

    # Process the data into the required format
    result = _process_nordpool_data(all_entries, config, today_values)

    return result


def _process_nordpool_data(all_entries, config, today_values=None):
    """
    Process raw Nordpool API data into the required format.

    Args:
        all_entries (list): Combined list of raw price entries from today and tomorrow
        config (dict): The full configuration dictionary

    Returns:
        list: Processed list of dictionaries with standardized format
    """
    result = []

    # Load pricing configuration
    pricing_config = config.get("pricing", {})
    vat_percent = pricing_config.get("vat_percent", 25.0)
    grid_transfer_fee_sek = pricing_config.get("grid_transfer_fee_sek", 0.2456)
    energy_tax_sek = pricing_config.get("energy_tax_sek", 0.439)

    # Get local timezone
    local_tz = pytz.timezone(config.get("timezone", "Europe/Stockholm"))

    # Process the hourly data
    for i, entry in enumerate(all_entries):
        # Manual timezone conversion
        if today_values is not None and i < len(today_values):
            # Original entries - use their actual timestamps
            start_time = entry["start"].astimezone(local_tz)
            end_time = entry["end"].astimezone(local_tz)
        else:
            # Extended entries - calculate timestamps based on position
            if today_values is not None and len(today_values) > 0:
                base_start = today_values[0]["start"].astimezone(local_tz)
                slot_duration = today_values[0]["end"] - today_values[0]["start"]
                start_time = base_start + (slot_duration * i)
                end_time = start_time + slot_duration
            else:
                # Fallback if no today_values available
                start_time = entry["start"].astimezone(local_tz)
                end_time = entry["end"].astimezone(local_tz)

        # Calculate base spot price (convert from MWh to kWh)
        spot_price_sek_kwh = entry["value"] / 1000.0

        # Export price is exactly the spot price
        export_price_sek_kwh = spot_price_sek_kwh

        # Import price includes all fees and taxes
        import_price_sek_kwh = (spot_price_sek_kwh + grid_transfer_fee_sek + energy_tax_sek) * (
            1 + vat_percent / 100.0
        )

        result.append(
            {
                "start_time": start_time,
                "end_time": end_time,
                "import_price_sek_kwh": import_price_sek_kwh,
                "export_price_sek_kwh": export_price_sek_kwh,
            }
        )

    # Sort by start time to ensure chronological order
    result.sort(key=lambda x: x["start_time"])

    return result


async def get_forecast_data(price_slots, config):
    """
    Generate PV and load forecasts based on price slots and configuration.

    Args:
        price_slots (list): List of price slot dictionaries with start_time
        config (dict): Configuration dictionary containing system parameters

    Returns:
        dict: {
            'slots': [ { 'pv_forecast_kwh': float, 'load_forecast_kwh': float } ... ],
            'daily_pv_forecast': { iso_date: kwh },
            'daily_load_forecast': { iso_date: kwh }
        }
    """
    system_config = config.get("system", {})
    latitude = system_config.get("location", {}).get("latitude", 59.3)
    longitude = system_config.get("location", {}).get("longitude", 18.1)
    kwp = system_config.get("solar_array", {}).get("kwp", 5.0)
    azimuth = system_config.get("solar_array", {}).get("azimuth", 180)
    tilt = system_config.get("solar_array", {}).get("tilt", 30)
    timezone = config.get("timezone", "Europe/Stockholm")
    local_tz = pytz.timezone(timezone)

    forecasting_cfg = config.get("forecasting", {}) or {}
    active_version = forecasting_cfg.get("active_forecast_version", "baseline_7_day_avg")

    # AURORA: DB-backed forecast
    if active_version == "aurora":
        # 1. Build slots strictly for the price horizon (0-48h)
        db_slots = build_db_forecast_for_slots(price_slots, config)
        
        forecast_data: list[dict] = []
        if db_slots:
            print("Info: Using AURORA forecasts from learning DB (aurora).")
            for slot, db_slot in zip(price_slots, db_slots):
                forecast_data.append(
                    {
                        "start_time": slot["start_time"],
                        "pv_forecast_kwh": float(db_slot.get("pv_forecast_kwh", 0.0)),
                        "load_forecast_kwh": float(db_slot.get("load_forecast_kwh", 0.0)),
                    }
                )
        else:
            print("Warning: AURORA slots missing for price horizon. Returning empty slots.")

        # 2. Build DAILY totals for the extended horizon required by S-index
        daily_pv_forecast: dict[str, float] = {}
        daily_load_forecast: dict[str, float] = {}
        
        if price_slots:
            start_dt = price_slots[0]["start_time"].astimezone(local_tz)
            
            # Calculate required horizon based on config
            s_index_cfg = config.get("s_index", {})
            days_list = s_index_cfg.get("days_ahead_for_sindex", [2, 3, 4])
            
            # Handle both list and single integer input types safely
            if isinstance(days_list, list):
                 max_days = max(days_list) if days_list else 4
            else:
                 try:
                     max_days = int(days_list)
                 except (TypeError, ValueError):
                     max_days = 4
                     
            # Ensure we fetch at least enough to cover the config
            horizon_days = max(4, max_days + 1)
            end_dt = start_dt + timedelta(days=horizon_days)
            
            # Fetch extended records from DB
            extended_records = get_forecast_slots(start_dt, end_dt, active_version)
            
            for rec in extended_records:
                ts = rec["slot_start"]
                if ts.tzinfo is None:
                    ts = pytz.UTC.localize(ts)
                date_key = ts.astimezone(local_tz).date().isoformat()
                
                pv_val = float(rec.get("pv_forecast_kwh", 0.0) or 0.0)
                load_val = float(rec.get("load_forecast_kwh", 0.0) or 0.0)
                
                daily_pv_forecast[date_key] = daily_pv_forecast.get(date_key, 0.0) + pv_val
                daily_load_forecast[date_key] = daily_load_forecast.get(date_key, 0.0) + load_val

        return {
            "slots": forecast_data,
            "daily_pv_forecast": daily_pv_forecast,
            "daily_load_forecast": daily_load_forecast,
        }

    # --- FALLBACK: Open-Meteo (Live API) ---
    pv_kwh_forecast: list[float] = []
    daily_pv_forecast: dict[str, float] = {}
    resolution_hours = 0.25

    try:
        async def _fetch_forecast():
            async with OpenMeteoSolarForecast(
                latitude=latitude,
                longitude=longitude,
                declination=tilt,
                azimuth=azimuth,
                dc_kwp=kwp,
            ) as forecast:
                estimate = await forecast.estimate()
                return estimate.watts

        solar_data_dict = await _fetch_forecast()
        if solar_data_dict:
            sorted_times = sorted(solar_data_dict.keys())
            if len(sorted_times) > 1:
                delta_seconds = abs((sorted_times[1] - sorted_times[0]).total_seconds())
                resolution_hours = max(delta_seconds / 3600.0, 0.0001)
            for dt in sorted_times:
                value = solar_data_dict[dt]
                dt_obj = dt
                if dt_obj.tzinfo is None:
                    dt_obj = pytz.UTC.localize(dt_obj)
                local_date = dt_obj.astimezone(local_tz).date().isoformat()
                energy_kwh = value * resolution_hours / 1000.0
                daily_pv_forecast[local_date] = daily_pv_forecast.get(local_date, 0.0) + energy_kwh

            # Map PV forecast to price slots (15 min resolution assumed)
            for slot in price_slots:
                slot_time = slot["start_time"]
                rounded_time = slot_time.replace(
                    minute=(slot_time.minute // 15) * 15, second=0, microsecond=0
                )
                power_watts = 0.0
                for solar_time, solar_power in solar_data_dict.items():
                    if solar_time == rounded_time:
                        power_watts = solar_power
                        break
                pv_kwh_forecast.append(power_watts * 0.25 / 1000.0)
    except Exception as exc:
        print(f"Warning: Open-Meteo Solar Forecast library call failed: {exc}")
        print("Falling back to dummy PV forecast")
        daily_pv_forecast = {}
        for slot in price_slots:
            start_time = slot["start_time"].astimezone(local_tz)
            hour = start_time.hour + start_time.minute / 60.0
            pv_kwh = max(0, math.sin(math.pi * (hour - 6) / 12)) * 1.25
            pv_kwh_forecast.append(pv_kwh)
            daily_iso = start_time.date().isoformat()
            daily_pv_forecast[daily_iso] = daily_pv_forecast.get(daily_iso, 0.0) + pv_kwh

    # Ensure we have at least four daily PV entries by extending with last known value
    if price_slots:
        first_date = price_slots[0]["start_time"].astimezone(local_tz).date()
        last_value = None
        for offset in range(4):
            target_date = (first_date + timedelta(days=offset)).isoformat()
            if target_date in daily_pv_forecast:
                last_value = daily_pv_forecast[target_date]
            elif last_value is not None:
                daily_pv_forecast[target_date] = last_value

    try:
        load_profile = _get_load_profile_from_ha(config)
    except Exception as exc:
        print(f"Warning: Failed to get HA load profile, using dummy: {exc}")
        load_profile = _get_dummy_load_profile(config)

    daily_load_total = sum(load_profile)
    daily_load_forecast: dict[str, float] = {}

    load_kwh_forecast: list[float] = []
    for slot in price_slots:
        slot_time = slot["start_time"]
        slot_index = int((slot_time.hour * 60 + slot_time.minute) // 15)
        load_kwh = load_profile[slot_index]
        load_kwh_forecast.append(load_kwh)
        local_date = slot_time.astimezone(local_tz).date().isoformat()
        daily_load_forecast[local_date] = daily_load_total

    if price_slots:
        first_date = price_slots[0]["start_time"].astimezone(local_tz).date()
        for offset in range(4):
            target_date = (first_date + timedelta(days=offset)).isoformat()
            daily_load_forecast.setdefault(target_date, daily_load_total)

    forecast_data = []
    total_slots = len(price_slots)
    for idx in range(total_slots):
        pv_kwh = pv_kwh_forecast[idx] if idx < len(pv_kwh_forecast) else 0.0
        load_kwh = load_kwh_forecast[idx] if idx < len(load_kwh_forecast) else 0.0
        slot = price_slots[idx]
        forecast_data.append(
            {
                "start_time": slot["start_time"],
                "pv_forecast_kwh": pv_kwh,
                "load_forecast_kwh": load_kwh,
            }
        )

    return {
        "slots": forecast_data,
        "daily_pv_forecast": daily_pv_forecast,
        "daily_load_forecast": daily_load_forecast,
    }


def get_initial_state(config_path="config.yaml"):
    """
    Get the initial battery state.

    Args:
        config_path (str): Path to config file

    Returns:
        dict: Dictionary with:
            - battery_soc_percent (float): Current battery state of charge
            - battery_kwh (float): Current battery energy in kWh
            - battery_cost_sek_per_kwh (float): Current average battery cost
    """
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # Use system.battery if available, otherwise fall back to battery
    battery_config = config.get("system", {}).get("battery", config.get("battery", {}))
    capacity_kwh = battery_config.get("capacity_kwh", 10.0)
    battery_soc_percent = 50.0
    battery_cost_sek_per_kwh = 0.20

    # Prefer Home Assistant SoC when available
    ha_config = load_home_assistant_config()
    soc_entity_id = ha_config.get("battery_soc_entity_id", "sensor.inverter_battery")
    ha_soc = get_home_assistant_sensor_float(soc_entity_id) if soc_entity_id else None

    if ha_soc is not None:
        battery_soc_percent = ha_soc

    battery_soc_percent = max(0.0, min(100.0, battery_soc_percent))
    battery_kwh = capacity_kwh * battery_soc_percent / 100.0

    return {
        "battery_soc_percent": battery_soc_percent,
        "battery_kwh": battery_kwh,
        "battery_cost_sek_per_kwh": battery_cost_sek_per_kwh,
    }


def get_all_input_data(config_path="config.yaml"):
    """
    Orchestrate all input data fetching.
    """
    # Load config
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # --- AUTO-RUN ML INFERENCE IF AURORA IS ACTIVE ---
    if config.get("forecasting", {}).get("active_forecast_version") == "aurora":
        try:
            print("🧠 Running AURORA ML Inference...")
            from ml.forward import generate_forward_slots

            generate_forward_slots(horizon_hours=168)
        except Exception as e:
            print(f"⚠️ AURORA Inference Failed: {e}")

    # --- FETCH CONTEXT (New in Rev 19) ---
    sensors = config.get("input_sensors", {})
    vacation_id = sensors.get("vacation_mode")
    alarm_id = sensors.get("alarm_state")

    context = {
        "vacation_mode": get_home_assistant_bool(vacation_id) if vacation_id else False,
        "alarm_armed": get_home_assistant_bool(alarm_id) if alarm_id else False,
    }
    # -------------------------------------

    price_data = get_nordpool_data(config_path)

    import asyncio

    forecast_result = asyncio.run(get_forecast_data(price_data, config))
    forecast_data = forecast_result.get("slots", [])
    initial_state = get_initial_state(config_path)

    return {
        "price_data": price_data,
        "forecast_data": forecast_data,
        "initial_state": initial_state,
        "daily_pv_forecast": forecast_result.get("daily_pv_forecast", {}),
        "daily_load_forecast": forecast_result.get("daily_load_forecast", {}),
        "context": context,
    }


def get_db_forecast_slots(start: datetime, end: datetime, config: dict) -> list[dict]:
    """
    Fetch forecast slots from the learning database via ml.api.

    This helper does not change planner behaviour by itself; it simply
    wraps get_forecast_slots using the configured active_forecast_version.
    """
    forecasting_cfg = config.get("forecasting", {}) or {}
    version = forecasting_cfg.get("active_forecast_version", "baseline_7_day_avg")
    return get_forecast_slots(start, end, version)


def build_db_forecast_for_slots(
    price_slots: list[dict],
    config: dict,
) -> list[dict]:
    """
    Build planner-style PV/load forecasts for the given price_slots from slot_forecasts.

    The returned list has the same length and ordering as price_slots, with
    dictionaries of the form:
        { "pv_forecast_kwh": float, "load_forecast_kwh": float }

    This is a thin adapter around ml.api.get_forecast_slots and does not
    change planner behaviour until it is used by get_forecast_data.
    """
    if not price_slots:
        return []

    forecasting_cfg = config.get("forecasting", {}) or {}
    version = forecasting_cfg.get("active_forecast_version", "baseline_7_day_avg")

    timezone = config.get("timezone", "Europe/Stockholm")
    local_tz = pytz.timezone(timezone)

    # Determine horizon from price slots
    start_time = price_slots[0]["start_time"].astimezone(local_tz)
    end_time = price_slots[-1]["start_time"].astimezone(local_tz) + timedelta(
        minutes=15,
    )

    records = get_forecast_slots(start_time, end_time, version)
    if not records:
        return []

    # Index forecasts by localised slot_start for quick lookup
    indexed: dict[datetime, dict] = {}
    for rec in records:
        ts = rec["slot_start"]
        if ts.tzinfo is None:
            ts = pytz.UTC.localize(ts)
        indexed[ts.astimezone(local_tz)] = rec

    result: list[dict] = []
    for slot in price_slots:
        ts = slot["start_time"].astimezone(local_tz)
        rec = indexed.get(ts)
        if rec is None:
            pv = 0.0
            load = 0.0
        else:
            pv = float(rec.get("pv_forecast_kwh") or 0.0)
            load = float(rec.get("load_forecast_kwh") or 0.0)
        result.append({"pv_forecast_kwh": pv, "load_forecast_kwh": load})

    return result


def _get_load_profile_from_ha(config: dict) -> list[float]:
    """Fetch actual load profile from Home Assistant historical data.

    Notes on averaging logic:
    - We build a 7-day matrix of 15-min buckets (7 x 96) and distribute kWh deltas.
    - The per-slot daily profile is the average across all 7 days, dividing by 7
      (not by the count of non-zero days), to avoid inflating totals when some
      slots are zero for certain days.
    """
    from datetime import timedelta

    ha_config = load_home_assistant_config()
    url = ha_config.get("url")
    token = ha_config.get("token")
    entity_id = ha_config.get("consumption_entity_id")

    if not all([url, token, entity_id]):
        print("Warning: Missing Home Assistant configuration for load profile")
        return _get_dummy_load_profile(config)

    # Set up headers and API URL
    headers = _make_ha_headers(token)

    # Calculate time range for last 7 days
    end_time = datetime.now(pytz.UTC)
    start_time = end_time - timedelta(days=7)

    api_url = f"{url}/api/history/period/{start_time.isoformat()}"
    params = {
        "filter_entity_id": entity_id,
        "end_time": end_time.isoformat(),
        "significant_changes_only": False,
        "minimal_response": False,
    }

    try:
        print(f"Fetching {entity_id} data from Home Assistant...")
        response = requests.get(api_url, headers=headers, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()
        if not data or not data[0]:
            print("Warning: No data received from Home Assistant")
            return _get_dummy_load_profile(config)

        # Process state changes into energy deltas
        states = data[0]
        if len(states) < 2:
            print("Warning: Insufficient data points from Home Assistant")
            return _get_dummy_load_profile(config)

        # Convert to local timezone for processing
        local_tz = pytz.timezone("Europe/Stockholm")

        # Calculate energy consumption between state changes
        time_buckets = [0.0] * (96 * 7)  # 7 days * 96 slots per day
        prev_state = None
        prev_time = None

        start_time_local = start_time.astimezone(local_tz)

        for state in states:
            try:
                current_time = datetime.fromisoformat(state["last_changed"])
                if current_time.tzinfo is None:
                    current_time = current_time.replace(tzinfo=pytz.UTC)
                current_time = current_time.astimezone(local_tz)
                current_value = float(state["state"])

                if prev_state is not None and prev_time is not None:
                    # Calculate energy delta (ensure positive)
                    energy_delta = max(0, current_value - prev_state)

                    # Distribute across time buckets
                    time_diff = current_time - prev_time
                    minutes_diff = time_diff.total_seconds() / 60

                    if minutes_diff > 0 and energy_delta > 0:
                        # Calculate which 15-minute buckets this spans
                        start_slot = int((prev_time.hour * 60 + prev_time.minute) // 15)
                        end_slot = int((current_time.hour * 60 + current_time.minute) // 15)
                        day_offset = int(
                            (prev_time - start_time_local).total_seconds() / (24 * 3600)
                        )

                        # Calculate start and end times for each slot
                        for slot_idx in range(max(0, start_slot), min(96, end_slot + 1)):
                            # Calculate slot start time relative to the day start
                            slot_start_minutes = slot_idx * 15
                            day_start = prev_time.replace(hour=0, minute=0, second=0, microsecond=0)
                            slot_start_time = day_start + timedelta(minutes=slot_start_minutes)
                            slot_end_time = slot_start_time + timedelta(minutes=15)

                            # Calculate overlap between this slot and the energy consumption period
                            overlap_start = max(prev_time, slot_start_time)
                            overlap_end = min(current_time, slot_end_time)
                            overlap_minutes = max(
                                0, (overlap_end - overlap_start).total_seconds() / 60
                            )

                            if overlap_minutes > 0:
                                # Distribute energy proportionally to time overlap
                                energy_fraction = overlap_minutes / minutes_diff
                                energy_for_slot = energy_delta * energy_fraction

                                bucket_idx = day_offset * 96 + slot_idx
                                if 0 <= bucket_idx < len(time_buckets):
                                    time_buckets[bucket_idx] += energy_for_slot

                prev_state = current_value
                prev_time = current_time

            except (ValueError, TypeError, KeyError) as e:
                print(f"Warning: Skipping invalid state data: {e}")
                continue

        # Create average daily profile from the 7 days of data (divide by 7 days)
        daily_profile = [0.0] * 96
        for slot in range(96):
            slot_sum = 0.0
            for day in range(7):
                bucket_idx = day * 96 + slot
                if 0 <= bucket_idx < len(time_buckets):
                    slot_sum += time_buckets[bucket_idx]
            daily_profile[slot] = slot_sum / 7.0

        # Validate and clean the profile
        total_daily = sum(daily_profile)
        if total_daily <= 0:
            print("Warning: No valid energy consumption data found")
            return _get_dummy_load_profile(config)

        print(f"Successfully loaded HA data: {total_daily:.2f} kWh/day average")

        # Ensure all values are positive and reasonable
        for i in range(96):
            if daily_profile[i] < 0:
                daily_profile[i] = 0
            elif daily_profile[i] > 10:  # Cap at 10kW per 15min
                daily_profile[i] = 10

        return daily_profile

    except requests.RequestException as e:
        print(f"Warning: Failed to fetch data from Home Assistant: {e}")
        return _get_dummy_load_profile(config)
    except Exception as e:
        print(f"Warning: Error processing Home Assistant data: {e}")
        return _get_dummy_load_profile(config)


def _get_dummy_load_profile(config: dict) -> list[float]:
    """Create a dummy load profile (sine wave pattern)."""
    import math

    return [0.5 + 0.3 * math.sin(2 * math.pi * i / 96 + math.pi) for i in range(96)]


if __name__ == "__main__":
    # Test the combined input data fetching
    print("Testing get_all_input_data()...")

    def test():
        try:
            data = get_all_input_data(config_path="config.yaml")
            print(f"Price slots: {len(data['price_data'])}")
            print(f"Forecast slots: {len(data['forecast_data'])}")
            print("Initial state:", data["initial_state"])
            print()

            # Show first 5 slots
            for i in range(min(5, len(data["price_data"]))):
                slot = data["price_data"][i]
                forecast = data["forecast_data"][i]
                slot_time = slot["start_time"]
                import_price = slot["import_price_sek_kwh"]
                pv_forecast = forecast["pv_forecast_kwh"]
                load_forecast = forecast["load_forecast_kwh"]
                summary = (
                    f"Slot {i+1}: {slot_time} - Import: {import_price:.3f} SEK/kWh, "
                    f"PV: {pv_forecast:.3f} kWh, "
                    f"Load: {load_forecast:.3f} kWh"
                )
                print(summary)

            if len(data["price_data"]) > 5:
                print(f"... and {len(data['price_data']) - 5} more slots")

        except Exception as e:
            print(f"Error: {e}")

    test()
