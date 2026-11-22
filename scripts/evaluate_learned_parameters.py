"""Offline check that learned battery efficiencies predict the SoC at least as well as config.

Replays archived planner runs against recorded data (read-only): for every run the learned
parameters are estimated from data recorded before it started, and the SoC is rolled forward
from the recorded start under the run's configured efficiencies and the learned ones.

    UV_NO_SYNC=1 uv run python scripts/evaluate_learned_parameters.py \\
        --archive data/plan_archive --db data/planner_learning.db [--days 30] [--replan] [--json]

Exit code 1 when the learned 24 h mean absolute SoC error is worse than the config one by
more than 0.25 percentage points, or when fewer than 10 runs could be evaluated.
Nothing is written: not the archive, the database, the configuration or schedule.json.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from backend.learning import hindsight_evaluation as he

# Replay scratch space (the planner writes relative paths); never inside /tmp or the project.
REPLAN_WORKDIR = Path.home() / ".cache" / "darkstar-evaluate"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--archive", type=Path, default=Path("data/plan_archive"))
    parser.add_argument("--db", type=Path, default=Path("data/planner_learning.db"))
    parser.add_argument("--days", type=int, default=None, help="only runs of the last N days")
    parser.add_argument(
        "--replan",
        action="store_true",
        help="also re-solve each run under both parameter sets (informational)",
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    runs = he.load_archive_runs(args.archive, args.days)
    if runs:
        start = min(run.started_at for run in runs) - timedelta(days=he.DB_LOOKBACK_DAYS + 1)
        end = max(run.started_at for run in runs) + timedelta(days=2)
    else:
        start = end = datetime.now(UTC)
    rows = he.load_slot_rows(args.db, start, end) if runs else []
    report = he.evaluate_runs(runs, rows)
    replan = None
    if args.replan:
        workdir = REPLAN_WORKDIR / f"run-{os.getpid()}"
        try:
            replan = he.replan_report(report, runs, args.db, workdir)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    if args.json:
        payload = report.to_dict()
        if replan is not None:
            payload["replan"] = replan
        print(json.dumps(payload, indent=2))
    else:
        print(he.format_report(report))
        if replan is not None:
            print("\nReplan (informational):")
            for item in replan:
                print(f"  {item}")
    return 0 if report.verdict()[0] else 1


if __name__ == "__main__":
    sys.exit(main())
