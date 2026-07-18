import asyncio
import logging
import re
import threading
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta
from typing import Any, cast

import httpx
import pytz

from backend.core import secrets
from backend.health import set_load_forecast_status

logger = logging.getLogger("darkstar.core.ha_client")

# Shared Home Assistant HTTP clients, one per running event loop.
# Keyed by event loop so the executor's background loop and the main server loop
# never share a client (sharing raises "Future ... bound to a different event loop").
_ha_http_clients: dict[asyncio.AbstractEventLoop, httpx.AsyncClient] = {}
_ha_http_clients_lock = threading.Lock()


def get_ha_http_client() -> httpx.AsyncClient:
    """Return a shared httpx.AsyncClient bound to the CURRENT running event loop.

    A separate client is kept per event loop so the executor's background loop and the
    main server loop never share a client (which would raise 'bound to a different event loop').
    """
    loop = asyncio.get_running_loop()
    with _ha_http_clients_lock:
        client = _ha_http_clients.get(loop)
        if client is None or client.is_closed:
            client = httpx.AsyncClient()
            _ha_http_clients[loop] = client
        return client


async def close_ha_http_client() -> None:
    """Close and forget the shared client for the CURRENT running event loop."""
    loop = asyncio.get_running_loop()
    with _ha_http_clients_lock:
        client = _ha_http_clients.pop(loop, None)
    if client is not None and not client.is_closed:
        await client.aclose()
        logger.info("Closed shared Home Assistant HTTP client for current event loop")


# Backend-owned HA action client (executor.actions.HAClient), used for goal
# writes (set_input_number/set_input_datetime). One per running event loop —
# never the executor's own client instance, which lives on the executor's
# (possibly different) loop.
_ha_action_clients: dict[asyncio.AbstractEventLoop, Any] = {}
_ha_action_clients_lock = threading.Lock()


def get_ha_action_client() -> Any:
    """Return a backend-owned HAClient bound to the CURRENT running event loop.

    Returns ``None`` if Home Assistant isn't configured (no url/token). Never
    returns the executor's own HAClient instance — that one belongs to the
    executor's loop and must not be used or closed from another loop.
    """
    from executor.actions import HAClient

    ha_config = secrets.load_home_assistant_config()
    url = ha_config.get("url")
    token = ha_config.get("token")
    if not url or not token:
        return None

    loop = asyncio.get_running_loop()
    with _ha_action_clients_lock:
        client = _ha_action_clients.get(loop)
        if client is None:
            client = HAClient(url, token)
            _ha_action_clients[loop] = client
        return client


async def close_ha_action_clients() -> None:
    """Close all backend-owned HA action clients (FastAPI shutdown).

    Each client's ``close()`` only touches the session for the loop it's
    called from, so this is safe to call from any single loop even if
    clients were created on others (those simply won't have their session
    closed here, matching HAClient's own cross-loop-safety guarantee).
    """
    with _ha_action_clients_lock:
        clients = list(_ha_action_clients.values())
        _ha_action_clients.clear()
    for client in clients:
        try:
            await client.close()
        except Exception as exc:
            logger.warning("Error closing HA action client: %s", exc)


