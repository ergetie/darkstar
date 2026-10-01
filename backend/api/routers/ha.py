import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Any, cast

import pytz
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.core.ha_client import get_ha_entity_state, get_ha_http_client, make_ha_headers
from backend.core.secrets import (
    load_home_assistant_config,
    load_yaml,
    save_home_assistant_config,
)

logger = logging.getLogger("darkstar.api.ha")

router = APIRouter(prefix="/api/ha", tags=["ha"])
router_misc = APIRouter(prefix="/api", tags=["ha"])


class HACredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1)
    token: str = Field(min_length=1)


# --- Helper ---
async def _fetch_ha_history_avg(entity_id: str, hours: int) -> float:
    """Fetch history from HA and calculate time-weighted average."""
    if not entity_id:
        return 0.0

    ha_config = load_home_assistant_config()
    url = ha_config.get("url")
    token = ha_config.get("token")
    if not url or not token:
        return 0.0

    headers = make_ha_headers(token)

    end_time = datetime.now(pytz.UTC)
    start_time = end_time - timedelta(hours=hours)

    # HA History API
    api_url = f"{url.rstrip('/')}/api/history/period/{start_time.isoformat()}"
    params = {
        "filter_entity_id": entity_id,
        "end_time": end_time.isoformat(),
        "significant_changes_only": False,
        "minimal_response": True,
        "no_attributes": True,
    }

    try:
        from backend.core.ha_client import get_ha_http_client

        client = get_ha_http_client()
        resp = await client.get(api_url, headers=headers, params=params, timeout=10.0)
        if resp.status_code != 200:
            return 0.0

        data = resp.json()
        if not data or not data[0]:
            return 0.0

        # Calculate Average
        states = data[0]
        total_weighted_sum = 0.0
        total_duration_sec = 0.0

        prev_time = start_time
        prev_val = 0.0

        # Initial value from first state? Or fetch state at start_time?
        # Simplified: Use first state's value as starting point
        try:
            prev_val = float(states[0]["state"])
            prev_time = datetime.fromisoformat(states[0]["last_changed"])
        except Exception:
            pass

        for s in states:
            try:
                curr_time = datetime.fromisoformat(s["last_changed"])
                val = float(s["state"])

                # Duration since last change
                duration = (curr_time - prev_time).total_seconds()
                if duration > 0:
                    total_weighted_sum += prev_val * duration
                    total_duration_sec += duration

                prev_time = curr_time
                prev_val = val
            except Exception:
                continue

        # Add remainder until now
        duration = (end_time - prev_time).total_seconds()
        if duration > 0:
            total_weighted_sum += prev_val * duration
            total_duration_sec += duration

        if total_duration_sec == 0:
            return 0.0

        return round(total_weighted_sum / total_duration_sec, 2)

    except Exception as e:
        logger.warning(f"Error fetching HA history for {entity_id}: {e}")
        return 0.0


@router.get(
    "/entity/{entity_id}",
    summary="Get HA Entity",
    description="Returns the state of a specific Home Assistant entity.",
)
async def get_ha_entity(entity_id: str) -> dict[str, Any]:
    state = await get_ha_entity_state(entity_id)
    if not state:
        return {
            "entity_id": entity_id,
            "state": "unknown",
            "attributes": {"friendly_name": "Offline/Missing"},
            "last_changed": None,
        }
    return state


