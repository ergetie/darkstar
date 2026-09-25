from __future__ import annotations

import logging
from typing import Any

from backend.core.ev_power import charger_disabled_reason, charger_max_kw, nominal_voltage_v
from backend.core.ha_client import get_ha_sensor_kw_normalized

from .base import DeferrableLoad, LoadType

logger = logging.getLogger("loads")


class LoadDisaggregator:
    """Service to manage controllable loads and separate them from base load."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.loads_registry: dict[str, DeferrableLoad] = {}
        self._ev_charger_ids: set[str] = set()  # REV F76: Track EV charger IDs
        self.metrics = {
            "negative_base_load_count": 0,
            "total_calculations": 0,
            "sensor_failures": 0,
        }
        self._initialize_loads()

    def _initialize_loads(self):
        """Initialize loads from configuration.

        ARC15: Updated to use new entity-centric structure (water_heaters[], ev_chargers[])
        while maintaining backward compatibility with deferrable_loads during transition.
        """
        config_version = self.config.get("config_version", 1)
        input_sensors = self.config.get("input_sensors", {})

        # Check for new entity-centric format (ARC15)
        water_heaters = self.config.get("water_heaters", [])
        ev_chargers = self.config.get("ev_chargers", [])

        if config_version >= 2 and (water_heaters or ev_chargers):
            # Use new entity-centric format
            self._initialize_from_entity_arrays(water_heaters, ev_chargers)
        else:
            # Fall back to legacy deferrable_loads format
            self._initialize_from_deferrable_loads(input_sensors)

    def _initialize_from_entity_arrays(
        self, water_heaters: list[dict[str, Any]], ev_chargers: list[dict[str, Any]]
    ):
        """Initialize loads from new entity-centric arrays (ARC15)."""
        # Ensure input_sensors dict exists in config
        if "input_sensors" not in self.config:
            self.config["input_sensors"] = {}

        # Process water heaters
        for wh in water_heaters:
            if not wh.get("enabled", True):
                logger.debug(f"Skipping disabled water heater: {wh.get('id')}")
                continue

            load_id = wh.get("id")
            if not load_id:
                logger.warning("Found water heater without ID, skipping.")
                continue

            name = wh.get("name", load_id)
            entity_id = wh.get("sensor")
            l_type_str = wh.get("type", "binary")
            nominal_power = wh.get("power_kw", 0.0)

            if not entity_id:
                logger.warning(f"No sensor configured for water heater '{load_id}', skipping.")
                continue

            # Map type string to enum
            try:
                l_type = LoadType(l_type_str)
            except ValueError:
                logger.warning(
                    f"Invalid load type '{l_type_str}' for water heater '{load_id}', defaulting to binary"
                )
                l_type = LoadType.BINARY

            load = DeferrableLoad(
                load_id=load_id,
                name=name,
                sensor_key=entity_id,
                load_type=l_type,
                nominal_power_kw=nominal_power,
            )
            self.register_load(load)
            logger.info(f"Registered water heater from ARC15 config: {load_id}")

        # Process EV chargers
        for ev in ev_chargers:
            if not ev.get("enabled", True):
                logger.debug(f"Skipping disabled EV charger: {ev.get('id')}")
                continue

            load_id = ev.get("id")
            if not load_id:
                logger.warning("Found EV charger without ID, skipping.")
                continue

            name = ev.get("name", load_id)
            entity_id = ev.get("sensor")
            l_type_str = ev.get("type", "binary")
            voltage = nominal_voltage_v(self.config)
            nominal_power = charger_max_kw(ev, voltage)

            if not entity_id:
                logger.warning(f"No sensor configured for EV charger '{load_id}', skipping.")
                continue

            disabled_reason = None
            problem = charger_disabled_reason(ev, voltage)
            if problem is not None:
                disabled_reason, message = problem
                logger.warning(
                    f"EV charger '{load_id}' registered as disabled ({disabled_reason}): {message}"
                )

            # Map type string to enum
            try:
                l_type = LoadType(l_type_str)
            except ValueError:
                logger.warning(
                    f"Invalid load type '{l_type_str}' for EV charger '{load_id}', defaulting to binary"
                )
                l_type = LoadType.BINARY

            load = DeferrableLoad(
                load_id=load_id,
                name=name,
                sensor_key=entity_id,
                load_type=l_type,
                nominal_power_kw=nominal_power,
                disabled_reason=disabled_reason,
            )
            self.register_load(load)
            self._ev_charger_ids.add(load_id)  # REV F76: Track EV charger IDs
            logger.info(f"Registered EV charger from ARC15 config: {load_id}")

            # REV F63: soc_sensor and plug_sensor are read directly from ev_chargers[]
            # in ha_socket.py and inputs.py - no need to add to input_sensors

    def _initialize_from_deferrable_loads(self, input_sensors: dict[str, Any]) -> None:
        """Initialize loads from legacy deferrable_loads format."""
        load_configs = self.config.get("deferrable_loads", [])

        if not load_configs:
            logger.debug("No deferrable_loads configured")
            return

        for lc in load_configs:
            load_id = lc.get("id")
            if not load_id:
                logger.warning("Found deferrable load config without ID, skipping.")
                continue

            name = lc.get("name", load_id)
            sensor_key = lc.get("sensor_key")
            l_type_str = lc.get("type", "variable")
            nominal_power = lc.get("nominal_power_kw", 0.0)

            # Map type string to enum
            try:
                l_type = LoadType(l_type_str)
            except ValueError:
                logger.warning(
                    f"Invalid load type '{l_type_str}' for load '{load_id}', defaulting to variable"
                )
                l_type = LoadType.VARIABLE

            # Use entity ID from input_sensors if sensor_key is a key, else assume it's an entity ID
            entity_id: str | None = input_sensors.get(sensor_key)
            if not entity_id:
                if sensor_key and "." in sensor_key:
                    entity_id = sensor_key
                else:
                    logger.warning(
                        f"No entity ID found for load '{load_id}' with sensor_key '{sensor_key}'"
                    )
                    continue

            # Ensure entity_id is a string for the constructor (Task 8)
            load = DeferrableLoad(
                load_id=load_id,
                name=name,
                sensor_key=str(entity_id),
                load_type=l_type,
                nominal_power_kw=float(nominal_power) if nominal_power else 0.0,
            )
            self.register_load(load)
            logger.debug(f"Registered deferrable load from legacy config: {load_id}")

    def register_load(self, load: DeferrableLoad):
        """Register a load in the disaggregator."""
        self.loads_registry[load.id] = load
        logger.info(f"Registered deferrable load: {load}")

    def get_load_by_id(self, load_id: str) -> DeferrableLoad | None:
        """Retrieve a registered load by its ID."""
        return self.loads_registry.get(load_id)

    def list_active_loads(self) -> list[DeferrableLoad]:
        """Return a list of all registered loads."""
        return list(self.loads_registry.values())

    async def update_current_power(self) -> float:
        """Fetch current power for all loads and return the total controllable load (kW).

        Uses get_ha_sensor_kw_normalized to correctly handle both W-reporting
        and kW-reporting sensors by reading unit_of_measurement from HA.
        """
        total_controllable_kw = 0.0

        for load in self.loads_registry.values():
            try:
                val = await get_ha_sensor_kw_normalized(load.sensor_key)
                if val is None:
                    load.is_healthy = False
                    load.current_power_kw = 0.0
                    self.metrics["sensor_failures"] += 1
                    logger.debug(f"Sensor {load.sensor_key} unavailable for load {load.id}")
                else:
                    load.is_healthy = True
                    load.current_power_kw = val
                    total_controllable_kw += load.current_power_kw
            except Exception as e:
                load.is_healthy = False
                self.metrics["sensor_failures"] += 1
                logger.error(f"Error updating power for load {load.id}: {e}")

        return total_controllable_kw

    def calculate_base_load(self, total_load_kw: float, controllable_kw: float) -> float:
        """
        Calculate base load by deducting controllable load from total load.
        Ensures base load is non-negative and tracks quality metrics.
        """
        self.metrics["total_calculations"] += 1
        base_load_kw = total_load_kw - controllable_kw

        if base_load_kw < -0.1:  # Significant negative drift
            self.metrics["negative_base_load_count"] += 1
            logger.warning(
                f"Negative base load detected: Total={total_load_kw:.3f}kW, "
                f"Controllable={controllable_kw:.3f}kW. Clamping to 0. "
                f"(Drift: {base_load_kw:.3f}kW)"
            )
            base_load_kw = 0.0
        elif base_load_kw < 0:
            base_load_kw = 0.0

        return base_load_kw

    def get_quality_metrics(self) -> dict[str, Any]:
        """Return current disaggregation quality metrics."""
        return {
            "metrics": self.metrics,
            "drift_rate": (
                self.metrics["negative_base_load_count"] / self.metrics["total_calculations"]
                if self.metrics["total_calculations"] > 0
                else 0
            ),
            "sensor_health": {lid: load.is_healthy for lid, load in self.loads_registry.items()},
        }

    def get_total_ev_power(self) -> float:
        """
        REV F76: Calculate total power consumption from all EV chargers.

        Returns:
            Total power in kW from all registered EV chargers.
            Returns 0.0 if no EV chargers are registered.
        """
        total_ev_kw = 0.0
        for ev_id in self._ev_charger_ids:
            load = self.loads_registry.get(ev_id)
            if load:
                total_ev_kw += load.current_power_kw
        return total_ev_kw
