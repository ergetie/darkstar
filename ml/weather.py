"""
Weather data fetching and processing for Aurora.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd
import pytz
import requests
import yaml

from utils.time_utils import dst_safe_localize

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from datetime import datetime


def _calculate_solar_position(
    latitude: float,
    longitude: float,
    dt: datetime,
) -> dict[str, float]:
    """
    Calculate solar position (elevation, azimuth) for a given location and time.

    Uses simplified algorithm based on NOAA formulas.

    Returns:
        dict with 'elevation' (degrees) and 'azimuth' (degrees) keys.
    """
    # Day of year
    day_of_year = dt.timetuple().tm_yday

    # Decimal hour (including fractional day)
    hour = dt.hour + dt.minute / 60.0 + dt.second / 3600.0

    # Fractional year in radians
    gamma = (2.0 * math.pi / 365.0) * (day_of_year - 1 + (hour - 12.0) / 24.0)

    # Equation of time (minutes)
    eq_time = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2.0 * gamma)
        - 0.040849 * math.sin(2.0 * gamma)
    )

    # Solar declination (radians)
    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2.0 * gamma)
        + 0.000907 * math.sin(2.0 * gamma)
        - 0.002697 * math.cos(3.0 * gamma)
        + 0.00148 * math.sin(3.0 * gamma)
    )

    # Convert latitude to radians
    lat_rad = math.radians(latitude)

    # Hour angle (degrees)
    utc_offset = dt.utcoffset()
    timezone_offset: float = 0.0
    if utc_offset is not None:
        timezone_offset = utc_offset.total_seconds() / 3600.0
    time_offset = eq_time / 60.0 + (longitude / 15.0) - timezone_offset
    hour_angle = 15.0 * (hour - 12.0 + time_offset)
    hour_angle_rad = math.radians(hour_angle)

    # Solar elevation angle
    sin_elev = math.sin(lat_rad) * math.sin(decl) + math.cos(lat_rad) * math.cos(decl) * math.cos(
        hour_angle_rad
    )
    elevation = math.degrees(math.asin(max(-1.0, min(1.0, sin_elev))))

    # Solar azimuth angle (degrees from north, clockwise)
    cos_az = (math.sin(decl) - math.sin(lat_rad) * sin_elev) / (
        math.cos(lat_rad) * math.cos(math.radians(elevation)) + 1e-10
    )
    azimuth = math.degrees(math.acos(max(-1.0, min(1.0, cos_az))))
    if hour_angle > 0:
        azimuth = 360.0 - azimuth

    return {"elevation": elevation, "azimuth": azimuth, "declination": math.degrees(decl)}


def _calculate_poa_irradiance(
    radiation_w_m2: float,
    panel_tilt: float,
    panel_azimuth: float,
    solar_elevation: float,
    solar_azimuth: float,
) -> float:
    """
    Calculate Plane of Array (POA) irradiance from horizontal radiation.

    Uses isotropic diffuse model for simplicity.

    Args:
        radiation_w_m2: Global horizontal irradiance (GHI) in W/m²
        panel_tilt: Panel tilt angle in degrees (0=horizontal, 90=vertical)
        panel_azimuth: Panel azimuth in degrees (0=South, 90=West, -90=East)
        solar_elevation: Solar elevation angle in degrees
        solar_azimuth: Solar azimuth in degrees (0=South, positive=West)

    Returns:
        POA irradiance in W/m²
    """
    if radiation_w_m2 <= 0 or solar_elevation <= 0:
        return 0.0

    # Convert to radians
    panel_tilt_rad = math.radians(panel_tilt)
    panel_azimuth_rad = math.radians(panel_azimuth)
    solar_elevation_rad = math.radians(solar_elevation)
    solar_azimuth_rad = math.radians(solar_azimuth)

    # Simple diffuse fraction model (clear sky approximation)
    # For more accuracy, use Perez model or similar
    diffuse_fraction = 0.2 if solar_elevation > 15.0 else 0.4
    dni = radiation_w_m2 * (1.0 - diffuse_fraction)
    dhi = radiation_w_m2 * diffuse_fraction

    # Angle of incidence
    cos_aoi = math.sin(solar_elevation_rad) * math.cos(panel_tilt_rad) + math.cos(
        solar_elevation_rad
    ) * math.sin(panel_tilt_rad) * math.cos(solar_azimuth_rad - panel_azimuth_rad)
    cos_aoi = max(0.0, cos_aoi)

    # Sky diffuse on tilted surface (isotropic model)
    sky_diffuse = dhi * (1.0 + math.cos(panel_tilt_rad)) / 2.0

    # POA irradiance
    poa = dni * cos_aoi + sky_diffuse

    return max(0.0, poa)


def calculate_physics_pv(
    radiation_w_m2: float | None,
    solar_arrays: list[dict[str, Any]],
    slot_start: datetime,
    latitude: float,
    longitude: float,
    efficiency: float = 0.85,
    slot_hours: float = 0.25,
) -> tuple[float | None, list[dict[str, Any]]]:
    """
    Calculate physics-based PV estimate using panel orientation and solar position.

    This is the core physics calculation for the hybrid forecasting system.
    It uses POA (Plane of Array) irradiance calculation to account for
    panel tilt and azimuth, providing more accurate estimates than the
    simplified radiation-based formula.

    Args:
        radiation_w_m2: Global horizontal irradiance in W/m²
        solar_arrays: List of array configs with 'name', 'kwp', 'tilt', 'azimuth' keys
        slot_start: Datetime of the slot for solar position calculation
        latitude: Location latitude in degrees
        longitude: Location longitude in degrees
        efficiency: System efficiency factor (default 0.85)
        slot_hours: Duration of the time slot in hours (default 0.25)

    Returns:
        Tuple of (total_kwh, per_array_list) where per_array_list contains
        dicts with 'name', 'kwh', 'poa_w_m2' keys. Returns (None, []) if no data.
    """
    if radiation_w_m2 is None or radiation_w_m2 <= 0 or not solar_arrays:
        return None, []

    # Calculate solar position
    try:
        solar_pos = _calculate_solar_position(latitude, longitude, slot_start)
    except Exception:
        # Fallback to simplified formula if solar position fails
        total_capacity = sum(float(arr.get("kwp", 0) or 0) for arr in solar_arrays)
        if total_capacity <= 0:
            return None, []
        pv_kwh = (radiation_w_m2 / 1000.0) * total_capacity * efficiency * slot_hours
        return round(pv_kwh, 4), []

    solar_elevation = solar_pos["elevation"]
    # Convert solar azimuth from North convention (0=North, clockwise) to
    # South convention (0=South, positive=West) expected by _calculate_poa_irradiance
    solar_azimuth = solar_pos["azimuth"] - 180.0

    # If sun is below horizon, return 0
    if solar_elevation <= 0:
        return 0.0, []

    per_array: list[dict[str, Any]] = []
    total_kwh = 0.0

    for arr in solar_arrays:
        name = str(arr.get("name", "Unknown"))
        kwp = float(arr.get("kwp", 0) or 0)
        if kwp <= 0:
            continue

        # Get panel orientation (default: 30° tilt, South-facing)
        panel_tilt = float(arr.get("tilt", 30.0) or 30.0)
        # Convert azimuth from Home Assistant convention (0=North, 180=South)
        # to solar convention (0=South, positive=West)
        panel_azimuth_ha = float(arr.get("azimuth", 180.0) or 180.0)
        panel_azimuth = (panel_azimuth_ha % 360) - 180

        # Calculate POA irradiance
        poa = _calculate_poa_irradiance(
            radiation_w_m2,
            panel_tilt,
            panel_azimuth,
            solar_elevation,
            solar_azimuth,
        )

        # Convert to kWh
        # POA is in W/m², capacity in kWp, efficiency accounts for system losses
        # Result is energy in kWh for the time slot
        pv_kw = (poa / 1000.0) * kwp * efficiency
        arr_kwh = pv_kw * slot_hours

        per_array.append(
            {
                "name": name,
                "kwh": round(arr_kwh, 4),
                "poa_w_m2": round(poa, 2),
            }
        )
        total_kwh += arr_kwh

    if not per_array:
        return None, []

    return round(total_kwh, 4), per_array


def calculate_physics_pv_simple(
    radiation_w_m2: float | None,
    total_capacity_kw: float,
    efficiency: float = 0.85,
    slot_hours: float = 0.25,
) -> float | None:
    """
    Simplified physics PV calculation fallback without solar position.

    Used when solar position calculation is not possible or as a fallback
    when the more accurate calculate_physics_pv() fails.

    Args:
        radiation_w_m2: Shortwave radiation in W/m²
        total_capacity_kw: Total DC peak power in kilowatts
        efficiency: System efficiency factor (default 0.85)
        slot_hours: Duration of the time slot in hours (default 0.25)

    Returns:
        Estimated PV production in kWh, or None if no data
    """
    if radiation_w_m2 is None or total_capacity_kw <= 0:
        return None

    pv_kwh = (radiation_w_m2 / 1000.0) * total_capacity_kw * efficiency * slot_hours
    return round(pv_kwh, 4)


# Simple in-memory cache with TTL (5 minutes)
_weather_cache: dict[str, tuple[float, pd.DataFrame]] = {}
_CACHE_TTL_SECONDS = 300.0  # 5 minutes


def _load_config(config_path: str = "config.yaml") -> dict[str, Any]:
    """Load configuration from YAML file."""
    with Path(config_path).open(encoding="utf-8") as handle:
        result: dict[str, Any] = yaml.safe_load(handle) or {}
        return result


def get_weather_series(
    start_time: datetime,
    end_time: datetime,
    config: dict[str, Any] | None = None,
    *,
    config_path: str = "config.yaml",
    forecast_days: int = 2,
    extra_params: list[str] | None = None,
) -> pd.DataFrame:
    """
    Fetch hourly outdoor weather data from Open-Meteo for the given window.

    Returns a DataFrame indexed by timezone-aware datetimes in the planner
    timezone with some or all of the following float columns:
        - temp_c: 2m air temperature in °C
        - cloud_cover_pct: total cloud cover in percent
        - shortwave_radiation_w_m2: shortwave radiation
        - wind_speed_10m: wind speed at 10m height (if requested via extra_params)

    Args:
        start_time: Start of the time window
        end_time: End of the time window
        config: Optional configuration dict (will load from config_path if not provided)
        config_path: Path to config file (default: "config.yaml")
        forecast_days: Number of days to forecast (default: 2, max: 16)
        extra_params: Additional Open-Meteo hourly parameters to fetch (e.g., ["wind_speed_10m"])

    This helper is best-effort and will return an empty DataFrame if the
    request fails or contains no usable data.
    """
    cfg: dict[str, Any] = config or _load_config(config_path)
    system_cfg: dict[str, Any] = cfg.get("system", {}) or {}
    loc_cfg: dict[str, Any] = system_cfg.get("location", {}) or {}

    latitude = float(loc_cfg.get("latitude", 59.3))
    longitude = float(loc_cfg.get("longitude", 18.1))
    timezone_name: str = cfg.get("timezone", "Europe/Stockholm")
    tz = pytz.timezone(timezone_name)

    start_local = start_time.astimezone(tz)
    end_local = end_time.astimezone(tz)
    start_date_obj = start_local.date()
    end_date_obj = end_local.date()

    # Build parameter list including any extra params
    hourly_params: list[str] = [
        "temperature_2m",
        "cloud_cover",
        "shortwave_radiation",
    ]
    if extra_params:
        hourly_params.extend(extra_params)
    hourly_param_str = ",".join(hourly_params)

    # Build extra params key for caching
    extra_params_key = "_".join(sorted(extra_params)) if extra_params else "none"

    # --- Cache Lookup ---
    cache_key = f"{latitude:.2f}_{longitude:.2f}_{start_date_obj}_{end_date_obj}_{forecast_days}_{extra_params_key}"
    now_ts = time.time()
    if cache_key in _weather_cache:
        cached_ts, cached_df = _weather_cache[cache_key]
        if now_ts - cached_ts < _CACHE_TTL_SECONDS:
            return cached_df.copy()

    try:
        # Always use forecast API with past_days + forecast_days for complete coverage
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": hourly_param_str,
            "past_days": 1,  # Yesterday's hindcast
            "forecast_days": forecast_days,
            "timezone": timezone_name,
        }

        # Reduced timeout from 20s to 5s to fail fast
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        payload: dict[str, Any] = response.json()  # type: ignore[assignment]
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to fetch weather data from Open-Meteo: %s", exc)
        return pd.DataFrame(dtype="float64")

    hourly: dict[str, Any] = payload.get("hourly") or {}
    times: list[Any] = hourly.get("time") or []
    temps: list[Any] = hourly.get("temperature_2m") or []
    clouds: list[Any] = hourly.get("cloud_cover") or []
    sw_rad: list[Any] = hourly.get("shortwave_radiation") or []

    if not times:
        return pd.DataFrame(dtype="float64")

    dt_index = pd.to_datetime(times)
    # Open-Meteo returns local-time strings when timezone is specified in the request.
    # Localize to the requested timezone (not UTC) to avoid shifting by the UTC offset.
    dt_index = dst_safe_localize(dt_index, tz) if dt_index.tz is None else dt_index.tz_convert(tz)

    data: dict[str, list[float]] = {}
    if temps and len(temps) == len(times):
        data["temp_c"] = temps
    if clouds and len(clouds) == len(times):
        data["cloud_cover_pct"] = clouds
    if sw_rad and len(sw_rad) == len(times):
        data["shortwave_radiation_w_m2"] = sw_rad

    # Extract any extra parameters
    if extra_params:
        for param in extra_params:
            values: list[Any] = hourly.get(param) or []
            if values and len(values) == len(times):
                # Map Open-Meteo param names to our column names
                col_name = param.replace("_", "_")
                data[col_name] = values

    if not data:
        return pd.DataFrame(dtype="float64")

    df = pd.DataFrame(data, index=dt_index).astype("float64")

    # DST spring-forward can create duplicate timestamps (e.g. 2:00 AM shifted to
    # 3:00 AM which already exists). Drop duplicates before resampling.
    if df.index.duplicated().any():
        df = df[~df.index.duplicated(keep="last")]

    # REV F67: Resample from hourly to 15-minute resolution via linear interpolation.
    # This ensures all slots (Bug #1) get weather data (radiation/temp/clouds).
    if not df.empty and len(df) > 1:
        # We resample BEFORE filtering to start/end so that boundary points
        # are used for interpolation of the edge slots.
        df = df.resample("15min").interpolate(method="linear")

    df = df[(df.index >= start_local) & (df.index < end_local)]

    # --- Cache Store ---
    _weather_cache[cache_key] = (time.time(), df.copy())

    return df


async def async_get_weather_series(
    start_time: datetime,
    end_time: datetime,
    config: dict[str, Any] | None = None,
    *,
    config_path: str = "config.yaml",
    forecast_days: int = 2,
    extra_params: list[str] | None = None,
) -> pd.DataFrame:
    """
    Asynchronous wrapper for get_weather_series using asyncio.to_thread.

    This allows the event loop to remain responsive during the synchronous
    network call to Open-Meteo API.
    """
    return await asyncio.to_thread(
        get_weather_series,
        start_time,
        end_time,
        config,
        config_path=config_path,
        forecast_days=forecast_days,
        extra_params=extra_params,
    )


def get_weather_volatility(
    start_time: datetime,
    end_time: datetime,
    config: dict[str, Any] | None = None,
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


async def async_get_weather_volatility(
    start_time: datetime,
    end_time: datetime,
    config: dict[str, Any] | None = None,
    *,
    config_path: str = "config.yaml",
) -> dict[str, float]:
    """
    Asynchronous wrapper for get_weather_volatility.

    Fetches weather data asynchronously and calculates volatility scores.
    """
    df = await async_get_weather_series(
        start_time, end_time, config=config, config_path=config_path
    )

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
    config: dict[str, Any] | None = None,
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


def calculate_physics_for_slots(
    slots: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Calculate physics-based PV for a list of historical slots.

    Used during training to calculate retroactive physics forecasts
    from stored radiation data.

    Args:
        slots: List of slot dicts with 'slot_start' and 'shortwave_radiation_w_m2' keys
        config: Configuration dict with 'system.location' and 'system.solar_arrays'

    Returns:
        List of slots with added 'physics_kwh' and 'physics_arrays' keys
    """
    system_cfg: dict[str, Any] = config.get("system", {}) or {}
    loc_cfg: dict[str, Any] = system_cfg.get("location", {}) or {}
    solar_arrays: list[Any] = system_cfg.get("solar_arrays", [])

    latitude = float(loc_cfg.get("latitude", 59.3))
    longitude = float(loc_cfg.get("longitude", 18.1))

    if not solar_arrays:
        # Fallback to legacy single array
        legacy_array: dict[str, Any] = system_cfg.get("solar_array", {}) or {}
        if legacy_array:
            solar_arrays = [legacy_array]

    if not solar_arrays:
        return [{**slot, "physics_kwh": None, "physics_arrays": []} for slot in slots]

    results: list[dict[str, Any]] = []
    for slot in slots:
        slot_start_raw = slot.get("slot_start")
        radiation = slot.get("shortwave_radiation_w_m2")

        # Parse slot_start if it's a string
        if isinstance(slot_start_raw, str):
            slot_start = pd.to_datetime(slot_start_raw, utc=True)
            if slot_start.tzinfo is None:
                slot_start = slot_start.tz_localize("UTC")
        elif isinstance(slot_start_raw, pd.Timestamp):
            slot_start = slot_start_raw
        else:
            results.append({**slot, "physics_kwh": None, "physics_arrays": []})
            continue

        # Calculate physics
        physics_kwh, physics_arrays = calculate_physics_pv(
            radiation_w_m2=radiation,
            solar_arrays=solar_arrays,  # type: ignore[arg-type]
            slot_start=slot_start,
            latitude=latitude,
            longitude=longitude,
        )

        results.append(
            {
                **slot,
                "physics_kwh": physics_kwh,
                "physics_arrays": physics_arrays,
            }
        )

    return results


