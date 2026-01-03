import os
import sys

sys.path.append(os.getcwd())
from debug.benchmark_range import run_day


def main():
    date_str = "2025-11-26"
    print(f"Running benchmark for {date_str}...")
    res = run_day(date_str)

    if res:
        print("\n--- Results ---")
        print(f"MPC Financial Cost: {res['mpc_cost']:.2f} SEK")
        print(f"Kepler Financial Cost: {res['kepler_cost']:.2f} SEK")
        print(f"MPC Objective Cost: {res['mpc_objective_cost']:.2f} SEK")
        print(f"Kepler Objective Cost: {res['kepler_objective_cost']:.2f} SEK")
        print(f"Savings: {res['savings']:.2f} SEK")
        print(f"Kepler Import: {res['kepler_import']:.2f} kWh")
    else:
        print("Failed to run benchmark.")


if __name__ == "__main__":
    main()
