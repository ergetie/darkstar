from datetime import datetime, timedelta, date
import yaml
from nordpool.elspot import Prices
import pytz
import math
import requests
import asyncio
from open_meteo_solar_forecast import OpenMeteoSolarForecast

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
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    timezone = config.get('timezone', 'Europe/Stockholm')
    nordpool_config = config.get('nordpool', {})
    price_area = nordpool_config.get('price_area', 'SE4')
    currency = nordpool_config.get('currency', 'SEK')
    resolution_minutes = nordpool_config.get('resolution_minutes', 60)

    # Initialize Nordpool Prices client with currency
    prices_client = Prices(currency)

    # Fetch today's prices
    try:
        today_data = prices_client.fetch(end_date=date.today(), areas=[price_area], resolution=resolution_minutes)
    except Exception:
        today_data = {}

    # Fetch tomorrow's prices safely
    try:
        tomorrow_data = prices_client.fetch(areas=[price_area], resolution=resolution_minutes)
    except Exception:
        tomorrow_data = {}

    # Combine data
    today_values = []
    if today_data and today_data.get('areas') and today_data['areas'].get(price_area):
        today_values = today_data['areas'][price_area].get('values', [])
    
    tomorrow_values = []
    if tomorrow_data and tomorrow_data.get('areas') and tomorrow_data['areas'].get(price_area):
        tomorrow_values = tomorrow_data['areas'][price_area].get('values', [])
    
    all_entries = today_values + tomorrow_values

    # If we don't have enough data for 48 hours, extend with today's pattern
    # This ensures we always have 192 slots (48 hours * 4 slots per hour)
    target_slots = 192  # 48 hours * 4 slots per hour
    current_slots = len(all_entries)
    
    if current_slots < target_slots:
        print(f"Warning: Only have {current_slots} price slots, extending to {target_slots} for 48-hour planning")
        # Repeat today's pattern to fill the gap
        repeat_pattern = today_values[:min(96, target_slots - current_slots)]  # Use up to 24 hours of today's data
        all_entries.extend(repeat_pattern)
    
    # Ensure we don't exceed target
    all_entries = all_entries[:target_slots]

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
    pricing_config = config.get('pricing', {})
    vat_percent = pricing_config.get('vat_percent', 25.0)
    grid_transfer_fee_sek = pricing_config.get('grid_transfer_fee_sek', 0.2456)
    energy_tax_sek = pricing_config.get('energy_tax_sek', 0.439)

    # Get local timezone
    local_tz = pytz.timezone(config.get('timezone', 'Europe/Stockholm'))

# Process the hourly data
    for i, entry in enumerate(all_entries):
        # Manual timezone conversion
        if today_values is not None and i < len(today_values):
            # Original entries - use their actual timestamps
            start_time = entry['start'].astimezone(local_tz)
            end_time = entry['end'].astimezone(local_tz)
        else:
            # Extended entries - calculate timestamps based on position
            if today_values is not None:
                base_start = today_values[0]['start'].astimezone(local_tz)
                slot_duration = today_values[0]['end'] - today_values[0]['start']
                start_time = base_start + (slot_duration * i)
                end_time = start_time + slot_duration
            else:
                # Fallback if no today_values available
                start_time = entry['start'].astimezone(local_tz)
                end_time = entry['end'].astimezone(local_tz)

        # Calculate base spot price (convert from MWh to kWh)
        spot_price_sek_kwh = entry['value'] / 1000.0

        # Export price is exactly the spot price
        export_price_sek_kwh = spot_price_sek_kwh

        # Import price includes all fees and taxes
        import_price_sek_kwh = (spot_price_sek_kwh + grid_transfer_fee_sek + energy_tax_sek) * (1 + vat_percent / 100.0)

        result.append({
            'start_time': start_time,
            'end_time': end_time,
            'import_price_sek_kwh': import_price_sek_kwh,
            'export_price_sek_kwh': export_price_sek_kwh
        })

    # Sort by start time to ensure chronological order
    result.sort(key=lambda x: x['start_time'])

    return result


