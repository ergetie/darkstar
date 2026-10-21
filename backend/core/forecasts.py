import logging
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, cast

import pytz
import yaml
from open_meteo_solar_forecast import OpenMeteoSolarForecast
from sqlalchemy.exc import OperationalError

from backend.core import ha_client, prices
from backend.core.open_meteo_retry import is_transient_pv_error, retry_async
from backend.exceptions import PVForecastError
from ml.api import get_forecast_slots

logger = logging.getLogger("darkstar.core.forecasts")


def _forecasting_flag(forecasting_cfg: dict[str, Any], key: str) -> bool:
    return bool(forecasting_cfg.get(key, True))


def get_forecast_db_path() -> str:
    """Get the path to the learning/planner database."""
    from pathlib import Path

    return str(Path("data/planner_learning.db").resolve())


# Stored baselines older than this (before the first price slot) are not used when
# estimating missing slots. Matches forecasting.pv_personalization_ramp_days default.
_PV_FALLBACK_LOOKBACK_DAYS = 14


def _slot_key(ts: datetime) -> int:
    """Canonical slot key: Unix seconds of the 15-minute-floored UTC instant.

    Accepts python datetimes (fixed-offset or pytz) and pandas Timestamps; naive values
    are treated as UTC. Integer keys avoid the hashing ambiguity of aware datetimes and
    Timestamps in a DST fold. Flooring on the instant assumes zone offsets are whole
    multiples of 15 minutes, which holds for all supported zones.
    """
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=pytz.UTC)
    seconds = int(ts.timestamp())
    return seconds - seconds % 900


def _estimate_from_same_time_of_day(
    ts: datetime,
    by_tod: dict[time, list[tuple[date, float]]],
) -> float | None:
    """Stored value at the same local time of day: latest earlier day, else earliest later day."""
    candidates = by_tod.get(ts.time())
    if not candidates:
        return None
    day = ts.date()
    earlier = [item for item in candidates if item[0] < day]
    if earlier:
        return max(earlier, key=lambda item: item[0])[1]
    later = [item for item in candidates if item[0] > day]
    if later:
        return min(later, key=lambda item: item[0])[1]
    return None


