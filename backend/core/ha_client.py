import asyncio
import logging
import threading
from bisect import bisect_right
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta
from typing import Any, cast

import httpx
import pytz

from backend.core import secrets
from backend.core.ev_live_state import (
    ResolvedSoc,
    discard_soc_recovery,
    resolve_soc,
    soc_stale_after_minutes,
    update_stale_soc_episode,
)
from backend.core.ev_plug import (
    DEFAULT_EV_PLUGGED_IN_STATES,
    is_ev_plugged_in,
    remember_plug_state,
    resolve_plug_state,
)
from backend.core.ha_timestamps import reading_timestamp
from backend.core.water_heating import (
    DEFAULT_IDLE_POWER_THRESHOLD_KW,
    normalize_active_power_kw,
    validate_water_heating_config,
)
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


def _state_float(state: dict[str, Any] | None) -> float | None:
    """Parse an HA state's value as float; None if missing/unknown/unavailable."""
    if not state:
        return None

    raw_value = state.get("state")
    if raw_value in (None, "unknown", "unavailable"):
        return None

    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return None


async def get_ha_sensor_float(entity_id: str) -> float | None:
    """Return numeric state of HA sensor asynchronously."""
    return _state_float(await get_ha_entity_state(entity_id))


async def get_ha_sensor_kw_normalized(entity_id: str) -> float | None:
    """Return numeric state of HA sensor normalized to kW (scales W to kW)."""
    state_data = await get_ha_entity_state(entity_id)
    if not state_data:
        return None

    raw_value = state_data.get("state")
    if raw_value in (None, "unknown", "unavailable"):
        return None

    try:
        attributes = state_data.get("attributes", {})
        return normalize_active_power_kw(raw_value, attributes.get("unit_of_measurement", "kW"))
    except (TypeError, ValueError):
        return None


PowerPoint = tuple[datetime, float]


def _state_timestamp(state: dict[str, Any]) -> datetime | None:
    for key in ("last_changed", "last_updated"):
        raw = state.get(key)
        if raw:
            try:
                return datetime.fromisoformat(str(raw))
            except (TypeError, ValueError):
                continue
    return None


def parse_power_states(states: list[dict[str, Any]]) -> list[PowerPoint]:
    """Parse HA history states of one power sensor into time-sorted ``(timestamp, kW)`` points.

    States without a timestamp or numeric value are skipped. A state lacking a unit
    inherits the last unit seen earlier in the series (HA often reports it only on the
    first state).
    """
    points: list[PowerPoint] = []
    cached_unit: str | None = None
    stamped = [(ts, state) for state in states if (ts := _state_timestamp(state)) is not None]
    stamped.sort(key=lambda item: item[0])
    for ts, state in stamped:
        state_val = state.get("state", "")
        if state_val in ("unknown", "unavailable", "", None):
            continue
        try:
            value = float(state_val)
        except (TypeError, ValueError):
            continue

        attributes: dict[str, Any] = state.get("attributes") or {}
        unit: str | None = attributes.get("unit_of_measurement")
        if unit is not None and unit != "":
            cached_unit = unit
        if unit is None or unit == "":
            unit = cached_unit
        normalized = normalize_active_power_kw(value, unit)
        if normalized is not None:
            points.append((ts, normalized))
    return points


def integrate_power_points(
    points: list[PowerPoint],
    start: datetime,
    end: datetime,
) -> tuple[float, float] | None:
    """Step-integrate (zero-order hold) parsed power points over ``[start, end]``.

    Returns ``(positive_kwh, negative_kwh)``, where each sample interval is added to
    one side by the sign of its held value (negative energy is returned as a magnitude).
    The last state at or before ``start`` is the pre-window value. Returns None when
    there are no valid points at all.
    """
    if not points:
        return None

    positive = 0.0
    negative = 0.0
    current_kw: float | None = None
    cursor = start

    def accumulate(kw: float, until: datetime) -> None:
        nonlocal positive, negative
        kwh = kw * ((until - cursor).total_seconds() / 3600.0)
        if kwh >= 0:
            positive += kwh
        else:
            negative -= kwh

    # Points are time-sorted: the last one at or before ``start`` is the pre-window state.
    first_in_window = bisect_right(points, start, key=lambda point: point[0])
    if first_in_window:
        current_kw = points[first_in_window - 1][1]

    for ts, value_kw in points[first_in_window:]:
        if ts >= end:
            break

        if current_kw is not None and cursor < ts:
            accumulate(current_kw, ts)

        current_kw = value_kw
        cursor = ts

    if current_kw is not None and cursor < end:
        accumulate(current_kw, end)

    return positive, negative


