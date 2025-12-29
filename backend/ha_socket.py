import asyncio
import json
import logging
import threading
from typing import Dict

import websockets
from inputs import load_home_assistant_config, _load_yaml

logger = logging.getLogger("darkstar.ha_socket")

class HAWebSocketClient:
    def __init__(self):
        self.config = load_home_assistant_config()
        base_url = self.config.get("url", "")
        if base_url.startswith("https"):
            self.url = base_url.replace("https", "wss") + "/api/websocket"
        else:
            self.url = base_url.replace("http", "ws") + "/api/websocket"
            
        self.token = self.config.get("token")
        self.id_counter = 1
        self.monitored_entities = self._get_monitored_entities()
        self.running = False

    def _get_monitored_entities(self) -> Dict[str, str]:
        # Load config to map entity_id -> metric_key
        try:
            cfg = _load_yaml("config.yaml")
            sensors = cfg.get("input_sensors", {})
            # Map: entity_id -> key (e.g. 'sensor.inverter_battery' -> 'soc')
            mapping = {}
            if "battery_soc" in sensors: mapping[sensors["battery_soc"]] = "soc"
            if "pv_power" in sensors: mapping[sensors["pv_power"]] = "pv_kw"
            if "load_power" in sensors: mapping[sensors["load_power"]] = "load_kw"
            if "grid_import_power" in sensors: mapping[sensors["grid_import_power"]] = "grid_import_kw"
            if "grid_export_power" in sensors: mapping[sensors["grid_export_power"]] = "grid_export_kw"
            if "vacation_mode" in sensors: mapping[sensors["vacation_mode"]] = "vacation_mode"
            return mapping
        except Exception:
            return {}

    async def connect(self):
        while self.running:
            try:
                async with websockets.connect(self.url) as ws:
                    logger.info(f"Connected to HA WebSocket: {self.url}")
                    
                    # Authenticate
                    await ws.recv() # Expect "auth_required"
                    
                    await ws.send(json.dumps({"type": "auth", "access_token": self.token}))
                    auth_response = await ws.recv()
                    auth_result = json.loads(auth_response)
                    
                    if auth_result.get("type") != "auth_ok":
                        logger.error(f"HA Auth failed: {auth_result}")
                        return

                    logger.info("HA Authenticated")

                    # Subscribe to state_changed
                    sub_id = self.id_counter
                    self.id_counter += 1
                    await ws.send(json.dumps({
                        "id": sub_id,
                        "type": "subscribe_events",
                        "event_type": "state_changed"
                    }))
                    
                    # Listen loop
                    while self.running:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        if data.get("type") == "event":
                            event = data.get("event", {})
                            entity_id = event.get("data", {}).get("entity_id")
                            new_state = event.get("data", {}).get("new_state", {})
                            
                            if entity_id in self.monitored_entities:
                                self._handle_state_change(entity_id, new_state)
            
            except Exception as e:
                logger.error(f"HA WebSocket error: {e}")
                await asyncio.sleep(5)

    def _handle_state_change(self, entity_id, new_state):
        if not new_state: return
        key = self.monitored_entities[entity_id]
        
        # Handle vacation_mode (binary sensor/input_boolean)
        if key == "vacation_mode":
            try:
                state_val = new_state.get("state")
                # Emit entity change event
                from backend.events import emit_ha_entity_change
                emit_ha_entity_change(
                    entity_id=entity_id,
                    state=state_val,
                    attributes=new_state.get("attributes", {})
                )
            except Exception as e:
                logger.error(f"Failed to emit vacation_mode change: {e}")
            return
        
        # Handle numeric sensors (existing logic)
        try:
            state_val = new_state.get("state")
            if state_val in ("unknown", "unavailable"):
                return
                
            value = float(state_val)
            # Normalize units if needed (kW vs W)
            unit = new_state.get("attributes", {}).get("unit_of_measurement", "")
            if unit == "W":
                value = value / 1000.0
            
            # Emit
            payload = {key: value}
            
            # Import here to avoid circular imports at module level
            from backend.events import emit_live_metrics
            emit_live_metrics(payload)
            
        except (ValueError, TypeError):
            pass

    def start(self):
        self.running = True
        threading.Thread(target=lambda: asyncio.run(self.connect()), daemon=True).start()

# Global instance
_ha_client = None

def start_ha_socket_client():
    global _ha_client
    if _ha_client is None:
        _ha_client = HAWebSocketClient()
        _ha_client.start()
