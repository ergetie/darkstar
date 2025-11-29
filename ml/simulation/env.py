"""Gym-style environment wrapper around the deterministic MPC simulator.

This environment is intentionally thin: it uses the existing planner and
SimulationDataLoader to build a schedule for a given historical day, then
exposes a simple reset/step API for downstream RL-style agents.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd
import pytz

from ml.simulation.data_loader import SimulationDataLoader
from planner import HeliosPlanner


@dataclass
class StepResult:
    next_state: np.ndarray
    reward: float
    done: bool
    info: Dict[str, Any]


class AntaresMPCEnv:
    """Thin environment that replays MPC schedules for historical days.

    For Rev 68 the action space is intentionally limited: the default
    and primary behaviour is to follow the deterministic MPC schedule
    produced by HeliosPlanner. The environment surfaces per-slot state
    and reward signals but does not yet implement complex control.
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.loader = SimulationDataLoader(config_path)
        self.timezone = pytz.timezone(self.loader.timezone_name)
        self.planner = HeliosPlanner(config_path)

        battery_cfg = self.loader.config.get("battery", {}) or {}
        system_cfg = self.loader.config.get("system", {}) or {}
        grid_cfg = system_cfg.get("grid", {}) or {}
        inverter_cfg = system_cfg.get("inverter", {}) or {}

        self._capacity_kwh: float = float(
            battery_cfg.get("capacity_kwh", self.loader.battery_capacity_kwh)
        )
        self._min_soc_percent: float = float(battery_cfg.get("min_soc_percent", 10.0))
        self._max_soc_percent: float = float(battery_cfg.get("max_soc_percent", 100.0))
        self._max_charge_power_kw: float = float(battery_cfg.get("max_charge_power_kw", 3.0))
        self._max_discharge_power_kw: float = float(
            battery_cfg.get("max_discharge_power_kw", 3.0)
        )

        inverter_limit = float(inverter_cfg.get("max_power_kw", 10.0))
        grid_limit = float(grid_cfg.get("max_power_kw", inverter_limit))
        self._max_export_power_kw: float = min(inverter_limit, grid_limit)

        self._soc_kwh: float = 0.0

        self._schedule: Optional[pd.DataFrame] = None
        self._current_idx: int = 0
        self._current_day: Optional[date] = None

    def _normalize_day(self, day: Any) -> date:
        if isinstance(day, date) and not isinstance(day, datetime):
            return day
        if isinstance(day, datetime):
            return day.date()
        if isinstance(day, str):
            return datetime.fromisoformat(day).date()
        raise TypeError(f"Unsupported day type: {type(day)}")

    def _build_state_vector(self, row: pd.Series) -> np.ndarray:
        """Build a simple, stable state vector from a schedule row."""
        features = [
            row.get("hour_of_day", 0),
            row.get("load_forecast_kwh", 0.0),
            row.get("pv_forecast_kwh", 0.0),
            row.get("projected_soc_percent", 0.0),
            row.get("import_price_sek_kwh", 0.0),
            row.get("export_price_sek_kwh", row.get("import_price_sek_kwh", 0.0)),
        ]
        return np.array([float(x) for x in features], dtype=np.float32)

    def _compute_reward(self, row: pd.Series) -> float:
        """Per-slot reward based on cost, revenue and battery wear.

        This mirrors the structure of LearningEngine._evaluate_schedule
        but operates on a single slot.
        """
        try:
            start_ts = pd.Timestamp(row.get("start_time"))
            end_ts = pd.Timestamp(row.get("end_time"))
        except Exception:
            return 0.0
        if start_ts.tzinfo is None:
            start_ts = start_ts.tz_localize(self.timezone)
        if end_ts.tzinfo is None:
            end_ts = end_ts.tz_localize(self.timezone)

        slot_hours = max(0.25, (end_ts - start_ts).total_seconds() / 3600.0)

        charge_kw = max(0.0, float(row.get("battery_charge_kw", row.get("charge_kw", 0.0) or 0.0)))
        discharge_kw = max(0.0, float(row.get("battery_discharge_kw", 0.0)))
        charge_kwh = charge_kw * slot_hours
        discharge_kwh = discharge_kw * slot_hours

        adjusted_load = float(row.get("adjusted_load_kwh", 0.0))
        adjusted_pv = float(row.get("adjusted_pv_kwh", 0.0))
        water_grid = float(row.get("water_from_grid_kwh", 0.0))
        water_pv = float(row.get("water_from_pv_kwh", 0.0))

        export_kwh = float(row.get("export_kwh", 0.0))

        grid_import_kwh = max(
            0.0,
            adjusted_load + water_grid + charge_kwh - adjusted_pv - discharge_kwh - water_pv,
        )

        import_price = float(row.get("import_price_sek_kwh", 0.0))
        export_price = float(row.get("export_price_sek_kwh", import_price))

        # Battery wear cost: for now use a simple fixed cycle cost from config.
        battery_cycle_cost = (
            self.loader.config.get("battery_economics", {}).get("battery_cycle_cost_kwh", 0.20)
        )
        wear_cost = (charge_kwh + discharge_kwh) * battery_cycle_cost

        cost = grid_import_kwh * import_price
        revenue = export_kwh * export_price

        # Reward is negative net cost including wear (higher is better).
        return -(cost - revenue + wear_cost)

    def reset(self, day: Any) -> np.ndarray:
        """Reset the environment to the start of a historical day."""
        target_day = self._normalize_day(day)
        start_dt = datetime.combine(target_day, datetime.min.time()).replace(tzinfo=self.timezone)

        # Build inputs and initial state for the day, then generate a full schedule.
        inputs = self.loader.get_window_inputs(start_dt)
        initial_state = self.loader.get_initial_state_from_history(start_dt)
        inputs["initial_state"] = {
            "battery_soc_percent": initial_state["battery_soc_percent"],
            "battery_kwh": initial_state["battery_kwh"],
            "battery_cost_sek_per_kwh": initial_state["battery_cost_sek_per_kwh"],
        }
        inputs["now_override"] = start_dt

        schedule = self.planner.generate_schedule(
            inputs,
            record_training_episode=False,
            now_override=start_dt,
            save_to_file=False,
        )
        if schedule is None or schedule.empty:
            raise RuntimeError(f"No schedule generated for day {target_day}")

        # Ensure we have explicit start/end time columns for reward computation.
        if schedule.index.name in {"start_time", "slot_start"} and "start_time" not in schedule.columns:
            schedule = schedule.reset_index()
        if "end_time" not in schedule.columns and "end_time" in schedule.index.names:
            schedule = schedule.reset_index()

        # Add simple time features if missing.
        if "start_time" in schedule.columns:
            start_col = pd.to_datetime(schedule["start_time"])
        else:
            start_col = pd.to_datetime(schedule.index)
        start_col = start_col.dt.tz_convert(self.timezone)
        schedule["hour_of_day"] = start_col.dt.hour

        self._soc_kwh = float(initial_state.get("battery_kwh", 0.0))
        self._soc_kwh = max(
            self._capacity_kwh * self._min_soc_percent / 100.0,
            min(self._soc_kwh, self._capacity_kwh * self._max_soc_percent / 100.0),
        )

        self._schedule = schedule
        self._current_idx = 0
        self._current_day = target_day

        first_row = self._schedule.iloc[self._current_idx]
        return self._build_state_vector(first_row)

    def step(self, action: Optional[Any] = None) -> StepResult:
        """Advance one 15-minute slot, optionally overriding MPC actions.

        - If `action` is None, the deterministic MPC schedule is replayed.
        - If `action` is a dict with keys like `battery_charge_kw`,
          `battery_discharge_kw`, or `export_kw`, these are used to
          override the slot flows (clamped to physical limits) before
          computing reward.
        """
        if self._schedule is None:
            raise RuntimeError("Environment not initialized. Call reset(day) first.")

        row = self._schedule.iloc[self._current_idx]

        if action is None or not isinstance(action, dict):
            effective_row = row
            charge_kw = float(row.get("battery_charge_kw", row.get("charge_kw", 0.0) or 0.0))
            discharge_kw = float(row.get("battery_discharge_kw", 0.0))
            export_kwh = float(row.get("export_kwh", 0.0))
        else:
            effective_row = row.copy()

            try:
                start_ts = pd.Timestamp(row.get("start_time"))
                end_ts = pd.Timestamp(row.get("end_time"))
                if start_ts.tzinfo is None:
                    start_ts = start_ts.tz_localize(self.timezone)
                if end_ts.tzinfo is None:
                    end_ts = end_ts.tz_localize(self.timezone)
                slot_hours = max(0.25, (end_ts - start_ts).total_seconds() / 3600.0)
            except Exception:
                slot_hours = 0.25

            # MPC baseline values
            base_charge_kw = float(
                row.get("battery_charge_kw", row.get("charge_kw", 0.0) or 0.0)
            )
            base_discharge_kw = float(row.get("battery_discharge_kw", 0.0))
            base_export_kwh = float(row.get("export_kwh", 0.0))

            # Requested actions
            req_charge_kw = float(action.get("battery_charge_kw", base_charge_kw) or 0.0)
            req_discharge_kw = float(
                action.get("battery_discharge_kw", base_discharge_kw) or 0.0
            )
            req_export_kw = float(action.get("export_kw", base_export_kwh / slot_hours) or 0.0)

            # Clamp to non-negative and power limits
            req_charge_kw = max(0.0, min(req_charge_kw, self._max_charge_power_kw))
            req_discharge_kw = max(0.0, min(req_discharge_kw, self._max_discharge_power_kw))
            req_export_kw = max(0.0, min(req_export_kw, self._max_export_power_kw))

            # Enforce simple mutual exclusivity: prefer discharge over charge when both requested.
            if req_charge_kw > 0.0 and req_discharge_kw > 0.0:
                if req_charge_kw >= req_discharge_kw:
                    req_discharge_kw = 0.0
                else:
                    req_charge_kw = 0.0

            # Clamp by SoC bounds
            if self._capacity_kwh > 0.0:
                max_charge_by_soc = max(
                    0.0,
                    (self._capacity_kwh * self._max_soc_percent / 100.0 - self._soc_kwh)
                    / slot_hours,
                )
                max_discharge_by_soc = max(
                    0.0,
                    (self._soc_kwh - self._capacity_kwh * self._min_soc_percent / 100.0)
                    / slot_hours,
                )
                req_charge_kw = min(req_charge_kw, max_charge_by_soc)
                req_discharge_kw = min(req_discharge_kw, max_discharge_by_soc)

            charge_kw = req_charge_kw
            discharge_kw = req_discharge_kw
            export_kwh = req_export_kw * slot_hours

            effective_row["battery_charge_kw"] = charge_kw
            effective_row["battery_discharge_kw"] = discharge_kw
            effective_row["export_kwh"] = export_kwh

            # Update internal SoC estimate
            self._soc_kwh += (charge_kw - discharge_kw) * slot_hours
            min_soc_kwh = self._capacity_kwh * self._min_soc_percent / 100.0
            max_soc_kwh = self._capacity_kwh * self._max_soc_percent / 100.0
            self._soc_kwh = max(min_soc_kwh, min(self._soc_kwh, max_soc_kwh))

        reward = self._compute_reward(effective_row)

        self._current_idx += 1
        done = self._current_idx >= len(self._schedule)

        if done:
            next_state = self._build_state_vector(row)
        else:
            next_row = self._schedule.iloc[self._current_idx]
            next_state = self._build_state_vector(next_row)

        info = {
            "day": self._current_day.isoformat() if self._current_day else None,
            "index": self._current_idx - 1,
            "done": done,
        }
        return StepResult(next_state=next_state, reward=reward, done=done, info=info)

