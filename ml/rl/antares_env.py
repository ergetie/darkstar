from __future__ import annotations

"""
Gym-style RL wrapper around AntaresMPCEnv (Rev 76).

This adapter exposes a minimal OpenAI Gym / Gymnasium style API:
    - reset() -> np.ndarray
    - step(action) -> (next_state, reward, done, info)

It iterates over a list of historical days (clean/mask_battery) and
delegates per-slot dynamics and rewards to AntaresMPCEnv.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import sqlite3

from learning import LearningEngine, get_learning_engine
from ml.simulation.env import AntaresMPCEnv


def _load_candidate_days(engine: LearningEngine, *, min_days: int = 30) -> List[str]:
    """Return a chronologically ordered list of clean/mask_battery days."""
    with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
        rows = conn.execute(
            """
            SELECT date
            FROM data_quality_daily
            WHERE status IN ('clean', 'mask_battery')
            ORDER BY date ASC
            """
        ).fetchall()
    days = [r[0] for r in rows]
    if len(days) < min_days:
        return days
    return days


@dataclass
class DayIterator:
    days: Sequence[str]
    index: int = 0

    def next_day(self) -> Optional[str]:
        if not self.days:
            return None
        day = self.days[self.index]
        self.index = (self.index + 1) % len(self.days)
        return day


class AntaresRLEnv:
    """
    Thin RL environment wrapper around AntaresMPCEnv.

    This class intentionally does not import Gym/Gymnasium directly to
    avoid hard dependency at import time; the training script can adapt
    it to a concrete Env implementation.
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.engine: LearningEngine = get_learning_engine()
        self.env = AntaresMPCEnv(config_path=config_path)
        self.days = _load_candidate_days(self.engine)
        self._iterator = DayIterator(self.days)
        self._current_day: Optional[str] = None
        self._low_price_threshold: Optional[float] = None

    @staticmethod
    def _sanitize_state(state: np.ndarray) -> np.ndarray:
        """Replace NaN/inf in the state vector with finite fallbacks."""
        arr = np.asarray(state, dtype=np.float32)
        if not np.isfinite(arr).all():
            arr = np.nan_to_num(arr, nan=0.0, posinf=1e6, neginf=-1e6)
        return arr

    def reset(self) -> np.ndarray:
        """Reset to the next day and return initial state."""
        day = self._iterator.next_day()
        if day is None:
            raise RuntimeError("No candidate days available for AntaresRLEnv.")
        self._current_day = day
        state = self.env.reset(day)
        # Compute a simple per-day low-price threshold for reward shaping:
        # use 80% of the median non-zero import price for the day.
        schedule = getattr(self.env, "_schedule", None)
        threshold: Optional[float] = None
        if schedule is not None:
            df = schedule.copy()
            if df.index.name in {"start_time", "slot_start"} and "start_time" not in df.columns:
                df = df.reset_index()
            prices = (
                pd.to_numeric(df.get("import_price_sek_kwh"), errors="coerce")
                .dropna()
                .astype(float)
            )
            prices = prices[prices > 0.0]
            if not prices.empty:
                median_price = float(prices.median())
                threshold = 0.8 * median_price
        self._low_price_threshold = threshold

        return self._sanitize_state(state)

    def step(self, action: np.ndarray) -> Tuple[np.ndarray, float, bool, Dict[str, Any]]:
        """
        Take an environment step.

        The action is expected to be a 3D vector:
            [battery_charge_kw, battery_discharge_kw, export_kw_placeholder]
        """
        if action is None:
            action_dict: Dict[str, Any] = {}
        else:
            action = np.asarray(action, dtype=float).flatten()
            if action.shape[0] < 3:
                raise ValueError("AntaresRLEnv action must have at least 3 elements.")
            action_dict = {
                "battery_charge_kw": float(action[0]),
                "battery_discharge_kw": float(action[1]),
                # RL v1 does not override export; third component is ignored.
                "export_kw": 0.0,
            }

        result = self.env.step(action=action_dict)
        next_state = self._sanitize_state(result.next_state)

        reward = float(result.reward)
        # Reward shaping: discourage discharging when price is below a per-day
        # threshold (roughly "cheap" hours). This does not change the cost
        # metric used for evaluation, only the learning signal.
        if self._low_price_threshold is not None and action is not None:
            try:
                # result.info["index"] holds the slot index in the schedule.
                idx = int(result.info.get("index", -1))
                schedule = getattr(self.env, "_schedule", None)
                if schedule is not None and 0 <= idx < len(schedule):
                    row = schedule.iloc[idx]
                    price = float(row.get("import_price_sek_kwh", 0.0) or 0.0)
                    discharge_kw = float(action_dict.get("battery_discharge_kw", 0.0) or 0.0)
                    if price < self._low_price_threshold and discharge_kw > 0.0:
                        # Apply a modest penalty per kW of discharge in cheap hours.
                        reward -= 0.25 * discharge_kw
            except Exception:
                # Never let shaping break the environment.
                pass
        if not np.isfinite(reward):
            reward = 0.0

        info = dict(result.info)
        if self._current_day is not None:
            info.setdefault("day", self._current_day)
        return next_state, reward, bool(result.done), info
