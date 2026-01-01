import logging
import threading
from flask import request
from flask_socketio import emit
from backend.extensions import socketio

logger = logging.getLogger("darkstar.events")

# Caches for latest state to sync new clients (Rev U7)
# Use RLock to allow nested calls and prevent deadlocks in multi-threaded environments
CACHE_LOCK = threading.RLock()
LATEST_METRICS = {}
LATEST_STATUS = {}

def emit_status_update(status_data: dict):
    """Broadcast executor status update to all connected clients."""
    try:
        if not isinstance(status_data, dict):
            return
        with CACHE_LOCK:
            LATEST_STATUS.update(status_data)
        socketio.emit("executor_status", status_data)
    except Exception as e:
        logger.error(f"Failed to emit executor_status: {e}")

def emit_live_metrics(live_data: dict):
    """Broadcast live system metrics (SoC, PV, Load) to all connected clients."""
    try:
        if not isinstance(live_data, dict):
            return
        with CACHE_LOCK:
            LATEST_METRICS.update(live_data)
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
        # Filter attributes to avoid massive payloads (Rev U12)
        filtered_attributes = {k: v for k, v in (attributes or {}).items() if k in ["unit_of_measurement", "icon", "friendly_name", "device_class"]}
        payload = {
            "entity_id": entity_id,
            "state": state,
            "attributes": filtered_attributes
        }
        socketio.emit("ha_entity_change", payload)
    except Exception as e:
        logger.error(f"Failed to emit ha_entity_change: {e}")

# Connection handler to sync latest state (Rev U22)
@socketio.on('connect')
def handle_connect():
    """Send latest metrics and status to newly connected client."""
    try:
        # Standard emit() inside an event handler targets the sender automatically.
        logger.info("🔌 Client connected, performing initial sync")
        
        with CACHE_LOCK:
            metrics = dict(LATEST_METRICS) if LATEST_METRICS else {}
            status = dict(LATEST_STATUS) if LATEST_STATUS else {}

        if metrics:
            emit('live_metrics', metrics)
        
        if status:
            emit('executor_status', status)
            
    except Exception as e:
        logger.error(f"❌ Error in handle_connect: {e}")

# Note: request is used implicitly by emit() in connection context
