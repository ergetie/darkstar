"""PPO fine-tuning on top of BC v2 (Rev 84, lab only).

Usage (dev only):
    PYTHONPATH=. ./venv/bin/python ml/rl_v2/train_ppo_v2.py --timesteps 1_000_000
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import gymnasium as gym
import numpy as np
import torch
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv

from backend.learning import LearningEngine, get_learning_engine
from ml.rl_v2.contract import RlV2StateSpec
from ml.rl_v2.ppo_env_v2 import AntaresRLEnvV2


@dataclass
class RlV2PpoConfig:
    timesteps: int
    learning_rate: float
    gamma: float
    n_steps: int
    batch_size: int
    seed: int
    seq_len: int
    n_envs: int
    hidden_dim: int
    layer_count: int


def _get_engine() -> LearningEngine:
    engine = get_learning_engine()
    if not isinstance(engine, LearningEngine):
        raise TypeError("get_learning_engine() did not return a LearningEngine instance")
    return engine


class CostLoggingCallback(BaseCallback):
    def __init__(self, verbose: int = 0) -> None:
        super().__init__(verbose)

    def _on_step(self) -> bool:
        return True


def _make_env_factory(config_path: str, seq_len: int):
    """Factory for picklable env creators."""

    def _init() -> gym.Env:
        return AntaresRLEnvV2(config_path=config_path, seq_len=seq_len)

    return _init


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Train PPO on AntaresEnvV2 (lab-only).",
    )
    parser.add_argument(
        "--timesteps",
        type=int,
        default=1_000_000,
        help="Total PPO timesteps (default: 1_000_000).",
    )
    parser.add_argument(
        "--seq-len",
        type=int,
        default=48,
        help="Sequence length for v2 state (default: 48).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed.",
    )
    parser.add_argument(
        "--n-envs",
        type=int,
        default=1,
        help="Number of parallel environments (default: 1). Increase for higher GPU usage.",
    )
    parser.add_argument(
        "--hidden-dim",
        type=int,
        default=64,
        help="Width of hidden layers (default: 64). Increase to 256/512 for GPU benchmarking.",
    )
    parser.add_argument(
        "--layer-count",
        type=int,
        default=2,
        help="Number of hidden layers (default: 2).",
    )
    args = parser.parse_args()

    cfg = RlV2PpoConfig(
        timesteps=int(args.timesteps),
        learning_rate=1e-4,
        gamma=0.995,
        n_steps=4096,
        batch_size=64,
        seed=int(args.seed),
        seq_len=int(args.seq_len),
        n_envs=int(args.n_envs),
        hidden_dim=int(args.hidden_dim),
        layer_count=int(args.layer_count),
    )

    np.random.seed(cfg.seed)
    torch.manual_seed(cfg.seed)

    # Note: Engine is initialized in main process for schema checks,
    # but workers will create their own instances.
    engine = _get_engine()

    # Vectorized Environment Setup
    # SubprocVecEnv is used for n_envs > 1 to bypass GIL and utilize multi-core CPUs
    vec_env_cls = SubprocVecEnv if cfg.n_envs > 1 else DummyVecEnv

    env = make_vec_env(
        _make_env_factory("config.yaml", cfg.seq_len),
        n_envs=cfg.n_envs,
        seed=cfg.seed,
        vec_env_cls=vec_env_cls,
    )

    # Custom Network Architecture
    # Larger networks allow the GPU to do more work per batch, reducing overhead ratio.
    net_arch = dict(pi=[cfg.hidden_dim] * cfg.layer_count, vf=[cfg.hidden_dim] * cfg.layer_count)

    print(f"[rl-v2-ppo] Starting training with:")
    print(f"  Environments: {cfg.n_envs} ({'Parallel' if cfg.n_envs > 1 else 'Sequential'})")
    print(f"  Network:      {cfg.layer_count}x{cfg.hidden_dim} (MlpPolicy)")
    print(f"  Device:       Auto (Will use GPU if available)")

    model = PPO(
        "MlpPolicy",
        env,
        learning_rate=cfg.learning_rate,
        gamma=cfg.gamma,
        n_steps=cfg.n_steps,
        batch_size=cfg.batch_size,
        verbose=1,
        seed=cfg.seed,
        device="auto",
        policy_kwargs={"net_arch": net_arch},
    )

    callback = CostLoggingCallback()
    model.learn(total_timesteps=cfg.timesteps, callback=callback)

    run_id = str(uuid.uuid4())
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    base_dir = Path("ml/models/antares_rl_v2_ppo")
    base_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir = base_dir / f"antares_rl_v2_ppo_{ts}_{run_id[:8]}"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    model_path = artifact_dir / "model.zip"
    model.save(model_path.as_posix())

    print("[rl-v2-ppo] Saved PPO model to", model_path)

    hyper = asdict(cfg)
    metrics: Dict[str, Any] = {"note": "RL v2 PPO lab run (env_v2 sequence state)."}

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
            {
                "run_id": run_id,
                "created_at": datetime.utcnow().isoformat(),
                "algo": "ppo_v2_seq",
                "state_version": f"rl_v2_seq_state_v1_len{cfg.seq_len}",
                "action_version": "rl_action_v1",
                "train_start_date": None,
                "train_end_date": None,
                "val_start_date": None,
                "val_end_date": None,
                "hyperparams_json": json.dumps(hyper, ensure_ascii=False),
                "metrics_json": json.dumps(metrics, ensure_ascii=False),
                "artifact_dir": artifact_dir.as_posix(),
            },
        )
        conn.commit()

    print("[rl-v2-ppo] Completed PPO training run:")
    print(f"  run_id:      {run_id}")
    print(f"  artifact_dir:{artifact_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
