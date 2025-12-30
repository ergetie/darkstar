import logging
from backend.extensions import socketio

logger = logging.getLogger("darkstar.events")

def emit_status_update(status_data: dict):
    """Broadcast executor status update to all connected clients."""
    try:
        socketio.emit("executor_status", status_data)
    except Exception as e:
        logger.error(f"Failed to emit executor_status: {e}")

def emit_live_metrics(live_data: dict):
    """Broadcast live system metrics (SoC, PV, Load) to all connected clients."""
    try:
        socketio.emit("live_metrics", live_data)
    except Exception as e:
        logger.error(f"Failed to emit live_metrics: {e}")

def emit_plan_updated():
    """Notify clients that a new schedule has been generated."""
    try:
        socketio.emit("plan_updated", {"timestamp": "now"})
    except Exception as e:
        logger.error(f"Failed to emit plan_updated: {e}")

def emit_ha_entity_change(entity_id: str, state: str, attributes: dict = None):
    """Broadcast HA entity state change to all connected clients."""
    try:
        payload = {
            "entity_id": entity_id,
            "state": state,
            "attributes": attributes or {}
        }
        socketio.emit("ha_entity_change", payload)
    except Exception as e:
        logger.error(f"Failed to emit ha_entity_change: {e}")
