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
        return self._sanitize_state(state)

    def step(self, action: np.ndarray) -> Tuple[np.ndarray, float, bool, Dict[str, Any]]:
        """
        Take an environment step.

        The action is expected to be a 3D vector:
            [battery_charge_kw, battery_discharge_kw, export_kw]
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
                "export_kw": float(action[2]),
            }

        result = self.env.step(action=action_dict)
        next_state = self._sanitize_state(result.next_state)
        info = dict(result.info)
        if self._current_day is not None:
            info.setdefault("day", self._current_day)
        return next_state, float(result.reward), bool(result.done), info
