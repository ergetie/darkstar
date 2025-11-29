from __future__ import annotations

"""
Run MPC vs Antares policy vs Oracle cost for a single day.

Usage (from project root):
    PYTHONPATH=. python debug/run_policy_cost_for_day.py --day 2025-08-01
"""

import argparse
from datetime import date, datetime

from learning import get_learning_engine
from ml.benchmark.milp_solver import solve_optimal_schedule
from ml.eval_antares_policy_cost import _load_latest_policy_run
from ml.policy.antares_policy import AntaresPolicyV1
from ml.simulation.env import AntaresMPCEnv


def _parse_day(value: str) -> date:
    return datetime.fromisoformat(value).date()


def _run_mpc_cost(day: str) -> float:
    env = AntaresMPCEnv(config_path="config.yaml")
    env.reset(day)
    total_reward = 0.0
    while True:
        result = env.step(action=None)
        total_reward += result.reward
        if result.done:
            break
    return -total_reward


def _run_policy_cost(day: str, policy: AntaresPolicyV1) -> float:
    env = AntaresMPCEnv(config_path="config.yaml")
    state = env.reset(day)
    total_reward = 0.0
    while True:
        action = policy.predict(state)
        result = env.step(action=action)
        total_reward += result.reward
        state = result.next_state
        if result.done:
            break
    return -total_reward


def _maybe_run_oracle(day: str) -> float | None:
    try:
        df = solve_optimal_schedule(day)
    except Exception:
        return None
    return float(df["oracle_slot_cost_sek"].sum())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare MPC vs policy vs Oracle cost for a single day.",
    )
    parser.add_argument(
        "--day",
        required=True,
        help="Day to evaluate (YYYY-MM-DD, local calendar).",
    )
    args = parser.parse_args()

    day_str = args.day

    engine = get_learning_engine()
    run = _load_latest_policy_run(engine)
    if run is None:
        print("[policy-cost-day] No antares_policy_runs entries found; train policy first.")
        return 1

    policy = AntaresPolicyV1.load_from_dir(run.models_dir)

    print(f"[policy-cost-day] Evaluating day {day_str} with policy run {run.run_id}")

    mpc_cost = _run_mpc_cost(day_str)
    policy_cost = _run_policy_cost(day_str, policy)
    oracle_cost = _maybe_run_oracle(day_str)

    print(f"  MPC cost:     {mpc_cost}")
    print(f"  Policy cost:  {policy_cost}")
    if oracle_cost is not None:
        print(f"  Oracle cost:  {oracle_cost}")
    else:
        print("  Oracle cost:  (no solution / error)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

