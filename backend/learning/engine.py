import logging
from pathlib import Path
from typing import Any

import pandas as pd
import pytz
import yaml

from backend.learning.store import LearningStore
from backend.validation import get_max_energy_per_slot

logger = logging.getLogger(__name__)


class LearningEngine:
    """
    Learning engine for auto-tuning and forecast calibration.
    Unified AsyncIO architecture (REV ARC11).
    """

    def __init__(self, config_path: str = "config.yaml"):
        self._config_path: str = config_path
        self.config: dict[str, Any] = self._load_config(config_path)
        self._config_mtime: float = self._get_config_mtime()
        self.learning_config: dict[str, Any] = self.config.get("learning", {})
        self.db_path = self.learning_config.get("sqlite_path", "data/planner_learning.db")
        self.timezone = pytz.timezone(self.config.get("timezone", "Europe/Stockholm"))

        # Ensure data directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize Store
        self.store = LearningStore(self.db_path, self.timezone)

    def _get_config_mtime(self) -> float:
        try:
            return Path(self._config_path).stat().st_mtime
        except OSError:
            return 0.0

    def _load_config(self, config_path: str) -> dict[str, Any]:
        """Load configuration from YAML file"""
        try:
            with Path(config_path).open(encoding="utf-8") as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            self._config_path = "config.default.yaml"
            with Path(self._config_path).open(encoding="utf-8") as f:
                return yaml.safe_load(f)

    def reload_config_if_changed(self) -> None:
        """Re-parse config only when its mtime has changed; no-op otherwise."""
        try:
            current_mtime = Path(self._config_path).stat().st_mtime
        except OSError:
            return
        if current_mtime == self._config_mtime:
            return
        self.config = self._load_config(self._config_path)
        self._config_mtime = self._get_config_mtime()
        logger.info("Config reloaded (mtime changed): %s", self._config_path)

    def refresh_config(self) -> None:
        """Force re-read of config (called after a config save)."""
        self.config = self._load_config(self._config_path)
        self._config_mtime = self._get_config_mtime()
        logger.info("Config refreshed: %s", self._config_path)

    # Delegate storage methods to store (Async)
    async def store_slot_prices(self, price_rows: Any) -> None:
        await self.store.store_slot_prices(price_rows)

    async def store_slot_observations(
        self, observations_df: pd.DataFrame, authoritative: bool = True
    ) -> None:
        await self.store.store_slot_observations(observations_df, authoritative=authoritative)

    async def store_forecasts(self, forecasts: list[dict[str, Any]], forecast_version: str) -> None:
        await self.store.store_forecasts(forecasts, forecast_version)

    async def store_openmeteo_pv_baselines(
        self, baselines: list[dict[str, Any]], forecast_version: str = "aurora"
    ) -> None:
        await self.store.store_openmeteo_pv_baselines(baselines, forecast_version)

    async def log_training_episode(
        self,
        input_data: dict[str, Any],
        schedule_df: pd.DataFrame,
        config_overrides: dict[str, Any] | None = None,
    ) -> None:
        """
        Log a training episode (inputs + outputs) for RL.
        Also logs the planned schedule to slot_plans for metric tracking.
        """
        # Log the planned schedule to slot_plans.
        await self.store.store_plan(schedule_df)

    async def calculate_metrics(self, days_back: int = 7) -> dict[str, Any]:
        """Calculate learning metrics for the last N days using the store."""
        # Get max threshold for spike filtering
        try:
            max_kwh = get_max_energy_per_slot(self.config)
        except ValueError:
            max_kwh = None

        return await self.store.calculate_metrics(days_back, max_kwh=max_kwh)

    async def get_status(self) -> dict[str, Any]:
        """Get current status of the learning engine."""
        last_obs = await self.store.get_last_observation_time()
        forecasting_cfg: dict[str, Any] = self.config.get("forecasting", {}) or {}
        ramp_days = float(forecasting_cfg.get("pv_personalization_ramp_days", 14) or 14)
        pv_days = await self.store.count_paired_openmeteo_pv_days(days_back=max(90, int(ramp_days)))
        pv_weight = min(1.0, max(0.0, pv_days / max(ramp_days, 1.0)))

        return {
            "status": "active",
            "last_observation": last_obs.isoformat() if last_obs else None,
            "db_path": self.db_path,
            "timezone": str(self.timezone),
            "pv_personalization": {
                "source": "openmeteo",
                "paired_days": pv_days,
                "ramp_days": ramp_days,
                "weight": pv_weight,
                "mode": "personalized" if pv_weight > 0 else "baseline",
            },
        }

    async def get_performance_series(self, days_back: int = 7) -> dict[str, list[dict[str, Any]]]:
        """Get time-series data for performance visualization using the store."""
        return await self.store.get_performance_series(days_back)
