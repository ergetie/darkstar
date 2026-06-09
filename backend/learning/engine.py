import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytz
import yaml

from backend.learning.store import LearningStore
from backend.validation import get_max_energy_per_slot
from utils.time_utils import dst_safe_date_range, dst_safe_localize

logger = logging.getLogger(__name__)


class LearningEngine:
    """
    Learning engine for auto-tuning and forecast calibration.
    Unified AsyncIO architecture (REV ARC11).
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config: dict[str, Any] = self._load_config(config_path)
        self.learning_config: dict[str, Any] = self.config.get("learning", {})
        self.db_path = self.learning_config.get("sqlite_path", "data/planner_learning.db")
        self.timezone = pytz.timezone(self.config.get("timezone", "Europe/Stockholm"))

        # Ensure data directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize Store
        self.store = LearningStore(self.db_path, self.timezone)

        raw_map: dict[str, Any] = self.learning_config.get("sensor_map", {}) or {}
        # Corrected: {entity_id: canonical} -> {entity_id: canonical}
        self.sensor_map = {str(k).lower(): str(v).lower() for k, v in raw_map.items()}

        # Load inversion flags from input_sensors (REV F55)
        input_sensors: dict[str, Any] = self.config.get("input_sensors", {})
        self.inversion_flags = {
            "battery": input_sensors.get("battery_power_inverted", False),
            "grid": input_sensors.get("grid_power_inverted", False),
        }

    def _load_config(self, config_path: str) -> dict[str, Any]:
        """Load configuration from YAML file"""
        try:
            with Path(config_path).open(encoding="utf-8") as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            # Fallback to default config
            with Path("config.default.yaml").open(encoding="utf-8") as f:
                return yaml.safe_load(f)

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
        # 1. Log to training_episodes (Legacy/Debug only)
        if self.config.get("debug", {}).get("enable_training_episodes", False):
            episode_id = str(uuid.uuid4())

            inputs_json = json.dumps(input_data, default=str)
            schedule_json = schedule_df.to_json(orient="records", date_format="iso")
            context_json = None
            config_overrides_json = json.dumps(config_overrides) if config_overrides else None

            await self.store.store_training_episode(
                episode_id=episode_id,
                inputs_json=inputs_json,
                schedule_json=schedule_json,
                context_json=context_json,
                config_overrides_json=config_overrides_json,
            )

        # 2. Log to slot_plans
        await self.store.store_plan(schedule_df)

    def _canonical_sensor_name(self, name: str) -> str:
        """Map incoming sensor names to canonical identifiers."""
        key = str(name).lower()
        if key in self.sensor_map:
            return self.sensor_map[key]

        stripped = key.replace("sensor.", "")
        # Remove common inverter/brand prefixes
        for brand in ("inverter_", "sungrow_", "goodwe_", "victron_", "fronius_"):
            stripped = stripped.replace(brand, "")

        for token in (
            "energy_",
            "power_",
            "total_",
            "cumulative_",
            "_kw",
            "_kwh",
            "_power",
            "_current",
            "_production",
            "_consumption",
        ):
            stripped = stripped.replace(token, "")
        stripped = stripped.strip("_")

        # Explicit handling for compound names often found in HA
        if stripped in ("load_consumption", "house_load"):
            return "load"
        if stripped in ("pv_production", "solar_yield", "solar"):
            return "pv"
        if stripped in ("grid_import", "energy_import", "from_grid"):
            return "import"
        if stripped in ("grid_export", "energy_export", "to_grid"):
            return "export"
        # REV F55: Handle battery_power and grid_power sensors
        if stripped in ("battery_power", "battery"):
            return "battery"
        if stripped in ("grid_power", "grid"):
            return "grid"

        aliases = {
            "import": {"grid_import", "gridin", "import", "grid", "from_grid", "energy_import"},
            "export": {"grid_export", "gridout", "export", "to_grid", "energy_export"},
            "pv": {"pv", "solar", "pvproduction", "production", "yield", "solar_yield"},
            "load": {"load", "consumption", "house", "usage", "load_consumption", "house_load"},
            "water": {"water", "vvb", "waterheater", "heater"},
            "ev_charging": {"ev", "evcharging", "evcharger", "charger"},
            "soc": {"soc", "battery_soc", "socpercent"},
            "battery": {"battery"},  # REV F55: battery power sensors (not SoC)
        }
        for canonical, names in aliases.items():
            if stripped in names:
                return canonical
        return stripped or key

    def etl_cumulative_to_slots(
        self,
        cumulative_data: dict[str, list[tuple[datetime, float]]],
        controllable_power_data: dict[str, list[tuple[datetime, float]]] | None = None,
        resolution_minutes: int = 15,
    ) -> pd.DataFrame:
        """
        Convert cumulative sensor data to 15-minute slot deltas.
        Aggregates multiple sensors for the same canonical name.
        """
        slot_records: dict[str, pd.DataFrame] = {}
        for sensor_name, data in cumulative_data.items():
            if data:
                df = pd.DataFrame(data, columns=["timestamp", "cumulative_value"])
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                if df["timestamp"].dt.tz is None:
                    df["timestamp"] = dst_safe_localize(df["timestamp"], self.timezone)
                else:
                    df["timestamp"] = df["timestamp"].dt.tz_convert(self.timezone)
                df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
                slot_records[sensor_name] = df

        if not slot_records:
            return pd.DataFrame()

        all_timestamps: list[Any] = []
        for df in slot_records.values():
            ts_list: list[Any] = df["timestamp"].tolist()
            all_timestamps.extend(ts_list)

        if not all_timestamps:
            return pd.DataFrame()

        min_ts: Any = min(all_timestamps)
        max_ts: Any = max(all_timestamps)

        if min_ts.tzinfo is None:
            min_ts = min_ts.replace(tzinfo=self.timezone)
        else:
            min_ts = min_ts.astimezone(self.timezone)

        floored_minute: int = (min_ts.minute // resolution_minutes) * resolution_minutes
        start_time: Any = min_ts.replace(minute=floored_minute, second=0, microsecond=0)
        end_time: Any = max_ts

        slots = dst_safe_date_range(
            start=start_time, end=end_time, freq=f"{resolution_minutes}min", tz=self.timezone
        )

        slot_df = pd.DataFrame({"slot_start": slots[:-1], "slot_end": slots[1:]})

        for sensor_name, df in slot_records.items():
            canonical = self._canonical_sensor_name(sensor_name)
            base_series = df.set_index("timestamp")["cumulative_value"]

            # --- FIX: interpolate to exact slot boundaries --------------------
            # Forward-fill (`method="ffill"`) picked up sensor values from
            # variable times before each boundary, producing alternating
            # short/long deltas (sawtooth).  Linear interpolation estimates the
            # true cumulative value at each boundary, giving consistent deltas.
            combined_index = base_series.index.union(slots).sort_values()
            combined = base_series.reindex(combined_index)
            combined = combined.interpolate(method="index")  # linear on time
            combined = combined.ffill().bfill()  # handle edges
            reindexed = combined.reindex(slots)
            # --- END FIX ------------------------------------------------------

            raw_diff = reindexed.diff().fillna(0)

            # Filter out huge spikes using config-derived threshold
            # (exceeding physically possible energy for the slot duration)
            try:
                max_kwh = get_max_energy_per_slot(self.config)
            except ValueError:
                max_kwh = 50.0  # Fallback to legacy threshold if config missing
                logger.warning(
                    "Could not get max energy from config, using fallback threshold 50.0 kWh"
                )
            # Clip negative values (sometimes counters reset to zero)
            deltas = raw_diff.clip(lower=0)
            deltas[deltas > max_kwh] = 0.0

            col_name = f"{canonical}_kwh"
            if col_name not in slot_df.columns:
                slot_df[col_name] = 0.0

            # Use align to ensure values are correctly added to slots
            # deltas.iloc[1:] corresponds to the slots [slots[0]:slots[1]], [slots[1]:slots[2]], etc.
            slot_df[col_name] = slot_df[col_name] + deltas.iloc[1:].values

        if controllable_power_data:
            power_df = self.etl_power_to_slots(controllable_power_data, resolution_minutes)
            if not power_df.empty:
                merge_cols = [
                    col
                    for col in ("slot_start", "water_kwh", "ev_charging_kwh")
                    if col in power_df.columns
                ]
                if len(merge_cols) > 1:
                    slot_df = slot_df.merge(power_df[merge_cols], on="slot_start", how="left")
                    for col in ("water_kwh", "ev_charging_kwh"):
                        if col not in slot_df.columns:
                            slot_df[col] = 0.0
                        elif f"{col}_x" in slot_df.columns or f"{col}_y" in slot_df.columns:
                            left = (
                                slot_df[f"{col}_x"].fillna(0.0)
                                if f"{col}_x" in slot_df.columns
                                else 0.0
                            )
                            right = (
                                slot_df[f"{col}_y"].fillna(0.0)
                                if f"{col}_y" in slot_df.columns
                                else 0.0
                            )
                            slot_df[col] = left + right
                            slot_df = slot_df.drop(
                                columns=[
                                    c for c in (f"{col}_x", f"{col}_y") if c in slot_df.columns
                                ]
                            )

        if "load_kwh" in slot_df.columns:
            controllable_kwh = 0.0
            for col in ("ev_charging_kwh", "water_kwh"):
                if col in slot_df.columns:
                    controllable_kwh = controllable_kwh + slot_df[col].fillna(0.0)
            slot_df["load_kwh"] = (slot_df["load_kwh"] - controllable_kwh).clip(lower=0.0)

        if any(self._canonical_sensor_name(name) == "soc" for name in slot_records):
            soc_name = next(
                name for name in slot_records if self._canonical_sensor_name(name) == "soc"
            )
            soc_series = (
                slot_records[soc_name]
                .set_index("timestamp")["cumulative_value"]
                .reindex(slots, method="ffill")
                .ffill()
            )
            slot_df["soc_start_percent"] = soc_series.iloc[:-1].values
            slot_df["soc_end_percent"] = soc_series.iloc[1:].values

        slot_df["duration_minutes"] = resolution_minutes
        return slot_df

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
        episodes = await self.store.get_episodes_count()
        forecasting_cfg: dict[str, Any] = self.config.get("forecasting", {}) or {}
        ramp_days = float(forecasting_cfg.get("pv_personalization_ramp_days", 14) or 14)
        pv_days = await self.store.count_paired_openmeteo_pv_days(days_back=max(90, int(ramp_days)))
        pv_weight = min(1.0, max(0.0, pv_days / max(ramp_days, 1.0)))

        return {
            "status": "active",
            "last_observation": last_obs.isoformat() if last_obs else None,
            "training_episodes": episodes,
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

    def etl_power_to_slots(
        self,
        power_data: dict[str, list[tuple[datetime, float]]],
        resolution_minutes: int = 15,
    ) -> pd.DataFrame:
        """
        Convert instantaneous power sensor data (W) to energy (kWh) per slot.
        Specifically optimized for backfill to populate bars in ChartCard.
        """
        slot_records: dict[str, pd.DataFrame] = {}
        for sensor_name, data in power_data.items():
            if data:
                df = pd.DataFrame(data, columns=["timestamp", "power_value"])
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                if df["timestamp"].dt.tz is None:
                    df["timestamp"] = dst_safe_localize(df["timestamp"], self.timezone)
                else:
                    df["timestamp"] = df["timestamp"].dt.tz_convert(self.timezone)
                df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
                slot_records[sensor_name] = df

        if not slot_records:
            return pd.DataFrame()

        all_timestamps: list[Any] = []
        for df in slot_records.values():
            ts_list: list[Any] = df["timestamp"].tolist()
            all_timestamps.extend(ts_list)

        if not all_timestamps:
            return pd.DataFrame()

        min_ts: Any = min(all_timestamps)
        max_ts: Any = max(all_timestamps)
        min_ts = min_ts.astimezone(self.timezone)

        floored_minute: int = (min_ts.minute // resolution_minutes) * resolution_minutes
        start_time: Any = min_ts.replace(minute=floored_minute, second=0, microsecond=0)

        rem: int = max_ts.minute % resolution_minutes
        end_time: Any = max_ts.replace(second=0, microsecond=0)
        if rem != 0 or max_ts.second > 0:
            end_time += timedelta(minutes=(resolution_minutes - rem))

        slots = dst_safe_date_range(
            start=start_time,
            end=end_time,
            freq=f"{resolution_minutes}min",
            tz=self.timezone,
            inclusive="both",
        )
        if len(slots) < 2:
            return pd.DataFrame()

        slot_df = pd.DataFrame({"slot_start": slots[:-1], "slot_end": slots[1:]})
        hours_per_slot = resolution_minutes / 60.0

        for sensor_name, df in slot_records.items():
            canonical = self._canonical_sensor_name(sensor_name)

            if canonical == "soc":
                continue

            resampled = (
                df.set_index("timestamp")["power_value"]
                .resample(f"{resolution_minutes}min")
                .mean()
                .reindex(slot_df["slot_start"].dt.floor("min"))
                .fillna(0)
            )

            is_kw = resampled.max() < 100.0 and resampled.max() > 0

            if is_kw:
                energy_kwh = resampled * hours_per_slot
            else:
                energy_kwh = (resampled / 1000.0) * hours_per_slot

            # Filter out huge spikes using config-derived threshold
            try:
                max_kwh = get_max_energy_per_slot(self.config)
                energy_kwh = energy_kwh.where(energy_kwh <= max_kwh, 0.0)
            except ValueError:
                # Config missing, proceed without filtering (legacy behavior)
                pass

            # Apply inversion for battery sensors (REV F55)
            if canonical == "battery" and self.inversion_flags.get("battery", False):
                energy_kwh = -energy_kwh
                logger.debug(f"Applied battery_power_inverted for {sensor_name}")

            # Apply inversion for grid sensors (REV F55)
            if canonical in ("grid", "import", "export") and self.inversion_flags.get(
                "grid", False
            ):
                energy_kwh = -energy_kwh
                logger.debug(f"Applied grid_power_inverted for {sensor_name}")

            if canonical == "battery":
                if "batt_discharge_kwh" not in slot_df.columns:
                    slot_df["batt_discharge_kwh"] = 0.0
                if "batt_charge_kwh" not in slot_df.columns:
                    slot_df["batt_charge_kwh"] = 0.0
                slot_df["batt_discharge_kwh"] = (
                    slot_df["batt_discharge_kwh"] + energy_kwh.clip(lower=0).values
                )
                slot_df["batt_charge_kwh"] = (
                    slot_df["batt_charge_kwh"] + energy_kwh.clip(upper=0).abs().values
                )
            elif canonical in ("grid", "import", "export"):
                if "import_kwh" not in slot_df.columns:
                    slot_df["import_kwh"] = 0.0
                if "export_kwh" not in slot_df.columns:
                    slot_df["export_kwh"] = 0.0

                if canonical == "grid":
                    slot_df["import_kwh"] = slot_df["import_kwh"] + energy_kwh.clip(lower=0).values
                    slot_df["export_kwh"] = (
                        slot_df["export_kwh"] + energy_kwh.clip(upper=0).abs().values
                    )
                elif canonical == "import":
                    slot_df["import_kwh"] = slot_df["import_kwh"] + energy_kwh.values
                elif canonical == "export":
                    slot_df["export_kwh"] = slot_df["export_kwh"] + energy_kwh.values
            else:
                col_name = f"{canonical}_kwh"
                if col_name not in slot_df.columns:
                    slot_df[col_name] = 0.0
                slot_df[col_name] = slot_df[col_name] + energy_kwh.values

        soc_name = next(
            (name for name in slot_records if self._canonical_sensor_name(name) == "soc"), None
        )
        if soc_name:
            soc_df = slot_records[soc_name].drop_duplicates(subset=["timestamp"], keep="last")
            soc_series = (
                soc_df.set_index("timestamp")["power_value"].reindex(slots, method="ffill").ffill()
            )
            slot_df["soc_start_percent"] = soc_series.iloc[:-1].values
            slot_df["soc_end_percent"] = soc_series.iloc[1:].values

        for col in ["pv_kwh", "load_kwh", "import_kwh", "export_kwh", "water_kwh"]:
            if col not in slot_df.columns:
                slot_df[col] = 0.0

        slot_df["duration_minutes"] = resolution_minutes
        return slot_df

    async def get_performance_series(self, days_back: int = 7) -> dict[str, list[dict[str, Any]]]:
        """Get time-series data for performance visualization using the store."""
        return await self.store.get_performance_series(days_back)