async def get_power_history_batch(
    entity_ids: list[str],
    start: datetime,
    end: datetime,
    timeout: float = 12.0,
) -> dict[str, list[dict[str, Any]]] | None:
    """Fetch the HA history of several entities in ONE request.

    Returns raw history states per requested entity (an entity HA returned nothing
    for maps to an empty list), or None when the request failed or HA is not
    configured. A failure is logged once.
    """
    ha_config = secrets.load_home_assistant_config()
    url = ha_config.get("url")
    token = ha_config.get("token")
    entities = [entity for entity in dict.fromkeys(entity_ids) if entity]

    if not url or not token or not entities:
        return None

    api_url = f"{url.rstrip('/')}/api/history/period/{start.isoformat()}"
    params = {
        "filter_entity_id": ",".join(entities),
        "end_time": end.isoformat(),
        "significant_changes_only": False,
        "minimal_response": False,
    }

    try:
        client = get_ha_http_client()
        response = await client.get(
            api_url, headers=make_ha_headers(token), params=params, timeout=timeout
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.warning("get_power_history_batch(%d entities): %s", len(entities), exc)
        return None

    result: dict[str, list[dict[str, Any]]] = {entity: [] for entity in entities}
    all_series: list[list[dict[str, Any]]] = data or []
    for series in all_series:
        if not series:
            continue
        entity_id: str | None = next((s["entity_id"] for s in series if s.get("entity_id")), None)
        if entity_id in result:
            result[entity_id] = series
        elif len(entities) == 1 and len(all_series) == 1:
            result[entities[0]] = series
    return result


async def get_energy_from_power_history(
    entity_id: str,
    start: datetime,
    end: datetime,
) -> float | None:
    """Fetch power sensor history and compute energy via step integration.

    Returns the signed energy in kWh, or None if history unavailable.
    """
    history = await get_power_history_batch([entity_id], start, end)
    if not history:
        return None
    integrated = integrate_power_points(parse_power_states(history[entity_id]), start, end)
    if integrated is None:
        return None
    return integrated[0] - integrated[1]


async def get_ha_bool(entity_id: str, connected_states: Any = None) -> bool:
    """Return a boolean HA state.

    ``connected_states`` is used by EV consumers to apply the shared,
    charger-specific plug vocabulary. Other callers retain the generic HA
    boolean behavior when it is omitted.
    """
    state = await get_ha_entity_state(entity_id)
    if not state:
        return False

    if connected_states is not None:
        return is_ev_plugged_in(state.get("state"), connected_states)

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
    ev_plug_overrides: dict[str, bool] | None = None,
    progress_cutoff: datetime | None = None,
) -> dict[str, Any]:
    """
    Get the initial battery state (Asynchronous).

    Args:
        config_path: Path to config.yaml
        ev_plug_overrides: Per-charger plug-state overrides ({charger_id: plugged}).
            A charger listed here uses the override instead of its HA plug sensor
            (avoids the REST race right after a plug event).
        progress_cutoff: First solver slot start; measured energy after this instant
            remains part of the horizon rather than being credited as delivered.
    """
    plug_overrides: dict[str, bool] = ev_plug_overrides or {}
    config = secrets.load_yaml(config_path)
    validate_water_heating_config(config)

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
    soc_timestamp: datetime | None = None

    if soc_entity_id:
        soc_state = await get_ha_entity_state(soc_entity_id)
        ha_soc = _state_float(soc_state)
        if ha_soc is not None:
            battery_soc_percent = ha_soc
            soc_timestamp = reading_timestamp(soc_state)
        else:
            # Critical safety check: Do not default to 50% if we expected a live reading.
            # This causes "phantom charging" when HA is down.
            from planner.errors import PlannerError, PlannerErrorCode

            raise PlannerError(
                PlannerErrorCode.HA_UNAVAILABLE,
                details={"entity_id": soc_entity_id},
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
            if plug_sensor and charger_id not in plug_overrides:
                key = f"ev_plug_{charger_id}"
                # Raw state: unavailable/unknown must be told apart from unplugged.
                per_device_reads.append((key, lambda e=plug_sensor: get_ha_entity_state(e)))

        per_device_results: dict[str, Any] = {}
        if per_device_reads:
            per_device_results = await gather_sensor_reads(
                per_device_reads, context="ev_initial_state"
            )

        for ev in enabled_ev_chargers:
            charger_id = ev.get("id", "")
            soc_sensor = ev.get("soc_sensor", "")
            plug_sensor = ev.get("plug_sensor", "")

            # SoC (ev-soc-staleness): a valid reading is ``live``; without one
            # the last valid reading is carried for ``soc_stale_after_minutes``,
            # after which the SoC is ``stale`` (None) and the planner suspends
            # goal charging. None is never read as 0% (see
            # planner.pipeline._calculate_required_kwh).
            soc_percent: float | None = None
            soc_status: str | None = None
            soc_age_minutes: float | None = None
            resolved: ResolvedSoc | None = None
            if soc_sensor:
                ha_soc_val = per_device_results.get(f"ev_soc_{charger_id}")
                window = soc_stale_after_minutes(ev)
                resolved = resolve_soc(
                    charger_id,
                    float(ha_soc_val) if ha_soc_val is not None else None,
                    window,
                )
                soc_percent = resolved.soc_percent
                soc_status = resolved.status
                soc_age_minutes = resolved.age_minutes
                if resolved.status == "live":
                    # This planner run already plans from the recovered
                    # reading; no separate recovery replan is needed.
                    discard_soc_recovery(charger_id)
                elif resolved.status == "carried":
                    logger.warning(
                        "EV %s SoC sensor %s unavailable - carrying last known SoC "
                        "%.1f%% from %.0f min ago",
                        charger_id,
                        soc_sensor,
                        resolved.soc_percent,
                        resolved.age_minutes or 0.0,
                    )
                elif resolved.status == "stale":
                    age_txt = (
                        f"{resolved.age_minutes:.0f} min"
                        if resolved.age_minutes is not None
                        else "no valid reading since startup"
                    )
                    logger.warning(
                        "EV %s SoC sensor %s unavailable for %s (window %.0f min) - "
                        "goal charging suspended",
                        charger_id,
                        soc_sensor,
                        age_txt,
                        window,
                    )

            # Plug state
            unreachable = False
            if charger_id in plug_overrides:
                plugged_in = plug_overrides[charger_id]
                remember_plug_state(charger_id, plugged_in)
                logger.debug("EV %s: using plug state override=%s", charger_id, plugged_in)
            elif plug_sensor:
                plug_state: Any = per_device_results.get(f"ev_plug_{charger_id}")
                raw_plug: object = (
                    cast("dict[str, Any]", plug_state).get("state")
                    if isinstance(plug_state, dict)
                    else None
                )
                plugged_in, unreachable = resolve_plug_state(
                    charger_id,
                    raw_plug,
                    ev.get("plugged_in_states") or DEFAULT_EV_PLUGGED_IN_STATES,
                )
                if unreachable:
                    logger.warning(
                        "EV %s: charger unreachable (plug sensor %s is %s) - "
                        "planning with last known plug state plugged_in=%s",
                        charger_id,
                        plug_sensor,
                        raw_plug,
                        plugged_in,
                    )
            else:
                # No plug sensor → assume plugged in (let enabled flag be the control)
                plugged_in = True

            ev_charger_states.append(
                {
                    "id": charger_id,
                    "soc_percent": soc_percent,
                    "soc_status": soc_status,
                    "soc_age_minutes": soc_age_minutes,
                    "plugged_in": plugged_in,
                    "unreachable": unreachable,
                }
            )
            # Only a plugged charger's stale SoC suspends goal charging and
            # warrants the notification; unplugged chargers plan from their
            # persisted SoC (assumed-plugged planning).
            update_stale_soc_episode(
                charger_id,
                resolved if plugged_in else None,
            )

    # Build aggregate values for backward compatibility (legacy scalar field:
    # unavailable SoC displays as 0.0 here, unlike the per-device list above).
    ev_soc_percent = (
        ev_charger_states[0]["soc_percent"]
        if ev_charger_states and ev_charger_states[0]["soc_percent"] is not None
        else 0.0
    )
    ev_plugged_in = ev_charger_states[0]["plugged_in"] if ev_charger_states else False

    raw_water_heaters = config.get("water_heaters", [])
    enabled_water_heaters: list[dict[str, Any]] = []
    if isinstance(raw_water_heaters, list) and system_config.get("has_water_heater", True):
        for raw_heater in cast("list[object]", raw_water_heaters):
            if isinstance(raw_heater, dict):
                heater = cast("dict[str, Any]", raw_heater)
                if heater.get("enabled", True):
                    enabled_water_heaters.append(heater)

    def water_power_reader(sensor_id: str) -> Callable[[], Coroutine[Any, Any, float | None]]:
        async def read() -> float | None:
            return await get_ha_sensor_kw_normalized(sensor_id)

        return read

    water_power_reads: list[tuple[str, Callable[[], Coroutine[Any, Any, float | None]]]] = []
    if progress_cutoff is not None:
        for heater in enabled_water_heaters:
            heater_id = heater.get("id")
            sensor_id = heater.get("sensor")
            if heater_id and sensor_id:
                water_power_reads.append(
                    (f"water_power_{heater_id}", water_power_reader(str(sensor_id)))
                )
    water_power_results = (
        await gather_sensor_reads(water_power_reads, context="water_initial_state")
        if water_power_reads
        else {}
    )
    current_water_power: dict[str, float | None] = {}
    for heater in enabled_water_heaters:
        heater_id = str(heater.get("id", ""))
        if not heater_id:
            continue
        raw_power = water_power_results.get(f"water_power_{heater_id}")
        current_water_power[heater_id] = (
            normalize_active_power_kw(
                raw_power,
                "kW",
                float(heater.get("idle_power_threshold_kw", DEFAULT_IDLE_POWER_THRESHOLD_KW)),
            )
            if raw_power is not None
            else None
        )

    if progress_cutoff is not None and enabled_water_heaters:
        from backend.core.water_progress import read_water_heating_progress

        water_heater_states: list[dict[str, Any]] = await read_water_heating_progress(
            config,
            progress_cutoff,
            str(config.get("learning", {}).get("sqlite_path", "data/planner_learning.db")),
            current_power_kw=current_water_power,
            measured_until=datetime.now(pytz.UTC),
        )
        water_heated_today_kwh = sum(state["heated_today_kwh"] for state in water_heater_states)
    else:
        water_heater_states = [
            {
                "id": str(heater.get("id", "")),
                "heated_today_kwh": 0.0,
                "progress_source": "unknown",
                "progress_coverage": "unavailable",
                "active_heating": None,
            }
            for heater in enabled_water_heaters
            if heater.get("id")
        ]

    initial_state: dict[str, Any] = {
        "battery_soc_percent": battery_soc_percent,
        "battery_kwh": battery_kwh,
        "battery_cost_sek_per_kwh": battery_cost_sek_per_kwh,
        "water_heated_today_kwh": water_heated_today_kwh,
        "water_heater_states": water_heater_states,
        "water_progress_cutoff": progress_cutoff,
        # Legacy scalar fields (backward compat)
        "ev_soc_percent": ev_soc_percent,
        "ev_plugged_in": ev_plugged_in,
        # Per-device EV state list
        "ev_charger_states": ev_charger_states,
    }
    if soc_timestamp is not None:
        # Feeds planner/preflight.py::check_soc_staleness (ha-sensor-freshness)
        initial_state["soc_timestamp"] = soc_timestamp.isoformat()
    return initial_state


_SLOT_SECONDS = 15 * 60
_LOAD_PROFILE_DAYS = 7


def _distribute_interval_energy(
    slot_sums: list[float],
    interval_start: datetime,
    interval_end: datetime,
    energy_kwh: float,
    local_tz: Any,
    window_start: datetime,
    window_end: datetime,
) -> None:
    """Spread ``energy_kwh`` consumed over [interval_start, interval_end)
    uniformly in time across 96 local time-of-day slots, adding into ``slot_sums``.

    The interval is walked in absolute (UTC) time in 15-minute steps, so it may
    cross local midnight (wrapping from slot 95 to slot 0), span several days,
    or cross a DST transition. Each piece is mapped to the local wall-clock slot
    it falls in: on a 25 h day the repeated hour lands in its wall-clock slots
    twice, on a 23 h day the skipped hour's slots receive nothing. All real UTC
    offsets are multiples of 15 minutes, so UTC and local slot boundaries align.

    Energy is apportioned over the full interval duration; only the part that
    overlaps [window_start, window_end) is recorded, keeping the caller's
    fixed 7-day averaging denominator honest.
    """
    total_seconds = (interval_end - interval_start).total_seconds()
    if total_seconds <= 0 or energy_kwh <= 0:
        return

    start_utc = max(interval_start, window_start).astimezone(pytz.UTC)
    end_utc = min(interval_end, window_end).astimezone(pytz.UTC)
    if end_utc <= start_utc:
        return

    epoch_seconds = start_utc.timestamp()
    cursor = start_utc
    # First boundary strictly after cursor on the 15-minute UTC grid.
    next_boundary = datetime.fromtimestamp(
        (epoch_seconds // _SLOT_SECONDS + 1) * _SLOT_SECONDS, tz=pytz.UTC
    )
    while cursor < end_utc:
        piece_end = min(next_boundary, end_utc)
        local_cursor = cursor.astimezone(local_tz)
        slot_idx = (local_cursor.hour * 60 + local_cursor.minute) // 15
        slot_sums[slot_idx] += energy_kwh * (piece_end - cursor).total_seconds() / total_seconds
        cursor = piece_end
        next_boundary = next_boundary + timedelta(seconds=_SLOT_SECONDS)


async def get_load_profile_from_ha(config: dict[str, Any]) -> list[float]:
    """Build the average daily load profile from 7 days of ``load_power`` history (Async).

    The power history is step-integrated per 15-minute slot and spread over the 96
    local time-of-day slots. This is total load, as recorded by the load sensor.
    """
    ha_config = secrets.load_home_assistant_config()
    url: str | None = cast("str | None", ha_config.get("url"))
    token = cast("str", ha_config.get("token", ""))

    _sensors_cfg: Any = config.get("input_sensors", {})
    if isinstance(_sensors_cfg, dict):
        input_sensors: dict[str, Any] = cast("dict[str, Any]", _sensors_cfg)
    else:
        input_sensors = {}

    entity_id: str | None = input_sensors.get("load_power")

    if not all([url, token, entity_id]):
        logger.warning("Missing Home Assistant configuration for load profile")
        return get_dummy_load_profile(config)

    entity = cast("str", entity_id)
    end_time = datetime.now(pytz.UTC)
    start_time = end_time - timedelta(days=_LOAD_PROFILE_DAYS)

    try:
        logger.info("Fetching %s history from Home Assistant", entity)
        # Convert to local timezone for processing
        local_tz = pytz.timezone("Europe/Stockholm")

        # Energy per local time-of-day slot, summed over the 7-day window
        slot_sums = [0.0] * 96
        valid_points = 0

        # One request per day keeps each response bounded (a power sensor reporting
        # every few seconds yields ~16k states per day).
        for day in range(_LOAD_PROFILE_DAYS):
            day_start = start_time + timedelta(days=day)
            day_end = day_start + timedelta(days=1)
            history = await get_power_history_batch([entity], day_start, day_end)
            if history is None:
                return get_dummy_load_profile(
                    config,
                    discard_reason=f"'{entity}' history could not be fetched from Home Assistant",
                )

            points = parse_power_states(history[entity])
            valid_points += len(points)
            slot_start = day_start
            while slot_start < day_end:
                slot_end = min(slot_start + timedelta(seconds=_SLOT_SECONDS), day_end)
                integrated = integrate_power_points(points, slot_start, slot_end)
                if integrated is not None and integrated[0] > 0:
                    _distribute_interval_energy(
                        slot_sums,
                        slot_start,
                        slot_end,
                        integrated[0],
                        local_tz,
                        window_start=start_time,
                        window_end=end_time,
                    )
                slot_start = slot_end

        if valid_points == 0:
            logger.warning("No history received from Home Assistant for %s", entity)
            return get_dummy_load_profile(
                config,
                discard_reason=(f"'{entity}' has no history in the last {_LOAD_PROFILE_DAYS} days"),
            )

        # Create average daily profile from the 7 days of data (divide by 7 days)
        daily_profile = [slot_sum / float(_LOAD_PROFILE_DAYS) for slot_sum in slot_sums]

        # Validate and clean the profile
        total_daily = sum(daily_profile)
        if total_daily > 500:
            logger.warning(
                "Daily total %.1f kWh/day for %s exceeds 500 kWh sanity bound, using dummy profile",
                total_daily,
                entity,
            )
            return get_dummy_load_profile(
                config,
                discard_reason=(
                    f"'{entity}' data discarded: {total_daily:.1f} kWh/day exceeds the "
                    "500 kWh/day plausibility bound"
                ),
            )
        if total_daily <= 0:
            logger.warning("No valid energy consumption data found for %s", entity)
            return get_dummy_load_profile(
                config,
                discard_reason=f"'{entity}' returned no valid (positive) power data",
            )

        logger.info("Successfully loaded HA data: %.2f kWh/day average", total_daily)

        # Ensure all values are positive and reasonable
        for i in range(96):
            if daily_profile[i] < 0:
                daily_profile[i] = 0
            elif daily_profile[i] > 10:  # Cap at 10kW per 15min
                daily_profile[i] = 10

        return daily_profile

    except Exception as e:
        logger.warning("Error processing Home Assistant data for %s: %s", entity, e)
        return get_dummy_load_profile(config)


def get_dummy_load_profile(
    config: dict[str, Any], discard_reason: str | None = None
) -> list[float]:
    """Create a dummy load profile or a synthetic scaled profile.

    If config.input_sensors.synthetic_daily_load_kwh is a positive daily estimate,
    we generate a synthetic winter heat-pump curve scaled to that daily total.
    Otherwise, we fall back to a 0.5 kWh flat dummy profile.

    ``discard_reason``, when set, means ``load_power`` WAS configured but its history
    was unavailable, empty or discarded as implausible (as opposed to no sensor being
    configured at all) — it flows into the degraded-status detail so the health banner
    names the sensor instead of telling the user to configure one that already
    exists.
    """
    import logging

    logger = logging.getLogger(__name__)

    estimated_daily_kwh = None
    sensors = config.get("input_sensors", {})
    # Reached only when load_power history is unusable (not configured, empty or discarded).
    raw_val = sensors.get("synthetic_daily_load_kwh")

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
            "⚠️ Using DEMO load profile (0.5 kWh flat) - no historical data available. Configure the load_power sensor for accurate forecasts."
        )

    # REV F65 Phase 5b: Set degraded status when using demo data
    set_load_forecast_status("degraded", "demo", detail=discard_reason or "")

    return [0.5] * 96
