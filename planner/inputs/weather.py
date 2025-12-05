"""
Weather Input

Functions for fetching weather forecasts (temperature, etc.).
"""

import requests
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def fetch_temperature_forecast(
    days_ahead: List[int], 
    tz: Any, 
    config: Dict[str, Any]
) -> Dict[int, float]:
    """
    Fetch mean daily temperatures for the requested day offsets.
    
    Args:
        days_ahead: List of day offsets to fetch (e.g. [1, 2])
        tz: Timezone object
        config: Full configuration dictionary
        
    Returns:
        Dictionary mapping day offset to mean temperature
    """
    if not days_ahead:
        return {}

    location = config.get("system", {}).get("location", {})
    latitude = location.get("latitude")
    longitude = location.get("longitude")
    if latitude is None or longitude is None:
        return {}

    try:
        today = datetime.now(tz).date()
    except Exception:
        today = datetime.now(timezone.utc).date()

    max_offset = max(days_ahead)
    timezone_name = config.get("timezone", "Europe/Stockholm")
    
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "temperature_2m_mean",
        "timezone": timezone_name,
        "forecast_days": max(1, max_offset + 1),
    }

    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params=params,
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        print(f"Warning: Failed to fetch temperature forecast: {exc}")
        return {}

    daily = payload.get("daily", {})
    dates = daily.get("time", [])
    temps = daily.get("temperature_2m_mean", [])

    result: Dict[int, float] = {}
    for date_str, temp in zip(dates, temps):
        try:
            date_obj = datetime.fromisoformat(date_str).date()
        except ValueError:
            continue
        offset = (date_obj - today).days
        if offset in days_ahead:
            try:
                result[offset] = float(temp)
            except (TypeError, ValueError):
                continue

    return result
