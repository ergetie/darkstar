from __future__ import annotations

"""
Train Antares RL Agent v1 (Rev 76).

This script trains a PPO-based RL agent on top of AntaresMPCEnv using the
AntaresRLEnv adapter and logs runs into antares_rl_runs.

Usage (from project root, after installing RL deps):
    PYTHONPATH=. python ml/train_antares_rl.py --timesteps 200_000
"""

import argparse
import json
import os
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import numpy as np

from learning import LearningEngine, get_learning_engine
from ml.rl.antares_env import AntaresRLEnv


def _ensure_rl_schema(engine: LearningEngine) -> None:
    with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS antares_rl_runs (
                run_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                algo TEXT NOT NULL,
                state_version TEXT NOT NULL,
                action_version TEXT NOT NULL,
                train_start_date TEXT,
                train_end_date TEXT,
                val_start_date TEXT,
                val_end_date TEXT,
                hyperparams_json TEXT,
                metrics_json TEXT,
                artifact_dir TEXT NOT NULL
            )
            """
        )
        conn.commit()


def _load_train_val_bounds(engine: LearningEngine) -> Dict[str, str]:
    """Derive a simple time-based train/val split from data_quality_daily."""
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
    if not days:
        raise RuntimeError("No clean/mask_battery days in data_quality_daily.")

    n = len(days)
    split_idx = max(1, int(n * 0.8))
    train_days = days[:split_idx]
    val_days = days[split_idx:]

    payload = {
        "train_start_date": train_days[0],
        "train_end_date": train_days[-1],
        "val_start_date": val_days[0] if val_days else None,
        "val_end_date": val_days[-1] if val_days else None,
    }
    return payload


def _make_vec_env(config_path: str = "config.yaml"):
    """Create a Gymnasium-compatible vectorized environment."""
    import gymnasium as gym

    class _GymAdapter(gym.Env):
        metadata = {"render.modes": []}

        def __init__(self):
            super().__init__()
            self._env = AntaresRLEnv(config_path=config_path)
            # State: 6-dim vector from AntaresMPCEnv
            self.observation_space = gym.spaces.Box(
                low=-np.inf, high=np.inf, shape=(6,), dtype=np.float32
            )
            # Action: 3-dim [charge_kw, discharge_kw, export_kw]
            self.action_space = gym.spaces.Box(
                low=np.array([0.0, 0.0, 0.0], dtype=np.float32),
                high=np.array([10.0, 10.0, 10.0], dtype=np.float32),
                dtype=np.float32,
            )

        def reset(self, *, seed: int | None = None, options: dict | None = None):
            if seed is not None:
                np.random.seed(seed)
            state = self._env.reset()
            return state, {}

        def step(self, action):
            next_state, reward, done, info = self._env.step(action)
            return next_state, reward, done, False, info

    def _make():
        return _GymAdapter()

    return _make


@dataclass
class RlRunConfig:
    algo: str
    timesteps: int
    learning_rate: float
    gamma: float
    n_steps: int
    batch_size: int
    seed: int


def main() -> int:
    parser = argparse.ArgumentParser(description="Train Antares RL Agent v1 (PPO).")
    parser.add_argument(
        "--timesteps",
        type=int,
        default=200_000,
        help="Total training timesteps (default: 200k).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility.",
    )
    args = parser.parse_args()

    engine = get_learning_engine()
    _ensure_rl_schema(engine)
    split = _load_train_val_bounds(engine)

    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv

    run_id = str(uuid.uuid4())
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    base_dir = Path("ml/models/antares_rl_v1")
    base_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir = base_dir / f"antares_rl_v1_{ts}_{run_id[:8]}"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    cfg = RlRunConfig(
        algo="ppo",
        timesteps=int(args.timesteps),
        learning_rate=1e-4,
        gamma=0.995,
        n_steps=4096,
        batch_size=64,
        seed=int(args.seed),
    )

    env_fn = _make_vec_env()
    vec_env = DummyVecEnv([env_fn])

    model = PPO(
        "MlpPolicy",
        vec_env,
        learning_rate=cfg.learning_rate,
        gamma=cfg.gamma,
        n_steps=cfg.n_steps,
        batch_size=cfg.batch_size,
        verbose=1,
        seed=cfg.seed,
        device="cpu",
    )

    model.learn(total_timesteps=cfg.timesteps)

    # Save model artefacts
    model_path = artifact_dir / "model.zip"
    model.save(model_path.as_posix())

    hyperparams = asdict(cfg)

    metrics = {
        "note": "Initial RL run; detailed reward/cost metrics to be computed by evaluation script.",
    }

    run_row = {
        "run_id": run_id,
        "created_at": datetime.utcnow().isoformat(),
        "algo": cfg.algo,
        "state_version": "rl_state_v1",
        "action_version": "rl_action_v1",
        "train_start_date": split["train_start_date"],
        "train_end_date": split["train_end_date"],
        "val_start_date": split["val_start_date"],
        "val_end_date": split["val_end_date"],
        "hyperparams_json": json.dumps(hyperparams, ensure_ascii=False),
        "metrics_json": json.dumps(metrics, ensure_ascii=False),
        "artifact_dir": artifact_dir.as_posix(),
    }

    with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
        conn.execute(
            """
            INSERT INTO antares_rl_runs (
                run_id,
                created_at,
                algo,
                state_version,
                action_version,
                train_start_date,
                train_end_date,
                val_start_date,
                val_end_date,
                hyperparams_json,
                metrics_json,
                artifact_dir
            ) VALUES (
                :run_id,
                :created_at,
                :algo,
                :state_version,
                :action_version,
                :train_start_date,
                :train_end_date,
                :val_start_date,
                :val_end_date,
                :hyperparams_json,
                :metrics_json,
                :artifact_dir
            )
            """,
            run_row,
        )
        conn.commit()

    print("[rl-train] Completed RL training run:")
    print(f"  run_id:      {run_id}")
    print(f"  artifact_dir:{artifact_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
