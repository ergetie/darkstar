from __future__ import annotations

"""
Compare Oracle MILP cost vs MPC replay for a given day (Rev 71).

Usage (from project root):
    PYTHONPATH=. python debug/run_oracle_vs_mpc.py --day 2025-08-01
"""

import argparse
from datetime import date, datetime

from ml.benchmark.milp_solver import solve_optimal_schedule
from ml.simulation.env import AntaresMPCEnv


def _parse_day(value: str) -> date:
    return datetime.fromisoformat(value).date()


def _run_mpc_cost(day: date) -> float:
    env = AntaresMPCEnv(config_path="config.yaml")
    env.reset(day)
    total_reward = 0.0
    while True:
        result = env.step(action=None)
        total_reward += result.reward
        if result.done:
            break
    # Reward is negative net cost
    return -total_reward


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare Oracle MILP vs MPC replay cost for a given day.",
    )
    parser.add_argument(
        "--day",
        required=True,
        help="Day to simulate (YYYY-MM-DD, local calendar).",
    )
    args = parser.parse_args()

    day = _parse_day(args.day)

    print(f"[oracle-vs-mpc] Day: {day.isoformat()}")

    oracle_df = solve_optimal_schedule(day)
    oracle_total = float(oracle_df["oracle_slot_cost_sek"].sum())
    print(f"[oracle] total cost: {oracle_total:0.2f} SEK")

    mpc_total = _run_mpc_cost(day)
    print(f"[mpc]    total cost: {mpc_total:0.2f} SEK")

    delta = mpc_total - oracle_total
    rel = (delta / abs(mpc_total)) * 100.0 if mpc_total != 0 else 0.0
    print(f"[delta] mpc - oracle: {delta:0.2f} SEK ({rel:0.1f} % of mpc cost)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

