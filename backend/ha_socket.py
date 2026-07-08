import asyncio
import json
import logging
import threading
from datetime import UTC, datetime
from typing import Any

import websockets

from backend.core.secrets import load_home_assistant_config, load_yaml

logger = logging.getLogger("darkstar.ha_socket")


class HAWebSocketClient:
    def __init__(self):
        logger.debug("Initializing HAWebSocketClient...")
        self._load_config()
        self.id_counter = 1
        self.inversion_flags: dict[str, bool] = {}
        self.water_heater_configs: list[dict[str, Any]] = []
        self.ev_charger_configs: list[
            dict[str, Any]
        ] = []  # Rev F64: Store EV config with index and name
        self.latest_values: dict[
            str, Any
        ] = {}  # Must init before _get_monitored_entities (F64 writes ev_chargers here)
        self.monitored_entities = self._get_monitored_entities()
        self.running = False
        self.main_loop: asyncio.AbstractEventLoop | None = (
            None  # Rev EVFIX: Store main event loop for cross-thread dispatch
        )
        self.background_tasks: set[asyncio.Task[Any]] = set()

        # Runtime Statistics (Production Observability)
        self.stats: dict[str, Any] = {
            "connected_at": None,
            "disconnected_at": None,
            "messages_received": 0,
            "last_message_at": None,
            "events_processed": 0,
            "metrics_emitted": 0,
            "last_emit_at": None,
            "errors": [],  # Keep last 5 errors
        }

        # Early validation with logging
        if not self.token:
            logger.warning("No HA token configured - WebSocket will not connect")
        if not self.url or self.url == "/api/websocket":
            logger.warning("No HA URL configured - WebSocket will not connect")
        else:
            logger.debug(f"HA WebSocket URL: {self.url}")

    def _load_config(self):
        """Load HA connection parameters from secrets.yaml."""
        try:
            self.config = load_home_assistant_config()
            base_url = self.config.get("url", "")

            if not base_url:
                logger.error("No HA URL found in secrets.yaml - WebSocket cannot connect")
                self.url = "/api/websocket"  # Invalid URL to prevent connection
                self.token = None
                return

            if base_url.startswith("https"):
                self.url = base_url.replace("https", "wss") + "/api/websocket"
            else:
                self.url = base_url.replace("http", "ws") + "/api/websocket"

            self.token = self.config.get("token")

            if not self.token:
                logger.error("No HA token found in secrets.yaml - WebSocket cannot authenticate")
            else:
                # Log token length for verification without exposing the actual token
                logger.info(f"✅ HA config loaded: URL={base_url}, token_len={len(self.token)}")

        except Exception as e:
            logger.error(f"Failed to load HA configuration: {e}", exc_info=True)
            self.url = "/api/websocket"
            self.token = None

    def _get_monitored_entities(self) -> dict[str, str]:
        # Load config to map entity_id -> metric_key
        try:
            cfg: dict[str, Any] = load_yaml("config.yaml")
            sensors: dict[str, Any] = cfg.get("input_sensors", {})
            system: dict[str, Any] = cfg.get("system", {})
            meter_type = system.get("grid_meter_type", "net")

            # Map: entity_id -> key (e.g. 'sensor.inverter_battery' -> 'soc')
            mapping: dict[str, str] = {}
            if "battery_soc" in sensors:
                mapping[sensors["battery_soc"]] = "soc"
            if "pv_power" in sensors:
                mapping[sensors["pv_power"]] = "pv_kw"
            if "load_power" in sensors:
                mapping[sensors["load_power"]] = "load_kw"
            if "grid_power" in sensors and meter_type == "net":
                mapping[sensors["grid_power"]] = "grid_kw"

            # Dual Meter Support (REV // UI5)
            if meter_type == "dual":
                if "grid_import_power" in sensors:
                    mapping[sensors["grid_import_power"]] = "grid_import_kw"
                if "grid_export_power" in sensors:
                    mapping[sensors["grid_export_power"]] = "grid_export_kw"
            if "battery_power" in sensors:
                mapping[sensors["battery_power"]] = "battery_kw"

            # ARC15: Water heater sensors from water_heaters[] array
            if system.get("has_water_heater", False):
                water_heaters: list[dict[str, Any]] = cfg.get("water_heaters", [])
                self.water_heater_configs: list[dict[str, Any]] = []
                used_water_sensors: set[str] = set()
                for idx, wh in enumerate(water_heaters):
                    if wh.get("enabled", True):
                        wh_name = wh.get("name", f"Water Heater {idx + 1}")
                        active_idx = len(self.water_heater_configs)
                        self.water_heater_configs.append({"index": active_idx, "name": wh_name})
                        if wh.get("sensor") and wh["sensor"] not in used_water_sensors:
                            mapping[wh["sensor"]] = f"water_kw_{active_idx}"
                            used_water_sensors.add(wh["sensor"])

            if "vacation_mode" in sensors:
                mapping[sensors["vacation_mode"]] = "vacation_mode"

            # Rev F64: EV Charging sensors - monitor ALL enabled EV chargers with indexed keys
            if system.get("has_ev_charger", False):
                ev_chargers = cfg.get("ev_chargers", [])
                self.ev_charger_configs = []
                # Phase 7: Separate tracking per sensor type to avoid cross-type collisions
                used_power_sensors: set[str] = set()
                used_soc_sensors: set[str] = set()
                used_plug_sensors: set[str] = set()
                for idx, ev in enumerate(ev_chargers):
                    if ev.get("enabled", True):
                        ev_name = ev.get("name", f"EV {idx + 1}")
                        ev_id = ev.get("id", f"ev_charger_{idx}")
                        active_idx = len(self.ev_charger_configs)
                        self.ev_charger_configs.append(
                            {"index": active_idx, "name": ev_name, "id": ev_id}
                        )
                        # Only map sensors that aren't already used for the same type
                        # This allows same sensor for different types (e.g., one sensor for both power and soc)
                        # but prevents duplicate mappings within the same type
                        if ev.get("sensor") and ev["sensor"] not in used_power_sensors:
                            mapping[ev["sensor"]] = f"ev_kw_{active_idx}"
                            used_power_sensors.add(ev["sensor"])
                        if ev.get("soc_sensor") and ev["soc_sensor"] not in used_soc_sensors:
                            mapping[ev["soc_sensor"]] = f"ev_soc_{active_idx}"
                            used_soc_sensors.add(ev["soc_sensor"])
                        if ev.get("plug_sensor") and ev["plug_sensor"] not in used_plug_sensors:
                            mapping[ev["plug_sensor"]] = f"ev_plug_{active_idx}"
                            used_plug_sensors.add(ev["plug_sensor"])

                # Initialize ev_chargers array upfront with configured EVs
                self.latest_values["ev_chargers"] = [
                    {
                        "name": ec.get("name", f"EV {i + 1}"),
                        "kw": 0.0,
                        "soc": None,
                        "plugged_in": False,
                    }
                    for i, ec in enumerate(self.ev_charger_configs)
                ]
                logger.info(
                    f"✅ Initialized {len(self.ev_charger_configs)} EV chargers for monitoring"
                )
            else:
                self.ev_charger_configs = []
                self.latest_values.pop("ev_chargers", None)

            # Store inversion flags for efficient lookup in _handle_state_change
            self.inversion_flags = {
                "grid_kw": sensors.get("grid_power_inverted", False),
                "battery_kw": sensors.get("battery_power_inverted", False),
            }

            if not mapping:
                logger.warning(
                    "⚠️ No entities configured for HA WebSocket monitoring - check input_sensors in config.yaml"
                )
            else:
                logger.info(
                    f"✅ HA WebSocket monitoring {len(mapping)} entities: {list(mapping.keys())}"
                )
            return mapping
        except Exception as e:
            logger.error(f"Failed to load monitored entities: {e}", exc_info=True)
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
                    logger.debug("DIAG: Entering listen loop")
                    self.stats["connected_at"] = datetime.now(UTC).isoformat()
                    self.stats["disconnected_at"] = None
                    rx_count = 0

                    while self.running:
                        msg = await ws.recv()
                        rx_count += 1
                        self.stats["messages_received"] += 1
                        self.stats["last_message_at"] = datetime.now(UTC).isoformat()

                        data = json.loads(msg)

                        # DIAG(Prob): Log first 5 messages to verify data flow
                        if rx_count <= 5:
                            logger.debug(
                                f"DIAG: WebSocket RX type={data.get('type')} id={data.get('id')} event={data.get('event', {}).get('event_type')}"
                            )

                        # Handle the get_states response
                        if data.get("id") == states_id and data.get("type") == "result":
                            logger.debug(
                                "DIAG: Received get_states result - processing initial states"
                            )
                            results = data.get("result", [])
                            for state in results:
                                entity_id = state.get("entity_id")
                                if entity_id in self.monitored_entities:
                                    self._handle_state_change(entity_id, state)

                            # Run startup synchronization for EV schedules
                            self._sync_ev_schedules_on_startup(results)

                            # Rev F64: Emit initial ev_chargers array after all states processed
                            if self.ev_charger_configs:
                                from backend.events import emit_live_metrics

                                # Initialize ev_chargers if not already done
                                ev_chargers: list[dict[str, Any]] = self.latest_values.get(
                                    "ev_chargers", []
                                )
                                if not ev_chargers:
                                    self.latest_values["ev_chargers"] = ev_chargers = []
                                while len(ev_chargers) < len(self.ev_charger_configs):
                                    ev_chargers.append(
                                        {
                                            "name": self.ev_charger_configs[len(ev_chargers)].get(
                                                "name",
                                                f"EV {len(ev_chargers) + 1}",
                                            ),
                                            "kw": 0.0,
                                            "soc": None,
                                            "plugged_in": False,
                                        }
                                    )

                                total_ev_kw = sum(ev.get("kw", 0.0) for ev in ev_chargers)
                                any_plugged = any(ev.get("plugged_in", False) for ev in ev_chargers)
                                emit_live_metrics(
                                    {
                                        "ev_chargers": self.latest_values["ev_chargers"],
                                        "ev_kw": total_ev_kw,
                                        "ev_plugged_in": any_plugged,
                                    }
                                )
                            continue

                        if data.get("type") == "event":
                            event = data.get("event", {})
                            entity_id = event.get("data", {}).get("entity_id")
                            new_state = event.get("data", {}).get("new_state", {})

                            # DIAG: Log EV state changes for debugging (F50)
                            if entity_id and "ev" in entity_id.lower():
                                logger.debug(
                                    f"Received state_changed for {entity_id} = {new_state.get('state')}, monitored={entity_id in self.monitored_entities}"
                                )

                            if entity_id in self.monitored_entities:
                                self._handle_state_change(entity_id, new_state)

            except Exception as e:
                logger.error(f"HA WebSocket error: {e}")
                await asyncio.sleep(5)

    def _sync_ev_schedules_on_startup(self, results: list[dict[str, Any]]) -> None:
        """Startup sync between HA and the state file for EV charger schedules.

        Runs after the initial get_states response has been received and processed.
        """
        try:
            from datetime import UTC, datetime

            import pytz

            from backend.api.routers.ev import resolve_next_ready_by, sync_goal_to_ha
            from backend.core.ev_state import read_ev_state, write_ev_state

            # Map entity_id -> state dict from the get_states results
            ha_states = {s.get("entity_id"): s for s in results if s.get("entity_id")}

            # Load current state file
            state_data = read_ev_state()

            # Load config to find timezone and ha entities
            cfg = load_yaml("config.yaml")
            timezone_name = cfg.get("timezone", "Europe/Stockholm")
            tz = pytz.timezone(timezone_name)

            ev_chargers: list[dict[str, Any]] = cfg.get("ev_chargers") or []

            for ev in ev_chargers:
                if not ev.get("enabled", True):
                    continue
                charger_id = str(ev.get("id"))

                ha_ready_by_entity: str | None = ev.get("ha_ready_by_entity")
                ha_target_soc_entity: str | None = ev.get("ha_target_soc_entity")

                if not ha_ready_by_entity and not ha_target_soc_entity:
                    continue

                # Check if state file has a goal (i.e. has target_soc_percent)
                charger_state = state_data.get(charger_id, {})
                has_state_goal = (
                    charger_state and charger_state.get("target_soc_percent") is not None
                )

                if not has_state_goal:
                    # Seed state file from HA if HA has valid values
                    ha_soc_val = None
                    if ha_target_soc_entity and ha_target_soc_entity in ha_states:
                        try:
                            val = ha_states[ha_target_soc_entity].get("state")
                            if val not in (None, "unknown", "unavailable", ""):
                                ha_soc_val = int(float(val))
                        except Exception:
                            pass

                    ha_ready_by_dt = None
                    if ha_ready_by_entity and ha_ready_by_entity in ha_states:
                        try:
                            val = ha_states[ha_ready_by_entity].get("state")
                            if val not in (None, "unknown", "unavailable", ""):
                                val_str = str(val).strip()
                                if "-" in val_str:
                                    normalized = val_str.replace(" ", "T")
                                    dt = datetime.fromisoformat(normalized)
                                    if dt.tzinfo is None:
                                        dt = tz.localize(dt)
                                    ha_ready_by_dt = dt
                        except Exception as e:
                            logger.warning(
                                "Failed to parse startup HA ready_by for %s: %s", charger_id, e
                            )

                    # If HA has valid values, seed the goal in state file
                    if ha_soc_val is not None or ha_ready_by_dt is not None:
                        target_soc = ha_soc_val if ha_soc_val is not None else 80

                        if ha_ready_by_dt is not None:
                            ready_by_str = f"{ha_ready_by_dt.hour:02d}:{ha_ready_by_dt.minute:02d}"
                            ready_by_date = ha_ready_by_dt.date().isoformat()
                        else:
                            ready_by_str = "07:00"
                            ready_by_date = None

                        state_data[charger_id] = {
                            "target_soc_percent": target_soc,
                            "ready_by": ready_by_str,
                            "repeat": "none" if ready_by_date else "daily",
                            "ready_by_date": ready_by_date,
                            "keep_on_after_target": False,
                            "source": "ha",
                            "last_updated": datetime.now(UTC).isoformat(),
                        }
                        logger.info(
                            "Startup sync: Seeding state goal for EV %s from HA (target=%s, ready_by=%s)",
                            charger_id,
                            target_soc,
                            ready_by_str,
                        )
                else:
                    # State file already has a goal: push it back to HA to resync
                    target_soc = charger_state.get("target_soc_percent")
                    ready_by = charger_state.get("ready_by")
                    repeat = charger_state.get("repeat")
                    ready_by_date = charger_state.get("ready_by_date")

                    ready_by_dt = (
                        resolve_next_ready_by(
                            ready_by=ready_by,
                            repeat=repeat,
                            ready_by_date=ready_by_date,
                            tz_name=timezone_name,
                        )
                        if ready_by and repeat
                        else None
                    )

                    # Call sync_goal_to_ha in background
                    task = asyncio.create_task(
                        sync_goal_to_ha(
                            charger_id,
                            target_soc,
                            ready_by_dt,
                            ha_target_soc_entity,
                            ha_ready_by_entity,
                        )
                    )
                    self.background_tasks.add(task)
                    task.add_done_callback(self.background_tasks.discard)
                    logger.info(
                        "Startup sync: Pushing state goal for EV %s back to HA to resync",
                        charger_id,
                    )

            write_ev_state(state_data)
        except Exception as e:
            logger.error("Error in EV schedule startup sync: %s", e, exc_info=True)

    def _handle_state_change(self, entity_id: str, new_state: dict[str, Any] | None) -> None:
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

                logger.debug(f"DIAG: Emitting vacation_mode {entity_id}={state_val}")
                emit_ha_entity_change(
                    entity_id=entity_id,
                    state=str(state_val) if state_val is not None else "unknown",
                    attributes=filtered_attrs,
                )
            except Exception as e:
                logger.error(f"Failed to emit vacation_mode change: {e}")
            return

        # Rev F64: Handle EV plug sensor changes - indexed per EV
        if key and key.startswith("ev_plug_"):
            try:
                ev_idx = int(key.split("_")[-1])
                state_val = new_state.get("state", "").lower()
                logger.info(f"EV{ev_idx} plug state changed: {entity_id}={state_val}")

                is_plugged = state_val in ("on", "true", "1", "connected")

                # Initialize ev_chargers data structure if needed
                ev_chargers: list[dict[str, Any]] = self.latest_values.get("ev_chargers", [])
                if not ev_chargers:
                    self.latest_values["ev_chargers"] = ev_chargers = []

                # Ensure we have entries for all configured EVs
                while len(ev_chargers) < len(self.ev_charger_configs):
                    ev_chargers.append(
                        {
                            "name": self.ev_charger_configs[len(ev_chargers)].get(
                                "name", f"EV {len(ev_chargers) + 1}"
                            ),
                            "kw": 0.0,
                            "soc": None,
                            "plugged_in": False,
                        }
                    )

                # Update this EV's plug status
                if ev_idx < len(ev_chargers):
                    ev_chargers[ev_idx]["plugged_in"] = is_plugged

                # Build aggregate for backward compat
                any_plugged = any(ev.get("plugged_in", False) for ev in ev_chargers)

                # Trigger immediate re-plan on plug-in or unplug (Task 7.2/7.3: pass charger ID)
                charger_id = (
                    self.ev_charger_configs[ev_idx].get("id", f"ev_charger_{ev_idx}")
                    if ev_idx < len(self.ev_charger_configs)
                    else f"ev_charger_{ev_idx}"
                )
                if is_plugged:
                    logger.info(
                        f"EV{ev_idx} ({charger_id}) plugged in - triggering immediate re-plan"
                    )
                    self._trigger_ev_replan(charger_id=charger_id, plugged_in=True)
                else:
                    logger.info(
                        f"EV{ev_idx} ({charger_id}) unplugged - triggering immediate re-plan"
                    )
                    self._trigger_ev_replan(charger_id=charger_id, plugged_in=False)

                # Emit entity change event
                from backend.events import emit_ha_entity_change

                emit_ha_entity_change(entity_id=entity_id, state=state_val)

                # Also emit via live_metrics for instant UI response in PowerFlowCard
                from backend.events import emit_live_metrics

                # Emit full ev_chargers array plus aggregate for backward compat
                emit_live_metrics(
                    {
                        "ev_chargers": ev_chargers,
                        "ev_plugged_in": any_plugged,
                    }
                )
            except Exception as e:
                logger.error(f"Failed to handle EV plug change: {e}")
            return

        # Handle EV ready-by and target-SoC changes from HA (HA wins)
        if key and (key.startswith("ev_ready_by_") or key.startswith("ev_target_soc_")):
            try:
                ev_idx = int(key.split("_")[-1])
                charger_id = (
                    self.ev_charger_configs[ev_idx].get("id")
                    if ev_idx < len(self.ev_charger_configs)
                    else None
                )
                if not charger_id:
                    return

                # Debounce check: skip if within 5s of a Darkstar write
                import time

                from backend.core.ev_state import (
                    last_darkstar_write,
                    read_ev_state,
                    write_ev_state,
                )

                last_write = last_darkstar_write.get(charger_id, 0.0)
                if time.time() - last_write < 5.0:
                    logger.debug(
                        "Debounce: skipping HA change event for EV %s within 5s of Darkstar write",
                        charger_id,
                    )
                    return

                state_val = new_state.get("state")
                if state_val in (None, "unknown", "unavailable", "", "None"):
                    return

                # Read current state
                state_data = read_ev_state()
                charger_state = state_data.get(charger_id, {})

                changed = False
                if key.startswith("ev_ready_by_"):
                    raw_str = str(state_val).strip()
                    if "-" in raw_str:
                        normalized = raw_str.replace(" ", "T")
                        try:
                            dt = datetime.fromisoformat(normalized)
                            ready_by_val = f"{dt.hour:02d}:{dt.minute:02d}"
                            if charger_state.get("ready_by") != ready_by_val:
                                charger_state["ready_by"] = ready_by_val
                                changed = True

                            # If repeat is "none" or not set, update ready_by_date
                            if charger_state.get("repeat") == "none":
                                date_val = dt.date().isoformat()
                                if charger_state.get("ready_by_date") != date_val:
                                    charger_state["ready_by_date"] = date_val
                                    changed = True
                        except Exception as e:
                            logger.error("Error parsing ready-by from HA: %s", e)
                elif key.startswith("ev_target_soc_"):
                    try:
                        target_soc = int(float(state_val))
                        if (
                            0 <= target_soc <= 100
                            and charger_state.get("target_soc_percent") != target_soc
                        ):
                            charger_state["target_soc_percent"] = target_soc
                            changed = True
                    except Exception as e:
                        logger.error("Error parsing target SoC from HA: %s", e)

                if changed:
                    # Update source and last_updated
                    charger_state["source"] = "ha"
                    charger_state["last_updated"] = datetime.now(UTC).isoformat()
                    # Make sure other required keys are set
                    if "repeat" not in charger_state:
                        charger_state["repeat"] = "daily"
                    if "keep_on_after_target" not in charger_state:
                        charger_state["keep_on_after_target"] = False

                    state_data[charger_id] = charger_state
                    write_ev_state(state_data)
                    logger.info(
                        "HA state changed - Updated state goal for EV %s: %s",
                        charger_id,
                        charger_state,
                    )

                    # Emit ev_schedule_changed Socket.IO event
                    from backend.core.websockets import ws_manager

                    ws_manager.emit_sync(
                        "ev_schedule_changed", {"charger_id": charger_id, "id": charger_id}
                    )
            except Exception as e:
                logger.error(f"Failed to handle HA EV schedule change: {e}", exc_info=True)
            return

        # Rev F64: Handle EV SoC changes - indexed per EV
        if key and key.startswith("ev_soc_"):
            try:
                ev_idx = int(key.split("_")[-1])
                state_val = new_state.get("state")
                logger.debug(f"EV{ev_idx} SoC updated: {entity_id}={state_val}")

                # Parse SoC value for live metrics
                soc_val = (
                    float(state_val) if state_val not in (None, "unknown", "unavailable") else None
                )

                # Initialize ev_chargers data structure if needed
                ev_chargers: list[dict[str, Any]] = self.latest_values.get("ev_chargers", [])
                if not ev_chargers:
                    self.latest_values["ev_chargers"] = ev_chargers = []

                # Ensure we have entries for all configured EVs
                while len(ev_chargers) < len(self.ev_charger_configs):
                    ev_chargers.append(
                        {
                            "name": self.ev_charger_configs[len(ev_chargers)].get(
                                "name", f"EV {len(ev_chargers) + 1}"
                            ),
                            "kw": 0.0,
                            "soc": None,
                            "plugged_in": False,
                        }
                    )

                # Update this EV's SoC
                if ev_idx < len(ev_chargers):
                    ev_chargers[ev_idx]["soc"] = soc_val

                # Build aggregate ev_kw for backward compat
                total_ev_kw = sum(ev.get("kw", 0.0) for ev in ev_chargers)

                # Emit via live_metrics for UI display
                from backend.events import emit_live_metrics

                emit_live_metrics(
                    {
                        "ev_chargers": ev_chargers,
                        "ev_kw": total_ev_kw,
                    }
                )
            except Exception as e:
                logger.error(f"Failed to handle EV SoC change: {e}")
            return

        # Rev F64: Handle EV power changes - indexed per EV (MUST be before numeric early return)
        if key and key.startswith("ev_kw_"):
            try:
                ev_idx = int(key.split("_")[-1])
                state_val = new_state.get("state")
                logger.debug(f"EV{ev_idx} power updated: {entity_id}={state_val}")

                # Parse numeric value (handle unknown/unavailable gracefully)
                value = 0.0
                if state_val and str(state_val).lower() not in (
                    "unknown",
                    "unavailable",
                    "none",
                    "null",
                    "",
                ):
                    value = float(state_val)
                    # Normalize units if needed (kW vs W)
                    unit = str(
                        new_state.get("attributes", {}).get("unit_of_measurement", "")
                    ).upper()
                    if unit == "W":
                        value = value / 1000.0

                    # Apply inversion if configured
                    if self.inversion_flags.get(key, False):
                        value = -value

                    # Sanitize value (prevent NaN/Inf from crashing JSON transport)
                    import math

                    if math.isnan(value) or math.isinf(value):
                        logger.warning(f"DIAG: Sanitized invalid float for {key}: {value} -> 0.0")
                        value = 0.0

                # Initialize ev_chargers data structure if needed
                ev_chargers: list[dict[str, Any]] = self.latest_values.get("ev_chargers", [])
                if not ev_chargers:
                    self.latest_values["ev_chargers"] = ev_chargers = []

                # Ensure we have entries for all configured EVs
                while len(ev_chargers) < len(self.ev_charger_configs):
                    ev_chargers.append(
                        {
                            "name": self.ev_charger_configs[len(ev_chargers)].get(
                                "name", f"EV {len(ev_chargers) + 1}"
                            ),
                            "kw": 0.0,
                            "soc": None,
                            "plugged_in": False,
                        }
                    )

                # Update this EV's power
                if ev_idx < len(ev_chargers):
                    ev_chargers[ev_idx]["kw"] = value

                # Build aggregate for backward compat
                total_ev_kw = sum(ev.get("kw", 0.0) for ev in ev_chargers)
                any_plugged = any(ev.get("plugged_in", False) for ev in ev_chargers)

                # Emit via live_metrics
                from backend.events import emit_live_metrics

                emit_live_metrics(
                    {
                        "ev_chargers": ev_chargers,
                        "ev_kw": total_ev_kw,
                        "ev_plugged_in": any_plugged,
                    }
                )
            except Exception as e:
                logger.error(f"Failed to handle EV power change: {e}")
            return

        # ARC15: Handle water heater power changes - indexed per heater
        if key and key.startswith("water_kw_"):
            try:
                wh_idx = int(key.split("_")[-1])
                state_val = new_state.get("state")
                logger.debug(f"WH{wh_idx} power updated: {entity_id}={state_val}")

                # Parse numeric value (handle unknown/unavailable gracefully)
                value = 0.0
                if state_val and str(state_val).lower() not in (
                    "unknown",
                    "unavailable",
                    "none",
                    "null",
                    "",
                ):
                    value = float(state_val)
                    # Normalize units if needed (kW vs W)
                    unit = str(
                        new_state.get("attributes", {}).get("unit_of_measurement", "")
                    ).upper()
                    if unit == "W":
                        value = value / 1000.0

                    # Apply inversion if configured
                    if self.inversion_flags.get(key, False):
                        value = -value

                    # Sanitize value (prevent NaN/Inf from crashing JSON transport)
                    import math

                    if math.isnan(value) or math.isinf(value):
                        logger.warning(f"DIAG: Sanitized invalid float for {key}: {value} -> 0.0")
                        value = 0.0

                # Initialize water_heater data structure if needed
                water_heaters: list[dict[str, Any]] = self.latest_values.get("water_heaters", [])
                if not water_heaters:
                    self.latest_values["water_heaters"] = water_heaters = []

                # Ensure we have entries for all configured water heaters
                while len(water_heaters) < len(self.water_heater_configs):
                    water_heaters.append(
                        {
                            "name": self.water_heater_configs[len(water_heaters)].get(
                                "name", f"Water Heater {len(water_heaters) + 1}"
                            ),
                            "kw": 0.0,
                        }
                    )

                # Update this water heater's power
                if wh_idx < len(water_heaters):
                    water_heaters[wh_idx]["kw"] = value

                # Build aggregate for backward compat
                total_wh_kw = sum(wh.get("kw", 0.0) for wh in water_heaters)

                # Emit via live_metrics
                from backend.events import emit_live_metrics

                emit_live_metrics(
                    {
                        "water_heaters": water_heaters,
                        "water_kw": total_wh_kw,
                    }
                )
            except Exception as e:
                logger.error(f"Failed to handle water heater power change: {e}")
            return

        # Handle numeric sensors (existing logic)
        state_val: Any = None
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

            # Sanitize value (prevent NaN/Inf from crashing JSON transport)
            import math

            if math.isnan(value) or math.isinf(value):
                logger.warning(f"DIAG: Sanitized invalid float for {key}: {value} -> 0.0")
                value = 0.0

            # Emit
            payload = {key: value}

            # Synthetic Net Calculation for Dual Meter (REV // UI5)
            if key in ("grid_import_kw", "grid_export_kw"):
                self.latest_values[key] = value
                # Default to 0.0 if one side hasn't been seen yet
                i = self.latest_values.get("grid_import_kw", 0.0)
                e = self.latest_values.get("grid_export_kw", 0.0)
                payload["grid_kw"] = i - e

            # Import here to avoid circular imports at module level
            from backend.events import emit_live_metrics

            # DIAG: Log every emission for now to prove data flow
            logger.debug(f"DIAG: Emitting live_metrics for {key} raw={state_val} val={value}")

            # Include EV plug state if we know it (Rev UI18)
            if "ev_plugged_in" in self.latest_values:
                payload["ev_plugged_in"] = self.latest_values["ev_plugged_in"]

            emit_live_metrics(payload)

            # Update Runtime Stats
            self.stats["metrics_emitted"] += 1
            self.stats["last_emit_at"] = datetime.now(UTC).isoformat()

        except (ValueError, TypeError) as e:
            # Catch parsing errors
            logger.warning(f"DIAG: Failed to parse state for {entity_id} value='{state_val}': {e}")

            # Record error in stats
            err_entry = {
                "time": datetime.now(UTC).isoformat(),
                "type": "parsing_error",
                "entity": entity_id,
                "value": str(state_val),
                "error": str(e),
            }
            self.stats["errors"].append(err_entry)
            # Keep only last 5
            if len(self.stats["errors"]) > 5:
                self.stats["errors"].pop(0)

        finally:
            self.stats["events_processed"] += 1

    def stop(self):
        """Signal the WebSocket client to stop."""
        self.running = False
        logger.info("HA WebSocket client stop requested")

    def start(self):
        self.running = True

        def _run_ws():
            """Thread target with exception handling to prevent silent crashes."""
            try:
                asyncio.run(self.connect())
            except Exception as e:
                logger.error(f"HA WebSocket thread crashed: {e}", exc_info=True)

        logger.info(f"🔗 Connecting to HA WebSocket: {self.url}")
        threading.Thread(target=_run_ws, daemon=True, name="HA-WebSocket").start()

    def reload_monitored_entities(self):
        """Reload the monitored entities mapping from config.yaml and HA params from secrets.yaml."""
        logger.info("Reloading HA configuration...")
        self._load_config()
        self.monitored_entities = self._get_monitored_entities()

    def _trigger_ev_replan(self, charger_id: str | None = None, plugged_in: bool = True):
        """Trigger immediate re-planning for EV state changes (Rev K25 + EVFIX + Task 7.2/7.3).

        Args:
            charger_id: ID of the charger that triggered the replan. When provided,
                checks that specific charger's replan_on_plugin/replan_on_unplug setting.
                Falls back to checking the first enabled charger if not provided.
            plugged_in: True if the EV just plugged in, False if it unplugged.
        """
        try:
            # Check if replan_on_plugin/replan_on_unplug is enabled in config (Rev EVFIX: use ev_chargers[])
            cfg = load_yaml("config.yaml")
            ev_chargers = cfg.get("ev_chargers", [])

            # Task 7.2: Find the specific charger that triggered the replan (or first enabled)
            triggering_ev = None
            if charger_id:
                for ev in ev_chargers:
                    if ev.get("enabled", True) and ev.get("id") == charger_id:
                        triggering_ev = ev
                        break
            if triggering_ev is None:
                # Fallback: first enabled charger
                for ev in ev_chargers:
                    if ev.get("enabled", True):
                        triggering_ev = ev
                        break

            if not triggering_ev:
                logger.debug("No enabled EV charger found, skipping replan")
                return

            if plugged_in:
                if not triggering_ev.get("replan_on_plugin", True):
                    logger.debug(
                        "EV replan on plugin disabled for charger: %s",
                        triggering_ev.get("name", "unknown"),
                    )
                    return
            else:
                if not triggering_ev.get("replan_on_unplug", False):
                    logger.debug(
                        "EV replan on unplug disabled for charger: %s",
                        triggering_ev.get("name", "unknown"),
                    )
                    return

            # Import here to avoid circular imports
            from backend.services.scheduler_service import scheduler_service

            # Task 7.3: Pass charger_id through so get_initial_state can override that
            # specific charger's plug state
            effective_charger_id = charger_id or triggering_ev.get("id")
            logger.info(
                "Triggering immediate EV re-plan for charger %s via scheduler_service (plugged_in=%s)",
                effective_charger_id,
                plugged_in,
            )

            # Rev EVFIX: Use run_coroutine_threadsafe for cross-thread dispatch
            if self.main_loop is None:
                logger.error("Main event loop not set, cannot trigger replan")
                return

            future = asyncio.run_coroutine_threadsafe(
                scheduler_service.trigger_now(
                    ev_plugged_in_override=plugged_in,
                    ev_charger_id_override=effective_charger_id,
                ),
                self.main_loop,
            )

            # Add done callback to log any exceptions
            def _on_replan_done(fut: Any) -> None:
                try:
                    fut.result()
                except Exception as exc:
                    logger.error(f"EV re-plan task failed: {exc}")

            future.add_done_callback(_on_replan_done)

        except Exception as e:
            logger.error(f"Failed to trigger EV re-plan: {e}")


