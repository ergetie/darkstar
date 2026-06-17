import logging
from datetime import datetime, timedelta
from typing import Any

import pytz

from backend.learning import get_learning_engine

# Configure logging
logger = logging.getLogger(__name__)


class BackfillEngine:
    """
    Handles backfilling of missing observations from Home Assistant history and MariaDB.
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = self._load_config(config_path)
        self.engine = get_learning_engine(config_path)
        self.store = self.engine.store
        self.ha_config = self._load_ha_config()
        self.timezone = pytz.timezone(self.config.get("timezone", "Europe/Stockholm"))
        self.learning_config = self.config.get("learning", {})

        # Load secrets for backfill fallback (HA)
        self.secrets = self._load_secrets()

    def _load_config(self, path: str) -> dict[str, Any]:
        from backend.core.secrets import load_yaml

        return load_yaml(path) or {}

    def _load_secrets(self) -> dict[str, Any]:
        from backend.core.secrets import load_yaml

        return load_yaml("secrets.yaml") or {}

    def _load_ha_config(self) -> dict[str, Any]:
        """Load HA config from secrets.yaml"""
        secrets = self._load_secrets()
        return secrets.get("home_assistant", {})

    def _make_ha_headers(self) -> dict[str, str]:
        token = self.ha_config.get("token")
        if not token:
            return {}
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _fetch_history(
        self, entity_id: str, start_time: datetime, end_time: datetime
    ) -> list[tuple[datetime, float]]:
        """Fetch history for a single entity from HA asynchronously."""
        url = self.ha_config.get("url")
        if not url or not entity_id:
            return []

        api_url = f"{url.rstrip('/')}/api/history/period/{start_time.isoformat()}"
        params = {
            "filter_entity_id": entity_id,
            "end_time": end_time.isoformat(),
            "significant_changes_only": False,
            "minimal_response": False,
        }

        try:
            from backend.core.ha_client import get_ha_http_client

            client = get_ha_http_client()
            response = await client.get(
                api_url, headers=self._make_ha_headers(), params=params, timeout=60.0
            )
            response.raise_for_status()
            data = response.json()

            if not data or not data[0]:
                return []

            history: list[tuple[datetime, float]] = []
            state_item: dict[str, Any]
            for state_item in data[0]:
                try:
                    ts = datetime.fromisoformat(state_item["last_changed"])
                    val = float(state_item["state"])
                    history.append((ts, val))
                except (ValueError, TypeError, KeyError):
                    continue
            return history

        except Exception as e:
            logger.error(f"Failed to fetch history for {entity_id}: {e}")
            return []

    async def run(self) -> None:
        """Run the backfill process asynchronously."""
        logger.info("Starting backfill process...")

        # 1. Sync from Home Assistant (Primary Source)
        try:
            # Check last observation time
            last_obs = await self.store.get_last_observation_time()
            now = datetime.now(self.timezone)

            # Default lookback if empty DB (e.g., 7 days)
            if not last_obs:
                logger.info("No existing observations. Backfilling last 7 days.")
                start_time = now - timedelta(days=7)
            else:
                # Check gap
                gap = now - last_obs
                if gap < timedelta(minutes=15):
                    logger.info("Data is up to date.")
                    return

                logger.info(f"Found data gap of {gap}. Starting backfill from {last_obs}.")
                start_time = last_obs

            # Cap backfill to 10 days to avoid overloading HA
            if (now - start_time) > timedelta(days=10):
                start_time = now - timedelta(days=10)
                logger.warning("Gap too large, capping backfill to last 10 days.")

            # 2. Identify sensors to fetch
            # REV // F26: Fallback to input_sensors if sensor_map is empty
            raw_map_source: dict[str, str] | None = self.learning_config.get("sensor_map")
            raw_map: dict[str, str] = raw_map_source or {}
            if not raw_map:
                logger.info("sensor_map is empty. Auto-detecting from config...")
                input_sensors = self.config.get("input_sensors", {})
                raw_map = {}
                # Map cumulative sensors (ARC15: water heater sensors now in water_heaters[])
                mapping = {
                    "total_grid_import": "import",
                    "total_grid_export": "export",
                    "total_pv_production": "pv",
                    "total_load_consumption": "load",
                    "battery_soc": "soc",
                }
                for config_key, canonical in mapping.items():
                    entity_id = input_sensors.get(config_key)
                    if entity_id:
                        raw_map[entity_id] = canonical

                for ev_charger in self.config.get("ev_chargers", []):
                    if ev_charger.get("enabled", True) and ev_charger.get("sensor"):
                        raw_map[str(ev_charger["sensor"])] = "ev_charging"

                if self.config.get("system", {}).get("has_water_heater", True):
                    for water_heater in self.config.get("water_heaters", []):
                        if water_heater.get("enabled", True) and water_heater.get("sensor"):
                            raw_map[str(water_heater["sensor"])] = "water"

            if not raw_map:
                logger.warning(
                    "No sensors identified for backfill (sensor_map and input_sensors empty)."
                )
                return

            cumulative_data: dict[str, list[tuple[datetime, float]]] = {}
            controllable_power_data: dict[str, list[tuple[datetime, float]]] = {}
            count = 0
            for entity_id_str, canonical_str in raw_map.items():
                logger.info(f"Backfilling {canonical_str} ({entity_id_str})...")
                history = await self._fetch_history(entity_id_str, start_time, now)
                if history:
                    self.engine.sensor_map[str(entity_id_str).lower()] = canonical_str
                    if canonical_str in {"ev_charging", "water"}:
                        controllable_power_data[entity_id_str] = history
                    else:
                        cumulative_data[entity_id_str] = history
                    count += len(history)

            if not cumulative_data and not controllable_power_data:
                logger.warning("No history data found for any sensors.")
                return

            logger.info(f"Fetched {count} data points. Processing into slots...")

            # 3. ETL to slots (CPU-bound, wrap in to_thread for 100% production grade)
            import asyncio

            df = await asyncio.to_thread(
                self.engine.etl_cumulative_to_slots, cumulative_data, controllable_power_data
            )

            if df.empty:
                logger.warning("ETL produced empty DataFrame.")
                return

            logger.info(f"Generated {len(df)} slots. Storing to DB...")

            # 4. Store
            await self.engine.store_slot_observations(df, authoritative=False)
            logger.info("Backfill complete.")

        except Exception as e:
            logger.error(f"Backfill failed during ETL/Storage: {e}")