async def _get_stored_openmeteo_pv_for_slots(
    price_slots: list[dict[str, Any]],
    config: dict[str, Any],
    known: dict[int, float] | None = None,
) -> tuple[list[float], dict[str, float], list[int]] | None:
    """Return PV values aligned to price slots built from stored Open-Meteo baselines.

    Slots with a stored baseline use it. Remaining slots are estimated from the stored
    value at the same local time of day (latest earlier day wins, else earliest later
    day) and their indices are returned as the third element. Missing slots are never
    defaulted to zero; ``None`` is returned when any slot cannot be filled.

    ``known`` maps slot index -> value already obtained from a live response. Slots
    outside ``known`` are then always treated as estimated.
    """
    if not price_slots:
        return [], {}, []

    from backend.learning.store import LearningStore

    timezone = str(config.get("timezone", "Europe/Stockholm"))
    local_tz = pytz.timezone(timezone)
    forecasting_cfg: dict[str, Any] = config.get("forecasting", {}) or {}
    forecast_version = str(forecasting_cfg.get("active_forecast_version", "aurora"))
    slot_times = [slot["start_time"].astimezone(local_tz) for slot in price_slots]
    start = min(slot_times) - timedelta(days=_PV_FALLBACK_LOOKBACK_DAYS)
    end = max(slot_times) + timedelta(minutes=15)
    store = LearningStore(get_forecast_db_path(), local_tz)
    try:
        rows = await store.get_openmeteo_pv_baselines_range(start, end, forecast_version)
    except OperationalError as exc:
        # A fresh install (or an unmigrated/unreadable DB) has no stored baselines;
        # that means "no estimate", never a crash that masks the real forecast error.
        logger.warning("Stored Open-Meteo PV baselines unavailable: %s", exc)
        return None
    finally:
        await store.close()

    by_slot: dict[int, float] = {}
    by_tod: dict[time, list[tuple[date, float]]] = {}
    for row in rows:
        raw_value = row["openmeteo_pv_forecast_kwh"]
        if raw_value is None:
            continue
        ts = row["slot_start"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        if ts.tzinfo is None:
            ts = pytz.UTC.localize(ts)
        local_ts = ts.astimezone(local_tz)
        value = float(raw_value)
        by_slot[_slot_key(ts)] = value
        by_tod.setdefault(local_ts.time(), []).append((local_ts.date(), value))

    values: list[float] = []
    daily: dict[str, float] = {}
    estimated: list[int] = []
    for idx, ts in enumerate(slot_times):
        if known is not None and idx in known:
            value = known[idx]
        else:
            exact = by_slot.get(_slot_key(ts))
            if known is None and exact is not None:
                value = exact
            else:
                filled = exact if exact is not None else _estimate_from_same_time_of_day(ts, by_tod)
                if filled is None:
                    return None
                value = filled
                estimated.append(idx)
        values.append(value)
        day = ts.date().isoformat()
        daily[day] = daily.get(day, 0.0) + value
    return values, daily, estimated


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


def _interpolate_small_pv_gaps(slots: list[dict[str, Any]], max_gap_slots: int = 2) -> None:
    """Linearly interpolate PV across genuine small gaps (1-2 slots) between stored slots.

    Operates in place on slots flagged ``pv_estimated``; longer gaps and gaps at either
    end keep their same-time-of-day estimate.
    """
    i = 0
    while i < len(slots):
        if not slots[i].get("pv_estimated"):
            i += 1
            continue
        end = i
        while end < len(slots) and slots[end].get("pv_estimated"):
            end += 1
        size = end - i
        if size <= max_gap_slots and i > 0 and end < len(slots):
            prev_pv = float(slots[i - 1]["pv_forecast_kwh"])
            next_pv = float(slots[end]["pv_forecast_kwh"])
            for j in range(i, end):
                fraction = (j - i + 1) / (size + 1)
                slots[j]["pv_forecast_kwh"] = prev_pv + fraction * (next_pv - prev_pv)
        i = end


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

                logger.info("Interpolated %d slot gap at index %d", gap_size, gap_start)

            i = gap_end
        else:
            i += 1

    return result


def _report_stored_pv_coverage(db_slots: list[dict[str, Any]], total_slots: int) -> None:
    """Surface stored-PV coverage problems through the forecast health status.

    Only slots missing from otherwise present stored data (a stale/failed refresh) are
    reported. Absence of any stored data is a learning-period state, never an error.
    """
    from backend.health import record_forecast_error

    if not db_slots:
        # Nothing stored at all (fresh install / learning period before the first forward
        # run). That is not an outage: no health error, only an informational log. Real
        # API failures are reported by the forward job and the Open-Meteo fetch itself.
        logger.info(
            "No stored Aurora PV forecast rows yet for the %d-slot horizon "
            "(learning period); no health error recorded",
            total_slots,
        )
        return

    estimated = sum(1 for slot in db_slots if slot.get("pv_estimated"))
    if estimated:
        record_forecast_error(
            RuntimeError(
                "Stored PV forecast does not cover the horizon — using last known forecast"
            ),
            context={
                "fallback": "stored_same_time_of_day",
                "estimated_slots": estimated,
                "total_slots": total_slots,
            },
        )
        logger.warning(
            "Stored PV forecast missing slots; %d of %d estimated from same time of day",
            estimated,
            total_slots,
        )


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

    if aurora_pv_enabled:
        _report_stored_pv_coverage(db_slots, len(price_slots))

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
        logger.info("Using AURORA forecasts from learning DB (aurora).")
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
                    "pv_estimated": bool(db_slot.get("pv_estimated")) and aurora_pv_enabled,
                    "openmeteo_pv_forecast_kwh": openmeteo_pv,
                    "load_forecast_kwh": val_load,
                    "pv_p10": db_slot.get("pv_p10"),
                    "pv_p90": db_slot.get("pv_p90"),
                    "load_p10": db_slot.get("load_p10"),
                    "load_p90": db_slot.get("load_p90"),
                }
            )
    else:
        logger.warning("AURORA slots missing for price horizon. Returning empty slots.")

    # 2. Build DAILY totals for the extended horizon required by S-index
    extended_slots: list[dict[str, Any]] = []
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
            ts_local = ts.astimezone(local_tz)
            date_key = ts_local.date().isoformat()

            # Use new nested structure from ml/api.py get_forecast_slots()
            base_pv = float(rec["final"]["pv_kwh"])
            base_load = float(rec["final"]["load_kwh"])
            openmeteo_base_pv = float(rec.get("base", {}).get("pv_kwh", base_pv))

            # Corrector removed - using base forecasts only (recency-weighted training)
            pv_val = base_pv if aurora_pv_enabled else openmeteo_base_pv

            # Fallback for Load if 0.0
            if not aurora_load_enabled:
                idx = int((ts_local.hour * 60 + ts_local.minute) // 15) % 96
                load_val = ha_profile[idx]
            elif base_load <= 0.001:
                # Calculate 15-min slot index (0-95)
                # ts is already localized or UTC, let's ensure local time for index match
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

            probabilistic = rec.get("probabilistic", {})
            extended_slots.append(
                {
                    "start_time": ts_local,
                    "pv_forecast_kwh": pv_val,
                    "load_forecast_kwh": load_val,
                    "pv_p10": probabilistic.get("pv_p10"),
                    "pv_p90": probabilistic.get("pv_p90"),
                    "load_p10": probabilistic.get("load_p10"),
                    "load_p90": probabilistic.get("load_p90"),
                }
            )

            if probabilistic.get("pv_p10") is not None:
                daily_pv_p10[date_key] = daily_pv_p10.get(date_key, 0.0) + float(
                    probabilistic["pv_p10"]
                )
            if probabilistic.get("pv_p90") is not None:
                daily_pv_p90[date_key] = daily_pv_p90.get(date_key, 0.0) + float(
                    probabilistic["pv_p90"]
                )
            if probabilistic.get("load_p10") is not None:
                daily_load_p10[date_key] = daily_load_p10.get(date_key, 0.0) + float(
                    probabilistic["load_p10"]
                )
            if probabilistic.get("load_p90") is not None:
                daily_load_p90[date_key] = daily_load_p90.get(date_key, 0.0) + float(
                    probabilistic["load_p90"]
                )

    return {
        "slots": forecast_data,
        "extended_slots": extended_slots,
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
    estimated_slots: list[int] = []
    incomplete_response = False
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
            for array_no, (azimuth, tilt, kwp) in enumerate(
                zip(azimuth_list_clean, tilt_list_clean, kwp_list_clean, strict=True), start=1
            ):

                async def _estimate_array(
                    azimuth: float = azimuth, tilt: float = tilt, kwp: float = kwp
                ) -> Any:
                    # Fresh session per attempt; only this array is retried.
                    async with OpenMeteoSolarForecast(
                        latitude=latitude,
                        longitude=longitude,
                        declination=tilt,
                        azimuth=azimuth,
                        dc_kwp=kwp,
                        # Slots start at today 00:00 at the earliest; the library
                        # default (92 days) only adds unused history.
                        past_days=1,
                    ) as forecast:
                        return await forecast.estimate()

                estimate = await retry_async(
                    _estimate_array,
                    label=f"PV array {array_no}",
                    is_transient=is_transient_pv_error,
                )
                for dt, watts in estimate.watts.items():
                    summed_watts[dt] = summed_watts.get(dt, 0.0) + float(watts or 0.0)

            return summed_watts

        solar_data_dict = await _fetch_forecast()
        if not solar_data_dict:
            # An empty estimate must never turn into an all-zero forecast.
            raise RuntimeError("Open-Meteo returned an empty PV estimate")

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
        # Match by canonical UTC instant: series keys are fixed-offset datetimes while
        # slot starts may be pytz datetimes or pandas Timestamps (incl. DST fold).
        watts_by_key = {_slot_key(dt): watts for dt, watts in solar_data_dict.items()}
        known_kwh: dict[int, float] = {}
        for slot_idx, slot in enumerate(price_slots):
            watts = watts_by_key.get(_slot_key(slot["start_time"]))
            if watts is not None:
                known_kwh[slot_idx] = watts * 0.25 / 1000.0

        if len(known_kwh) < len(price_slots):
            # Slots beyond the API horizon are estimated, never defaulted to zero.
            filled = await _get_stored_openmeteo_pv_for_slots(price_slots, config, known_kwh)
            if filled is None:
                raise RuntimeError("Open-Meteo response misses slots and no estimate exists")
            pv_kwh_forecast, daily_pv_forecast, estimated_slots = filled
            incomplete_response = True
        else:
            pv_kwh_forecast = [known_kwh[i] for i in range(len(price_slots))]

        if incomplete_response:
            from backend.health import record_forecast_error

            record_forecast_error(
                RuntimeError("Open-Meteo forecast incomplete — using last known forecast"),
                context={
                    "arrays": len(kwp_list),
                    "fallback": "last_known_openmeteo",
                    "estimated_slots": len(estimated_slots),
                    "total_slots": len(price_slots),
                },
            )
            logger.warning(
                "Open-Meteo response missing slots; %d of %d slots estimated",
                len(estimated_slots),
                len(price_slots),
            )
        else:
            # REV F60 Phase 7: Clear forecast errors after successful forecast
            from backend.health import clear_forecast_errors

            clear_forecast_errors()

    except Exception as exc:
        from backend.health import record_forecast_error

        stored = await _get_stored_openmeteo_pv_for_slots(price_slots, config)
        if stored is not None:
            pv_kwh_forecast, daily_pv_forecast, estimated_slots = stored
            record_forecast_error(
                RuntimeError("API unreachable — using last known forecast"),
                context={
                    "arrays": len(kwp_list),
                    "fallback": "last_known_openmeteo",
                    "estimated_slots": len(estimated_slots),
                    "total_slots": len(price_slots),
                },
            )
            logger.warning(
                "Open-Meteo PV fetch failed; using stored last-known forecast "
                "(%d of %d slots estimated)",
                len(estimated_slots),
                len(price_slots),
            )
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
        logger.warning("Failed to get HA load profile, using dummy: %s", exc)
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
    estimated_set = set(estimated_slots)
    for idx in range(total_slots):
        pv_kwh = pv_kwh_forecast[idx]
        load_kwh = load_kwh_forecast[idx] if idx < len(load_kwh_forecast) else 0.0
        slot = price_slots[idx]
        is_estimated = idx in estimated_set
        forecast_data.append(
            {
                "start_time": slot["start_time"],
                "pv_forecast_kwh": pv_kwh,
                # Estimated slots carry no baseline so store_forecasts (COALESCE)
                # never persists them as real Open-Meteo values.
                "openmeteo_pv_forecast_kwh": None if is_estimated else pv_kwh,
                "pv_estimated": is_estimated,
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
    ev_plug_overrides: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """
    Orchestrate all input data fetching.

    Args:
        config_path: Path to config.yaml
        ev_plug_overrides: Per-charger plug-state overrides ({charger_id: plugged}),
            passed to get_initial_state to avoid the REST race after plug events
    """
    # Load config
    with Path(config_path).open() as f:
        config = yaml.safe_load(f)
    from backend.core.water_heating import validate_water_heating_config

    validate_water_heating_config(config)

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
            logger.info("Running AURORA ML Inference Pipeline (base + correction)...")
            from ml.pipeline import run_inference

            # Rev 2.4.13: Respect configured horizon (default 2 days / 48h)
            # Previously hardcoded to 168h (7 days), causing wasted CPU cycles.
            learning_cfg = config.get("learning", {})
            days = int(learning_cfg.get("horizon_days", 2))
            hours = days * 24

            await run_inference(horizon_hours=hours, forecast_version="aurora")
        except Exception as e:
            logger.warning("AURORA Inference Pipeline failed: %s", e)

    # --- FETCH CONTEXT (New in Rev 19, extended in Rev 58) ---
    sensors = config.get("input_sensors", {})
    vacation_id = sensors.get("vacation_mode")
    alarm_id = sensors.get("alarm_state")

    context = {
        "vacation_mode": await ha_client.get_ha_bool(vacation_id) if vacation_id else False,
        "alarm_armed": await ha_client.get_ha_bool(alarm_id) if alarm_id else False,
    }
    # -------------------------------------

    price_data = await prices.get_nordpool_data(config_path)

    forecast_result = await get_forecast_data(price_data, config)
    forecast_data = forecast_result.get("slots", [])
    extended_forecast_data = forecast_result.get("extended_slots", [])
    timezone = pytz.timezone(str(config.get("timezone", "Europe/Stockholm")))
    now = datetime.now(timezone)
    horizon_start = now.replace(minute=now.minute // 15 * 15, second=0, microsecond=0)
    progress_cutoff = next(
        (slot["start_time"] for slot in price_data if slot["start_time"] >= horizon_start),
        price_data[0]["start_time"] if price_data else None,
    )
    initial_state = await ha_client.get_initial_state(
        config_path,
        ev_plug_overrides=ev_plug_overrides,
        progress_cutoff=progress_cutoff,
    )

    return {
        "price_data": price_data,
        "forecast_data": forecast_data,
        "extended_forecast_data": extended_forecast_data,
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

    # Determine horizon from price slots. Stored days before the first slot are fetched
    # too so slots without a stored row can be estimated from the same time of day.
    start_time = price_slots[0]["start_time"].astimezone(local_tz)
    end_time = price_slots[-1]["start_time"].astimezone(local_tz) + timedelta(
        minutes=15,
    )

    records = await get_forecast_slots(
        start_time - timedelta(days=_PV_FALLBACK_LOOKBACK_DAYS), end_time, version
    )
    if not records:
        return []

    # Index forecasts by canonical UTC slot key for quick lookup; local times are kept
    # for the ordered fallback search and time-of-day estimates.
    indexed: dict[int, dict[str, Any]] = {}
    local_by_key: dict[int, datetime] = {}
    pv_by_tod: dict[time, list[tuple[date, float]]] = {}
    for rec in records:
        ts = rec["slot_start"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        if ts.tzinfo is None:
            ts = pytz.UTC.localize(ts)
        local_ts = ts.astimezone(local_tz)
        key = _slot_key(ts)
        indexed[key] = rec
        local_by_key[key] = local_ts
        pv_by_tod.setdefault(local_ts.time(), []).append(
            (local_ts.date(), float(rec["final"]["pv_kwh"]))
        )
    sorted_stored = sorted(local_by_key.items(), key=lambda item: item[1])

    result: list[dict[str, Any]] = []
    for slot in price_slots:
        ts = slot["start_time"].astimezone(local_tz)
        rec = indexed.get(_slot_key(ts))
        estimated = rec is None

        # Default values in case no forecast is found
        pv = 0.0
        load = 0.0
        pv_p10 = None
        pv_p90 = None
        load_p10 = None
        load_p90 = None

        if rec is None:
            # Non-PV fields keep the closest stored forecast at or before the slot.
            fallback_ts = None
            fallback_key = None
            for forecast_key, forecast_ts in sorted_stored:
                if forecast_ts <= ts:
                    fallback_ts = forecast_ts
                    fallback_key = forecast_key
                else:
                    break

            if fallback_key is not None:
                fallback_rec = indexed[fallback_key]
                logger.warning(
                    "No exact forecast match for %s, using fallback from %s", ts, fallback_ts
                )
                load = float(fallback_rec["final"]["load_kwh"])
                prob_data = fallback_rec.get("probabilistic", {})
                load_p10 = prob_data.get("load_p10")
                load_p90 = prob_data.get("load_p90")
            # PV must never repeat the last stored slot (a night-time zero would be
            # carried into daytime); use the same local time of day from a stored day.
            tod_pv = _estimate_from_same_time_of_day(ts, pv_by_tod)
            if tod_pv is not None:
                pv = tod_pv
        else:
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
                "pv_estimated": estimated,
            }
        )

    _interpolate_small_pv_gaps(result)
    return result
