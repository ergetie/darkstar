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


# ``(timestamp, kW)``; ``None`` marks a state that is not a usable reading (a gap).
PowerPoint = tuple[datetime, float | None]


def _state_timestamp(state: dict[str, Any]) -> datetime | None:
    for key in ("last_changed", "last_updated"):
        raw = state.get(key)
        if raw:
            try:
                return datetime.fromisoformat(str(raw))
            except (TypeError, ValueError):
                continue
    return None


# Entities already warned about for a missing unit (once per entity per process).
_unitless_warned: set[str] = set()


def _warn_unknown_unit_once(entity_id: str | None) -> None:
    key = entity_id or "<unknown entity>"
    if key in _unitless_warned:
        return
    _unitless_warned.add(key)
    logger.warning("No unit_of_measurement known for %s; assuming kW", key)


def parse_power_states(
    states: list[dict[str, Any]], entity_id: str | None = None
) -> list[PowerPoint]:
    """Parse HA history states of one power sensor into time-sorted ``(timestamp, kW)`` points.

    States without a timestamp are skipped. A state without a usable numeric value
    (``unavailable``, ``unknown``, empty, non-numeric) is kept as a gap marker
    ``(timestamp, None)`` so that integration ends the hold there instead of carrying
    the previous valid value across the period. A state lacking a unit
    inherits the last unit seen earlier in the series (HA often reports it only on the
    first state, which may be a non-numeric one, so the unit is learned from every
    state before its value is skipped). A numeric series with no unit anywhere is read
    as kW; ``entity_id`` only names it in the once-per-process warning.
    """
    points: list[PowerPoint] = []
    cached_unit: str | None = None
    stamped = [(ts, state) for state in states if (ts := _state_timestamp(state)) is not None]
    stamped.sort(key=lambda item: item[0])
    for ts, state in stamped:
        attributes: dict[str, Any] = state.get("attributes") or {}
        unit: str | None = attributes.get("unit_of_measurement")
        if unit is not None and unit != "":
            cached_unit = unit

        state_val = state.get("state", "")
        if state_val in ("unknown", "unavailable", "", None):
            points.append((ts, None))
            continue
        try:
            value = float(state_val)
        except (TypeError, ValueError):
            points.append((ts, None))
            continue

        if unit is None or unit == "":
            unit = cached_unit
        if unit is None:
            _warn_unknown_unit_once(entity_id)
        points.append((ts, normalize_active_power_kw(value, unit)))
    return points


def integrate_power_points_covered(
    points: list[PowerPoint],
    start: datetime,
    end: datetime,
) -> tuple[float, float, float] | None:
    """Step-integrate (zero-order hold) parsed power points over ``[start, end]``.

    Returns ``(positive_kwh, negative_kwh, covered_seconds)``. Each sample interval is
    added to one side by the sign of its held value (negative energy is returned as a
    magnitude); ``covered_seconds`` is the time inside the window that had a valid
    held value. The last state at or before ``start`` is the pre-window value. A gap
    marker (``None`` value) ends the hold: nothing is accumulated, and no coverage is
    counted, until the next valid point. Returns None when no valid interval overlaps
    the window.
    """
    if not points:
        return None

    positive = 0.0
    negative = 0.0
    covered_seconds = 0.0
    current_kw: float | None = None
    cursor = start

    def accumulate(kw: float, until: datetime) -> None:
        nonlocal positive, negative, covered_seconds
        seconds = (until - cursor).total_seconds()
        covered_seconds += seconds
        kwh = kw * (seconds / 3600.0)
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

    return (positive, negative, covered_seconds) if covered_seconds > 0 else None


def integrate_power_points(
    points: list[PowerPoint],
    start: datetime,
    end: datetime,
) -> tuple[float, float] | None:
    """Step-integrate parsed power points over ``[start, end]``.

    Returns ``(positive_kwh, negative_kwh)`` as :func:`integrate_power_points_covered`
    does, without the covered duration. Returns None when no valid interval overlaps
    the window.
    """
    integrated = integrate_power_points_covered(points, start, end)
    return None if integrated is None else (integrated[0], integrated[1])


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
        # HA enables minimal_response by mere presence of the key (only the first state
        # of a series then carries attributes) and significant_changes_only unless it
        # equals "0". Full attributes would bloat each response by several MB, so the
        # minimal form is kept deliberately and missing units are filled in below.
        "significant_changes_only": "0",
        "minimal_response": "true",
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
    await _fill_missing_units(result)
    return result


def _unit_of(state: dict[str, Any]) -> str | None:
    attributes = state.get("attributes")
    if not isinstance(attributes, dict):
        return None
    unit = cast("dict[str, Any]", attributes).get("unit_of_measurement")
    return str(unit) if unit else None


def _series_has_unit(series: list[dict[str, Any]]) -> bool:
    return any(_unit_of(state) for state in series)


