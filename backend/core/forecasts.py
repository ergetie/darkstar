import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytz
import yaml
from open_meteo_solar_forecast import OpenMeteoSolarForecast

from backend.core import ha_client, prices
from backend.exceptions import PVForecastError
from ml.api import get_forecast_slots
from ml.weather import async_get_weather_volatility

logger = logging.getLogger("darkstar.core.forecasts")


def _forecasting_flag(forecasting_cfg: dict[str, Any], key: str) -> bool:
    return bool(forecasting_cfg.get(key, True))


def get_forecast_db_path() -> str:
    """Get the path to the learning/planner database."""
    from pathlib import Path

    return str(Path("data/planner_learning.db").resolve())


async def _get_stored_openmeteo_pv_for_slots(
    price_slots: list[dict[str, Any]],
    config: dict[str, Any],
) -> tuple[list[float], dict[str, float]] | None:
    """Return stored Open-Meteo PV baselines aligned to price slots, if fully covered."""
    if not price_slots:
        return [], {}

    from backend.learning.store import LearningStore

    timezone = str(config.get("timezone", "Europe/Stockholm"))
    local_tz = pytz.timezone(timezone)
    forecasting_cfg: dict[str, Any] = config.get("forecasting", {}) or {}
    forecast_version = str(forecasting_cfg.get("active_forecast_version", "aurora"))
    start = price_slots[0]["start_time"].astimezone(local_tz)
    end = price_slots[-1]["start_time"].astimezone(local_tz) + timedelta(minutes=15)
    store = LearningStore(get_forecast_db_path(), local_tz)
    try:
        rows = await store.get_openmeteo_pv_baselines_range(start, end, forecast_version)
    finally:
        await store.close()

    by_slot: dict[datetime, float] = {}
    for row in rows:
        ts = row["slot_start"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        if ts.tzinfo is None:
            ts = pytz.UTC.localize(ts)
        by_slot[ts.astimezone(local_tz)] = float(row["openmeteo_pv_forecast_kwh"] or 0.0)

    values: list[float] = []
    daily: dict[str, float] = {}
    for slot in price_slots:
        ts = slot["start_time"].astimezone(local_tz)
        if ts not in by_slot:
            return None
        value = by_slot[ts]
        values.append(value)
        day = ts.date().isoformat()
        daily[day] = daily.get(day, 0.0) + value
    return values, daily


async def get_forecast_data(
    price_slots: list[dict[str, Any]], config: dict[str, Any]
) -> dict[str, Any]:
    """
    Generate PV and load forecasts based on price slots and configuration (Asynchronous).
    """
    forecasting_cfg = cast("dict[str, Any]", config.get("forecasting", {}) or {})
    active_version = str(forecasting_cfg.get("active_forecast_version", "baseline_7_day_avg"))
    aurora_load_enabled = _forecasting_flag(forecasting_cfg, "aurora_load_enabled")
    aurora_pv_enabled = _forecasting_flag(forecasting_cfg, "aurora_pv_enabled")

    if active_version == "aurora" and (aurora_load_enabled or aurora_pv_enabled):
        return await _get_forecast_data_aurora(price_slots, config)
    else:
        return await _get_forecast_data_async(price_slots, config)


def _interpolate_small_gaps(
    db_slots: list[dict[str, Any]],
    max_gap_slots: int = 2,
) -> list[dict[str, Any]]:
    """
    Interpolate small gaps (1-2 slots) in forecast data.

    Only interpolates if gap is between valid (non-zero) data points.
    Never extrapolates - gaps at start or end are left as-is.
    """
    if not db_slots or len(db_slots) < 3:
        return db_slots

    result = list(db_slots)

    def is_valid_value(val: Any) -> bool:
        try:
            return float(val) > 0.001
        except (TypeError, ValueError):
            return False

    i = 0
    while i < len(result):
        slot = result[i]

        pv = slot.get("pv_forecast_kwh", 0.0)
        load = slot.get("load_forecast_kwh", slot.get("base_load_forecast_kwh", 0.0))

        if not is_valid_value(pv) or not is_valid_value(load):
            gap_start = i
            gap_end = i

            while gap_end < len(result) and (
                not is_valid_value(result[gap_end].get("pv_forecast_kwh", 0.0))
                or not is_valid_value(
                    result[gap_end].get(
                        "load_forecast_kwh",
                        result[gap_end].get("base_load_forecast_kwh", 0.0),
                    )
                )
            ):
                gap_end += 1

            gap_size = gap_end - gap_start

            if gap_size <= max_gap_slots and gap_start > 0 and gap_end < len(result):
                prev_pv = float(result[gap_start - 1].get("pv_forecast_kwh", 0.0))
                prev_load = float(
                    result[gap_start - 1].get("load_forecast_kwh")
                    or result[gap_start - 1].get("base_load_forecast_kwh", 0.0)
                )
                next_pv = float(result[gap_end].get("pv_forecast_kwh", 0.0))
                next_load = float(
                    result[gap_end].get("load_forecast_kwh")
                    or result[gap_end].get("base_load_forecast_kwh", 0.0)
                )

                for j in range(gap_start, gap_end):
                    fraction = (j - gap_start + 1) / (gap_size + 1)

                    result[j]["pv_forecast_kwh"] = prev_pv + fraction * (next_pv - prev_pv)
                    result[j]["load_forecast_kwh"] = prev_load + fraction * (next_load - prev_load)

                print(f"Info: Interpolated {gap_size} slot gap at index {gap_start}")

            i = gap_end
        else:
            i += 1

    return result


async def _get_forecast_data_aurora(
    price_slots: list[dict[str, Any]], config: dict[str, Any]
) -> dict[str, Any]:
    """Asynchronous logic for Aurora DB-backed forecasts."""
    timezone_name = str(config.get("timezone", "Europe/Stockholm"))
    local_tz = pytz.timezone(timezone_name)
    _fcfg: Any = config.get("forecasting", {})
    forecasting_cfg: dict[str, Any] = (
        cast("dict[str, Any]", _fcfg) if isinstance(_fcfg, dict) else {}
    )

    active_version = str(forecasting_cfg.get("active_forecast_version", "aurora"))
    aurora_load_enabled = _forecasting_flag(forecasting_cfg, "aurora_load_enabled")
    aurora_pv_enabled = _forecasting_flag(forecasting_cfg, "aurora_pv_enabled")

    # 1. Build slots strictly for the price horizon (0-48h)
    db_slots = await build_db_forecast_for_slots(price_slots, config)

    # 1b. Defensive interpolation for small gaps (1-2 slots / 15-30 min)
    # Belt-and-suspenders: handles race conditions where ML forecast
    # generation slightly misaligns with price slot boundaries. Larger gaps
    # (>2 slots) fall through to HA baseline fallback below.
    db_slots = _interpolate_small_gaps(db_slots)

    # 2. Fetch HA Load Baseline for fallback
    try:
        ha_profile = await ha_client.get_load_profile_from_ha(config)
    except Exception:
        ha_profile = [0.0] * 96

    openmeteo_result: dict[str, Any] | None = None
    if not aurora_pv_enabled:
        openmeteo_result = await _get_forecast_data_async(price_slots, config)
    raw_openmeteo_slots = (openmeteo_result or {}).get("slots", [])
    openmeteo_slots: list[dict[str, Any]] = (
        cast("list[dict[str, Any]]", raw_openmeteo_slots)
        if isinstance(raw_openmeteo_slots, list)
        else []
    )

    forecast_data: list[dict[str, Any]] = []
    if db_slots:
        print("Info: Using AURORA forecasts from learning DB (aurora).")
        for slot_idx, (slot, db_slot) in enumerate(zip(price_slots, db_slots, strict=False)):
            # Map slot time to 15-min index (0-95)
            # Localize to Stockholm/configured TZ to match profile
            ts = slot["start_time"].astimezone(local_tz)
            idx = int((ts.hour * 60 + ts.minute) // 15) % 96

            # Strictly prefer base_load_forecast_kwh (CLEAN) over load_forecast_kwh (DIRTY/TOTAL)
            val_load = float(
                db_slot.get("base_load_forecast_kwh") or db_slot.get("load_forecast_kwh", 0.0)
            )
            if not aurora_load_enabled or val_load <= 0.001:
                val_load = ha_profile[idx]

            val_pv = float(db_slot.get("pv_forecast_kwh", 0.0))
            openmeteo_pv = db_slot.get("openmeteo_pv_forecast_kwh")
            if not aurora_pv_enabled:
                om_slot: dict[str, Any] = (
                    openmeteo_slots[slot_idx] if slot_idx < len(openmeteo_slots) else {}
                )
                val_pv = float(
                    om_slot.get("openmeteo_pv_forecast_kwh")
                    or om_slot.get("pv_forecast_kwh")
                    or 0.0
                )
                openmeteo_pv = val_pv

            forecast_data.append(
                {
                    "start_time": slot["start_time"],
                    "pv_forecast_kwh": val_pv,
                    "openmeteo_pv_forecast_kwh": openmeteo_pv,
                    "load_forecast_kwh": val_load,
                    "pv_p10": db_slot.get("pv_p10"),
                    "pv_p90": db_slot.get("pv_p90"),
                    "load_p10": db_slot.get("load_p10"),
                    "load_p90": db_slot.get("load_p90"),
                }
            )
    else:
        print("Warning: AURORA slots missing for price horizon. Returning empty slots.")

    # 2. Build DAILY totals for the extended horizon required by S-index
    daily_pv_forecast: dict[str, float] = {}
    daily_load_forecast: dict[str, float] = {}
    daily_pv_p10: dict[str, float] = {}
    daily_pv_p90: dict[str, float] = {}
    daily_load_p10: dict[str, float] = {}
    daily_load_p90: dict[str, float] = {}

    if price_slots:
        start_dt = price_slots[0]["start_time"].astimezone(local_tz)
        s_index_cfg = config.get("s_index", {})
        horizon_days_cfg = s_index_cfg.get("s_index_horizon_days", 4)
        try:
            max_days = int(horizon_days_cfg)
        except (TypeError, ValueError):
            max_days = 4

        horizon_days = max(4, max_days + 1)
        end_dt = start_dt + timedelta(days=horizon_days)

        # Fetch extended records from DB (base + corrections)
        extended_records = await get_forecast_slots(start_dt, end_dt, active_version)

        for rec in extended_records:
            ts = rec["slot_start"]
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            if ts.tzinfo is None:
                ts = pytz.UTC.localize(ts)
            date_key = ts.astimezone(local_tz).date().isoformat()

            # Use new nested structure from ml/api.py get_forecast_slots()
            base_pv = float(rec["final"]["pv_kwh"])
            base_load = float(rec["final"]["load_kwh"])
            openmeteo_base_pv = float(rec.get("base", {}).get("pv_kwh", base_pv))

            # Corrector removed - using base forecasts only (recency-weighted training)
            pv_val = base_pv if aurora_pv_enabled else openmeteo_base_pv

            # Fallback for Load if 0.0
            if not aurora_load_enabled:
                ts_local = ts.astimezone(local_tz)
                idx = int((ts_local.hour * 60 + ts_local.minute) // 15) % 96
                load_val = ha_profile[idx]
            elif base_load <= 0.001:
                # Calculate 15-min slot index (0-95)
                # ts is already localized or UTC, let's ensure local time for index match
                ts_local = ts.astimezone(local_tz)
                idx = int((ts_local.hour * 60 + ts_local.minute) // 15) % 96

                # Lazy load HA profile if needed (optimization)
                # But we likely already loaded it in _get_forecast_data_aurora if we are here?
                # Actually this is _get_forecast_data_aurora
                # We need to make sure ha_profile is available here.
                # It is not available in specific scope for "extended_records" loop below.
                # Let's fetch it if not existent (or pass it in).
                # Ideally use the one fetched above if possible.
                # To be safe and clean, we'll try fetch again or use a safe method.
                # Since this is "daily" aggregation, running fetching once is fine.
                try:
                    # We might want to cache this call if it's expensive, but for now it's okay.
                    # ha_profile from above scope is available here
                    # unless we are in the SAME function.
                    # We ARE in _get_forecast_data_aurora function scope.
                    # So 'ha_profile' defined at line 269 IS available!
                    load_val = ha_profile[idx]
                except (UnboundLocalError, NameError):
                    # Just in case code structure changed or valid ha_profile logic was conditioned
                    # We will re-fetch or use 0 default to avoid crash
                    try:
                        load_val = (await ha_client.get_load_profile_from_ha(config))[idx]
                    except Exception:
                        load_val = 0.0
            else:
                load_val = base_load

            daily_pv_forecast[date_key] = daily_pv_forecast.get(date_key, 0.0) + pv_val
            daily_load_forecast[date_key] = daily_load_forecast.get(date_key, 0.0) + load_val

            if rec.get("probabilistic", {}).get("pv_p10") is not None:
                daily_pv_p10[date_key] = daily_pv_p10.get(date_key, 0.0) + float(
                    rec["probabilistic"]["pv_p10"]
                )
            if rec.get("probabilistic", {}).get("pv_p90") is not None:
                daily_pv_p90[date_key] = daily_pv_p90.get(date_key, 0.0) + float(
                    rec["probabilistic"]["pv_p90"]
                )
            if rec.get("probabilistic", {}).get("load_p10") is not None:
                daily_load_p10[date_key] = daily_load_p10.get(date_key, 0.0) + float(
                    rec["probabilistic"]["load_p10"]
                )
            if rec.get("probabilistic", {}).get("load_p90") is not None:
                daily_load_p90[date_key] = daily_load_p90.get(date_key, 0.0) + float(
                    rec["probabilistic"]["load_p90"]
                )

    return {
        "slots": forecast_data,
        "daily_pv_forecast": daily_pv_forecast,
        "daily_load_forecast": daily_load_forecast,
        "daily_probabilistic": {
            "pv_p10": daily_pv_p10,
            "pv_p90": daily_pv_p90,
            "pv_p50": daily_pv_forecast,  # P50 = corrected base forecast
            "load_p10": daily_load_p10,
            "load_p90": daily_load_p90,
            "load_p50": daily_load_forecast,  # P50 = corrected base forecast
        },
    }


async def _get_forecast_data_async(
    price_slots: list[dict[str, Any]], config: dict[str, Any]
) -> dict[str, Any]:
    """
    Async logic for fallback Open-Meteo forecasts.
    """
    _sys_cfg: Any = config.get("system", {})
    if isinstance(_sys_cfg, dict):
        system_config: dict[str, Any] = cast("dict[str, Any]", _sys_cfg)
    else:
        system_config = {}

    _loc_cfg: Any = system_config.get("location", {})
    if isinstance(_loc_cfg, dict):
        location: dict[str, Any] = cast("dict[str, Any]", _loc_cfg)
    else:
        location = {}

    latitude = float(location.get("latitude", 59.3))
    longitude = float(location.get("longitude", 18.1))

    # Support for Multi-Array (REV ARC14 Phase 2)
    solar_arrays: list[Any] = system_config.get("solar_arrays", [])
    azimuth_list: list[float] = []
    tilt_list: list[float] = []
    kwp_list: list[float] = []
    if not solar_arrays or not isinstance(solar_arrays, list):  # type: ignore[unnecessary-isinstance-call]
        # Fallback to legacy single array or default
        _legacy_cfg: Any = system_config.get("solar_array", {})
        solar_array: dict[str, Any] = (
            cast("dict[str, Any]", _legacy_cfg) if isinstance(_legacy_cfg, dict) else {}
        )
        azimuth_list = [float(solar_array.get("azimuth", 180))]
        tilt_list = [float(solar_array.get("tilt", 30))]
        kwp_list = [float(solar_array.get("kwp", 5.0))]
        logger.debug("Falling back to legacy solar_array for forecast")
    else:
        for i, _array in enumerate(solar_arrays):
            a_idx = i + 1
            array: dict[str, Any] = (
                cast("dict[str, Any]", _array) if isinstance(_array, dict) else {}
            )
            name: str = str(array.get("name", f"Array {a_idx}"))
            az = float(array.get("azimuth", 180))
            ti = float(array.get("tilt", 30))
            kp = float(array.get("kwp", 0.0))
            azimuth_list.append(az)
            tilt_list.append(ti)
            kwp_list.append(kp)
            logger.debug(
                "Solar array %d (%s) configured: %.1fkWp, Azimuth: %.0f, Tilt: %.0f",
                a_idx,
                name,
                kp,
                az,
                ti,
            )

    timezone = str(config.get("timezone", "Europe/Stockholm"))
    local_tz = pytz.timezone(timezone)

    # --- FALLBACK: Open-Meteo (Live API) ---

    pv_kwh_forecast: list[float] = []
    daily_pv_forecast: dict[str, float] = {}
    resolution_hours = 0.25

    try:

        async def _fetch_forecast():
            # Filter out invalid arrays (kwp <= 0) - REV F62 fix
            valid_arrays = [
                (az, ti, kp)
                for az, ti, kp in zip(azimuth_list, tilt_list, kwp_list, strict=False)
                if kp > 0.0
            ]

            if not valid_arrays:
                logger.warning(
                    "No valid solar arrays with kwp > 0 found. Using default single array."
                )
                # Fallback to default single array
                azimuth_list_clean = [0.0]  # Open-Meteo South is 0
                tilt_list_clean = [30.0]
                kwp_list_clean = [5.0]
            else:
                # Open-Meteo expects -180 to 180 (0=South, 90=West)
                # Convert from HA (North=0, East=90, South=180, West=270)
                azimuth_list_clean = [(arr[0] % 360) - 180 for arr in valid_arrays]
                tilt_list_clean = [arr[1] for arr in valid_arrays]
                kwp_list_clean = [arr[2] for arr in valid_arrays]

                # Log which arrays were filtered out
                filtered_count = len(kwp_list) - len(valid_arrays)
                if filtered_count > 0:
                    logger.warning("Filtered out %d solar array(s) with kwp <= 0.0", filtered_count)

            summed_watts: dict[datetime, float] = {}
            for azimuth, tilt, kwp in zip(
                azimuth_list_clean, tilt_list_clean, kwp_list_clean, strict=True
            ):
                async with OpenMeteoSolarForecast(
                    latitude=latitude,
                    longitude=longitude,
                    declination=tilt,
                    azimuth=azimuth,
                    dc_kwp=kwp,
                ) as forecast:
                    estimate = await forecast.estimate()
                    for dt, watts in estimate.watts.items():
                        summed_watts[dt] = summed_watts.get(dt, 0.0) + float(watts or 0.0)

            return summed_watts

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

        # REV F60 Phase 7: Clear forecast errors after successful forecast
        from backend.health import clear_forecast_errors

        clear_forecast_errors()

    except Exception as exc:
        from backend.health import record_forecast_error

        stored = await _get_stored_openmeteo_pv_for_slots(price_slots, config)
        if stored is not None:
            pv_kwh_forecast, daily_pv_forecast = stored
            record_forecast_error(
                RuntimeError("API unreachable — using last known forecast"),
                context={"arrays": len(kwp_list), "fallback": "last_known_openmeteo"},
            )
            logger.warning("Open-Meteo PV fetch failed; using stored last-known forecast")
        else:
            # REV F60: Removed dangerous dummy fallback. PV forecast failure is critical.
            # Using fake solar data would cause the planner to make incorrect decisions.
            error = PVForecastError(
                "Open-Meteo Solar Forecast failed - cannot generate valid PV forecast",
                original_exception=exc,
                solar_arrays=len(kwp_list),
                details={
                    "latitude": latitude,
                    "longitude": longitude,
                    "arrays": len(kwp_list),
                    "total_kwp": sum(kwp_list),
                },
            )
            record_forecast_error(error, context={"arrays": len(kwp_list)})
            raise error from exc
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
        load_profile = await ha_client.get_load_profile_from_ha(config)
    except Exception as exc:
        print(f"Warning: Failed to get HA load profile, using dummy: {exc}")
        load_profile = ha_client.get_dummy_load_profile(config)

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

    forecast_data: list[dict[str, Any]] = []
    total_slots = len(price_slots)
    for idx in range(total_slots):
        pv_kwh = pv_kwh_forecast[idx] if idx < len(pv_kwh_forecast) else 0.0
        load_kwh = load_kwh_forecast[idx] if idx < len(load_kwh_forecast) else 0.0
        slot = price_slots[idx]
        forecast_data.append(
            {
                "start_time": slot["start_time"],
                "pv_forecast_kwh": pv_kwh,
                "openmeteo_pv_forecast_kwh": pv_kwh,
                "load_forecast_kwh": load_kwh,
            }
        )

    return {
        "slots": forecast_data,
        "daily_pv_forecast": daily_pv_forecast,
        "daily_load_forecast": daily_load_forecast,
    }


async def get_all_input_data(
    config_path: str = "config.yaml",
    ev_plugged_in_override: bool | None = None,
    ev_plug_override_charger_id: str | None = None,
) -> dict[str, Any]:
    """
    Orchestrate all input data fetching.

    Args:
        config_path: Path to config.yaml
        ev_plugged_in_override: If provided, passed to get_initial_state to avoid REST race
        ev_plug_override_charger_id: Charger ID to apply the plug state override to (Task 7.3)
    """
    # Load config
    with Path(config_path).open() as f:
        config = yaml.safe_load(f)

    # --- AUTO-RUN ML INFERENCE IF ANY AURORA DOMAIN IS ACTIVE ---
    _forecasting_cfg: Any = config.get("forecasting", {}) or {}
    forecasting_cfg: dict[str, Any] = (
        cast("dict[str, Any]", _forecasting_cfg) if isinstance(_forecasting_cfg, dict) else {}
    )
    if forecasting_cfg.get("active_forecast_version") == "aurora" and (
        _forecasting_flag(forecasting_cfg, "aurora_load_enabled")
        or _forecasting_flag(forecasting_cfg, "aurora_pv_enabled")
    ):
        try:
            print("🧠 Running AURORA ML Inference Pipeline (base + correction)...")
            from ml.pipeline import run_inference

            # Rev 2.4.13: Respect configured horizon (default 2 days / 48h)
            # Previously hardcoded to 168h (7 days), causing wasted CPU cycles.
            learning_cfg = config.get("learning", {})
            days = int(learning_cfg.get("horizon_days", 2))
            hours = days * 24

            await run_inference(horizon_hours=hours, forecast_version="aurora")
        except Exception as e:
            print(f"⚠️ AURORA Inference Pipeline Failed: {e}")

    # --- FETCH CONTEXT (New in Rev 19, extended in Rev 58) ---
    sensors = config.get("input_sensors", {})
    vacation_id = sensors.get("vacation_mode")
    alarm_id = sensors.get("alarm_state")

    timezone_name = config.get("timezone", "Europe/Stockholm")
    local_tz = pytz.timezone(timezone_name)
    now_local = datetime.now(local_tz)
    horizon_end = now_local + timedelta(hours=48)

    volatility_raw = await async_get_weather_volatility(now_local, horizon_end, config)
    cloud_vol = float(volatility_raw.get("cloud_volatility", 0.0) or 0.0)
    temp_vol = float(volatility_raw.get("temp_volatility", 0.0) or 0.0)

    context = {
        "vacation_mode": await ha_client.get_ha_bool(vacation_id) if vacation_id else False,
        "alarm_armed": await ha_client.get_ha_bool(alarm_id) if alarm_id else False,
        "weather_volatility": {
            "cloud": max(0.0, min(1.0, cloud_vol)),
            "temp": max(0.0, min(1.0, temp_vol)),
        },
    }
    # -------------------------------------

    price_data = await prices.get_nordpool_data(config_path)

    forecast_result = await get_forecast_data(price_data, config)
    forecast_data = forecast_result.get("slots", [])
    initial_state = await ha_client.get_initial_state(
        config_path,
        ev_plugged_in_override=ev_plugged_in_override,
        ev_plug_override_charger_id=ev_plug_override_charger_id,
    )

    return {
        "price_data": price_data,
        "forecast_data": forecast_data,
        "initial_state": initial_state,
        "daily_pv_forecast": forecast_result.get("daily_pv_forecast", {}),
        "daily_load_forecast": forecast_result.get("daily_load_forecast", {}),
        "daily_probabilistic": forecast_result.get("daily_probabilistic", {}),
        "context": context,
    }


async def get_db_forecast_slots(
    start: datetime, end: datetime, config: dict[str, Any]
) -> list[dict[str, Any]]:
    """
    Fetch forecast slots from the learning database via ml.api.

    This helper does not change planner behaviour by itself; it simply
    wraps get_forecast_slots using the configured active_forecast_version.
    """
    _fcfg: Any = config.get("forecasting", {})
    if isinstance(_fcfg, dict):
        forecasting_cfg: dict[str, Any] = cast("dict[str, Any]", _fcfg)
    else:
        forecasting_cfg = {}

    version = str(forecasting_cfg.get("active_forecast_version", "baseline_7_day_avg"))
    return await get_forecast_slots(start, end, version)


async def build_db_forecast_for_slots(
    price_slots: list[dict[str, Any]], config: dict[str, Any]
) -> list[dict[str, Any]]:
    """
    Fetch DB forecast records matching the exact time range of price_slots.
    Returns a list of dicts aligned with price_slots (or empty list if no match).
    """
    if not price_slots:
        return []

    _fcfg: Any = config.get("forecasting", {})
    if isinstance(_fcfg, dict):
        forecasting_cfg: dict[str, Any] = cast("dict[str, Any]", _fcfg)
    else:
        forecasting_cfg = {}

    version = str(forecasting_cfg.get("active_forecast_version", "baseline_7_day_avg"))

    timezone = str(config.get("timezone", "Europe/Stockholm"))
    local_tz = pytz.timezone(timezone)

    # Determine horizon from price slots
    start_time = price_slots[0]["start_time"].astimezone(local_tz)
    end_time = price_slots[-1]["start_time"].astimezone(local_tz) + timedelta(
        minutes=15,
    )

    records = await get_forecast_slots(start_time, end_time, version)
    if not records:
        return []

    # Index forecasts by localised slot_start for quick lookup
    indexed: dict[datetime, dict[str, Any]] = {}
    for rec in records:
        ts = rec["slot_start"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        if ts.tzinfo is None:
            ts = pytz.UTC.localize(ts)
        indexed[ts.astimezone(local_tz)] = rec

    result: list[dict[str, Any]] = []
    for slot in price_slots:
        ts = slot["start_time"].astimezone(local_tz)
        rec = indexed.get(ts)

        # Default values in case no forecast is found
        pv = 0.0
        load = 0.0
        pv_p10 = None
        pv_p90 = None
        load_p10 = None
        load_p90 = None

        if rec is None:
            # Defensive fallback: find closest forecast at or before requested slot
            fallback_ts = None
            for forecast_ts in sorted(indexed.keys()):
                if forecast_ts <= ts:
                    fallback_ts = forecast_ts
                else:
                    break

            if fallback_ts is not None:
                rec = indexed[fallback_ts]
                print(
                    f"Warning: No exact forecast match for {ts}, using fallback from {fallback_ts}"
                )

        if rec is not None:
            # Use new nested structure from ml/api.py get_forecast_slots()
            pv = float(rec["final"]["pv_kwh"])
            load = float(rec["final"]["load_kwh"])

            # Extract probabilistic data
            prob_data = rec.get("probabilistic", {})
            pv_p10 = prob_data.get("pv_p10")
            pv_p90 = prob_data.get("pv_p90")
            load_p10 = prob_data.get("load_p10")
            load_p90 = prob_data.get("load_p90")

        result.append(
            {
                "pv_forecast_kwh": pv,
                "load_forecast_kwh": load,
                "pv_p10": pv_p10,
                "pv_p90": pv_p90,
                "load_p10": load_p10,
                "load_p90": load_p90,
            }
        )

    return result
