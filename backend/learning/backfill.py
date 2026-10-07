import asyncio
import logging
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import pytz

from backend.core.ha_client import PowerPoint, get_power_history_batch, parse_power_states
from backend.core.slot_energy import (
    SlotEnergy,
    SlotEnergySources,
    build_slot_sources,
    compute_slot_energy,
    isolate_base_load,
)
from backend.learning import get_learning_engine
from backend.measurement_provenance import metadata_object, recording_metadata
from backend.validation import get_max_energy_per_slot, validate_energy_values

# Configure logging
logger = logging.getLogger(__name__)

SLOT_MINUTES = 15
MAX_BACKFILL_DAYS = 10
# A day of high-rate power history for all entities is a large response
HISTORY_TIMEOUT_SECONDS = 60.0


class BackfillEngine:
    """
    Handles backfilling of missing observations from Home Assistant power history.

    Slots are integrated from the same power sensors, with the same sign rules and
    load isolation, as the live recorder.
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = self._load_config(config_path)
        self.engine = get_learning_engine(config_path)
        self.store = self.engine.store
        self.timezone = pytz.timezone(self.config.get("timezone", "Europe/Stockholm"))
        self.learning_config = self.config.get("learning", {})

    def _load_config(self, path: str) -> dict[str, Any]:
        from backend.core.secrets import load_yaml

        return load_yaml(path) or {}

    def _missing_slots(self, last_obs: datetime | None, now: datetime) -> list[datetime]:
        """Completed 15-minute slot starts after the last observation (capped at 10 days)."""
        slot = timedelta(minutes=SLOT_MINUTES)
        earliest = now - timedelta(days=MAX_BACKFILL_DAYS)
        if last_obs is None:
            # Default lookback if empty DB (e.g., 7 days)
            logger.info("No existing observations. Backfilling last 7 days.")
            first = now - timedelta(days=7)
        else:
            first = last_obs + slot
        if first < earliest:
            first = earliest
            logger.warning("Gap too large, capping backfill to last 10 days.")

        # Slot boundaries are UTC-aligned (all real UTC offsets are multiples of 15 minutes)
        slot_seconds = slot.total_seconds()
        first_epoch = -(-first.timestamp() // slot_seconds) * slot_seconds
        last_end_epoch = now.timestamp() // slot_seconds * slot_seconds

        slots: list[datetime] = []
        epoch = first_epoch
        while epoch + slot_seconds <= last_end_epoch:
            slots.append(datetime.fromtimestamp(epoch, tz=pytz.UTC).astimezone(self.timezone))
            epoch += slot_seconds
        return slots

    @staticmethod
    def _value_at(points: list[PowerPoint], moment: datetime) -> float | None:
        """Last value at or before ``moment`` (zero-order hold), None before the first point."""
        index = bisect_right(points, moment, key=lambda point: point[0])
        return points[index - 1][1] if index else None

    def _build_record(
        self,
        sources: SlotEnergySources,
        series: dict[str, list[PowerPoint]],
        soc_points: list[PowerPoint],
        slot_start: datetime,
    ) -> dict[str, Any]:
        slot_end = slot_start + timedelta(minutes=SLOT_MINUTES)
        energy: SlotEnergy = compute_slot_energy(sources, series, slot_start, slot_end)

        # EV / water without history for this slot count as 0 for load isolation.
        ev_kwh = sum(value or 0.0 for value in energy.ev.values())
        water_kwh = sum(value or 0.0 for value in energy.water.values())
        load_kwh = (
            None if energy.load is None else isolate_base_load(energy.load, ev_kwh, water_kwh)
        )

        system = metadata_object(self.config.get("system"))

        def component(
            value: float | None, configured: bool, enabled: bool = True
        ) -> dict[str, str]:
            method = (
                "disabled_zero"
                if not enabled
                else "unconfigured_zero"
                if not configured
                else "power_history"
                if value is not None
                else "unknown"
            )
            return {"method": method, "owner": "backfill"}

        components = {
            "pv": component(energy.pv, bool(sources.pv), bool(system.get("has_solar", True))),
            "import": component(
                energy.import_kwh,
                bool(sources.grid_import if sources.meter_type == "dual" else sources.grid),
            ),
            "export": component(
                energy.export_kwh,
                bool(sources.grid_export if sources.meter_type == "dual" else sources.grid),
            ),
            "load": component(load_kwh, bool(sources.load)),
            "water": component(
                water_kwh, bool(sources.water_heaters), bool(system.get("has_water_heater", True))
            ),
            "ev": component(
                ev_kwh, bool(sources.ev_chargers), bool(system.get("has_ev_charger", False))
            ),
            "battery_charge": component(
                energy.batt_charge, bool(sources.battery), bool(system.get("has_battery", True))
            ),
            "battery_discharge": component(
                energy.batt_discharge, bool(sources.battery), bool(system.get("has_battery", True))
            ),
        }
        for name, device_values in (("ev", energy.ev), ("water", energy.water)):
            configured_devices = self.config.get(
                "ev_chargers" if name == "ev" else "water_heaters", []
            )
            enabled_devices = [item for item in configured_devices if item.get("enabled", True)]
            if configured_devices and not enabled_devices:
                components[name]["method"] = "disabled_zero"
            if components[name]["method"] == "power_history" and any(
                value is None for value in device_values.values()
            ):
                components[name]["method"] = "mixed"
            if components[name]["method"] == "power_history" and any(
                not item.get("sensor") for item in enabled_devices
            ):
                components[name]["method"] = "mixed"
        if components["load"]["method"] == "power_history":
            components["load"]["method"] = (
                "mixed"
                if any(
                    components[name]["method"] in {"mixed", "unknown", "unconfigured_zero"}
                    for name in ("ev", "water")
                )
                else "derived_history"
            )
        recording = recording_metadata(
            self.config,
            components,
            "power_history" if self._value_at(soc_points, slot_end) is not None else "unavailable",
            owner="backfill",
        )

        return {
            "slot_start": slot_start,
            "slot_end": slot_end,
            "pv_kwh": energy.pv,
            "load_kwh": load_kwh,
            "import_kwh": energy.import_kwh,
            "export_kwh": energy.export_kwh,
            "water_kwh": water_kwh,
            "ev_charging_kwh": ev_kwh,
            "batt_charge_kwh": energy.batt_charge,
            "batt_discharge_kwh": energy.batt_discharge,
            "soc_start_percent": self._value_at(soc_points, slot_start),
            "soc_end_percent": self._value_at(soc_points, slot_end),
            "duration_minutes": SLOT_MINUTES,
            "quality_flags": {"source": "backfill", "recording": recording},
        }

    def integrate_slots(
        self,
        sources: SlotEnergySources,
        soc_entity: str | None,
        history: dict[str, list[dict[str, Any]]],
        slot_starts: list[datetime],
    ) -> list[dict[str, Any]]:
        """Integrate one day's batched history into one record per slot (CPU-bound)."""
        series = {entity: parse_power_states(states) for entity, states in history.items()}
        if not any(series.get(entity) for entity in sources.entity_ids()):
            return []
        soc_points = series.get(soc_entity, []) if soc_entity else []

        try:
            max_kwh: float | None = get_max_energy_per_slot(self.config)
        except ValueError as e:
            logger.warning(f"Could not validate energy values: {e}. Proceeding with raw values.")
            max_kwh = None

        records: list[dict[str, Any]] = []
        for slot_start in slot_starts:
            record = self._build_record(sources, series, soc_points, slot_start)
            if max_kwh is not None:
                original_record = record
                record = validate_energy_values(record, max_kwh)
                for field, component_name in {
                    "pv_kwh": "pv",
                    "load_kwh": "load",
                    "import_kwh": "import",
                    "export_kwh": "export",
                    "water_kwh": "water",
                    "ev_charging_kwh": "ev",
                    "batt_charge_kwh": "battery_charge",
                    "batt_discharge_kwh": "battery_discharge",
                }.items():
                    if record.get(field) != original_record.get(field):
                        record["quality_flags"]["recording"]["components"][component_name][
                            "method"
                        ] = "unknown"
            records.append(record)
        return records

    async def run(self) -> None:
        """Run the backfill process asynchronously."""
        logger.info("Starting backfill process...")

        # 1. Sync from Home Assistant (Primary Source)
        try:
            # Check last observation time
            last_obs = await self.store.get_last_observation_time()
            now = datetime.now(self.timezone)

            if last_obs:
                gap = now - last_obs
                if gap < timedelta(minutes=SLOT_MINUTES):
                    logger.info("Data is up to date.")
                    return
                logger.info(f"Found data gap of {gap}. Starting backfill from {last_obs}.")

            slot_starts = self._missing_slots(last_obs, now)
            if not slot_starts:
                logger.info("No completed slots to backfill.")
                return

            # 2. Identify the power entities to fetch (same list as the live recorder)
            sources = build_slot_sources(self.config)
            input_sensors: dict[str, Any] = self.config.get("input_sensors", {}) or {}
            soc_entity: str | None = input_sensors.get("battery_soc") or None
            entities = sources.entity_ids()
            if soc_entity:
                entities.append(soc_entity)
            if not sources.entity_ids():
                logger.warning("No power sensors identified for backfill (input_sensors empty).")
                return

            # 3. One batched history request per local day, integrated per 15-minute slot
            slots_by_day: dict[Any, list[datetime]] = defaultdict(list)
            for slot_start in slot_starts:
                slots_by_day[slot_start.date()].append(slot_start)

            records: list[dict[str, Any]] = []
            for day_slots in slots_by_day.values():
                window_start = day_slots[0]
                window_end = day_slots[-1] + timedelta(minutes=SLOT_MINUTES)
                logger.info(f"Backfilling {window_start} to {window_end}...")
                history = await get_power_history_batch(
                    entities, window_start, window_end, timeout=HISTORY_TIMEOUT_SECONDS
                )
                if history is None:
                    continue
                # CPU-bound, keep it off the event loop
                records.extend(
                    await asyncio.to_thread(
                        self.integrate_slots, sources, soc_entity, history, day_slots
                    )
                )

            if not records:
                logger.warning("No history data found for any sensors.")
                return

            logger.info(f"Generated {len(records)} slots. Storing to DB...")

            # 4. Store
            await self.engine.store_slot_observations(pd.DataFrame(records), authoritative=False)
            logger.info("Backfill complete.")

        except Exception as e:
            logger.error(f"Backfill failed during integration/storage: {e}")