async def get_forecast_data(price_slots, config):
    """
    Generate PV and load forecasts based on price slots and configuration.

    Args:
        price_slots (list): List of price slot dictionaries with start_time
        config (dict): Configuration dictionary containing system parameters

    Returns:
        list: List of dictionaries with:
            - pv_forecast_kwh (float): PV generation in kWh for the slot
            - load_forecast_kwh (float): Load consumption in kWh for the slot
    """
    # Read system parameters from config
    system_config = config.get('system', {})
    latitude = system_config.get('location', {}).get('latitude', 59.3)
    longitude = system_config.get('location', {}).get('longitude', 18.1)
    kwp = system_config.get('solar_array', {}).get('kwp', 5.0)
    azimuth = system_config.get('solar_array', {}).get('azimuth', 180)
    # Map tilt to declination parameter for the library
    tilt = system_config.get('solar_array', {}).get('tilt', 30)
    
# Try to get real PV forecast from Open-Meteo Solar Forecast library
    pv_kwh_forecast = []
    try:
        # Initialize the forecast with system parameters using async with for proper resource management
        async def _fetch_forecast():
            async with OpenMeteoSolarForecast(
                latitude=latitude,
                longitude=longitude,
                declination=tilt,  # Correct mapping
                azimuth=azimuth,
                dc_kwp=kwp         # Correct parameter name
            ) as forecast:
                estimate = await forecast.estimate()
                
                # Get the datetime keys and power values
                solar_data_dict = estimate.watts
                
                # We need to map this data to our price slots
                # Return the raw dictionary so we can map it properly in the main function
                return solar_data_dict
        
        # Run the async function
        solar_data_dict = await _fetch_forecast()
        
        # Map solar data to our price slots
        for i, slot in enumerate(price_slots):
            slot_time = slot['start_time']
            
            # Find the closest 15-minute timestamp in the solar data
            # Round to the nearest 15 minutes
            rounded_time = slot_time.replace(minute=(slot_time.minute // 15) * 15, second=0, microsecond=0)
            
            # Find exact match by iterating through keys (to avoid dictionary collision issues)
            power_watts = 0
            for solar_time, solar_power in solar_data_dict.items():
                if solar_time == rounded_time:
                    power_watts = solar_power
                    break
            
            
            
            
            # Convert watts to kWh for 15-minute periods: (watts * 0.25 hours) / 1000
            pv_kwh = power_watts * 0.25 / 1000
            
            pv_kwh_forecast.append(pv_kwh)
            
    except Exception as e:
        print(f"Warning: Open-Meteo Solar Forecast library call failed: {e}")
        print("Falling back to dummy PV forecast")
        
        # Fallback: generate dummy PV forecast using sine wave
        for slot in price_slots:
            start_time = slot['start_time']
            hour = start_time.hour + start_time.minute / 60.0
            pv_kwh = max(0, math.sin(math.pi * (hour - 6) / 12)) * 1.25  # Peak 1.25 kWh per 15 min
            pv_kwh_forecast.append(pv_kwh)
    
    # Get load forecast from Home Assistant or fallback to dummy
    try:
        load_profile = _get_load_profile_from_ha(config)
    except Exception as e:
        print(f"Warning: Failed to get HA load profile, using dummy: {e}")
        load_profile = _get_dummy_load_profile(config)
    
    # Apply load profile to each slot
    load_kwh_forecast = []
    for slot in price_slots:
        start_time = slot['start_time']
        hour = start_time.hour + start_time.minute / 60.0
        slot_of_day = int((start_time.hour * 60 + start_time.minute) // 15)
        
        # Use the HA load profile for the corresponding 15-minute slot
        load_kwh = load_profile[slot_of_day]
        load_kwh_forecast.append(load_kwh)
    
    # Combine forecasts into final format
    forecast_data = []
    for i in range(len(price_slots)):
        # Use real PV forecast if available, otherwise use dummy
        pv_kwh = pv_kwh_forecast[i] if i < len(pv_kwh_forecast) else 0.0
        load_kwh = load_kwh_forecast[i] if i < len(load_kwh_forecast) else 0.0
        
        forecast_data.append({
            'pv_forecast_kwh': pv_kwh,
            'load_forecast_kwh': load_kwh
        })

    return forecast_data


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
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    # Use system.battery if available, otherwise fall back to battery
    battery_config = config.get('system', {}).get('battery', config.get('battery', {}))
    capacity_kwh = battery_config.get('capacity_kwh', 10.0)
    battery_soc_percent = 50.0
    battery_kwh = capacity_kwh * battery_soc_percent / 100.0
    battery_cost_sek_per_kwh = 0.20

    return {
        'battery_soc_percent': battery_soc_percent,
        'battery_kwh': battery_kwh,
        'battery_cost_sek_per_kwh': battery_cost_sek_per_kwh
    }


def get_all_input_data(config_path="config.yaml"):
    """
    Orchestrate all input data fetching.

    Args:
        config_path (str): Path to config file

    Returns:
        dict: Combined data with price_data, forecast_data, initial_state
    """
    # Load config to pass to get_forecast_data
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    price_data = get_nordpool_data(config_path)
    
    # Run the async forecast function
    import asyncio
    forecast_data = asyncio.run(get_forecast_data(price_data, config))
    initial_state = get_initial_state(config_path)

    return {
        'price_data': price_data,
        'forecast_data': forecast_data,
        'initial_state': initial_state
    }


def _get_load_profile_from_ha(config: dict) -> list[float]:
    """Fetch actual load profile from Home Assistant historical data."""
    import json
    from datetime import timedelta
    
    # Load secrets
    try:
        with open('secrets.yaml', 'r') as f:
            secrets = yaml.safe_load(f)
    except Exception as e:
        print(f"Warning: Could not load secrets.yaml: {e}")
        return _get_dummy_load_profile(config)
    
    ha_config = secrets.get('home_assistant', {})
    url = ha_config.get('url')
    token = ha_config.get('token')
    entity_id = ha_config.get('consumption_entity_id')
    
    if not all([url, token, entity_id]):
        print("Warning: Missing Home Assistant configuration in secrets.yaml")
        return _get_dummy_load_profile(config)
    
    # Set up headers and API URL
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    
    # Calculate time range for last 7 days
    end_time = datetime.now(pytz.UTC)
    start_time = end_time - timedelta(days=7)
    
    api_url = f"{url}/api/history/period/{start_time.isoformat()}"
    params = {
        'filter_entity_id': entity_id,
        'end_time': end_time.isoformat(),
        'significant_changes_only': False,
        'minimal_response': False,
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
        local_tz = pytz.timezone('Europe/Stockholm')
        
        # Calculate energy consumption between state changes
        time_buckets = [0.0] * (96 * 7)  # 7 days * 96 slots per day
        prev_state = None
        prev_time = None
        
        for state in states:
            try:
                current_time = datetime.fromisoformat(state['last_changed']).replace(tzinfo=pytz.UTC).astimezone(local_tz)
                current_value = float(state['state'])
                
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
                        day_offset = int((prev_time - start_time.replace(tzinfo=local_tz)).total_seconds() / (24 * 3600))

                        # Time-weighted distribution: calculate how much time each slot gets
                        slot_duration = 15.0  # minutes per slot

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
                            overlap_minutes = max(0, (overlap_end - overlap_start).total_seconds() / 60)

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
        
        # Create average daily profile from the 7 days of data
        daily_profile = [0.0] * 96
        daily_counts = [0] * 96
        
        for day in range(7):
            for slot in range(96):
                bucket_idx = day * 96 + slot
                if bucket_idx < len(time_buckets) and time_buckets[bucket_idx] > 0:
                    daily_profile[slot] += time_buckets[bucket_idx]
                    daily_counts[slot] += 1
        
        # Calculate averages
        for slot in range(96):
            if daily_counts[slot] > 0:
                daily_profile[slot] /= daily_counts[slot]
        
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
    return [
        0.5 + 0.3 * math.sin(2 * math.pi * i / 96 + math.pi)
        for i in range(96)
    ]


if __name__ == "__main__":
    # Test the combined input data fetching
    print("Testing get_all_input_data()...")

    def test():
        try:
            data = get_all_input_data(config_path="config.yaml")
            print(f"Price slots: {len(data['price_data'])}")
            print(f"Forecast slots: {len(data['forecast_data'])}")
            print("Initial state:", data['initial_state'])
            print()

            # Show first 5 slots
            for i in range(min(5, len(data['price_data']))):
                slot = data['price_data'][i]
                forecast = data['forecast_data'][i]
                print(f"Slot {i+1}: {slot['start_time']} - Import: {slot['import_price_sek_kwh']:.3f} SEK/kWh, PV: {forecast['pv_forecast_kwh']:.3f} kWh, Load: {forecast['load_forecast_kwh']:.3f} kWh")

            if len(data['price_data']) > 5:
                print(f"... and {len(data['price_data']) - 5} more slots")

        except Exception as e:
            print(f"Error: {e}")

    test()