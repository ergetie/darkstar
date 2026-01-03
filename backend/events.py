import logging
from typing import Any

from backend.core.websockets import ws_manager

logger = logging.getLogger("darkstar.events")

# Caches for latest state (Rev U7/U22)
# We can use a simple dict if we assume the manager handles threading safety for us,
# but keeping a local cache for 'connect' handling is good.
_LATEST_METRICS: dict[str, Any] = {}
_LATEST_STATUS: dict[str, Any] = {}


def emit_status_update(status_data: dict[str, Any]):
    """Broadcast executor status update (Thread-safe)."""
    # status_data is typed as dict[str, Any]
    _LATEST_STATUS.update(status_data)
    # emit_sync handles the bridge to the async loop
    ws_manager.emit_sync("executor_status", status_data)


def emit_live_metrics(live_data: dict[str, Any]):
    """Broadcast live metrics (Thread-safe)."""
    # live_data is typed as dict[str, Any]
    _LATEST_METRICS.update(live_data)
    ws_manager.emit_sync("live_metrics", live_data)


def emit_plan_updated():
    """Notify clients of plan update."""
    ws_manager.emit_sync("plan_updated", {"timestamp": "now"})


def emit_ha_entity_change(entity_id: str, state: str, attributes: dict[str, Any] | None = None):
    """Broadcast HA entity change."""
    filtered = {
        k: v
        for k, v in (attributes or {}).items()
        if k in ["unit_of_measurement", "icon", "friendly_name", "device_class"]
    }
    payload: dict[str, Any] = {"entity_id": entity_id, "state": state, "attributes": filtered}
    ws_manager.emit_sync("ha_entity_change", payload)


# Register Event Handlers
# This code runs on import, so when 'backend.events' is imported by main or others,
# the handlers are registered on the singleton SIO instance.


@ws_manager.sio.on("connect")  # pyright: ignore [reportUnknownMemberType, reportUntypedFunctionDecorator]
async def handle_connect(sid: str, environ: dict[str, Any]):
    logger.info(f"🔌 Client connected: {sid}")
    # Send cached state
    if _LATEST_METRICS:
        await ws_manager.emit("live_metrics", _LATEST_METRICS, to=sid)
    if _LATEST_STATUS:
        await ws_manager.emit("executor_status", _LATEST_STATUS, to=sid)


@ws_manager.sio.on("disconnect")  # pyright: ignore [reportUnknownMemberType, reportUntypedFunctionDecorator]
async def handle_disconnect(sid: str):
    logger.info(f"Client disconnected: {sid}")
