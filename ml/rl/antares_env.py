from __future__ import annotations

"""
Gym-style RL wrapper around AntaresMPCEnv (Rev 76).

This adapter exposes a minimal OpenAI Gym / Gymnasium style API:
    - reset() -> np.ndarray
    - step(action) -> (next_state, reward, done, info)

It iterates over a list of historical days (clean/mask_battery) and
delegates per-slot dynamics and rewards to AntaresMPCEnv.
"""

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from backend.learning import LearningEngine, get_learning_engine
from ml.simulation.env import AntaresMPCEnv


def _load_candidate_days(engine: LearningEngine, *, min_days: int = 30) -> list[str]:
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

    def next_day(self) -> str | None:
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
        self._current_day: str | None = None
        self._low_price_threshold: float | None = None
        self._high_price_threshold: float | None = None
        self._initial_soc_percent: float | None = None

    @staticmethod
    def _sanitize_state(state: np.ndarray) -> np.ndarray:
        """Replace NaN/inf in the state vector with finite fallbacks."""
        arr = np.asarray(state, dtype=np.float32)
        if not np.isfinite(arr).all():
            arr = np.nan_to_num(arr, nan=0.0, posinf=1e6, neginf=-1e6)
        return arr

    def reset(self) -> np.ndarray:
        """Reset to the next day and return initial state."""
        max_retries = len(self.days)
        attempts = 0

        while attempts < max_retries:
            day = self._iterator.next_day()
            if day is None:
                raise RuntimeError("No candidate days available for AntaresRLEnv.")

            try:
                self._current_day = day
                state = self.env.reset(day)
                # Compute simple per-day price thresholds for reward shaping:
                # - low threshold: 80% of median non-zero import price
                # - high threshold: 120% of median (rough proxy for "expensive")
                schedule = getattr(self.env, "_schedule", None)
                threshold: float | None = None
                high_threshold: float | None = None
                if schedule is not None:
                    df = schedule.copy()
                    if (
                        df.index.name in {"start_time", "slot_start"}
                        and "start_time" not in df.columns
                    ):
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
                        high_threshold = 1.2 * median_price
                self._low_price_threshold = threshold
                self._high_price_threshold = high_threshold

                # Cache initial SoC percent for terminal shaping.
                try:
                    capacity_kwh = float(getattr(self.env, "_capacity_kwh", 0.0) or 0.0)
                    soc_kwh = float(getattr(self.env, "_soc_kwh", 0.0) or 0.0)
                    if capacity_kwh > 0.0:
                        self._initial_soc_percent = 100.0 * soc_kwh / capacity_kwh
                    else:
                        self._initial_soc_percent = None
                except Exception:
                    self._initial_soc_percent = None

                return self._sanitize_state(state)

            except Exception:
                # If reset failed (e.g. empty data), just try the next day
                # print(f"Warning: Skipping day {day} due to error: {e}")
                attempts += 1

        raise RuntimeError(f"Failed to find a valid simulation day after {max_retries} attempts.")

    def step(self, action: np.ndarray) -> tuple[np.ndarray, float, bool, dict[str, Any]]:
        """
        Take an environment step.

        The action is expected to be a 3D vector:
            [battery_charge_kw, battery_discharge_kw, export_kw_placeholder]
        """
        if action is None:
            action_dict: dict[str, Any] = {}
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
        # Reward shaping around cheap/expensive prices. This does not change
        # the cost metric used for evaluation, only the learning signal.
        if (
            self._low_price_threshold is not None or self._high_price_threshold is not None
        ) and action is not None:
            try:
                # result.info["index"] holds the slot index in the schedule.
                idx = int(result.info.get("index", -1))
                schedule = getattr(self.env, "_schedule", None)
                if schedule is not None and 0 <= idx < len(schedule):
                    row = schedule.iloc[idx]
                    price = float(row.get("import_price_sek_kwh", 0.0) or 0.0)
                    low_thr = self._low_price_threshold
                    high_thr = self._high_price_threshold

                    charge_kw = float(
                        result.info.get(
                            "battery_charge_kw",
                            action_dict.get("battery_charge_kw", 0.0),
                        )
                        or 0.0
                    )
                    discharge_kw = float(
                        result.info.get(
                            "battery_discharge_kw",
                            action_dict.get("battery_discharge_kw", 0.0),
                        )
                        or 0.0
                    )
                    soc_pct = float(result.info.get("soc_percent_internal", 0.0) or 0.0)

                    # Cheap hours: strongly discourage discharging, gently reward charging
                    # when SoC is not already high.
                    if low_thr is not None and price < low_thr:
                        if discharge_kw > 0.0:
                            # Stronger penalty per kW of discharge in cheap hours.
                            reward -= 0.5 * discharge_kw
                        if soc_pct < 80.0 and charge_kw > 0.0:
                            # Small bonus for charging when cheap and SoC < 80%.
                            reward += 0.1 * charge_kw

                    # Expensive hours: mild penalty for sitting on energy when SoC is high
                    # and very little discharge is used.
                    if high_thr is not None and price > high_thr and soc_pct > 60.0:
                        if discharge_kw < 0.25:
                            reward -= 0.1
            except Exception:
                # Never let shaping break the environment.
                pass
        # Terminal shaping: encourage ending the day near the initial SoC.
        if result.done and self._initial_soc_percent is not None:
            try:
                final_soc_pct = float(result.info.get("soc_percent_internal", 0.0) or 0.0)
                diff = abs(final_soc_pct - self._initial_soc_percent)
                # Small penalty proportional to deviation from starting SoC.
                reward -= 0.05 * diff
            except Exception:
                pass
        if not np.isfinite(reward):
            reward = 0.0

        info = dict(result.info)
        if self._current_day is not None:
            info.setdefault("day", self._current_day)
        return next_state, reward, bool(result.done), info