@router.get(
    "/average",
    summary="Get Entity Average",
    description="Calculate average value for an entity over the last N hours.",
)
async def get_ha_average(entity_id: str | None = None, hours: int = 24) -> dict[str, Any]:
    """Calculate average value for an entity over the last N hours."""
    from backend.core.cache import cache
    from backend.core.ha_client import get_load_profile_from_ha

    # Check cache first
    cache_key = f"ha_average:{entity_id}:{hours}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    if not entity_id:
        # Default to load power sensor
        config = load_yaml("config.yaml")
        sensors: dict[str, Any] = config.get("input_sensors", {})
        entity_id = cast("str | None", sensors.get("load_power"))

    if not entity_id:
        return {"average": 0.0, "entity_id": None, "hours": hours}

    avg_val = await _fetch_ha_history_avg(entity_id, hours)

    # Fallback to static profile if history unavailable/zero
    if avg_val == 0.0:
        try:
            config = load_yaml("config.yaml")
            profile = await get_load_profile_from_ha(config)
            if profile:
                avg_val = sum(profile) / len(profile)
        except Exception as e:
            logger.warning(f"Fallback average calc failed: {e}")

    # Calculate daily_kwh estimate (avg * 24h)
    # Note: avg_val is usually Watts.
    # HA sensors are usually W. If fetch_ha_history_avg returns W, then /1000 is correct for kWh.
    # If it returns kW, then *24 is correct.
    # Let's assume the sensor is W (standard HA).
    # But wait, fetch_ha_history_avg just returns value.
    # The frontend expects 'average_load_kw'.
    # If standard sensor is W, we should divide by 1000 for kw.

    # Let's ensure we return kW.
    # If value > 100 (likely Watts), divide by 1000.
    # If value < 50 (likely kW), keep as is. Simple heuristic or just be explicit?
    # Let's trust the value is W from typical HA power sensors, so convert to kW.

    val_kw = avg_val / 1000.0 if avg_val > 100 else avg_val

    result = {
        "average_load_kw": round(val_kw, 3),
        "daily_kwh": round(val_kw * 24, 2),
        "entity_id": entity_id,
        "hours": hours,
    }

    # Cache for 60 seconds
    await cache.set(cache_key, result, ttl_seconds=60.0)

    return result


