"""
Gym-style adapter for AntaresEnvV2 (RL v2 lab).

This wraps the sequence-based AntaresEnvV2 into a simple Gym interface
for PPO training:
    - Observation: flat float32 vector (see RlV2StateSpec.flat_dim).
    - Action: 3D Box [charge_kw, discharge_kw, export_kw_placeholder].

Episodes are single historical days; the day list is loaded from
data_quality_daily (clean/mask_battery) similar to AntaresRLEnv.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

import gymnasium as gym
import numpy as np

from backend.learning import LearningEngine, get_learning_engine
from ml.rl_v2.contract import RlV2StateSpec
from ml.rl_v2.env_v2 import AntaresEnvV2

if TYPE_CHECKING:
    from collections.abc import Sequence


def _load_candidate_days(engine: LearningEngine, *, min_days: int = 30) -> list[str]:
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


class AntaresRLEnvV2(gym.Env):
    metadata: ClassVar[dict[str, list[str]]] = {"render_modes": []}

    def __init__(self, config_path: str = "config.yaml", seq_len: int = 48) -> None:
        super().__init__()
        self.engine: LearningEngine = get_learning_engine()
        self.env = AntaresEnvV2(config_path=config_path, seq_len=seq_len)
        self.days = _load_candidate_days(self.engine)
        self._iterator = DayIterator(self.days)
        self._current_day: str | None = None

        spec = RlV2StateSpec(seq_len=seq_len)
        self.observation_space = gym.spaces.Box(
            low=-1e6, high=1e6, shape=(spec.flat_dim,), dtype=np.float32
        )
        # Actions are clamped by AntaresEnvV2; provide generous bounds here.
        self.action_space = gym.spaces.Box(
            low=np.array([0.0, 0.0, 0.0], dtype=np.float32),
            high=np.array([10.0, 10.0, 10.0], dtype=np.float32),
            dtype=np.float32,
        )

    @staticmethod
    def _sanitize_state(state: np.ndarray) -> np.ndarray:
        arr = np.asarray(state, dtype=np.float32)
        if not np.isfinite(arr).all():
            arr = np.nan_to_num(arr, nan=0.0, posinf=1e6, neginf=-1e6)
        return arr

    def reset(
        self, *, seed: int | None = None, options: dict[str, Any] | None = None
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)
        max_retries = len(self.days)
        attempts = 0

        while attempts < max_retries:
            day = self._iterator.next_day()
            if day is None:
                raise RuntimeError("No candidate days available for AntaresRLEnvV2.")

            try:
                self._current_day = day
                state = self.env.reset(day)
                return self._sanitize_state(state), {"day": day}
            except Exception:
                # Warning: Skipping day due to error (likely missing data)
                attempts += 1

        raise RuntimeError(f"Failed to find a valid simulation day after {max_retries} attempts.")

    def step(self, action: np.ndarray) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        action = np.asarray(action, dtype=float).flatten()
        if action.shape[0] < 3:
            raise ValueError("AntaresRLEnvV2 action must have at least 3 elements.")
        action_dict: dict[str, Any] = {
            "battery_charge_kw": float(max(0.0, action[0])),
            "battery_discharge_kw": float(max(0.0, action[1])),
            # Export still unused in env_v2 (derived from flows), keep placeholder.
        }
        result = self.env.step(action_dict)
        next_state = self._sanitize_state(result.next_state)
        reward = float(result.reward)
        if not np.isfinite(reward):
            reward = 0.0
        info = dict(result.info)
        if self._current_day is not None:
            info.setdefault("day", self._current_day)
        terminated = bool(result.done)
        truncated = False
        return next_state, reward, terminated, truncated, info
