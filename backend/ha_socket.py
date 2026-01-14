import asyncio
import json
import logging
import threading

import websockets

from inputs import load_home_assistant_config, load_yaml

logger = logging.getLogger("darkstar.ha_socket")


class HAWebSocketClient:
    def __init__(self):
        logger.debug("Initializing HAWebSocketClient...")
        self._load_config()
        self.id_counter = 1
        self.inversion_flags: dict[str, bool] = {}
        self.monitored_entities = self._get_monitored_entities()
        self.running = False

        # Early validation with logging
        if not self.token:
            logger.warning("⚠️ No HA token configured - WebSocket will not connect")
        if not self.url or self.url == "/api/websocket":
            logger.warning("⚠️ No HA URL configured - WebSocket will not connect")
        else:
            logger.debug(f"HA WebSocket URL: {self.url}")

    def _load_config(self):
        """Load HA connection parameters from secrets.yaml."""
        try:
            self.config = load_home_assistant_config()
            base_url = self.config.get("url", "")

            if not base_url:
                logger.error("❌ No HA URL found in secrets.yaml - WebSocket cannot connect")
                self.url = "/api/websocket"  # Invalid URL to prevent connection
                self.token = None
                return

            if base_url.startswith("https"):
                self.url = base_url.replace("https", "wss") + "/api/websocket"
            else:
                self.url = base_url.replace("http", "ws") + "/api/websocket"

            self.token = self.config.get("token")

            if not self.token:
                logger.error("❌ No HA token found in secrets.yaml - WebSocket cannot authenticate")
            else:
                # Log token length for verification without exposing the actual token
                logger.info(f"✅ HA config loaded: URL={base_url}, token_len={len(self.token)}")

        except Exception as e:
            logger.error(f"❌ Failed to load HA configuration: {e}", exc_info=True)
            self.url = "/api/websocket"
            self.token = None

    def _get_monitored_entities(self) -> dict[str, str]:
        # Load config to map entity_id -> metric_key
        try:
            cfg = load_yaml("config.yaml")
            sensors = cfg.get("input_sensors", {})
            # Map: entity_id -> key (e.g. 'sensor.inverter_battery' -> 'soc')
            mapping = {}
            if "battery_soc" in sensors:
                mapping[sensors["battery_soc"]] = "soc"
            if "pv_power" in sensors:
                mapping[sensors["pv_power"]] = "pv_kw"
            if "load_power" in sensors:
                mapping[sensors["load_power"]] = "load_kw"
            if "grid_power" in sensors:
                mapping[sensors["grid_power"]] = "grid_kw"
            if "battery_power" in sensors:
                mapping[sensors["battery_power"]] = "battery_kw"
            if "water_power" in sensors:
                mapping[sensors["water_power"]] = "water_kw"
            if "vacation_mode" in sensors:
                mapping[sensors["vacation_mode"]] = "vacation_mode"

            # Store inversion flags for efficient lookup in _handle_state_change
            self.inversion_flags = {
                "grid_kw": sensors.get("grid_power_inverted", False),
                "battery_kw": sensors.get("battery_power_inverted", False),
            }

            if not mapping:
                logger.warning("⚠️ No entities configured for HA WebSocket monitoring - check input_sensors in config.yaml")
            else:
                logger.info(f"✅ HA WebSocket monitoring {len(mapping)} entities: {list(mapping.keys())}")
            return mapping
        except Exception as e:
            logger.error(f"❌ Failed to load monitored entities: {e}", exc_info=True)
            return {}

    async def connect(self):
        while self.running:
            try:
                # Increase max_size to 10MB to handle large HA get_states responses (Rev U3)
                async with websockets.connect(self.url, max_size=10485760) as ws:
                    logger.info(f"Connected to HA WebSocket: {self.url}")

                    # Authenticate
                    await ws.recv()  # Expect "auth_required"

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
                    await ws.send(
                        json.dumps(
                            {
                                "id": sub_id,
                                "type": "subscribe_events",
                                "event_type": "state_changed",
                            }
                        )
                    )

                    # Get initial states (Rev U2)
                    states_id = self.id_counter
                    self.id_counter += 1
                    await ws.send(json.dumps({"id": states_id, "type": "get_states"}))

                    # Listen loop
                    while self.running:
                        msg = await ws.recv()
                        data = json.loads(msg)

                        # Handle the get_states response
                        if data.get("id") == states_id and data.get("type") == "result":
                            results = data.get("result", [])
                            for state in results:
                                entity_id = state.get("entity_id")
                                if entity_id in self.monitored_entities:
                                    self._handle_state_change(entity_id, state)
                            continue

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
        if not new_state:
            return
        key = self.monitored_entities[entity_id]

        # Handle vacation_mode (binary sensor/input_boolean)
        if key == "vacation_mode":
            try:
                state_val = new_state.get("state")
                # Emit entity change event
                from backend.events import emit_ha_entity_change

                # Filter attributes to avoid massive payloads (Rev U12)
                allowed_attrs = {
                    "friendly_name",
                    "unit_of_measurement",
                    "device_class",
                    "state_class",
                }
                filtered_attrs = {
                    k: v for k, v in new_state.get("attributes", {}).items() if k in allowed_attrs
                }

                emit_ha_entity_change(
                    entity_id=entity_id, state=state_val, attributes=filtered_attrs
                )
            except Exception as e:
                logger.error(f"Failed to emit vacation_mode change: {e}")
            return

        # Handle numeric sensors (existing logic)
        try:
            state_val = new_state.get("state")
            if state_val is None or str(state_val).lower() in (
                "unknown",
                "unavailable",
                "none",
                "null",
                "",
            ):
                return

            value = float(state_val)
            # Normalize units if needed (kW vs W)
            unit = str(new_state.get("attributes", {}).get("unit_of_measurement", "")).upper()
            if unit == "W":
                value = value / 1000.0

            # Apply inversion if configured
            if self.inversion_flags.get(key, False):
                value = -value

            # Emit
            payload = {key: value}

            # Import here to avoid circular imports at module level
            from backend.events import emit_live_metrics

            # Only log at info if it's a significant change or periodically to avoid spam
            # For now, info is fine for debugging
            logger.debug(f"Emitting live_metrics: {payload}")
            emit_live_metrics(payload)

        except (ValueError, TypeError):
            pass

    def start(self):
        self.running = True

        def _run_ws():
            """Thread target with exception handling to prevent silent crashes."""
            try:
                asyncio.run(self.connect())
            except Exception as e:
                logger.error(f"❌ HA WebSocket thread crashed: {e}", exc_info=True)

        logger.info(f"🔗 Connecting to HA WebSocket: {self.url}")
        threading.Thread(target=_run_ws, daemon=True, name="HA-WebSocket").start()

    def reload_monitored_entities(self):
        """Reload the monitored entities mapping from config.yaml and HA params from secrets.yaml."""
        logger.info("Reloading HA configuration...")
        self._load_config()
        self.monitored_entities = self._get_monitored_entities()


# Global instance
_ha_client = None


def start_ha_socket_client():
    """Start the HA WebSocket client for live sensor updates."""
    global _ha_client
    logger.info("🔌 Starting HA WebSocket client...")
    if _ha_client is None:
        try:
            _ha_client = HAWebSocketClient()
            _ha_client.start()
            logger.info("✅ HA WebSocket client initialized")
        except Exception as e:
            logger.error(f"❌ Failed to start HA WebSocket client: {e}", exc_info=True)


def reload_ha_socket_client():
    """Trigger a reload of the monitored entities in the running client."""
    if _ha_client:
        _ha_client.reload_monitored_entities()


def get_ha_socket_status() -> dict:
    """Return diagnostic info about HA WebSocket connection."""
    if _ha_client is None:
        return {"status": "not_started", "monitored_entities": {}}
    return {
        "status": "running" if _ha_client.running else "stopped",
        "monitored_entities": _ha_client.monitored_entities,
        "url": _ha_client.url,
    }