async def _fill_missing_units(result: dict[str, list[dict[str, Any]]]) -> None:
    """Give every non-empty series without a unit the entity's current unit (in place).

    The unit is written into a copy of the first state's attributes. A failed lookup
    leaves the series unchanged.
    """
    unitless = [
        entity for entity, series in result.items() if series and not _series_has_unit(series)
    ]
    if not unitless:
        return
    current = await asyncio.gather(
        *(get_ha_entity_state(entity) for entity in unitless), return_exceptions=True
    )
    for entity, state in zip(unitless, current, strict=True):
        if not isinstance(state, dict):
            continue
        unit = _unit_of(state)
        if not unit:
            continue
        series = list(result[entity])
        first = dict(series[0])
        first["attributes"] = {**(first.get("attributes") or {}), "unit_of_measurement": unit}
        series[0] = first
        result[entity] = series


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
    integrated = integrate_power_points(
        parse_power_states(history[entity_id], entity_id), start, end
    )
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

            # Measured charger power: tells Kepler whether a session is running
            # now, so continuing it costs no start loss (ev-charging-losses D2).
            power_sensor = ev.get("sensor", "")
            if power_sensor:
                per_device_reads.append(
                    (
                        f"ev_power_{charger_id}",
                        lambda e=power_sensor: get_ha_sensor_kw_normalized(e),
                    )
                )

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
                    "power_kw": per_device_results.get(f"ev_power_{charger_id}"),
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
# A time-of-day slot is only trusted when its valid data adds up to at least one full
# slot length over the whole window; below that the mean rests on less than one slot's
# worth of observation and the slot is filled from its neighbours instead.
_MIN_SLOT_COVERAGE_SECONDS = _SLOT_SECONDS
# Interpolating across gaps is only sensible while most of the day is measured. With
# fewer than half of the 96 slots supported the shape of the day is guesswork (the
# widest hole could exceed 12 h), so the profile is treated as insufficient instead.
_MIN_SUPPORTED_SLOTS = 48


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
    overlaps [window_start, window_end) is recorded.
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


def _coverage_averaged_profile(
    slot_sums: list[float], slot_covered: list[float]
) -> tuple[list[float], int]:
    """Turn per-slot energy and covered seconds into a 96-slot kWh-per-slot profile.

    A supported slot (valid data of at least ``_MIN_SLOT_COVERAGE_SECONDS``) gets its
    mean power over the covered time scaled to the slot length, which is exact for
    slots measured only in part. Other slots are filled by linear interpolation
    between the nearest supported slots around the clock (wrapping over midnight).
    Returns the profile and the number of supported slots; with none, all zeros.
    """
    supported = [covered >= _MIN_SLOT_COVERAGE_SECONDS for covered in slot_covered]
    profile = [
        slot_sums[i] / slot_covered[i] * _SLOT_SECONDS if supported[i] else 0.0 for i in range(96)
    ]
    anchors = [i for i in range(96) if supported[i]]
    if not anchors:
        return profile, 0
    for i in range(96):
        if supported[i]:
            continue
        before = next(j for j in range(1, 97) if supported[(i - j) % 96])
        after = next(j for j in range(1, 97) if supported[(i + j) % 96])
        low = profile[(i - before) % 96]
        high = profile[(i + after) % 96]
        profile[i] = low + (high - low) * before / (before + after)
    return profile, len(anchors)


async def get_load_profile_from_ha(config: dict[str, Any]) -> list[float]:
    """Build the average daily load profile from 7 days of ``load_power`` history (Async).

    The power history is step-integrated per 15-minute slot and spread over the 96
    local time-of-day slots. This is total load, as recorded by the load sensor. Each
    slot is the mean power over the time it was validly measured, so sensor gaps are
    not zero load; slots never measured are interpolated, and a profile with too few
    measured slots is discarded.
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
        # Seconds of valid (non-gap) data per local time-of-day slot over the window
        slot_covered = [0.0] * 96
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

            points = parse_power_states(history[entity], entity)
            valid_points += sum(1 for _ts, value in points if value is not None)
            slot_start = day_start
            while slot_start < day_end:
                slot_end = min(slot_start + timedelta(seconds=_SLOT_SECONDS), day_end)
                integrated = integrate_power_points_covered(points, slot_start, slot_end)
                if integrated is not None:
                    positive_kwh, _negative_kwh, covered_seconds = integrated
                    # Energy and covered time are apportioned identically, so each
                    # local slot keeps the interval's mean power over its valid time.
                    for target, amount in (
                        (slot_sums, positive_kwh),
                        (slot_covered, covered_seconds),
                    ):
                        _distribute_interval_energy(
                            target,
                            slot_start,
                            slot_end,
                            amount,
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

        # Average each slot over the time it was actually measured (not over 7 days), so
        # a sensor outage never counts as zero load.
        daily_profile, supported_slots = _coverage_averaged_profile(slot_sums, slot_covered)
        if supported_slots < _MIN_SUPPORTED_SLOTS:
            logger.warning(
                "Only %d of 96 slots of %s have enough valid history, using dummy profile",
                supported_slots,
                entity,
            )
            return get_dummy_load_profile(
                config,
                discard_reason=(
                    f"'{entity}' has valid data for only {supported_slots} of 96 "
                    f"time-of-day slots in the last {_LOAD_PROFILE_DAYS} days"
                ),
            )

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
