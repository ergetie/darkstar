from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np


@dataclass
class AntaresRLPolicyV1:
    """
    RL-based Antares policy wrapper (v1).

    This loads a trained RL model (e.g. Stable-Baselines3 PPO) from disk and
    exposes a `.predict(state)` interface compatible with the existing
    Antares shadow runner (returns a dict with charge/discharge/export).
    """

    model: Any

    @classmethod
    def load_from_dir(cls, path: str | Path) -> "AntaresRLPolicyV1":
        from stable_baselines3 import PPO

        model_path = Path(path) / "model.zip"
        if not model_path.exists():
            raise FileNotFoundError(f"RL model not found at {model_path}")
        model = PPO.load(model_path.as_posix())
        return cls(model=model)

    def predict(self, state: np.ndarray) -> Dict[str, float]:
        if self.model is None:
            return {
                "battery_charge_kw": 0.0,
                "battery_discharge_kw": 0.0,
                "export_kw": 0.0,
            }
        x = np.asarray(state, dtype=float).reshape(1, -1)
        action, _ = self.model.predict(x, deterministic=True)
        action = np.asarray(action, dtype=float).flatten()
        if action.shape[0] < 3:
            return {
                "battery_charge_kw": 0.0,
                "battery_discharge_kw": 0.0,
                "export_kw": 0.0,
            }
        return {
            "battery_charge_kw": float(action[0]),
            "battery_discharge_kw": float(action[1]),
            "export_kw": float(action[2]),
        }