@router.get(
    "/entities",
    summary="List HA Entities",
    description="List available Home Assistant entities.",
)
async def get_ha_entities() -> dict[str, list[dict[str, Any]]]:
    """List available HA entities."""
    # Fetch from HA states
    config = load_home_assistant_config()
    url = config.get("url")
    token = config.get("token")
    if not url or not token:
        return {"entities": []}

    try:
        headers = make_ha_headers(token)
        from backend.core.ha_client import get_ha_http_client

        client = get_ha_http_client()
        resp = await client.get(f"{url.rstrip('/')}/api/states", headers=headers, timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            # Filter and format
            entities: list[dict[str, Any]] = []
            for s in data:
                eid = str(s.get("entity_id", ""))
                if eid.startswith(
                    (
                        "sensor.",
                        "binary_sensor.",
                        "input_boolean.",
                        "switch.",
                        "input_number.",
                        "input_datetime.",
                        "input_select.",
                        "select.",
                        "number.",
                        "alarm_control_panel.",
                    )
                ):
                    attrs = s.get("attributes", {})
                    options: object = attrs.get("options", [])
                    entities.append(
                        {
                            "entity_id": eid,
                            "friendly_name": str(attrs.get("friendly_name", eid)),
                            "domain": eid.split(".")[0],
                            "unit_of_measurement": str(attrs.get("unit_of_measurement", "")),
                            "device_class": str(attrs.get("device_class", "")),
                            "options": (
                                [str(option) for option in cast("list[object]", options)]
                                if eid.startswith(("select.", "input_select."))
                                and isinstance(options, list)
                                else []
                            ),
                        }
                    )
            return {"entities": entities}
    except Exception as e:
        logger.warning(f"Error fetching HA entities: {e}")

    return {"entities": []}


@router.get(
    "/services",
    summary="List HA Services",
    description="List available Home Assistant services.",
)
async def get_ha_services() -> dict[str, list[str]]:
    """List available HA services."""
    config = load_home_assistant_config()
    url = config.get("url")
    token = config.get("token")
    if not url or not token:
        return {"services": []}

    try:
        headers = make_ha_headers(token)
        from backend.core.ha_client import get_ha_http_client

        client = get_ha_http_client()
        resp = await client.get(f"{url.rstrip('/')}/api/services", headers=headers, timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            # Flatten to list of "domain.service" strings
            services: list[str] = []
            for domain_obj in data:
                domain = str(domain_obj.get("domain", ""))
                for service_name in domain_obj.get("services", {}):
                    services.append(f"{domain}.{service_name}")
            return {"services": sorted(services)}
    except Exception as e:
        logger.warning(f"Error fetching HA services: {e}")

    return {"services": []}


@router.post(
    "/test",
    summary="Test HA Connection",
    description="Test connection to Home Assistant API.",
)
async def test_ha_connection(body: "HACredentials | None" = None) -> dict[str, Any]:
    """Test credentials without saving them; the add-on always uses Supervisor auth."""
    config = load_home_assistant_config()
    if body is not None and not os.environ.get("SUPERVISOR_TOKEN"):
        config = body.model_dump()
    url, token = config.get("url"), config.get("token")
    if not url or not token:
        return {"status": "error", "message": "HA not configured"}
    return await _test_ha_credentials(str(url), str(token))


async def _test_ha_credentials(url: str, token: str) -> dict[str, Any]:
    """Test an explicit HA URL/token pair without persisting it."""
    from backend.core.ha_registry import get_registry

    try:
        client = get_ha_http_client()
        headers = make_ha_headers(token)
        response = await client.get(f"{url.rstrip('/')}/api/", headers=headers, timeout=5)
        if response.status_code != 200:
            message = (
                "Authentication failed"
                if response.status_code in (401, 403)
                else f"HTTP {response.status_code}"
            )
            return {"status": "error", "message": message}
        core = await client.get(f"{url.rstrip('/')}/api/config", headers=headers, timeout=5)
        version = core.json().get("version") if core.status_code == 200 else None
        _, available = await get_registry(url, token)
        return {
            "status": "success",
            "message": "Connected to Home Assistant",
            "ha_version": version,
            "registry_available": available,
        }
    except Exception:
        return {"status": "error", "message": "Could not connect to Home Assistant"}


@router.put(
    "/config",
    summary="Save Home Assistant Connection",
    description="Test a standalone Home Assistant connection and save credentials on success.",
)
async def save_ha_connection(body: HACredentials) -> dict[str, str]:
    """Persist typed standalone credentials only after Home Assistant accepts them."""
    if os.environ.get("SUPERVISOR_TOKEN"):
        raise HTTPException(400, "Home Assistant add-on connections use Supervisor authentication")

    result = await _test_ha_credentials(body.url, body.token)
    if result.get("status") != "success":
        raise HTTPException(400, result.get("message", "Could not connect to Home Assistant"))
    try:
        await asyncio.to_thread(save_home_assistant_config, body.url, body.token)
    except (OSError, ValueError) as exc:
        logger.exception("Could not save Home Assistant credentials")
        raise HTTPException(500, "Could not save Home Assistant credentials") from exc
    return {"status": "success", "message": "Connected and saved Home Assistant credentials"}


@router.get("/discovery")
async def get_ha_discovery() -> dict[str, Any]:
    from backend.core.ha_registry import discover_entities

    try:
        return await discover_entities()
    except Exception as exc:
        raise HTTPException(502, "Could not discover Home Assistant entities") from exc


@router.get("/core-config")
async def get_ha_core_config() -> dict[str, Any]:
    from backend.core.ha_client import get_ha_http_client

    config = load_home_assistant_config()
    url, token = config.get("url"), config.get("token")
    if not url or not token:
        raise HTTPException(502, "HA not configured")
    try:
        response = await get_ha_http_client().get(
            f"{url.rstrip('/')}/api/config", headers=make_ha_headers(token), timeout=5
        )
        response.raise_for_status()
        data = response.json()
        result = {
            key: data.get(key)
            for key in ("latitude", "longitude", "time_zone", "currency", "country", "unit_system")
        }
        if not result["currency"] and result["country"] == "SE":
            result["currency"] = "SEK"
        return result
    except Exception as exc:
        raise HTTPException(502, "Could not read Home Assistant configuration") from exc


@router_misc.get(
    "/ha-socket",
    summary="Get HA Socket Status",
    description="Return status of the HA WebSocket connection.",
)
async def get_ha_socket_status() -> dict[str, Any]:
    """Return status of the HA WebSocket connection."""
    try:
        from backend.ha_socket import get_ha_socket_status as _get_status

        return _get_status()
    except ImportError:
        return {"status": "unavailable", "message": "HA socket module not loaded"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