# Global instance
_ha_client = None


def start_ha_socket_client():
    """Start the HA WebSocket client for live sensor updates."""
    global _ha_client
    logger.info("🔌 Starting HA WebSocket client...")
    if _ha_client is None:
        try:
            _ha_client = HAWebSocketClient()
            # Rev EVFIX: Capture main event loop for cross-thread dispatch
            try:
                _ha_client.main_loop = asyncio.get_running_loop()
                logger.debug("Captured main event loop for cross-thread dispatch")
            except RuntimeError:
                logger.warning(
                    "No running event loop - EV replan will not work until loop is available"
                )
            _ha_client.start()
            logger.info("✅ HA WebSocket client initialized")
        except Exception as e:
            logger.error(f"Failed to start HA WebSocket client: {e}", exc_info=True)


def reload_ha_socket_client():
    """Trigger a reload of the monitored entities in the running client."""
    if _ha_client:
        _ha_client.reload_monitored_entities()


def stop_ha_socket_client():
    """Stop the HA WebSocket client."""
    global _ha_client
    if _ha_client is not None:
        _ha_client.stop()
        logger.info("✅ HA WebSocket client stop requested")


def get_ha_socket_status() -> dict[str, Any]:
    """Return diagnostic info about HA WebSocket connection."""
    if _ha_client is None:
        return {"status": "not_started", "monitored_entities": {}}

    # Return full stats for debugging without logs
    return {
        "status": "running" if _ha_client.running else "stopped",
        "url": _ha_client.url,
        "monitored_entities": _ha_client.monitored_entities,
        "stats": _ha_client.stats,
        "config": {
            "has_token": bool(_ha_client.token),
            "token_len": len(_ha_client.token) if _ha_client.token else 0,
        },
    }
