from __future__ import annotations

from datetime import datetime
from typing import Dict

import pandas as pd
import pytz
import requests
import yaml


def _load_config(config_path: str = "config.yaml") -> Dict:
    """Load configuration from YAML file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_temperature_series(
    start_time: datetime,
    end_time: datetime,
    config: Dict | None = None,
    *,
    config_path: str = "config.yaml",
) -> pd.Series:
    """
    Fetch hourly outdoor temperature (temp_c) from Open-Meteo for the given window.

    Returns a pandas Series indexed by timezone-aware datetimes in the planner
    timezone, with float temperature values in degrees Celsius.

    This helper is best-effort and will return an empty Series if the request
    fails for any reason; callers should treat missing data as optional and
    continue without temperature features.
    """
    cfg = config or _load_config(config_path)
    system_cfg = cfg.get("system", {}) or {}
    loc_cfg = system_cfg.get("location", {}) or {}

    latitude = float(loc_cfg.get("latitude", 59.3))
    longitude = float(loc_cfg.get("longitude", 18.1))
    timezone_name = cfg.get("timezone", "Europe/Stockholm")
    tz = pytz.timezone(timezone_name)

    # Normalise window to local dates for the archive API
    start_local = start_time.astimezone(tz)
    end_local = end_time.astimezone(tz)
    start_date = start_local.date().isoformat()
    end_date = end_local.date().isoformat()

    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": "temperature_2m",
        "timezone": timezone_name,
    }

    try:
        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"Warning: Failed to fetch temperature data from Open-Meteo: {exc}")
        return pd.Series(dtype="float64")

    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []

    if not times or not temps or len(times) != len(temps):
        return pd.Series(dtype="float64")

    # Build Series indexed by localised datetimes
    dt_index = pd.to_datetime(times)
    if dt_index.tz is None:
        dt_index = dt_index.dt.tz_localize(tz)
    else:
        dt_index = dt_index.tz_convert(tz)

    series = pd.Series(temps, index=dt_index, name="temp_c").astype("float64")

    # Restrict to the exact window [start_time, end_time)
    series = series[(series.index >= start_local) & (series.index < end_local)]
    return series