def load_regions_config(regions_path: str = "ml/regions.json") -> dict[str, Any]:
    """Load regional weather coordinates configuration."""
    try:
        with Path(regions_path).open(encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        logger.warning("Invalid JSON in %s", regions_path)
        return {}


def get_regional_weather(
    start_time: datetime,
    end_time: datetime,
    price_area: str,
    config: dict[str, Any] | None = None,
    *,
    config_path: str = "config.yaml",
    regions_path: str = "ml/regions.json",
) -> dict[str, pd.DataFrame]:
    """
    Fetch weather data for all coordinates defined for a price area.

    Args:
        start_time: Start of the time window
        end_time: End of the time window
        price_area: Nordpool price area (e.g., "SE1", "SE2", "SE3", "SE4")
        config: Optional configuration dict
        config_path: Path to config file
        regions_path: Path to regions.json file

    Returns:
        Dict mapping coordinate keys to their weather DataFrames
    """
    cfg: dict[str, Any] = config or _load_config(config_path)
    regions = load_regions_config(regions_path)

    # Get fallback coordinates from config
    system_cfg: dict[str, Any] = cfg.get("system", {}) or {}
    loc_cfg: dict[str, Any] = system_cfg.get("location", {}) or {}
    fallback_lat: float = float(loc_cfg.get("latitude", 59.3))
    fallback_lon: float = float(loc_cfg.get("longitude", 18.1))

    # Check if price_area exists in regions
    if price_area not in regions:
        logger.warning(
            "Price area %r not found in %s, falling back to home coordinates",
            price_area,
            regions_path,
        )
        # Fetch weather for home coordinates only
        df = get_weather_series(
            start_time,
            end_time,
            cfg,
            config_path=config_path,
            forecast_days=16,
            extra_params=["wind_speed_10m"],
        )
        return {"local": df}

    area_coords = regions[price_area]
    results: dict[str, pd.DataFrame] = {}

    for coord_key, coord_data in area_coords.items():
        try:
            lat = float(coord_data.get("lat", fallback_lat))
            lon = float(coord_data.get("lon", fallback_lon))

            # Create a temporary config with this coordinate
            temp_cfg = copy.deepcopy(cfg)
            temp_cfg.setdefault("system", {}).setdefault("location", {})
            temp_cfg["system"]["location"]["latitude"] = lat
            temp_cfg["system"]["location"]["longitude"] = lon

            df = get_weather_series(
                start_time,
                end_time,
                temp_cfg,
                config_path=config_path,
                forecast_days=16,
                extra_params=["wind_speed_10m"],
            )

            if not df.empty:
                results[coord_key] = df
            else:
                logger.warning("No weather data for %s/%s", price_area, coord_key)

        except Exception as exc:
            logger.warning("Failed to fetch weather for %s/%s: %s", price_area, coord_key, exc)

    # If no coordinates succeeded, fall back to home coordinates
    if not results:
        logger.warning(
            "All regional weather fetches failed for %s, falling back to home coordinates",
            price_area,
        )
        df = get_weather_series(
            start_time,
            end_time,
            cfg,
            config_path=config_path,
            forecast_days=16,
            extra_params=["wind_speed_10m"],
        )
        return {"local": df}

    return results


def compute_regional_wind_index(
    regional_weather: dict[str, pd.DataFrame],
) -> pd.Series:
    """
    Compute the regional wind index as the arithmetic mean of wind speeds
    across all available coordinates.

    Args:
        regional_weather: Dict mapping coordinate keys to weather DataFrames

    Returns:
        Series with the averaged wind index values
    """
    wind_series_list: list[pd.Series] = []

    for coord_key, df in regional_weather.items():
        if df.empty:
            continue

        # Look for wind speed column (could be named wind_speed_10m or similar)
        wind_col = None
        for col in df.columns:
            if "wind_speed" in col.lower():
                wind_col = col
                break

        if wind_col is None:
            logger.warning("No wind speed column found for coordinate %s", coord_key)
            continue

        wind_series = df[wind_col].copy()
        wind_series.name = coord_key
        wind_series_list.append(wind_series)

    if not wind_series_list:
        # Return empty series if no wind data available
        return pd.Series(dtype="float64", name="wind_index")

    # Combine all series and compute mean (handles different indices via outer join)
    combined = pd.concat(wind_series_list, axis=1)
    wind_index = combined.mean(axis=1, skipna=True)
    wind_index.name = "wind_index"

    return wind_index
