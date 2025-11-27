"""Load historical price and sensor data for the simulator."""

import asyncio
import math
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
import pytz
import yaml

from ml.api import get_forecast_slots
from ml.simulation.ha_client import HomeAssistantHistoryClient


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert a value to float or fall back to the provided default."""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_iso(value: Any) -> Optional[datetime]:
    """Parse an ISO8601 string into a datetime, handling trailing Z."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


class SimulationDataLoader:
    """Build planner-ready inputs from historical observations."""

    DEFAULT_HORIZON_HOURS = 48

    def __init__(self, config_path: str = "config.yaml", horizon_hours: int = DEFAULT_HORIZON_HOURS):
        config = self._load_yaml(config_path)
        learning_cfg = config.get("learning", {}) or {}
        battery_cfg = config.get("system", {}).get("battery") or config.get("battery", {})

        self.config = config
        self.db_path = learning_cfg.get("sqlite_path", "data/planner_learning.db")
        self.timezone_name = config.get("timezone", "Europe/Stockholm")
        self.timezone = pytz.timezone(self.timezone_name)
        self.horizon_hours = horizon_hours
        self.battery_capacity_kwh = battery_cfg.get("capacity_kwh", 10.0)
        self.battery_cost = (
            learning_cfg.get("default_battery_cost_sek_per_kwh", 0.2)
        )
        self.sensor_entities = {
            "load": config.get("input_sensors", {}).get("total_load_consumption"),
            "pv": config.get("input_sensors", {}).get("total_pv_production"),
        }
        self.ha_client = HomeAssistantHistoryClient()

    @staticmethod
    def _load_yaml(path: str) -> Dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as fp:
                return yaml.safe_load(fp) or {}
        except FileNotFoundError:
            return {}
        except Exception:  # pragma: no cover - defensive fallback
            return {}

    def _localize_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return self.timezone.localize(value)
        return value.astimezone(self.timezone)

    def _to_utc_iso(self, value: datetime) -> str:
        return self._localize_datetime(value).astimezone(pytz.UTC).isoformat()

    def get_window_inputs(
        self,
        now: datetime,
        horizon_hours: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return price/forecast inputs covering the requested window."""
        horizon = horizon_hours or self.horizon_hours
        start = self._localize_datetime(now)
        end = start + timedelta(hours=horizon)

        price_slots = self._load_price_data(start, end)
        forecast_slots = self._load_forecast_slots(start, end)
        if not forecast_slots:
            forecast_slots = self._build_naive_forecasts(start, end)

        return {
            "price_data": price_slots,
            "forecast_data": forecast_slots,
            "daily_pv_forecast": self._aggregate_daily(forecast_slots, "pv_forecast_kwh"),
            "daily_load_forecast": self._aggregate_daily(forecast_slots, "load_forecast_kwh"),
            "timezone": self.timezone_name,
        }

    def get_initial_state_from_history(self, now: datetime) -> Dict[str, float]:
        """Return the historical SoC for the most recent observation before `now`."""
        start_iso = self._to_utc_iso(now)
        query = (
            "SELECT soc_end_percent, soc_start_percent "
            "FROM slot_observations "
            "WHERE slot_start <= ? "
            "ORDER BY slot_start DESC LIMIT 1"
        )
        soc_value = 50.0
        try:
            with sqlite3.connect(self.db_path, timeout=30.0) as conn:
                row = conn.execute(query, (start_iso,)).fetchone()
        except sqlite3.Error:  # pragma: no cover - best effort
            row = None
        if row:
            soc_value = _safe_float(row[0], _safe_float(row[1], soc_value))
        soc_value = max(0.0, min(100.0, soc_value))
        return {
            "battery_soc_percent": soc_value,
            "battery_kwh": self.battery_capacity_kwh * soc_value / 100.0,
            "battery_cost_sek_per_kwh": self.battery_cost,
        }

    def _load_price_data(self, start: datetime, end: datetime) -> List[Dict[str, Any]]:
        query = (
            "SELECT slot_start, slot_end, import_price_sek_kwh, export_price_sek_kwh "
            "FROM slot_observations "
            "WHERE slot_start >= ? AND slot_start < ? "
            "ORDER BY slot_start ASC"
        )
        params = (self._to_utc_iso(start), self._to_utc_iso(end))
        try:
            with sqlite3.connect(self.db_path, timeout=30.0) as conn:
                df = pd.read_sql_query(query, conn, params=params)
        except sqlite3.Error:
            return []
        if df.empty:
            return []
        df["slot_start"] = pd.to_datetime(df["slot_start"], utc=True, errors="coerce")
        df["slot_end"] = pd.to_datetime(df["slot_end"], utc=True, errors="coerce")
        df = df.dropna(subset=["slot_start", "slot_end"])
        if df.empty:
            return []
        df["slot_start"] = df["slot_start"].dt.tz_convert(self.timezone)
        df["slot_end"] = df["slot_end"].dt.tz_convert(self.timezone)

        records: List[Dict[str, Any]] = []
        for row in df.to_dict("records"):
            base = {
                "import_price_sek_kwh": _safe_float(row.get("import_price_sek_kwh")),
                "export_price_sek_kwh": _safe_float(row.get("export_price_sek_kwh"))
                or _safe_float(row.get("import_price_sek_kwh")),
            }
            segments = self._split_slot(
                row["slot_start"],
                row["slot_end"],
                base,
                tuple(),
            )
            records.extend(segments)
        return sorted(records, key=lambda item: item["start_time"])

    def _load_forecast_slots(self, start: datetime, end: datetime) -> List[Dict[str, Any]]:
        version = (
            self.config.get("forecasting", {})
            .get("active_forecast_version")
            or "aurora"
        )
        try:
            slots = get_forecast_slots(start, end, version)
        except Exception:
            slots = []
        result: List[Dict[str, Any]] = []
        for slot in slots:
            slot_start = slot.get("slot_start")
            if not isinstance(slot_start, datetime):
                continue
            slot_end = slot_start + timedelta(minutes=15)
            pv = _safe_float(slot.get("pv_forecast_kwh")) + _safe_float(
                slot.get("pv_correction_kwh")
            )
            load = _safe_float(slot.get("load_forecast_kwh")) + _safe_float(
                slot.get("load_correction_kwh")
            )
            result.append(
                {
                    "start_time": slot_start,
                    "end_time": slot_end,
                    "pv_forecast_kwh": pv,
                    "load_forecast_kwh": load,
                }
            )
        return sorted(result, key=lambda item: item["start_time"])

    def _build_naive_forecasts(
        self, start: datetime, end: datetime
    ) -> List[Dict[str, Any]]:
        sensor_points = self._collect_sensor_points(start, end)
        load_slots = self._convert_sensor_points(
            sensor_points.get("load", []), "load_kwh"
        )
        pv_slots = self._convert_sensor_points(sensor_points.get("pv", []), "pv_kwh")
        if not load_slots and not pv_slots:
            return self._build_forecasts_from_observations(start, end)
        return self._merge_sensor_slots(load_slots, pv_slots)

    def _collect_sensor_points(
        self, start: datetime, end: datetime
    ) -> Dict[str, List[Dict[str, Any]]]:
        if not self.ha_client.enabled:
            return {}

        async def _gather() -> Dict[str, List[Dict[str, Any]]]:
            tasks: Dict[str, asyncio.Task] = {}
            for key, entity in self.sensor_entities.items():
                if not entity:
                    continue
                tasks[key] = asyncio.create_task(
                    self.ha_client.fetch_statistics(entity, start, end)
                )
            results: Dict[str, List[Dict[str, Any]]] = {}
            for key, task in tasks.items():
                try:
                    results[key] = await task
                except Exception:
                    results[key] = []
            return results

        try:
            return asyncio.run(_gather())
        except RuntimeError:
            return {}

    def _convert_sensor_points(
        self,
        points: List[Dict[str, Any]],
        value_key: str,
    ) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for point in points:
            start = _parse_iso(point.get("start"))
            end = _parse_iso(point.get("end"))
            if not start or not end:
                continue
            start = self._localize_datetime(start)
            end = self._localize_datetime(end)
            base = {value_key: _safe_float(point.get("sum"))}
            records.extend(
                self._split_slot(start, end, base, (value_key,))
            )
        return records

    def _merge_sensor_slots(
        self,
        load_slots: List[Dict[str, Any]],
        pv_slots: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        timeline: Dict[datetime, Dict[str, float]] = {}
        for slot in load_slots:
            start_time = slot["start_time"]
            entry = timeline.setdefault(start_time, {})
            entry["load_kwh"] = entry.get("load_kwh", 0.0) + _safe_float(
                slot.get("load_kwh")
            )
        for slot in pv_slots:
            start_time = slot["start_time"]
            entry = timeline.setdefault(start_time, {})
            entry["pv_kwh"] = entry.get("pv_kwh", 0.0) + _safe_float(
                slot.get("pv_kwh")
            )
        result: List[Dict[str, Any]] = []
        for start_time in sorted(timeline):
            values = timeline[start_time]
            result.append(
                {
                    "start_time": start_time,
                    "end_time": start_time + timedelta(minutes=15),
                    "pv_forecast_kwh": values.get("pv_kwh", 0.0),
                    "load_forecast_kwh": values.get("load_kwh", 0.0),
                }
            )
        return result

    def _build_forecasts_from_observations(
        self, start: datetime, end: datetime
    ) -> List[Dict[str, Any]]:
        query = (
            "SELECT slot_start, slot_end, pv_kwh, load_kwh "
            "FROM slot_observations "
            "WHERE slot_start >= ? AND slot_start < ? "
            "ORDER BY slot_start ASC"
        )
        params = (self._to_utc_iso(start), self._to_utc_iso(end))
        try:
            with sqlite3.connect(self.db_path, timeout=30.0) as conn:
                df = pd.read_sql_query(query, conn, params=params)
        except sqlite3.Error:
            return []
        if df.empty:
            return []
        df["slot_start"] = pd.to_datetime(df["slot_start"], utc=True, errors="coerce")
        df["slot_end"] = pd.to_datetime(df["slot_end"], utc=True, errors="coerce")
        df = df.dropna(subset=["slot_start", "slot_end"])
        if df.empty:
            return []
        df["slot_start"] = df["slot_start"].dt.tz_convert(self.timezone)
        df["slot_end"] = df["slot_end"].dt.tz_convert(self.timezone)

        records: List[Dict[str, Any]] = []
        for row in df.to_dict("records"):
            base = {
                "pv_kwh": _safe_float(row.get("pv_kwh")),
                "load_kwh": _safe_float(row.get("load_kwh")),
            }
            segments = self._split_slot(
                row["slot_start"],
                row["slot_end"],
                base,
                ("pv_kwh", "load_kwh"),
            )
            for segment in segments:
                records.append(
                    {
                        "start_time": segment["start_time"],
                        "end_time": segment["end_time"],
                        "pv_forecast_kwh": segment.get("pv_kwh", 0.0),
                        "load_forecast_kwh": segment.get("load_kwh", 0.0),
                    }
                )
        return sorted(records, key=lambda item: item["start_time"])

    def _split_slot(
        self,
        start: datetime,
        end: datetime,
        base: Dict[str, Any],
        divisor_keys: tuple[str, ...],
    ) -> List[Dict[str, Any]]:
        duration = int((end - start).total_seconds() // 60)
        if duration <= 0:
            return []
        segments = max(1, math.ceil(duration / 15))
        shares: Dict[str, float] = {}
        for key in divisor_keys:
            shares[key] = _safe_float(base.get(key)) / segments
        entries: List[Dict[str, Any]] = []
        for index in range(segments):
            segment_start = start + timedelta(minutes=index * 15)
            if segment_start >= end:
                break
            segment_end = min(end, segment_start + timedelta(minutes=15))
            entry = base.copy()
            entry["start_time"] = segment_start
            entry["end_time"] = segment_end
            for key, share in shares.items():
                entry[key] = share
            entries.append(entry)
        return entries

    @staticmethod
    def _aggregate_daily(slots: List[Dict[str, Any]], key: str) -> Dict[str, float]:
        totals: Dict[str, float] = {}
        for slot in slots:
            start = slot.get("start_time")
            if not isinstance(start, datetime):
                continue
            day_key = start.date().isoformat()
            totals[day_key] = totals.get(day_key, 0.0) + _safe_float(slot.get(key))
        return totals