def make_ha_headers(token: str) -> dict[str, str]:
    """Return headers for Home Assistant REST calls."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def gather_sensor_reads(
    reads: list[tuple[str, Callable[[], Coroutine[Any, Any, Any]]]],
    context: str = "sensor_batch",
) -> dict[str, Any]:
    """Run multiple sensor reads concurrently using asyncio.gather().

    Args:
        reads: List of (name, coroutine_factory) pairs. Each factory is called
               to produce a coroutine (e.g., lambda: get_ha_sensor_float(entity_id)).
        context: Label included in log messages to identify the call site.

    Returns:
        Dict mapping each name to its result value, or None if that read failed.
    """
    names = [name for name, _ in reads]
    coros = [fn() for _, fn in reads]
    raw = await asyncio.gather(*coros, return_exceptions=True)

    out: dict[str, Any] = {}
    failures = 0
    for name, result in zip(names, raw, strict=True):
        if isinstance(result, Exception):
            logger.warning("[%s] Sensor read failed for '%s': %s", context, name, result)
            out[name] = None
            failures += 1
        else:
            out[name] = result

    if failures > 0 and failures == len(reads):
        logger.warning("[%s] All %d sensor reads failed", context, failures)

    return out


async def get_ha_entity_state(entity_id: str) -> dict[str, Any] | None:
    """Fetch a single entity state from Home Assistant asynchronously."""
    ha_config = secrets.load_home_assistant_config()
    url = ha_config.get("url")
    token = ha_config.get("token")

    if not url or not token or not entity_id:
        logger.warning(
            "[get_ha_entity_state] Missing config: url=%s, token=%s, entity=%s",
            bool(url),
            bool(token),
            entity_id,
        )
        return None

    endpoint = f"{url.rstrip('/')}/api/states/{entity_id}"
    try:
        client = get_ha_http_client()
        response = await client.get(endpoint, headers=make_ha_headers(token), timeout=10.0)
        response.raise_for_status()
        data = response.json()
        return data
    except Exception as exc:
        logger.warning("Could not fetch HA entity %s: %s", entity_id, exc)
        return None


async def get_ha_sensor_float(entity_id: str) -> float | None:
    """Return numeric state of HA sensor asynchronously."""
    state = await get_ha_entity_state(entity_id)
    if not state:
        return None

    raw_value = state.get("state")
    if raw_value in (None, "unknown", "unavailable"):
        return None

    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return None


async def get_ha_sensor_kw_normalized(entity_id: str) -> float | None:
    """Return numeric state of HA sensor normalized to kW (scales W to kW)."""
    state_data = await get_ha_entity_state(entity_id)
    if not state_data:
        return None

    raw_value = state_data.get("state")
    if raw_value in (None, "unknown", "unavailable"):
        return None

    try:
        value = float(raw_value)
        # Check units
        attributes = state_data.get("attributes", {})
        unit = str(attributes.get("unit_of_measurement", "")).upper()
        if unit == "W":
            return value / 1000.0
        return value
    except (TypeError, ValueError):
        return None


def _normalize_energy_to_kwh(value: float, unit: str | None) -> float:
    """Normalize energy value to kWh based on Home Assistant unit_of_measurement.

    Handles common energy units: Wh, kWh, MWh with case-insensitive matching.
    Uses magnitude-based heuristic when no unit is specified.

    Args:
        value: The raw numeric value from HA
        unit: The unit_of_measurement attribute from HA state

    Returns:
        Value normalized to kWh
    """
    if not unit:
        if value > 100_000:
            result = value / 1000.0
            logger.info(
                "Energy normalization: %s (no unit) → %s kWh (Wh inferred from magnitude)",
                value,
                result,
            )
            return result
        logger.debug("Energy normalization: %s (no unit) → %s kWh (assumed kWh)", value, value)
        return value

    unit_clean = re.sub(r"[^A-Z0-9]", "", str(unit).upper())

    if unit_clean in ("WH", "WATTHOUR", "WATTHOURS"):
        result = value / 1000.0
        logger.debug(
            "Energy normalization: %s %s → %s kWh (from unit_of_measurement)", value, unit, result
        )
        return result
    elif unit_clean in ("KWH", "KILOWATTHOUR", "KILOWATTHOURS"):
        logger.debug(
            "Energy normalization: %s %s → %s kWh (from unit_of_measurement)", value, unit, value
        )
        return value
    elif unit_clean in ("MWH", "MEGAWATTHOUR", "MEGAWATTHOURS"):
        result = value * 1000.0
        logger.debug(
            "Energy normalization: %s %s → %s kWh (from unit_of_measurement)", value, unit, result
        )
        return result
    else:
        logger.warning(
            "Energy normalization: unknown unit '%s' for value %s, assuming kWh", unit, value
        )
        return value


async def get_energy_from_power_history(
    entity_id: str,
    start: datetime,
    end: datetime,
) -> float | None:
    """Fetch power sensor history and compute energy via step integration.

    Returns energy in kWh, or None if history unavailable.
    """
    ha_config = secrets.load_home_assistant_config()
    url = ha_config.get("url")
    token = ha_config.get("token")

    if not url or not token or not entity_id:
        return None

    api_url = f"{url.rstrip('/')}/api/history/period/{start.isoformat()}"
    params = {
        "filter_entity_id": entity_id,
        "end_time": end.isoformat(),
        "significant_changes_only": False,
        "minimal_response": False,
    }

    try:
        client = get_ha_http_client()
        response = await client.get(
            api_url, headers=make_ha_headers(token), params=params, timeout=12.0
        )
        response.raise_for_status()
        data = response.json()

        if not data or not data[0]:
            return None

        states = data[0]
        valid_points = 0
        energy_kwh = 0.0
        current_kw: float | None = None
        cursor = start

        def state_timestamp(state: dict[str, Any]) -> datetime | None:
            for key in ("last_changed", "last_updated"):
                raw = state.get(key)
                if raw:
                    try:
                        return datetime.fromisoformat(str(raw))
                    except (TypeError, ValueError):
                        continue
            return None

        def normalize_kw(value: float, unit: str | None) -> float:
            unit = str(unit or "").upper()
            if unit == "W":
                return value / 1000.0
            if unit == "MW":
                return value * 1000.0
            return value

        cached_unit: str | None = None
        for state in sorted(states, key=lambda item: state_timestamp(item) or start):
            ts = state_timestamp(state)
            if ts is None:
                continue
            state_val = state.get("state", "")
            if state_val in ("unknown", "unavailable", "", None):
                continue

            try:
                value = float(state_val)
            except (TypeError, ValueError):
                continue

            attributes = state.get("attributes", {})
            unit = attributes.get("unit_of_measurement")
            if unit is not None and unit != "":
                cached_unit = unit
            if unit is None or unit == "":
                unit = cached_unit

            value_kw = normalize_kw(value, unit)
            valid_points += 1

            if ts <= start:
                current_kw = value_kw
                cursor = start
                continue

            if ts >= end:
                if current_kw is not None and cursor < end:
                    energy_kwh += current_kw * ((end - cursor).total_seconds() / 3600.0)
                cursor = end
                break

            if current_kw is not None and cursor < ts:
                energy_kwh += current_kw * ((ts - cursor).total_seconds() / 3600.0)

            current_kw = value_kw
            cursor = ts

        if valid_points == 0:
            return None

        if current_kw is not None and cursor < end:
            energy_kwh += current_kw * ((end - cursor).total_seconds() / 3600.0)

        return energy_kwh

    except Exception as exc:
        logger.warning("get_energy_from_power_history(%s): %s", entity_id, exc)
        return None


async def get_ha_bool(entity_id: str) -> bool:
    """Return True if entity is 'on', 'true', 'armed', etc."""
    state = await get_ha_entity_state(entity_id)
    if not state:
        return False

    raw = str(state.get("state", "")).lower()
    # Common 'on' states in Home Assistant
    true_states = {"on", "true", "yes", "1", "armed_away", "armed_home", "armed_night"}
    is_true = raw in true_states
    if is_true and "vacation" in entity_id:
        logger.debug("Vacation mode detected TRUE. Raw state: %r from entity %r", raw, entity_id)
    return is_true


def parse_ha_datetime_state(raw_value: Any, tz: pytz.BaseTzInfo) -> datetime | None:
    """Parse a raw Home Assistant ``input_datetime`` state string.

    Supports ``'YYYY-MM-DD HH:MM:SS'`` and ISO 8601 (with or without
    timezone) formats; naive results are localized to ``tz``. Returns
    ``None`` for unknown/unavailable/empty/time-only/unparseable values.
    """
    if raw_value in (None, "unknown", "unavailable", "", "None"):
        return None

    raw_str = str(raw_value).strip()
    if not raw_str or "-" not in raw_str:
        return None

    normalized = raw_str.replace(" ", "T")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if dt.tzinfo is None:
        dt = tz.localize(dt)

    return dt


async def get_ha_datetime(entity_id: str) -> datetime | None:
    """Fetch datetime state from HA entity asynchronously and parse it.

    Supports 'YYYY-MM-DD HH:MM:SS', ISO 8601, and ISO 8601 with timezone formats,
    applying the system timezone when none is present.
    Returns None + warning for time-only / unknown / unavailable / empty.
    """
    state = await get_ha_entity_state(entity_id)
    if not state:
        return None

    raw_value = state.get("state")
    try:
        config = secrets.load_yaml("config.yaml")
        tz_name = config.get("timezone", "Europe/Stockholm")
        tz = pytz.timezone(tz_name)
    except Exception:
        tz = pytz.timezone("Europe/Stockholm")

    dt = parse_ha_datetime_state(raw_value, tz)
    if dt is None:
        logger.warning(
            "HA datetime entity %s has unparseable/time-only/unavailable value: %r",
            entity_id,
            raw_value,
        )
    return dt


async def get_initial_state(
    config_path: str = "config.yaml",
    ev_plugged_in_override: bool | None = None,
    ev_plug_override_charger_id: str | None = None,
) -> dict[str, Any]:
    """
    Get the initial battery state (Asynchronous).

    Args:
        config_path: Path to config.yaml
        ev_plugged_in_override: If provided, use this value for the specific charger
            identified by ev_plug_override_charger_id (or all chargers if None).
        ev_plug_override_charger_id: Charger ID to apply the plug state override to.
            If None and ev_plugged_in_override is set, applies to the first enabled charger
            (legacy behaviour). With per-device replans, this should always be set.
    """
    config = secrets.load_yaml(config_path)

    # Use system.battery if available, otherwise fall back to battery
    battery_config = config.get("system", {}).get("battery", config.get("battery", {}))
    capacity_kwh = battery_config.get("capacity_kwh", 10.0)
    battery_soc_percent = 50.0
    battery_cost_sek_per_kwh = config.get("battery_economics", {}).get(
        "battery_cycle_cost_kwh", 0.20
    )

    # HA Config
    ha_config = secrets.load_home_assistant_config()
    input_sensors = config.get("input_sensors", {})
    soc_entity_id = input_sensors.get("battery_soc", ha_config.get("soc_entity_id"))

    if soc_entity_id:
        ha_soc = await get_ha_sensor_float(soc_entity_id)
        if ha_soc is not None:
            battery_soc_percent = ha_soc
        else:
            # Critical safety check: Do not default to 50% if we expected a live reading.
            # This causes "phantom charging" when HA is down.
            raise RuntimeError(
                f"Critical: Failed to read battery SoC from {soc_entity_id}. "
                "Planning aborted to prevent unsafe assumptions."
            )

    battery_soc_percent = max(0.0, min(100.0, battery_soc_percent))
    battery_kwh = capacity_kwh * battery_soc_percent / 100.0

    system_config = config.get("system", {})
    water_heated_today_kwh = 0.0

    # Per-device EV state fetching
    has_ev_charger = system_config.get("has_ev_charger", False)
    ev_chargers_cfg = config.get("ev_chargers", [])
    enabled_ev_chargers = [ev for ev in ev_chargers_cfg if ev.get("enabled", True)]

    # Build per-device EV state list
    ev_charger_states: list[dict[str, Any]] = []

    if has_ev_charger and enabled_ev_chargers:
        # Build batch reads for all enabled chargers
        per_device_reads: list[tuple[str, Any]] = []
        for ev in enabled_ev_chargers:
            charger_id = ev.get("id", "")
            soc_sensor = ev.get("soc_sensor", "")
            plug_sensor = ev.get("plug_sensor", "")

            if soc_sensor:
                key = f"ev_soc_{charger_id}"
                per_device_reads.append((key, lambda e=soc_sensor: get_ha_sensor_float(e)))

            # Only fetch plug from HA if no override applies to this charger
            is_override_charger = ev_plug_override_charger_id == charger_id or (
                ev_plug_override_charger_id is None and ev is enabled_ev_chargers[0]
            )
            if plug_sensor and not (ev_plugged_in_override is not None and is_override_charger):
                key = f"ev_plug_{charger_id}"
                per_device_reads.append((key, lambda e=plug_sensor: get_ha_bool(e)))

        per_device_results: dict[str, Any] = {}
        if per_device_reads:
            per_device_results = await gather_sensor_reads(
                per_device_reads, context="ev_initial_state"
            )

        for ev in enabled_ev_chargers:
            charger_id = ev.get("id", "")
            soc_sensor = ev.get("soc_sensor", "")
            plug_sensor = ev.get("plug_sensor", "")

            # SoC: None when unavailable (no sensor configured, or the sensor
            # read failed) — distinguished from a real 0.0% reading, so the
            # required-kWh calculation doesn't misidentify "unknown" as
            # "already at 0%" (see planner.pipeline._calculate_required_kwh).
            soc_percent: float | None = None
            if soc_sensor:
                ha_soc_val = per_device_results.get(f"ev_soc_{charger_id}")
                if ha_soc_val is not None:
                    soc_percent = float(ha_soc_val)
                else:
                    logger.warning(
                        "EV %s SoC sensor %s returned no data, defaulting to 0%%",
                        charger_id,
                        soc_sensor,
                    )

            # Plug state
            is_override_charger = ev_plug_override_charger_id == charger_id or (
                ev_plug_override_charger_id is None and ev is enabled_ev_chargers[0]
            )
            if ev_plugged_in_override is not None and is_override_charger:
                plugged_in = ev_plugged_in_override
                logger.debug(
                    "EV %s: using plug state override=%s", charger_id, ev_plugged_in_override
                )
            elif plug_sensor:
                plugged_in = bool(per_device_results.get(f"ev_plug_{charger_id}", False))
            else:
                # No plug sensor → assume plugged in (let enabled flag be the control)
                plugged_in = True

            ev_charger_states.append(
                {
                    "id": charger_id,
                    "soc_percent": soc_percent,
                    "plugged_in": plugged_in,
                }
            )

    # Build aggregate values for backward compatibility (legacy scalar field:
    # unavailable SoC displays as 0.0 here, unlike the per-device list above).
    ev_soc_percent = (
        ev_charger_states[0]["soc_percent"]
        if ev_charger_states and ev_charger_states[0]["soc_percent"] is not None
        else 0.0
    )
    ev_plugged_in = ev_charger_states[0]["plugged_in"] if ev_charger_states else False

    return {
        "battery_soc_percent": battery_soc_percent,
        "battery_kwh": battery_kwh,
        "battery_cost_sek_per_kwh": battery_cost_sek_per_kwh,
        "water_heated_today_kwh": water_heated_today_kwh,
        # Legacy scalar fields (backward compat)
        "ev_soc_percent": ev_soc_percent,
        "ev_plugged_in": ev_plugged_in,
        # Per-device EV state list
        "ev_charger_states": ev_charger_states,
    }


async def get_load_profile_from_ha(config: dict[str, Any]) -> list[float]:
    """Fetch actual load profile from Home Assistant historical data (Async)."""
    ha_config = secrets.load_home_assistant_config()
    url: str | None = cast("str | None", ha_config.get("url"))
    token = cast("str", ha_config.get("token", ""))

    _sensors_cfg: Any = config.get("input_sensors", {})
    if isinstance(_sensors_cfg, dict):
        input_sensors: dict[str, Any] = cast("dict[str, Any]", _sensors_cfg)
    else:
        input_sensors = {}

    entity_id: str | None = input_sensors.get(
        "total_load_consumption", ha_config.get("consumption_entity_id")
    )

    if not all([url, token, entity_id]):
        logger.warning("Missing Home Assistant configuration for load profile")
        return get_dummy_load_profile(config)

    headers = make_ha_headers(token)
    end_time = datetime.now(pytz.UTC)
    start_time = end_time - timedelta(days=7)

    url_str: str = cast("str", url)
    api_url = f"{url_str.rstrip('/')}/api/history/period/{start_time.isoformat()}"
    params = {
        "filter_entity_id": entity_id,
        "end_time": end_time.isoformat(),
        "significant_changes_only": False,
        "minimal_response": True,
        "no_attributes": True,
    }

    try:
        logger.info("Fetching %s data from Home Assistant", entity_id)
        client = get_ha_http_client()
        response = await client.get(api_url, headers=headers, params=params, timeout=30.0)
        response.raise_for_status()

        data = response.json()
        if not data or not data[0]:
            logger.warning("No data received from Home Assistant for %s", entity_id)
            return get_dummy_load_profile(config)

        states = data[0]
        if len(states) < 2:
            logger.warning("Insufficient data points from Home Assistant for %s", entity_id)
            return get_dummy_load_profile(config)

        # Convert to local timezone for processing
        local_tz = pytz.timezone("Europe/Stockholm")

        # Calculate energy consumption between state changes
        time_buckets = [0.0] * (96 * 7)  # 7 days * 96 slots per day
        prev_state = None
        prev_time = None
        cached_unit: str | None = None

        max_meter_delta_kwh = float(config.get("recorder", {}).get("max_meter_delta_kwh", 50.0))
        skipped_delta_count = 0
        largest_skipped_delta = 0.0

        start_time_local = start_time.astimezone(local_tz)

        for state in states:
            try:
                # Skip unavailable/unknown/null states silently
                state_val = state.get("state", "")
                if state_val in ("unavailable", "unknown", "null", "", None):
                    continue

                current_time = datetime.fromisoformat(state["last_changed"])
                if current_time.tzinfo is None:
                    current_time = current_time.replace(tzinfo=pytz.UTC)
                current_time = current_time.astimezone(local_tz)
                current_value = float(state_val)

                # Normalize energy unit to kWh (handles Wh, kWh, MWh)
                attributes = state.get("attributes", {})
                unit = attributes.get("unit_of_measurement")
                if unit is not None and unit != "":
                    cached_unit = unit
                if unit is None or unit == "":
                    unit = cached_unit
                current_value = _normalize_energy_to_kwh(current_value, unit)

                if prev_state is not None and prev_time is not None:
                    # Calculate energy delta (ensure positive)
                    energy_delta = max(0, current_value - prev_state)

                    if energy_delta > max_meter_delta_kwh:
                        # Implausible cumulative-meter jump (e.g. a Fronius
                        # lifetime sensor resetting to 0 overnight and back).
                        # Skip this interval but still advance the baseline
                        # below so subsequent deltas stay correct.
                        skipped_delta_count += 1
                        largest_skipped_delta = max(largest_skipped_delta, energy_delta)
                        prev_state = current_value
                        prev_time = current_time
                        continue

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
                logger.warning("Skipping invalid state data for %s: %s", entity_id, e)
                continue

        if skipped_delta_count:
            logger.warning(
                "Skipped %d implausible cumulative-meter delta(s) for %s "
                "(largest %.1f kWh, max allowed %.1f kWh)",
                skipped_delta_count,
                entity_id,
                largest_skipped_delta,
                max_meter_delta_kwh,
            )

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
        if total_daily > 500:
            logger.warning(
                "Daily total %.1f kWh/day for %s exceeds 500 kWh sanity bound, using dummy profile",
                total_daily,
                entity_id,
            )
            return get_dummy_load_profile(
                config,
                discard_reason=(
                    f"'{entity_id}' data discarded: {total_daily:.1f} kWh/day exceeds the "
                    "500 kWh/day plausibility bound"
                ),
            )
        if total_daily <= 0:
            logger.warning("No valid energy consumption data found for %s", entity_id)
            return get_dummy_load_profile(
                config,
                discard_reason=f"'{entity_id}' returned no valid (positive) energy consumption data",
            )

        logger.info("Successfully loaded HA data: %.2f kWh/day average", total_daily)

        # Ensure all values are positive and reasonable
        for i in range(96):
            if daily_profile[i] < 0:
                daily_profile[i] = 0
            elif daily_profile[i] > 10:  # Cap at 10kW per 15min
                daily_profile[i] = 10

        return daily_profile

    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.warning("Failed to fetch data from Home Assistant for %s: %s", entity_id, e)
        return get_dummy_load_profile(config)
    except Exception as e:
        logger.warning("Error processing Home Assistant data for %s: %s", entity_id, e)
        return get_dummy_load_profile(config)


def get_dummy_load_profile(
    config: dict[str, Any], discard_reason: str | None = None
) -> list[float]:
    """Create a dummy load profile or a synthetic scaled profile.

    If config.input_sensors.total_load_consumption is a number (estimated daily kWh),
    we generate a synthetic winter heat-pump curve scaled to that daily total.
    Otherwise, we fall back to a 0.5 kWh flat dummy profile.

    ``discard_reason``, when set, means a sensor WAS configured but its fetched
    data was discarded as implausible (as opposed to no sensor being configured
    at all) — it flows into the degraded-status detail so the health banner
    names the sensor instead of telling the user to configure one that already
    exists.
    """
    import logging

    logger = logging.getLogger(__name__)

    # Check if the user provided an estimated daily kWh (from Startup Wizard)
    # The wizard stores this as a string, e.g. "20", in the total_load_consumption field
    # if they selected 'synthetic' mode.
    estimated_daily_kwh = None
    sensors = config.get("input_sensors", {})
    raw_val = sensors.get("total_load_consumption")

    if raw_val is not None:
        try:
            val = float(raw_val)
            if val > 0 and not str(raw_val).startswith(("sensor.", "input_")):
                estimated_daily_kwh = val
        except (ValueError, TypeError):
            pass

    if estimated_daily_kwh is not None:
        logger.info(
            f"Generating Synthetic Heat Pump profile scaled to {estimated_daily_kwh} kWh/day."
        )
        set_load_forecast_status("synthetic", "estimated")

        # Base normalized heat pump curve (higher in night/morning, lower in afternoon)
        # 96 slots representing a standard winter day shape. Sums to ~1.0.
        base_curve = [
            1.2,
            1.2,
            1.1,
            1.1,
            1.1,
            1.1,
            1.2,
            1.2,  # 00:00 - 02:00
            1.2,
            1.3,
            1.3,
            1.3,
            1.4,
            1.4,
            1.5,
            1.6,  # 02:00 - 04:00
            1.7,
            1.8,
            1.9,
            1.9,
            2.0,
            2.0,
            1.9,
            1.8,  # 04:00 - 06:00
            1.7,
            1.6,
            1.5,
            1.4,
            1.3,
            1.2,
            1.1,
            1.0,  # 06:00 - 08:00
            0.9,
            0.9,
            0.8,
            0.8,
            0.8,
            0.7,
            0.7,
            0.7,  # 08:00 - 10:00
            0.7,
            0.6,
            0.6,
            0.6,
            0.6,
            0.5,
            0.5,
            0.5,  # 10:00 - 12:00
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.6,  # 12:00 - 14:00
            0.6,
            0.6,
            0.7,
            0.7,
            0.8,
            0.8,
            0.9,
            1.0,  # 14:00 - 16:00
            1.1,
            1.2,
            1.3,
            1.4,
            1.5,
            1.6,
            1.7,
            1.7,  # 16:00 - 18:00
            1.6,
            1.5,
            1.4,
            1.3,
            1.2,
            1.1,
            1.0,
            1.0,  # 18:00 - 20:00
            0.9,
            0.9,
            0.9,
            1.0,
            1.0,
            1.0,
            1.1,
            1.1,  # 20:00 - 22:00
            1.1,
            1.1,
            1.1,
            1.2,
            1.2,
            1.2,
            1.2,
            1.2,  # 22:00 - 00:00
        ]

        curve_sum = sum(base_curve)
        # Scale the curve so its integral (sum) equals the estimated daily kWh
        return [(val / curve_sum) * estimated_daily_kwh for val in base_curve]

    if discard_reason:
        logger.warning("⚠️ Using DEMO load profile (0.5 kWh flat) - %s.", discard_reason)
    else:
        logger.warning(
            "⚠️ Using DEMO load profile (0.5 kWh flat) - no historical data available. Configure total_load_consumption sensor for accurate forecasts."
        )

    # REV F65 Phase 5b: Set degraded status when using demo data
    set_load_forecast_status("degraded", "demo", detail=discard_reason or "")

    return [0.5] * 96
