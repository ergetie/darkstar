"""Short-lived, credential-scoped Home Assistant registry discovery."""

import asyncio
import hashlib
import json
import logging
import time
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

import websockets

from backend.core.ha_client import get_ha_http_client, make_ha_headers
from backend.core.secrets import load_home_assistant_config

logger = logging.getLogger(__name__)
_CACHE: dict[tuple[str, str], tuple[float, dict[str, dict[str, Any]], bool]] = {}
_LOCK = asyncio.Lock()


def websocket_url(url: str) -> str:
    parts = urlsplit(url.rstrip("/"))
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("HA URL must be an absolute HTTP or HTTPS URL")
    return urlunsplit(
        (
            "wss" if parts.scheme == "https" else "ws",
            parts.netloc,
            parts.path + "/api/websocket",
            "",
            "",
        )
    )


async def _fetch_registry(url: str, token: str) -> dict[str, dict[str, Any]]:
    async with asyncio.timeout(10):
        async with websockets.connect(websocket_url(url), max_size=10485760) as ws:
            greeting = json.loads(await ws.recv())
            if greeting.get("type") != "auth_required":
                raise ValueError("Unexpected HA authentication greeting")
            await ws.send(json.dumps({"type": "auth", "access_token": token}))
            if json.loads(await ws.recv()).get("type") != "auth_ok":
                raise PermissionError("HA websocket authentication failed")
            results: list[list[dict[str, Any]]] = []
            for request_id, command in enumerate(
                ("config/entity_registry/list", "config/device_registry/list"), 1
            ):
                await ws.send(json.dumps({"id": request_id, "type": command}))
                response = json.loads(await ws.recv())
                if (
                    response.get("id") != request_id
                    or response.get("type") != "result"
                    or not response.get("success")
                ):
                    raise ValueError("HA registry command failed")
                result = response.get("result")
                if not isinstance(result, list):
                    raise ValueError("Malformed HA registry response")
                results.append(cast("list[dict[str, Any]]", result))
            devices = {device["id"]: device for device in results[1]}
            registry: dict[str, dict[str, Any]] = {}
            for entity in results[0]:
                device = devices.get(entity.get("device_id"), {})
                registry[entity["entity_id"]] = {
                    "platform": entity.get("platform"),
                    "device_id": entity.get("device_id"),
                    "manufacturer": device.get("manufacturer"),
                    "model": device.get("model"),
                }
            return registry


async def get_registry(url: str, token: str) -> tuple[dict[str, dict[str, Any]], bool]:
    # Never retain plaintext credentials in the cache or mix registry data between tokens.
    key = (url.rstrip("/"), hashlib.sha256(token.encode()).hexdigest())
    async with _LOCK:
        cached = _CACHE.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1], cached[2]
        try:
            registry, available = await _fetch_registry(url, token), True
        except Exception:
            logger.warning("HA registry unavailable; using state-only discovery")
            registry, available = {}, False
        now = time.monotonic()
        for expired in [k for k, v in _CACHE.items() if v[0] <= now]:
            del _CACHE[expired]
        _CACHE[key] = (now + 60, registry, available)
        return registry, available


async def discover_entities() -> dict[str, Any]:
    config = load_home_assistant_config()
    url, token = config.get("url"), config.get("token")
    if not url or not token:
        raise ValueError("HA not configured")
    response = await get_ha_http_client().get(
        f"{url.rstrip('/')}/api/states", headers=make_ha_headers(token), timeout=5
    )
    response.raise_for_status()
    states = response.json()
    registry, available = await get_registry(url, token)
    entities: list[dict[str, Any]] = []
    for state in states:
        eid = state["entity_id"]
        attrs = state.get("attributes", {})
        entities.append(
            {
                "entity_id": eid,
                "friendly_name": attrs.get("friendly_name", eid),
                "domain": eid.split(".")[0],
                "state": state.get("state"),
                **{
                    key: attrs.get(key)
                    for key in ("unit_of_measurement", "device_class", "state_class")
                },
                **{
                    key: registry.get(eid, {}).get(key)
                    for key in ("platform", "device_id", "manufacturer", "model")
                },
            }
        )
    return {"entities": entities, "registry_available": available}
