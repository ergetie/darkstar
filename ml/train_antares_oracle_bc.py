from __future__ import annotations

"""
Train an Oracle-guided Antares policy via behaviour cloning (Rev 82).

Usage:
    PYTHONPATH=. ./venv/bin/python ml/train_antares_oracle_bc.py --days 60
"""

import argparse
import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from learning import LearningEngine, get_learning_engine
from torch.utils.data import DataLoader, TensorDataset

from ml.benchmark.milp_solver import solve_optimal_schedule
from ml.simulation.env import AntaresMPCEnv


@dataclass
class OracleBcConfig:
    days: int
    hidden_dim: int
    batch_size: int
    epochs: int
    learning_rate: float
    seed: int


class OracleBcNet(nn.Module):
    def __init__(self, in_dim: int, hidden_dim: int, out_dim: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, out_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


def _load_candidate_days(engine: LearningEngine, max_days: int) -> list[str]:
    """Return the most recent clean/mask_battery days, oldest first."""
    with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
        rows = conn.execute(
            """
            SELECT date
            FROM data_quality_daily
            WHERE status IN ('clean', 'mask_battery')
            ORDER BY date DESC
            LIMIT ?
            """,
            (max_days,),
        ).fetchall()
    days = [r[0] for r in rows]
    days.reverse()
    return days


def _build_day_pairs(
    env: AntaresMPCEnv,
    day: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Build (state, oracle_action) pairs for a single day."""
    # MPC-based schedule and state vectors
    env.reset(day)
    schedule = env._schedule.copy()  # type: ignore[attr-defined]
    if schedule.index.name in {"start_time", "slot_start"} and "start_time" not in schedule.columns:
        schedule = schedule.reset_index()
    schedule["start_time"] = np.asarray(schedule["start_time"], dtype="datetime64[ns]")

    # Oracle schedule
    oracle_df = solve_optimal_schedule(day)
    oracle_df = oracle_df.copy()
    oracle_df["start_time"] = np.asarray(oracle_df["slot_start"], dtype="datetime64[ns]")

    joined = schedule.merge(oracle_df, on="start_time", how="inner", suffixes=("", "_oracle"))
    if joined.empty:
        return np.empty((0, 8), dtype=np.float32), np.empty((0, 3), dtype=np.float32)

    states: list[list[float]] = []
    actions: list[list[float]] = []

    for _, row in joined.iterrows():
        # Build state via the same helper used in RL env.
        s_vec = env._build_state_vector(row)  # type: ignore[attr-defined]
        if s_vec.shape[0] != 8:
            continue

        slot_hours = float(row.get("slot_hours", 0.25) or 0.25)
        if slot_hours <= 0.0:
            slot_hours = 0.25

        charge_kwh = float(row.get("oracle_charge_kwh", 0.0) or 0.0)
        discharge_kwh = float(row.get("oracle_discharge_kwh", 0.0) or 0.0)
        export_kwh = float(row.get("oracle_grid_export_kwh", 0.0) or 0.0)

        charge_kw = charge_kwh / slot_hours
        discharge_kw = discharge_kwh / slot_hours
        export_kw = export_kwh / slot_hours

        states.append(s_vec.tolist())
        actions.append([charge_kw, discharge_kw, export_kw])

    if not states:
        return np.empty((0, 8), dtype=np.float32), np.empty((0, 3), dtype=np.float32)

    x = np.asarray(states, dtype=np.float32)
    y = np.asarray(actions, dtype=np.float32)
    return x, y


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Train Oracle-guided Antares policy via behaviour cloning.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=60,
        help="Number of recent clean/mask_battery days to use (default: 60).",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=30,
        help="Number of training epochs (default: 30).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility.",
    )
    args = parser.parse_args()

    cfg = OracleBcConfig(
        days=int(args.days),
        hidden_dim=64,
        batch_size=256,
        epochs=int(args.epochs),
        learning_rate=1e-3,
        seed=int(args.seed),
    )

    np.random.seed(cfg.seed)
    torch.manual_seed(cfg.seed)

    engine = get_learning_engine()
    if not isinstance(engine, LearningEngine):
        raise TypeError("get_learning_engine() did not return a LearningEngine instance")

    days = _load_candidate_days(engine, cfg.days)
    if not days:
        raise SystemExit("[oracle-bc] No candidate days found in data_quality_daily.")

    env = AntaresMPCEnv(config_path="config.yaml")

    xs: list[np.ndarray] = []
    ys: list[np.ndarray] = []

    print(f"[oracle-bc] Building dataset from {len(days)} days...")
    for day in days:
        x_day, y_day = _build_day_pairs(env, day)
        if x_day.size == 0:
            continue
        xs.append(x_day)
        ys.append(y_day)
        print(f"[oracle-bc]   {day}: {len(x_day)} slots")

    if not xs:
        raise SystemExit("[oracle-bc] No training samples collected.")

    X = np.concatenate(xs, axis=0)
    Y = np.concatenate(ys, axis=0)

    # Sanitize dataset: drop any rows with NaN/inf in state or action.
    mask_finite = np.isfinite(X).all(axis=1) & np.isfinite(Y).all(axis=1)
    if not mask_finite.any():
        raise SystemExit("[oracle-bc] All samples contain NaN/inf; nothing to train on.")
    if not mask_finite.all():
        before = len(mask_finite)
        after = int(mask_finite.sum())
        print(f"[oracle-bc] Dropping {before - after} non-finite samples (keeping {after}).")
    X = X[mask_finite]
    Y = Y[mask_finite]

    print(f"[oracle-bc] Total samples (finite): {len(X)}")

    dataset = TensorDataset(torch.from_numpy(X), torch.from_numpy(Y))
    loader = DataLoader(dataset, batch_size=cfg.batch_size, shuffle=True)

    model = OracleBcNet(in_dim=X.shape[1], hidden_dim=cfg.hidden_dim, out_dim=Y.shape[1])
    optimizer = optim.Adam(model.parameters(), lr=cfg.learning_rate)
    loss_fn = nn.MSELoss()

    model.train()
    for epoch in range(cfg.epochs):
        epoch_loss = 0.0
        for batch_x, batch_y in loader:
            optimizer.zero_grad()
            preds = model(batch_x)
            loss = loss_fn(preds, batch_y)
            loss.backward()
            optimizer.step()
            epoch_loss += float(loss.item()) * batch_x.size(0)
        epoch_loss /= len(dataset)
        print(f"[oracle-bc] Epoch {epoch + 1}/{cfg.epochs} - MSE loss: {epoch_loss:.4f}")

    run_id = str(uuid.uuid4())
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    base_dir = Path("ml/models/antares_rl_v2_bc")
    base_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir = base_dir / f"antares_rl_v2_bc_{ts}_{run_id[:8]}"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    model_path = artifact_dir / "model.pt"
    torch.save(model.state_dict(), model_path.as_posix())

    print("[oracle-bc] Saved model to", model_path)

    # Log run in antares_rl_runs for reuse in evaluation tooling.
    hyper = asdict(cfg)
    metrics = {"note": "Oracle behaviour cloning run (v2_bc)."}

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
                "algo": "oracle_bc",
                "state_version": "rl_state_v2_oracle_bc",
                "action_version": "rl_action_v1",
                "train_start_date": days[0],
                "train_end_date": days[-1],
                "val_start_date": None,
                "val_end_date": None,
                "hyperparams_json": json.dumps(hyper, ensure_ascii=False),
                "metrics_json": json.dumps(metrics, ensure_ascii=False),
                "artifact_dir": artifact_dir.as_posix(),
            },
        )
        conn.commit()

    print("[oracle-bc] Completed Oracle BC training run:")
    print(f"  run_id:      {run_id}")
    print(f"  artifact_dir:{artifact_dir}")

    return 0


if __name__ == "__main__":
    import json

    raise SystemExit(main())
