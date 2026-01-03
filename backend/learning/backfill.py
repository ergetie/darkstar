import logging
from datetime import datetime, timedelta

import pytz
import requests
import yaml

from backend.learning import get_learning_engine
from backend.learning.mariadb_sync import MariaDBSync

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

        # Load secrets for MariaDB
        self.secrets = self._load_secrets()
        self.mariadb = MariaDBSync(self.store, self.secrets) if self.secrets else None

    def _load_config(self, path: str) -> dict:
        try:
            with open(path) as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            return {}

    def _load_secrets(self) -> dict:
        try:
            with open("secrets.yaml") as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            return {}

    def _load_ha_config(self) -> dict:
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

    def _fetch_history(
        self, entity_id: str, start_time: datetime, end_time: datetime
    ) -> list[tuple[datetime, float]]:
        """Fetch history for a single entity from HA."""
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
            response = requests.get(
                api_url, headers=self._make_ha_headers(), params=params, timeout=60
            )
            response.raise_for_status()
            data = response.json()

            if not data or not data[0]:
                return []

            history = []
            for state in data[0]:
                try:
                    ts = datetime.fromisoformat(state["last_changed"])
                    val = float(state["state"])
                    history.append((ts, val))
                except (ValueError, TypeError, KeyError):
                    continue
            return history

        except Exception as e:
            logger.error(f"Failed to fetch history for {entity_id}: {e}")
            return []

    def run(self) -> None:
        """Run the backfill process."""
        logger.info("Starting backfill process...")

        # 1. Sync from MariaDB (Primary Source)
        if self.mariadb:
            days_back = 30
            logger.info(f"Syncing from MariaDB (last {days_back} days)...")
            self.mariadb.sync_plans(days_back=days_back)
            self.mariadb.sync_plans_from_execution(days_back=days_back)
            self.mariadb.sync_observations(days_back=days_back)

        # 2. Sync from Home Assistant (Fallback/Augment)
        try:
            # Check last observation time
            last_obs = self.store.get_last_observation_time()
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
            raw_map = self.engine.learning_config.get("sensor_map", {})
            cumulative_data: dict[str, list[tuple[datetime, float]]] = {}

            count = 0
            for entity_id, canonical in raw_map.items():
                logger.info(f"Backfilling {canonical} ({entity_id})...")
                history = self._fetch_history(str(entity_id), start_time, now)
                if history:
                    cumulative_data[str(entity_id)] = history
                    count += len(history)

            if not cumulative_data:
                logger.warning("No history data found for any sensors.")
                return

            logger.info(f"Fetched {count} data points. Processing into slots...")

            # 3. ETL to slots
            df = self.engine.etl_cumulative_to_slots(cumulative_data)

            if df.empty:
                logger.warning("ETL produced empty DataFrame.")
                return

            logger.info(f"Generated {len(df)} slots. Storing to DB...")

            # 4. Store
            self.engine.store_slot_observations(df)
            logger.info("Backfill complete.")

        except Exception as e:
            logger.error(f"Backfill failed during ETL/Storage: {e}")
