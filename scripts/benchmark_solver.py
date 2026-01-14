#!/usr/bin/env python3
"""
MILP Solver Benchmark - Direct Test
"""

import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.resolve()))

import pulp


def create_simple_milp(n_slots=100):
    """Create a simplified version of the Kepler problem."""
    prob = pulp.LpProblem("BenchmarkMILP", pulp.LpMinimize)

    # Variables
    charge = pulp.LpVariable.dicts("charge", range(n_slots), lowBound=0)
    discharge = pulp.LpVariable.dicts("discharge", range(n_slots), lowBound=0)
    soc = pulp.LpVariable.dicts("soc", range(n_slots + 1), lowBound=0, upBound=20)
    water = pulp.LpVariable.dicts("water", range(n_slots), cat="Binary")

    # Initial SoC
    prob += soc[0] == 10

    # Constraints for each slot
    for t in range(n_slots):
        # Battery dynamics
        prob += soc[t + 1] == soc[t] + charge[t] * 0.95 - discharge[t]
        # Power limits
        prob += charge[t] <= 5
        prob += discharge[t] <= 5

    # Water heating constraint
    prob += pulp.lpSum(water) >= 8

    # Objective: minimize cost
    prob += pulp.lpSum(charge[t] * (1.0 + t * 0.01) - discharge[t] * 0.5 for t in range(n_slots))

    return prob


def main():
    print("=" * 60)
    print("MILP SOLVER BENCHMARK (Direct)")
    print("=" * 60)

    n_slots = 100
    print(f"Creating MILP problem with {n_slots} slots...")

    # Test each solver
    solvers = [
        ("CBC", pulp.PULP_CBC_CMD(msg=False)),
    ]

    # Try GLPK
    try:
        glpk = pulp.GLPK_CMD(msg=False)
        solvers.insert(0, ("GLPK", glpk))
    except Exception as e:
        print(f"GLPK not available: {e}")

    # Try HiGHS
    try:
        highs = pulp.HiGHS_CMD(msg=False)
        solvers.append(("HiGHS", highs))
    except Exception as e:
        print(f"HiGHS not available: {e}")

    for name, solver in solvers:
        print(f"\nTesting {name}...")
        prob = create_simple_milp(n_slots)

        try:
            start = time.time()
            prob.solve(solver)
            elapsed = time.time() - start

            status = pulp.LpStatus[prob.status]
            print(f"  {name}: {elapsed:.2f}s (status={status})")
        except Exception as e:
            print(f"  {name}: FAILED - {e}")

    print("\n" + "=" * 60)
    print("If a solver is much faster, we can switch to it in Kepler.")
    print("=" * 60)


if __name__ == "__main__":
    main()
