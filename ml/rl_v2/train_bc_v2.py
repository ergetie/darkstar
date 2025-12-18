"""Train Oracle-guided BC model for RL v2 (Rev 84).

Usage:
    PYTHONPATH=. ./venv/bin/python ml/rl_v2/train_bc_v2.py --days 60
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

from learning import LearningEngine, get_learning_engine
from ml.benchmark.milp_solver import solve_optimal_schedule
from ml.rl_v2.contract import RlV2StateSpec


@dataclass
class OracleBcV2Config:
    days: int
    seq_len: int
    hidden_dim: int
    batch_size: int
    epochs: int
    learning_rate: float
    seed: int


class OracleBcV2Net(nn.Module):
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


def _get_engine() -> LearningEngine:
    engine = get_learning_engine()
    if not isinstance(engine, LearningEngine):
        raise TypeError("get_learning_engine() did not return a LearningEngine instance")
    return engine


def _load_candidate_days(engine: LearningEngine, max_days: int) -> List[str]:
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


def _build_day_pairs_v2(
    day: str,
    seq_len: int,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Build (state, oracle_action, soc_percent, sample_weight) for RL v2 BC."""
    df = solve_optimal_schedule(day)
    if df.empty:
        return (
            np.empty((0, 0), dtype=np.float32),
            np.empty((0, 0), dtype=np.float32),
            np.empty((0,), dtype=np.float32),
            np.empty((0,), dtype=np.float32),
        )

    df = df.copy()
    df["slot_start"] = pd.to_datetime(df["slot_start"], utc=True, errors="coerce")
    df["slot_end"] = pd.to_datetime(df["slot_end"], utc=True, errors="coerce")
    df = df.dropna(subset=["slot_start", "slot_end"])
    if df.empty:
        return (
            np.empty((0, 0), dtype=np.float32),
            np.empty((0, 0), dtype=np.float32),
            np.empty((0,), dtype=np.float32),
            np.empty((0,), dtype=np.float32),
        )

    df["slot_start"] = df["slot_start"].dt.tz_convert("Europe/Stockholm")
    df["slot_end"] = df["slot_end"].dt.tz_convert("Europe/Stockholm")

    df["load_kwh"] = pd.to_numeric(df["load_kwh"], errors="coerce").fillna(0.0)
    df["pv_kwh"] = pd.to_numeric(df["pv_kwh"], errors="coerce").fillna(0.0)
    df["import_price_sek_kwh"] = pd.to_numeric(df["import_price_sek_kwh"], errors="coerce").fillna(
        0.0
    )

    df["slot_hours"] = pd.to_numeric(df["slot_hours"], errors="coerce").fillna(0.25)
    df["slot_hours"] = df["slot_hours"].clip(lower=0.01)

    df["hour_of_day"] = df["slot_start"].dt.hour + df["slot_start"].dt.minute / 60.0

    df["oracle_soc_percent"] = pd.to_numeric(df["oracle_soc_percent"], errors="coerce").fillna(0.0)
    df["oracle_charge_kwh"] = pd.to_numeric(df["oracle_charge_kwh"], errors="coerce").fillna(0.0)
    df["oracle_discharge_kwh"] = pd.to_numeric(df["oracle_discharge_kwh"], errors="coerce").fillna(
        0.0
    )
    df["oracle_grid_export_kwh"] = pd.to_numeric(
        df["oracle_grid_export_kwh"], errors="coerce"
    ).fillna(0.0)

    T = len(df)
    spec = RlV2StateSpec(seq_len=seq_len)

    prices = df["import_price_sek_kwh"].to_numpy(dtype=np.float32)
    net_load_kwh = (df["load_kwh"] - df["pv_kwh"]).to_numpy(dtype=np.float32)
    slot_hours = df["slot_hours"].to_numpy(dtype=np.float32)
    slot_hours = np.where(slot_hours <= 0.0, 0.25, slot_hours)
    net_load_kw = net_load_kwh / slot_hours

    # Price quantiles for simple cost-aware weighting.
    q25 = float(np.quantile(prices, 0.25))
    q75 = float(np.quantile(prices, 0.75))

    states: List[np.ndarray] = []
    actions: List[List[float]] = []
    soc_targets: List[float] = []
    sample_weights: List[float] = []

    for idx in range(T):
        row = df.iloc[idx]
        soc_percent = float(row["oracle_soc_percent"])
        hour_of_day = float(row["hour_of_day"])

        price_seq = np.empty(seq_len, dtype=np.float32)
        net_load_seq = np.empty(seq_len, dtype=np.float32)
        for offset in range(seq_len):
            j = idx + offset
            if j >= T:
                j = T - 1
            price_seq[offset] = float(prices[j])
            net_load_seq[offset] = float(net_load_kw[j])

        state = np.empty(spec.flat_dim, dtype=np.float32)
        state[0] = soc_percent
        state[1] = hour_of_day
        state[2 : 2 + seq_len] = price_seq
        state[2 + seq_len :] = net_load_seq
        states.append(state)

        slot_h = float(slot_hours[idx]) or 0.25
        charge_kwh = float(row["oracle_charge_kwh"])
        discharge_kwh = float(row["oracle_discharge_kwh"])
        export_kwh = float(row["oracle_grid_export_kwh"])

        charge_kw = charge_kwh / slot_h
        discharge_kw = discharge_kwh / slot_h
        export_kw = export_kwh / slot_h
        actions.append([charge_kw, discharge_kw, export_kw])
        soc_targets.append(soc_percent)

        # Base sample weight = 1.0, then up-weight economically critical slots.
        price = float(row["import_price_sek_kwh"])
        w = 1.0
        if price <= q25 and charge_kwh > 0.0:
            # Cheap charging slots should be imitated strongly.
            w *= 2.0
        if price >= q75 and discharge_kwh > 0.0:
            # Expensive discharging slots are also critical.
            w *= 2.0
        sample_weights.append(w)

    X = np.stack(states, axis=0)
    Y = np.asarray(actions, dtype=np.float32)
    soc = np.asarray(soc_targets, dtype=np.float32)
    weights = np.asarray(sample_weights, dtype=np.float32)
    return X, Y, soc, weights


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Train Oracle-guided BC v2 policy (sequence state).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=60,
        help="Number of recent clean/mask_battery days to use (default: 60).",
    )
    parser.add_argument(
        "--seq-len",
        type=int,
        default=48,
        help="Sequence length in slots for v2 state (default: 48).",
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

    cfg = OracleBcV2Config(
        days=int(args.days),
        seq_len=int(args.seq_len),
        hidden_dim=128,
        batch_size=256,
        epochs=int(args.epochs),
        learning_rate=1e-3,
        seed=int(args.seed),
    )

    np.random.seed(cfg.seed)
    torch.manual_seed(cfg.seed)

    engine = _get_engine()
    days = _load_candidate_days(engine, cfg.days)
    if not days:
        raise SystemExit("[oracle-bc-v2] No candidate days found in data_quality_daily.")

    xs: List[np.ndarray] = []
    ys: List[np.ndarray] = []
    socs: List[np.ndarray] = []
    ws: List[np.ndarray] = []

    print(f"[oracle-bc-v2] Building dataset from {len(days)} days...")
    for day in days:
        x_day, y_day, soc_day, w_day = _build_day_pairs_v2(day, cfg.seq_len)
        if x_day.size == 0 or y_day.size == 0:
            continue
        xs.append(x_day)
        ys.append(y_day)
        socs.append(soc_day)
        ws.append(w_day)
        print(f"[oracle-bc-v2]   {day}: {len(x_day)} slots")

    if not xs:
        raise SystemExit("[oracle-bc-v2] No training samples collected.")

    X = np.concatenate(xs, axis=0)
    Y_act = np.concatenate(ys, axis=0)
    soc_all = np.concatenate(socs, axis=0).reshape(-1, 1)
    W = np.concatenate(ws, axis=0)

    # Combine actions + soc target into a single label matrix.
    Y = np.concatenate([Y_act, soc_all], axis=1)

    mask_finite = (
        np.isfinite(X).all(axis=1) & np.isfinite(Y).all(axis=1) & np.isfinite(W).reshape(-1)
    )
    if not mask_finite.any():
        raise SystemExit("[oracle-bc-v2] All samples contain NaN/inf; nothing to train on.")
    if not mask_finite.all():
        before = len(mask_finite)
        after = int(mask_finite.sum())
        print(f"[oracle-bc-v2] Dropping {before - after} non-finite samples " f"(keeping {after}).")
    X = X[mask_finite]
    Y = Y[mask_finite]
    W = W[mask_finite]

    print(f"[oracle-bc-v2] Total samples (finite): {len(X)}")

    dataset = TensorDataset(torch.from_numpy(X), torch.from_numpy(Y), torch.from_numpy(W))
    loader = DataLoader(dataset, batch_size=cfg.batch_size, shuffle=True)

    model = OracleBcV2Net(in_dim=X.shape[1], hidden_dim=cfg.hidden_dim, out_dim=Y.shape[1])
    optimizer = optim.Adam(model.parameters(), lr=cfg.learning_rate)
    loss_fn = nn.MSELoss()

    lambda_soc = 0.1
    model.train()
    for epoch in range(cfg.epochs):
        epoch_loss = 0.0
        weight_sum = 0.0
        for batch_x, batch_y, batch_w in loader:
            optimizer.zero_grad()
            preds = model(batch_x)

            # Split actions vs SoC (last column).
            act_pred = preds[:, :3]
            soc_pred = preds[:, 3:4]
            act_true = batch_y[:, :3]
            soc_true = batch_y[:, 3:4]

            # Per-sample MSE.
            act_err = (act_pred - act_true) ** 2
            soc_err = (soc_pred - soc_true) ** 2
            per_sample = act_err.mean(dim=1) + lambda_soc * soc_err.mean(dim=1)

            w = batch_w.reshape(-1)
            # Normalise by mean weight to keep scale stable.
            w_clamped = torch.clamp(w, min=1e-3)
            weighted = per_sample * w_clamped
            loss = weighted.mean() / w_clamped.mean()

            loss.backward()
            optimizer.step()
            epoch_loss += float(loss.item()) * batch_x.size(0)
            weight_sum += float(w_clamped.mean().item()) * batch_x.size(0)
        epoch_loss /= max(len(dataset), 1)
        print(f"[oracle-bc-v2] Epoch {epoch+1}/{cfg.epochs} " f"- weighted loss: {epoch_loss:.4f}")

    run_id = str(uuid.uuid4())
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    base_dir = Path("ml/models/antares_rl_v2_bc")
    base_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir = base_dir / f"antares_rl_v2_bc_seq_{ts}_{run_id[:8]}"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    model_path = artifact_dir / "model.pt"
    torch.save(model.state_dict(), model_path.as_posix())

    print("[oracle-bc-v2] Saved model to", model_path)

    hyper = asdict(cfg)
    metrics: Dict[str, Any] = {
        "note": "Oracle behaviour cloning v2 (sequence state, SoC+cost-weighted).",
        "num_samples": int(len(X)),
        "output_dim": int(Y.shape[1]),
    }

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
                "algo": "oracle_bc_v2_seq",
                "state_version": f"rl_v2_seq_state_v1_len{cfg.seq_len}",
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

    print("[oracle-bc-v2] Completed Oracle BC v2 training run:")
    print(f"  run_id:      {run_id}")
    print(f"  artifact_dir:{artifact_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
