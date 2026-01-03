from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytz
import requests
import yaml


def _load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file."""
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def get_weather_series(
    start_time: datetime,
    end_time: datetime,
    config: dict | None = None,
    *,
    config_path: str = "config.yaml",
) -> pd.DataFrame:
    """
    Fetch hourly outdoor weather data from Open-Meteo for the given window.

    Returns a DataFrame indexed by timezone-aware datetimes in the planner
    timezone with some or all of the following float columns:
        - temp_c: 2m air temperature in °C
        - cloud_cover_pct: total cloud cover in percent
        - shortwave_radiation_w_m2: shortwave radiation

    This helper is best-effort and will return an empty DataFrame if the
    request fails or contains no usable data.
    """
    cfg = config or _load_config(config_path)
    system_cfg = cfg.get("system", {}) or {}
    loc_cfg = system_cfg.get("location", {}) or {}

    latitude = float(loc_cfg.get("latitude", 59.3))
    longitude = float(loc_cfg.get("longitude", 18.1))
    timezone_name = cfg.get("timezone", "Europe/Stockholm")
    tz = pytz.timezone(timezone_name)

    start_local = start_time.astimezone(tz)
    end_local = end_time.astimezone(tz)
    start_date_obj = start_local.date()
    end_date_obj = end_local.date()
    today_local = datetime.now(tz).date()

    try:
        hourly_params: list[str] = [
            "temperature_2m",
            "cloud_cover",
            "shortwave_radiation",
        ]
        hourly_param_str = ",".join(hourly_params)

        if end_date_obj <= today_local:
            url = "https://archive-api.open-meteo.com/v1/archive"
            # Open-Meteo archive API typically supports data up to yesterday.
            archive_end = min(end_date_obj, today_local - timedelta(days=1))
            if archive_end < start_date_obj:
                return pd.DataFrame(dtype="float64")
            params = {
                "latitude": latitude,
                "longitude": longitude,
                "start_date": start_date_obj.isoformat(),
                "end_date": archive_end.isoformat(),
                "hourly": hourly_param_str,
                "timezone": timezone_name,
            }
        else:
            url = "https://api.open-meteo.com/v1/forecast"
            days_ahead = max(1, (end_local.date() - today_local).days + 1)
            params = {
                "latitude": latitude,
                "longitude": longitude,
                "hourly": hourly_param_str,
                "forecast_days": days_ahead,
                "timezone": timezone_name,
            }

        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"Warning: Failed to fetch weather data from Open-Meteo: {exc}")
        return pd.DataFrame(dtype="float64")

    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    clouds = hourly.get("cloud_cover") or []
    sw_rad = hourly.get("shortwave_radiation") or []

    if not times:
        return pd.DataFrame(dtype="float64")

    dt_index = pd.to_datetime(times)
    dt_index = dt_index.tz_localize("UTC") if dt_index.tz is None else dt_index.tz_convert("UTC")
    dt_index = dt_index.tz_convert(tz)

    data: dict[str, list[float]] = {}
    if temps and len(temps) == len(times):
        data["temp_c"] = temps
    if clouds and len(clouds) == len(times):
        data["cloud_cover_pct"] = clouds
    if sw_rad and len(sw_rad) == len(times):
        data["shortwave_radiation_w_m2"] = sw_rad

    if not data:
        return pd.DataFrame(dtype="float64")

    df = pd.DataFrame(data, index=dt_index).astype("float64")
    df = df[(df.index >= start_local) & (df.index < end_local)]
    return df


def get_weather_volatility(
    start_time: datetime,
    end_time: datetime,
    config: dict | None = None,
    *,
    config_path: str = "config.yaml",
) -> dict[str, float]:
    """
    Calculate normalized volatility scores for cloud cover and temperature.

    Volatility is defined as:
        min(1.0, standard_deviation / normalization_factor)
    where normalization_factor is 40.0 for cloud cover (percent) and
    5.0 for temperature (deg C).

    The function returns a dictionary:
        {
            "cloud_volatility": float,
            "temp_volatility": float,
        }
    with each value in the range [0.0, 1.0].
    """
    df = get_weather_series(start_time, end_time, config=config, config_path=config_path)

    if df.empty:
        return {"cloud_volatility": 0.0, "temp_volatility": 0.0}

    cloud_std = float(df["cloud_cover_pct"].std()) if "cloud_cover_pct" in df.columns else 0.0
    temp_std = float(df["temp_c"].std()) if "temp_c" in df.columns else 0.0

    cloud_norm = 20.0
    temp_norm = 5.0

    cloud_volatility = 0.0
    temp_volatility = 0.0

    if cloud_std > 0.0 and cloud_norm > 0.0:
        cloud_volatility = min(1.0, cloud_std / cloud_norm)

    if temp_std > 0.0 and temp_norm > 0.0:
        temp_volatility = min(1.0, temp_std / temp_norm)

    return {
        "cloud_volatility": float(cloud_volatility),
        "temp_volatility": float(temp_volatility),
    }


def get_temperature_series(
    start_time: datetime,
    end_time: datetime,
    config: dict | None = None,
    *,
    config_path: str = "config.yaml",
) -> pd.Series:
    """Compatibility wrapper returning only the temp_c series."""
    df = get_weather_series(start_time, end_time, config=config, config_path=config_path)
    if df.empty or "temp_c" not in df.columns:
        return pd.Series(dtype="float64")
    series = df["temp_c"].copy()
    series.name = "temp_c"
    return series
