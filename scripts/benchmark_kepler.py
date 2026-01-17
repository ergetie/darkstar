#!/usr/bin/env python3
"""
Kepler Solver Benchmark
======================

Runs a comprehensive benchmark of the Kepler MILP solver across different
complexities and horizons to identify bottlenecks.

Usage:
    python scripts/benchmark_kepler.py
"""

import logging
import platform
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pulp

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.resolve()))

from planner.solver.kepler import KeplerSolver  # noqa: E402
from planner.solver.types import (  # noqa: E402
    KeplerConfig,
    KeplerInput,
    KeplerInputSlot,
)  # noqa: E402

# Configure nice logging
logging.basicConfig(level=logging.ERROR, format="%(message)s")  # Silence most logs
logger = logging.getLogger("benchmark")
logging.getLogger("darkstar.performance").setLevel(logging.CRITICAL)
logging.getLogger("planner").setLevel(logging.CRITICAL)


# -----------------------------------------------------------------------------
# ANSI Colors (Matched to bench_dashboard.py)
# -----------------------------------------------------------------------------
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GRAY = "\033[90m"


def colored(text: str, color: str) -> str:
    """Apply ANSI color to text."""
    return f"{color}{text}{Colors.RESET}"


def generate_scenario(
    name: str, slots: int, water_enabled: bool = False, spacing_enabled: bool = False
) -> dict[str, Any]:
    """Generate a benchmark scenario."""
    start = datetime(2025, 1, 1, 0, 0)
    input_slots = []

    for i in range(slots):
        s = start + timedelta(minutes=15 * i)
        e = s + timedelta(minutes=15)

        # Complex price pattern (volatility makes solver work harder)
        hour = s.hour
        base_price = 0.5
        if 6 <= hour <= 9:
            base_price = 2.0  # Morning peak
        if 17 <= hour <= 20:
            base_price = 2.5  # Evening peak
        if 0 <= hour <= 4:
            base_price = 0.1  # Night cheap

        # Add some noise
        import_price = base_price + (i % 3) * 0.1
        export_price = import_price - 0.1

        # Load pattern
        load = 0.5
        if 18 <= hour <= 21:
            load = 2.0

        input_slots.append(
            KeplerInputSlot(
                start_time=s,
                end_time=e,
                load_kwh=load / 4,
                pv_kwh=0.0,  # Simplify PV
                import_price_sek_kwh=import_price,
                export_price_sek_kwh=export_price,
            )
        )

    input_data = KeplerInput(slots=input_slots, initial_soc_kwh=5.0)

    config = KeplerConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        min_soc_percent=10.0,
        max_soc_percent=90.0,
        wear_cost_sek_per_kwh=0.05,
        # Water Heating Settings
        water_heating_power_kw=3.0 if water_enabled else 0.0,
        water_heating_min_kwh=5.0 if water_enabled else 0.0,
        water_heating_max_gap_hours=12.0 if water_enabled else 0.0,
        water_comfort_penalty_sek=10.0 if water_enabled else 0.0,
        # Spacing Constraint (The heavy one)
        water_min_spacing_hours=4.0 if spacing_enabled else 0.0,
    )

    return {
        "name": name,
        "slots": slots,
        "input": input_data,
        "config": config,
        "features": {
            "Water": water_enabled,
            "Spacing": spacing_enabled,
            "Horizon": f"{slots/4:.1f}h",
        },
    }


def run_benchmark():
    print()
    print(colored("╭" + "─" * 68 + "╮", Colors.CYAN))
    print(
        colored("│", Colors.CYAN)
        + colored("  DARKSTAR SOLVER BENCHMARK", Colors.BOLD).center(76)
        + colored("│", Colors.CYAN)
    )
    print(colored("╰" + "─" * 68 + "╯", Colors.CYAN))
    print()
    print(f"  {colored('Platform:', Colors.GRAY)} {platform.system()} {platform.release()}")
    print(f"  {colored('Python:', Colors.GRAY)}   {sys.version.split()[0]}")
    print(f"  {colored('PuLP:', Colors.GRAY)}     {pulp.__version__}")
    print()

    # Check Solvers
    glpk_ok = pulp.GLPK_CMD(msg=False).available()
    cbc_ok = pulp.PULP_CBC_CMD(msg=False).available()

    print(f"  {colored('Backend Check:', Colors.BLUE)}")
    print(
        f"    {'GLPK':<10} {colored('✅ Available', Colors.GREEN) if glpk_ok else colored('❌ Not Found', Colors.RED)}"  # noqa: E501
    )
    print(
        f"    {'CBC':<10} {colored('✅ Available', Colors.GREEN) if cbc_ok else colored('❌ Not Found', Colors.RED)}"  # noqa: E501
    )

    print()
    print(colored("─" * 70, Colors.GRAY))
    print(f"  {'SCENARIO':<25} {'SLOTS':<6} {'TIME':>10} {'VARS':>8} {'CONST':>8}   {'STATUS'}")
    print(colored("─" * 70, Colors.GRAY))

    scenarios = [
        generate_scenario("Baseline (24h)", 96, water_enabled=False),
        generate_scenario("Baseline (48h)", 192, water_enabled=False),
        generate_scenario("Water Heat (48h)", 192, water_enabled=True, spacing_enabled=False),
        generate_scenario("Water + Spacing (48h)", 192, water_enabled=True, spacing_enabled=True),
        generate_scenario("Stress Test (72h)", 288, water_enabled=True, spacing_enabled=True),
    ]

    solver = KeplerSolver()

    for sc in scenarios:
        start = time.time()
        result = solver.solve(sc["input"], sc["config"])
        duration = time.time() - start

        # We can't easily get vars/consts from result object, using placeholders or parsing logs if needed  # noqa: E501
        # For this script, we just focus on time.
        vars_est = "?"
        const_est = "?"

        status_color = Colors.GREEN if result.is_optimal else Colors.RED
        status_msg = f"{colored('✅', status_color)} {result.status_msg}"

        time_color = Colors.GREEN
        if duration > 0.5:
            time_color = Colors.YELLOW
        if duration > 2.0:
            time_color = Colors.RED

        print(
            f"  {sc['name']:<25} {sc['slots']:<6} {colored(f'{duration:>9.4f}s', time_color)} {colored(f'{vars_est:>8}', Colors.GRAY)} {colored(f'{const_est:>8}', Colors.GRAY)}   {status_msg}"  # noqa: E501
        )

    print(colored("─" * 70, Colors.GRAY))
    print()


if __name__ == "__main__":
    run_benchmark()
