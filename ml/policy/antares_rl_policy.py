from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    def load_from_dir(cls, path: str | Path) -> AntaresRLPolicyV1:
        from stable_baselines3 import PPO

        model_path = Path(path) / "model.zip"
        if not model_path.exists():
            raise FileNotFoundError(f"RL model not found at {model_path}")
        # Always load RL models on CPU to avoid CUDA issues on older GPUs.
        model = PPO.load(model_path.as_posix(), device="cpu")
        return cls(model=model)

    def predict(self, state: np.ndarray) -> dict[str, float]:
        if self.model is None:
            return {
                "battery_charge_kw": 0.0,
                "battery_discharge_kw": 0.0,
                "export_kw": 0.0,
            }

        # Sanitize input state to avoid NaNs propagating through the network.
        x = np.asarray(state, dtype=float).reshape(1, -1)
        if not np.isfinite(x).all():
            x = np.nan_to_num(x, nan=0.0, posinf=1e6, neginf=-1e6)

        action, _ = self.model.predict(x, deterministic=True)
        action = np.asarray(action, dtype=float).flatten()

        # If network outputs NaNs or infs, fall back to safe zeros.
        if action.shape[0] < 3 or not np.isfinite(action).all():
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


@dataclass
class AntaresRLPolicyOracleBC:
    """
    Oracle-guided Antares policy wrapper (v2, behaviour cloning).

    Loads a simple PyTorch MLP trained to imitate the Oracle MILP actions
    given the Rev 81 8-D state vector and exposes `.predict(state)` with
    the same action dict as v1.
    """

    model: Any

    @classmethod
    def load_from_dir(cls, path: str | Path) -> AntaresRLPolicyOracleBC:
        import torch

        from ml.train_antares_oracle_bc import OracleBcNet

        base = Path(path)
        model_path = base / "model.pt"
        if not model_path.exists():
            raise FileNotFoundError(f"Oracle BC model not found at {model_path}")

        # Rev 81 state: 8-D, action: 3-D.
        net = OracleBcNet(in_dim=8, hidden_dim=64, out_dim=3)
        state_dict = torch.load(model_path.as_posix(), map_location="cpu")
        net.load_state_dict(state_dict)
        net.eval()
        return cls(model=net)

    def predict(self, state: np.ndarray) -> dict[str, float]:
        import torch

        if self.model is None:
            return {
                "battery_charge_kw": 0.0,
                "battery_discharge_kw": 0.0,
                "export_kw": 0.0,
            }

        x = np.asarray(state, dtype=float).reshape(1, -1)
        if not np.isfinite(x).all():
            x = np.nan_to_num(x, nan=0.0, posinf=1e6, neginf=-1e6)

        with torch.no_grad():
            inp = torch.from_numpy(x.astype(np.float32))
            out = self.model(inp).cpu().numpy().reshape(-1)

        if out.shape[0] < 3 or not np.isfinite(out).all():
            return {
                "battery_charge_kw": 0.0,
                "battery_discharge_kw": 0.0,
                "export_kw": 0.0,
            }
        return {
            "battery_charge_kw": float(out[0]),
            "battery_discharge_kw": float(out[1]),
            "export_kw": float(out[2]),
        }
