from __future__ import annotations

"""
Quick sanity check for AntaresMPCEnv (Rev 70).

Usage (from project root):
    PYTHONPATH=. python debug/run_antares_env_episode.py --day 2025-08-01
"""

import argparse
from datetime import date, datetime

from ml.simulation.env import AntaresMPCEnv


def _parse_day(value: str) -> date:
    return datetime.fromisoformat(value).date()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a single AntaresMPCEnv episode for a given day.",
    )
    parser.add_argument(
        "--day",
        required=True,
        help="Day to simulate (YYYY-MM-DD, local calendar).",
    )
    args = parser.parse_args()

    env = AntaresMPCEnv(config_path="config.yaml")
    day = _parse_day(args.day)

    state = env.reset(day)
    print(f"[env] reset on {day.isoformat()}, initial state shape={state.shape}")

    total_reward = 0.0
    steps = 0

    while True:
        result = env.step(action=None)
        total_reward += result.reward
        steps += 1

        if steps <= 4 or result.done:
            print(
                f"[step {steps:03d}] reward={result.reward: .4f} "
                f"done={result.done} info={result.info}"
            )

        if result.done:
            break

    print(f"[env] episode finished: steps={steps}, total_reward={total_reward: .2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
