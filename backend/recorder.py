"""Slot observation recorder.

Column ownership for ``slot_observations``:

| Owner | Columns | Meaning |
| --- | --- | --- |
| Recorder | energy columns, price columns | Slot-aligned measurements; ``load_kwh`` is base load after EV/water subtraction. |
| Executor | ``executed_action`` | Action summary for the slot, keyed by ``slot_start``. |

No column is intentionally written by both owners.
"""

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytz
import yaml

from backend.core.ha_client import (
    _normalize_energy_to_kwh,  # pyright: ignore[reportPrivateUsage]
    gather_sensor_reads,
    get_energy_from_power_history,
    get_ha_entity_state,
    get_ha_sensor_float,
    get_ha_sensor_kw_normalized,
)
from backend.core.prices import get_current_slot_prices
from backend.learning.backfill import BackfillEngine

# Local imports
from backend.learning.store import LearningStore
from backend.loads.service import LoadDisaggregator
from backend.validation import get_max_energy_per_slot, validate_energy_values

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("recorder")


class RecorderStateStore:
    """Manages JSON persistence of meter readings for delta-based energy calculation.

    Stores last seen cumulative meter values and timestamps to calculate energy
    deltas between 15-minute observation slots.
    """

    def __init__(
        self,
        state_file: Path | str = "data/recorder_state.json",
        max_meter_delta_kwh: float = 50.0,
    ):
        self.state_file = Path(state_file)
        self.max_meter_delta_kwh = max_meter_delta_kwh
        self._state: dict[str, Any] = {}
        self._ensure_directory()

    def _ensure_directory(self) -> None:
        """Ensure the state file directory exists."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        """Load state from JSON file. Returns empty dict if file doesn't exist or is corrupted."""
        try:
            if self.state_file.exists():
                with self.state_file.open("r", encoding="utf-8") as f:
                    self._state = json.load(f)
                    logger.debug(f"Loaded recorder state from {self.state_file}")
                    return self._state
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load state file ({e}), starting fresh")
            # If corrupted, remove the file to start fresh
            with contextlib.suppress(OSError):
                self.state_file.unlink()

        self._state = {}
        return self._state

    def save(self) -> None:
        """Save current state to JSON file."""
        try:
            self._ensure_directory()
            with self.state_file.open("w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2)
            logger.debug(f"Saved recorder state to {self.state_file}")
        except OSError as e:
            logger.error(f"Failed to save state file: {e}")

    def get_delta(
        self,
        key: str,
        current_value: float,
        timestamp: datetime,
        sensor_timestamp: datetime | None = None,
        target_seconds: float = 900.0,
    ) -> tuple[float | None, bool]:
        """Calculate delta between current and previous meter reading.

        When *sensor_timestamp* (the HA ``last_updated`` time) is supplied,
        the raw delta is scaled proportionally so that it represents exactly
        *target_seconds* of energy (default 900 s = 15 min).  This corrects
        the sawtooth artifact caused by sensor-update and recorder cycles
        running at different frequencies.

        Args:
            key: Unique identifier for this meter (e.g., 'total_pv_production')
            current_value: Current meter reading
            timestamp: Current timestamp (recorder time)
            sensor_timestamp: HA sensor's last_updated time (optional)
            target_seconds: Target time span for scaling (default 900 = 15 min)

        Returns:
            Tuple of (delta_value, is_valid):
            - delta_value: Energy delta in kWh, or None if no previous state
            - is_valid: False if meter reset detected (negative delta)
        """
        previous = self._state.get(key, {})
        previous_value = previous.get("value")
        previous_sensor_ts_str = previous.get("sensor_timestamp")

        # -- persist new state ------------------------------------------------
        new_entry: dict[str, Any] = {
            "value": current_value,
            "timestamp": timestamp.isoformat(),
        }
        if sensor_timestamp is not None:
            new_entry["sensor_timestamp"] = sensor_timestamp.isoformat()

        # No previous state - can't calculate delta
        if previous_value is None:
            logger.debug(f"No previous state for {key}, storing initial value")
            self._state[key] = new_entry
            self.save()
            return None, True

        # Calculate delta
        try:
            delta = current_value - float(previous_value)
        except (TypeError, ValueError):
            logger.warning(f"Invalid previous value for {key}: {previous_value}")
            self._state[key] = new_entry
            self.save()
            return None, True

        # Check for meter reset (negative delta)
        if delta < 0:
            logger.warning(
                f"Meter reset detected for {key}: {previous_value} -> {current_value} "
                f"(delta={delta:.3f} kWh). Using fallback."
            )
            self._state[key] = new_entry
            self.save()
            return None, False

        # -- time-proportional scaling ----------------------------------------
        # Without this, deltas alternate between ~10 min and ~20 min of real
        # production when sensors update every 10 min but we record every 15.
        if delta > 0 and sensor_timestamp is not None and previous_sensor_ts_str is not None:
            try:
                prev_sensor_ts = datetime.fromisoformat(previous_sensor_ts_str)
                actual_seconds = (sensor_timestamp - prev_sensor_ts).total_seconds()
                # Only scale within a sane window (5 min - 60 min).
                # Outside that range (restarts, long gaps) raw delta is safer.
                if 300 <= actual_seconds <= 3600:
                    scaled_delta = delta * (target_seconds / actual_seconds)
                    logger.debug(
                        f"{key}: scaled {delta:.3f} kWh over {actual_seconds:.0f}s "
                        f"to {scaled_delta:.3f} kWh over {target_seconds:.0f}s"
                    )
                    delta = scaled_delta
            except (ValueError, TypeError):
                pass  # keep raw delta on parse errors

        # Reject physically-implausible spikes (e.g. sensor glitch) instead of
        # recording them as energy. Mirrors the negative-delta path: advance
        # the baseline so the next reading computes a correct delta.
        if delta > self.max_meter_delta_kwh:
            logger.warning(
                f"Implausible meter delta for {key}: {delta:.1f} kWh > ceiling "
                f"({self.max_meter_delta_kwh:.1f} kWh)"
            )
            self._state[key] = new_entry
            self.save()
            return None, False

        self._state[key] = new_entry
        self.save()

        return delta, True

    def get_last_timestamp(self, key: str) -> datetime | None:
        """Get the timestamp of the last reading for a given key."""
        previous = self._state.get(key, {})
        timestamp_str = previous.get("timestamp")
        if timestamp_str:
            try:
                return datetime.fromisoformat(timestamp_str)
            except ValueError:
                pass
        return None


def _load_config() -> dict[str, Any]:
    try:
        with Path("config.yaml").open(encoding="utf-8") as f:
            result: Any = yaml.safe_load(f)
            if isinstance(result, dict):
                return result  # type: ignore[return-value]
            return {}
    except FileNotFoundError:
        return {}


async def record_observation_from_current_state(
    config: dict[str, Any] | None = None,
    disaggregator: LoadDisaggregator | None = None,
    state_store: RecorderStateStore | None = None,
):
    """Capture current system state and store as an observation."""
    if not config:
        config = _load_config()
    db_path = config.get("learning", {}).get("sqlite_path", "data/planner_learning.db")
    tz_name = config.get("timezone", "Europe/Stockholm")
    tz = pytz.timezone(tz_name)

    # Initialize store (in-place initialization is acceptable for the standalone script)
    store = LearningStore(db_path, tz)

    # Initialize state store for cumulative energy tracking
    if state_store is None:
        max_meter_delta_kwh = float(config.get("recorder", {}).get("max_meter_delta_kwh", 50.0))
        state_store = RecorderStateStore(max_meter_delta_kwh=max_meter_delta_kwh)
        state_store.load()

    # Identify the just-finished 15-minute slot from the wall clock.
    now = datetime.now(tz)
    minute_block = (now.minute // 15) * 15
    slot_end = now.replace(minute=minute_block, second=0, microsecond=0)
    slot_start = slot_end - timedelta(minutes=15)

    # Gather Data
    input_sensors = config.get("input_sensors", {})

    # Helper to get sensor value and convert W to kW if needed.
    # Uses get_ha_sensor_kw_normalized which reads unit_of_measurement from HA
    # and only divides by 1000 when the sensor reports in Watts.
    # This correctly handles both W-reporting (most inverters) and
    # kW-reporting (Fronius SolarNet) sensors automatically.
    async def get_kw(key: str, default: float = 0.0) -> float:
        entity = input_sensors.get(key)
        if not entity:
            return default
        val = await get_ha_sensor_kw_normalized(str(entity))
        if val is None:
            return default
        return val

    # Helper to get cumulative energy sensor value and timestamp
    async def get_cumulative_kwh(key: str) -> tuple[float | None, datetime | None]:
        """Fetch cumulative energy sensor value in kWh and its HA timestamp.

        Returns:
            Tuple of (kwh_value, sensor_timestamp) where sensor_timestamp is
            the HA entity's last_updated time for time-proportional scaling.
        """
        entity = input_sensors.get(key)
        if not entity:
            return None, None
        return await get_cumulative_kwh_for_entity(str(entity))

    async def get_cumulative_kwh_for_entity(entity_id: str) -> tuple[float | None, datetime | None]:
        """Fetch cumulative energy sensor value in kWh and its HA timestamp by entity ID.

        Args:
            entity_id: The Home Assistant entity ID to fetch

        Returns:
            Tuple of (kwh_value, sensor_timestamp) where sensor_timestamp is
            the HA entity's last_updated time for time-proportional scaling.
        """
        try:
            # Fetch full state to get both value and unit_of_measurement
            state = await get_ha_entity_state(entity_id)
            if not state:
                return None, None

            raw_value = state.get("state")
            if raw_value in (None, "unknown", "unavailable"):
                return None, None

            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                return None, None

            # Get unit of measurement for normalization (handles Wh, kWh, MWh)
            attributes = state.get("attributes", {})
            unit = attributes.get("unit_of_measurement")

            # Normalize to kWh
            kwh = _normalize_energy_to_kwh(value, unit)

            # Extract the sensor's own timestamp for time-proportional scaling
            sensor_ts: datetime | None = None
            for ts_key in ("last_updated", "last_changed"):
                ts_str = state.get(ts_key)
                if ts_str:
                    try:
                        sensor_ts = datetime.fromisoformat(ts_str)
                        break
                    except (ValueError, TypeError):
                        continue

            return kwh, sensor_ts
        except Exception:
            return None, None

    # Grid Metering Logic (REV // UI5)
    meter_type = config.get("system", {}).get("grid_meter_type", "net")

    # Build batch of independent power sensor reads (Current Power State Snapshot)
    power_reads: list[tuple[str, Any]] = [
        ("pv_power", lambda: get_kw("pv_power")),
        ("load_power", lambda: get_kw("load_power")),
        ("battery_power", lambda: get_kw("battery_power")),
    ]

    # Collect water heater sensor reads (ARC15: read from water_heaters[] array)
    water_heater_sensors: list[str] = []
    if config.get("system", {}).get("has_water_heater", True):
        for water_heater in config.get("water_heaters", []):
            if water_heater.get("enabled", True):
                sensor = water_heater.get("sensor")
                if sensor:
                    water_heater_sensors.append(str(sensor))
                    power_reads.append(
                        (f"wh_{sensor}", lambda s=str(sensor): get_ha_sensor_kw_normalized(s))
                    )
    if meter_type == "dual":
        power_reads.append(("grid_import_power", lambda: get_kw("grid_import_power")))
        power_reads.append(("grid_export_power", lambda: get_kw("grid_export_power")))
    else:
        power_reads.append(("grid_power", lambda: get_kw("grid_power")))

    # Collect EV charger sensor reads into the batch
    ev_charger_sensors: list[str] = []
    if config.get("system", {}).get("has_ev_charger", False):
        ev_chargers = config.get("ev_chargers", [])
        for ev_charger in ev_chargers:
            if ev_charger.get("enabled", True):
                sensor = ev_charger.get("sensor")
                if sensor:
                    ev_charger_sensors.append(str(sensor))
                    power_reads.append(
                        (f"ev_{sensor}", lambda s=str(sensor): get_ha_sensor_kw_normalized(s))
                    )

    power_results = await gather_sensor_reads(power_reads, context="recorder_observation")

    pv_kw: float = power_results.get("pv_power") or 0.0
    total_load_kw: float = power_results.get("load_power") or 0.0
    battery_kw: float = power_results.get("battery_power") or 0.0

    # Disaggregate loads if disaggregator is provided (REV // ML2)
    controllable_kw = 0.0
    if disaggregator:
        controllable_kw = await disaggregator.update_current_power()
        load_kw = disaggregator.calculate_base_load(total_load_kw, controllable_kw)
        logger.info(
            f"Disaggregation: Total={total_load_kw:.3f}kW, Controllable={controllable_kw:.3f}kW -> Base={load_kw:.3f}kW"
        )
    else:
        load_kw = total_load_kw

    import_kw: float = 0.0
    export_kw: float = 0.0
    grid_net_kw: float = 0.0

    if meter_type == "dual":
        import_kw = power_results.get("grid_import_power") or 0.0
        export_kw = power_results.get("grid_export_power") or 0.0
    else:
        grid_net_kw = power_results.get("grid_power") or 0.0
        import_kw = max(0.0, grid_net_kw)
        export_kw = max(0.0, -grid_net_kw)

    # Apply inversion flags if configured (REV F55)
    input_sensors = config.get("input_sensors", {})
    if input_sensors.get("battery_power_inverted", False):
        battery_kw = -battery_kw
        logger.debug(f"Applied battery_power_inverted: {battery_kw:.3f}kW")

    # Handle grid inversion for net meter type
    if meter_type == "net" and input_sensors.get("grid_power_inverted", False):
        grid_net_kw = -grid_net_kw
        import_kw = max(0.0, grid_net_kw)
        export_kw = max(0.0, -grid_net_kw)
        logger.debug(f"Applied grid_power_inverted: net={grid_net_kw:.3f}kW")

    # Calculate Energy for the 15m slot
    # Try cumulative energy sensors first, fallback to power snapshot method
    async def calculate_energy_from_cumulative(
        cumulative_key: str, power_kw: float, state_key: str
    ) -> tuple[float, bool]:
        """Calculate energy using cumulative sensor with fallback to power snapshot.

        Returns:
            Tuple of (energy_kwh, used_cumulative):
            - energy_kwh: Calculated energy in kWh
            - used_cumulative: True if cumulative sensor was used, False if fallback
        """
        cumulative, sensor_ts = await get_cumulative_kwh(cumulative_key)
        if cumulative is not None:
            delta, is_valid = state_store.get_delta(
                state_key, cumulative, now, sensor_timestamp=sensor_ts
            )
            if delta is not None and is_valid:
                logger.debug(f"Using cumulative {cumulative_key}: delta={delta:.3f} kWh")
                return delta, True
            elif not is_valid:
                # Meter reset detected, use fallback
                logger.warning(f"Meter reset for {cumulative_key}, using power snapshot")

        # Fallback to power snapshot
        return power_kw * 0.25, False

    # Calculate PV energy
    pv_kwh, _ = await calculate_energy_from_cumulative("total_pv_production", pv_kw, "pv_total")

    # Calculate load energy
    load_kwh, used_cumulative_load = await calculate_energy_from_cumulative(
        "total_load_consumption", load_kw, "load_total"
    )

    # Calculate import energy (only if dual meter or using cumulative)
    import_kwh: float
    export_kwh: float

    if meter_type == "dual":
        # For dual meters, calculate import and export separately
        import_kwh, _ = await calculate_energy_from_cumulative(
            "total_grid_import", import_kw, "grid_import_total"
        )
        export_kwh, _ = await calculate_energy_from_cumulative(
            "total_grid_export", export_kw, "grid_export_total"
        )
    else:
        # For net meter, try to get cumulative import and export if available
        import_cumulative, import_ts = await get_cumulative_kwh("total_grid_import")
        export_cumulative, export_ts = await get_cumulative_kwh("total_grid_export")

        if import_cumulative is not None and export_cumulative is not None:
            # Use cumulative sensors for both
            import_delta, import_valid = state_store.get_delta(
                "grid_import_total", import_cumulative, now, sensor_timestamp=import_ts
            )
            export_delta, export_valid = state_store.get_delta(
                "grid_export_total", export_cumulative, now, sensor_timestamp=export_ts
            )

            if import_delta is not None and import_valid:
                import_kwh = import_delta
            else:
                import_kwh = import_kw * 0.25
                if not import_valid:
                    logger.warning("Import meter reset detected, using power snapshot")

            if export_delta is not None and export_valid:
                export_kwh = export_delta
            else:
                export_kwh = export_kw * 0.25
                if not export_valid:
                    logger.warning("Export meter reset detected, using power snapshot")
        else:
            # Fallback to net power calculation
            import_kwh = import_kw * 0.25
            export_kwh = export_kw * 0.25

    # Calculate EV charging energy using power history API
    ev_charging_kwh = 0.0
    ev_charger_energy: dict[str, float] = {}  # Task 8.1: per-device recording
    if config.get("system", {}).get("has_ev_charger", False):
        ev_chargers = config.get("ev_chargers", [])
        for ev_charger in ev_chargers:
            if ev_charger.get("enabled", True):
                sensor = ev_charger.get("sensor")
                charger_id = str(ev_charger.get("id", ""))
                if sensor:
                    energy = await get_energy_from_power_history(str(sensor), slot_start, slot_end)
                    if energy is not None:
                        ev_charging_kwh += energy
                        if charger_id:
                            ev_charger_energy[charger_id] = energy
                        logger.debug(f"EV {charger_id}: history energy={energy:.3f} kWh")
                    else:
                        charger_power = power_results.get(f"ev_{sensor}") or 0.0
                        device_kwh = charger_power * 0.25
                        ev_charging_kwh += device_kwh
                        if charger_id:
                            ev_charger_energy[charger_id] = device_kwh
                        logger.debug(f"EV {charger_id}: snapshot fallback={device_kwh:.3f} kWh")

    # Calculate water heater energy using power history API
    water_kwh = 0.0
    water_heater_energy: dict[str, float] = {}  # Task 8.1: per-device recording
    for water_heater in config.get("water_heaters", []):
        if water_heater.get("enabled", True):
            sensor = water_heater.get("sensor")
            heater_id = str(water_heater.get("id", ""))
            if sensor:
                energy = await get_energy_from_power_history(str(sensor), slot_start, slot_end)
                if energy is not None:
                    water_kwh += energy
                    if heater_id:
                        water_heater_energy[heater_id] = energy
                    logger.debug(f"Water {heater_id}: history energy={energy:.3f} kWh")
                else:
                    heater_power = power_results.get(f"wh_{sensor}") or 0.0
                    device_kwh = heater_power * 0.25
                    water_kwh += device_kwh
                    if heater_id:
                        water_heater_energy[heater_id] = device_kwh
                    logger.debug(f"Water {heater_id}: snapshot fallback={device_kwh:.3f} kWh")

    # Isolate base load: subtract known deferrable loads from total load.
    # Apply when load represents total consumption (cumulative sensor, or power snapshot without
    # disaggregator). Skip when disaggregator already provided base-load-only power_kw.
    if (used_cumulative_load or not disaggregator) and (ev_charging_kwh > 0 or water_kwh > 0):
        base_load_kwh = load_kwh - ev_charging_kwh - water_kwh
        if base_load_kwh < 0:
            logger.warning(
                f"Negative base load: total={load_kwh:.3f}kWh, EV={ev_charging_kwh:.3f}kWh, "
                f"water={water_kwh:.3f}kWh. Clamping to 0."
            )
            base_load_kwh = 0.0
        load_kwh = base_load_kwh

    # Standard inverter convention: positive = discharge, negative = charge
    discharge_power_kw = battery_kw if battery_kw > 0 else 0.0
    charge_power_kw = abs(battery_kw) if battery_kw < 0 else 0.0

    batt_discharge_kwh, _ = await calculate_energy_from_cumulative(
        "total_battery_discharge", discharge_power_kw, "battery_discharge_total"
    )
    batt_charge_kwh, _ = await calculate_energy_from_cumulative(
        "total_battery_charge", charge_power_kw, "battery_charge_total"
    )

    # Battery
    soc_entity = input_sensors.get("battery_soc")
    soc_percent = None
    if soc_entity:
        soc_percent = await get_ha_sensor_float(soc_entity)

    if soc_percent is None:
        # Fallback: Try to get last known SoC from DB
        cached_soc = await store.get_system_state("last_known_soc")
        if cached_soc and soc_entity:
            try:
                soc_percent = float(cached_soc)
                logger.warning(
                    f"Battery SoC sensor ({soc_entity}) unavailable. "
                    f"Using last known value: {soc_percent:.1f}%"
                )
            except ValueError:
                logger.error(
                    f"Cached SoC value is corrupted: '{cached_soc}'. "
                    "Cannot use fallback. Skipping observation."
                )
                soc_percent = None

        if soc_percent is None and soc_entity:
            logger.warning(
                f"Battery SoC sensor ({soc_entity}) unavailable and no valid cached value. "
                "Skipping observation record."
            )
            await store.close()
            return
    else:
        # Valid SoC obtained - update cache
        await store.set_system_state("last_known_soc", str(soc_percent))

    # Fetch Price Data (REV // Complete Cost Reality Fix)
    prices = await get_current_slot_prices(config)
    import_price = prices.get("import_price_sek_kwh") if prices else None
    export_price = prices.get("export_price_sek_kwh") if prices else None

    if prices:
        logger.info(f"Price data fetched: Import={import_price:.4f}, Export={export_price:.4f}")
    else:
        logger.warning("Failed to fetch price data for current observation")

    # Construct Record
    record = {
        "slot_start": slot_start,
        "slot_end": slot_end,
        "pv_kwh": pv_kwh,
        "load_kwh": load_kwh,
        "import_kwh": import_kwh,
        "export_kwh": export_kwh,
        "water_kwh": water_kwh,  # Task 8.3: aggregate preserved for backward compat
        "water_heater_energy": water_heater_energy if water_heater_energy else None,  # Task 8.2
        "ev_charging_kwh": ev_charging_kwh,
        "ev_charger_energy": ev_charger_energy if ev_charger_energy else None,
        "batt_charge_kwh": batt_charge_kwh,
        "batt_discharge_kwh": batt_discharge_kwh,
        "soc_end_percent": soc_percent,
        "import_price_sek_kwh": import_price,
        "export_price_sek_kwh": export_price,
        "created_at": datetime.now(UTC).isoformat(),
    }

    logger.info(
        f"Recording observation for {slot_start}: SOC={soc_percent}% "
        f"PV={pv_kwh:.3f}kWh Load={load_kwh:.3f}kWh Water={water_kwh:.3f}kWh "
        f"EV={ev_charging_kwh:.3f}kWh Bat={battery_kw:.3f}kW"
    )

    # Validate energy values before storage
    try:
        max_kwh = get_max_energy_per_slot(config)
        record = validate_energy_values(record, max_kwh)
    except ValueError as e:
        logger.warning(f"Could not validate energy values: {e}. Proceeding with raw values.")

    # Store
    df = pd.DataFrame([record])
    await store.store_slot_observations(df)
    await store.close()  # Clean up async engine connections


async def _sleep_until_next_quarter() -> None:
    """Sleep until the next 15-minute boundary (UTC-based)."""
    now = datetime.now(UTC)
    minute_block = (now.minute // 15) * 15
    current_slot = now.replace(minute=minute_block, second=0, microsecond=0)
    next_slot = current_slot + timedelta(minutes=15)
    sleep_seconds = max(5.0, (next_slot - now).total_seconds())
    await asyncio.sleep(sleep_seconds)


async def backfill_missing_prices():
    """Backfill missing price data for historical observations."""
    try:
        from backend.core.prices import get_nordpool_data

        config = _load_config()
        db_path = config.get("learning", {}).get("sqlite_path", "data/planner_learning.db")
        tz_name = config.get("timezone", "Europe/Stockholm")
        tz = pytz.timezone(tz_name)

        store = LearningStore(db_path, tz)
        observations = await store.get_history_range(
            datetime.now(tz) - timedelta(days=30), datetime.now(tz)
        )

        missing_any = any(obs.get("import_price_sek_kwh") is None for obs in observations)
        if not missing_any:
            logger.info("[recorder] No missing prices to backfill.")
            await store.close()
            return

        logger.info("[recorder] Backfilling missing prices...")
        price_data = await get_nordpool_data()
        if not price_data:
            logger.error("[recorder] Failed to fetch price data for backfill.")
            await store.close()
            return

        indexed_prices = {p["start_time"]: p for p in price_data}
        updated_count = 0

        for obs in observations:
            if obs.get("import_price_sek_kwh") is None:
                slot_start_raw = obs["slot_start"]
                if isinstance(slot_start_raw, str):
                    slot_start = datetime.fromisoformat(slot_start_raw)
                else:
                    slot_start = slot_start_raw

                if slot_start.tzinfo is None:
                    slot_start = tz.localize(slot_start)
                else:
                    slot_start = slot_start.astimezone(tz)

                # Round to nearest 15/60 min boundary if needed, but get_nordpool_data handles it
                # We need exact match or closest previous
                price_slot = indexed_prices.get(slot_start)
                if price_slot:
                    obs["import_price_sek_kwh"] = price_slot["import_price_sek_kwh"]
                    obs["export_price_sek_kwh"] = price_slot["export_price_sek_kwh"]
                    updated_count += 1

        if updated_count > 0:
            # We need a way to update specific observations.
            # store.store_slot_prices handles upsert by slot_start.
            # Convert back to list of dicts with required fields
            rows_to_update = [
                {
                    "slot_start": obs["slot_start"],
                    "import_price_sek_kwh": obs["import_price_sek_kwh"],
                    "export_price_sek_kwh": obs["export_price_sek_kwh"],
                }
                for obs in observations
                if obs.get("import_price_sek_kwh") is not None
            ]
            await store.store_slot_prices(rows_to_update)
            logger.info(f"[recorder] Backfilled {updated_count} observation prices.")

        await store.close()
    except Exception as e:
        logger.error(f"[recorder] Price backfill failed: {e}")
        import traceback

        traceback.print_exc()


async def main() -> int:
    """Background recorder loop: capture observations every 15 minutes."""
    logger.info("[recorder] Starting live observation recorder (15m cadence)")

    config = _load_config()

    # Run backfill on startup
    try:
        # BackfillEngine.run is now async.
        backfill = BackfillEngine()
        await backfill.run()
    except Exception as e:
        logger.warning("[recorder] Backfill failed: %s", e)

    # Run Price Backfill on startup
    await backfill_missing_prices()

    # Initialize disaggregator (REV // ML2)
    disaggregator = LoadDisaggregator(config)

    while True:
        try:
            await record_observation_from_current_state(config, disaggregator)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("[recorder] Error while recording observation: %s", exc)

        await _sleep_until_next_quarter()


if __name__ == "__main__":
    import contextlib

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
