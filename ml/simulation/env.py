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
from planner_legacy import HeliosPlanner


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
            row.get("hours_until_end", 0.0),
            row.get("max_import_price_next_12h", row.get("import_price_sek_kwh", 0.0)),
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

        # Day-end reference for horizon features.
        day_start = start_dt
        day_end = day_start + timedelta(days=1)
        schedule["hours_until_end"] = (
            (day_end - start_col).dt.total_seconds() / 3600.0
        ).astype(float)

        # Precompute rolling max import price over the next ~12 hours (48 slots).
        prices_series = pd.to_numeric(
            schedule.get("import_price_sek_kwh"), errors="coerce"
        ).astype(float)
        prices_series = prices_series.fillna(0.0)
        window_slots = 48
        max_next = prices_series.iloc[::-1].rolling(
            window=window_slots, min_periods=1
        ).max().iloc[::-1]
        schedule["max_import_price_next_12h"] = max_next

        # Precompute simple per-day price quantiles for RL gating.
        prices = (
            pd.to_numeric(schedule.get("import_price_sek_kwh"), errors="coerce")
            .dropna()
            .astype(float)
        )
        prices = prices[prices > 0.0]
        if not prices.empty:
            self._price_q25 = float(prices.quantile(0.25))
            self._price_q50 = float(prices.quantile(0.50))
            self._price_q75 = float(prices.quantile(0.75))
        else:
            self._price_q25 = self._price_q50 = self._price_q75 = 0.0

        # Cache simple SoC thresholds for cheap-hour charging guards.
        self._soc_min_kwh = self._capacity_kwh * self._min_soc_percent / 100.0
        # Aim to keep some headroom; treat ~90% as a soft upper bound for auto-charging.
        self._soc_soft_max_kwh = self._capacity_kwh * 0.90

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

        # Default to the planner's baseline actions and export for this slot.
        charge_kw = float(row.get("battery_charge_kw", row.get("charge_kw", 0.0) or 0.0))
        discharge_kw = float(row.get("battery_discharge_kw", 0.0))
        export_kwh = float(row.get("export_kwh", 0.0))

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

        if action is None or not isinstance(action, dict):
            effective_row = row
            # Pure MPC replay: keep baseline charge/discharge/export. We do not
            # currently evolve the internal SoC for this path; `_soc_kwh` is
            # only used for RL clamping and diagnostics.
        else:
            effective_row = row.copy()

            # MPC baseline values
            base_charge_kw = charge_kw
            base_discharge_kw = discharge_kw
            base_export_kwh = export_kwh

            # Requested actions
            req_charge_kw = float(action.get("battery_charge_kw", base_charge_kw) or 0.0)
            req_discharge_kw = float(
                action.get("battery_discharge_kw", base_discharge_kw) or 0.0
            )

            # Clamp to non-negative and power limits
            req_charge_kw = max(0.0, min(req_charge_kw, self._max_charge_power_kw))
            req_discharge_kw = max(0.0, min(req_discharge_kw, self._max_discharge_power_kw))

            # Price-aware mutual exclusivity and simple horizon-based guard.
            # - In cheap hours (price <= q25), prefer charging.
            # - In expensive hours (price >= q75), prefer discharging.
            # - If a much higher price is coming soon, avoid discharging too early.
            current_price = float(row.get("import_price_sek_kwh", 0.0) or 0.0)
            price_q25 = getattr(self, "_price_q25", 0.0)
            price_q75 = getattr(self, "_price_q75", 0.0)
            max_next_price = float(
                row.get("max_import_price_next_12h", current_price) or current_price
            )
            peak_guard_delta = 0.30  # SEK/kWh considered a meaningful spread

            if req_charge_kw > 0.0 and req_discharge_kw > 0.0:
                if current_price <= price_q25:
                    # Cheap slot: enforce pure charging.
                    req_discharge_kw = 0.0
                elif current_price >= price_q75:
                    # Expensive slot: enforce pure discharging.
                    req_charge_kw = 0.0
                else:
                    # Mid-price: keep simple magnitude-based decision.
                    if req_charge_kw >= req_discharge_kw:
                        req_discharge_kw = 0.0
                    else:
                        req_charge_kw = 0.0

            # Additional guard: never discharge in clearly cheap slots.
            if current_price <= price_q25 and req_discharge_kw > 0.0 and req_charge_kw <= 0.0:
                req_discharge_kw = 0.0

            # Pre-peak guard: if a materially higher price is within the look-ahead
            # window, avoid discharging unless SoC is already high.
            if (
                max_next_price >= current_price + peak_guard_delta
                and req_discharge_kw > 0.0
                and self._capacity_kwh > 0.0
            ):
                soc_pct_now = 100.0 * self._soc_kwh / self._capacity_kwh
                if soc_pct_now < 90.0:
                    req_discharge_kw = 0.0

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
            # Export remains whatever the planner scheduled; RL does not override it in v1.
            export_kwh = base_export_kwh

            effective_row["battery_charge_kw"] = charge_kw
            effective_row["battery_discharge_kw"] = discharge_kw
            effective_row["export_kwh"] = export_kwh

            # Update internal SoC estimate based on effective charge/discharge.
            # Convention: positive (charge_kw - discharge_kw) increases SoC.
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

        if self._capacity_kwh > 0.0:
            soc_percent_internal = 100.0 * self._soc_kwh / self._capacity_kwh
        else:
            soc_percent_internal = 0.0

        info = {
            "day": self._current_day.isoformat() if self._current_day else None,
            "index": self._current_idx - 1,
            "done": done,
            # Effective actions and internal SoC used for this slot. These are
            # the clamped values that actually drive reward and SoC updates.
            "battery_charge_kw": float(charge_kw),
            "battery_discharge_kw": float(discharge_kw),
            # Convention: positive = charging the battery, negative = discharging.
            "net_battery_kw": float(charge_kw - discharge_kw),
            "export_kwh": float(export_kwh),
            "slot_hours": float(slot_hours),
            "soc_kwh": float(self._soc_kwh),
            "soc_percent_internal": float(soc_percent_internal),
            "projected_soc_percent": float(row.get("projected_soc_percent", 0.0) or 0.0),
        }
        return StepResult(next_state=next_state, reward=reward, done=done, info=info)
