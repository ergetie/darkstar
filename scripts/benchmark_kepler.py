#!/usr/bin/env python3
"""
Kepler Solver Benchmark
======================

Runs a comprehensive benchmark of the Kepler MILP solver across different
complexities and horizons to identify bottlenecks.

Now includes Rust Sidecar integration for comparison.

Usage:
    python scripts/benchmark_kepler.py
"""

import logging
import platform
import sys
import time
import json
import subprocess
import tempfile
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
    KeplerResult,
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


class RustSolverAdapter:
    """Adapter to run the Rust Sidecar solver."""

    def __init__(self, binary_path: Path):
        self.binary_path = binary_path

    def solve(self, input_data: KeplerInput, config: KeplerConfig) -> KeplerResult:
        # 1. Prepare JSON Payload (SidecarInput format)
        payload = {
            "input": {
                "slots": [
                    {
                        "start_time": s.start_time.isoformat()
                        + "Z",  # Rust expects ISO 8601 with Z
                        "end_time": s.end_time.isoformat() + "Z",
                        "load_kwh": s.load_kwh,
                        "pv_kwh": s.pv_kwh,
                        "import_price_sek_kwh": s.import_price_sek_kwh,
                        "export_price_sek_kwh": s.export_price_sek_kwh,
                    }
                    for s in input_data.slots
                ],
                "initial_soc_kwh": input_data.initial_soc_kwh,
            },
            "config": {
                "capacity_kwh": config.capacity_kwh,
                "min_soc_percent": config.min_soc_percent,
                "max_soc_percent": config.max_soc_percent,
                "max_charge_power_kw": config.max_charge_power_kw,
                "max_discharge_power_kw": config.max_discharge_power_kw,
                "charge_efficiency": config.charge_efficiency,
                "discharge_efficiency": config.discharge_efficiency,
                "wear_cost_sek_per_kwh": config.wear_cost_sek_per_kwh,
                "max_export_power_kw": config.max_export_power_kw,
                "max_import_power_kw": config.max_import_power_kw,
                "target_soc_kwh": config.target_soc_kwh,
                "target_soc_penalty_sek": config.target_soc_penalty_sek,
                "terminal_value_sek_kwh": config.terminal_value_sek_kwh,
                "ramping_cost_sek_per_kw": config.ramping_cost_sek_per_kw,
                "export_threshold_sek_per_kwh": config.export_threshold_sek_per_kwh,
                "grid_import_limit_kw": config.grid_import_limit_kw,
                "water_heating_power_kw": config.water_heating_power_kw,
                "water_heating_min_kwh": config.water_heating_min_kwh,
                "water_heating_max_gap_hours": config.water_heating_max_gap_hours,
                "water_heated_today_kwh": config.water_heated_today_kwh,
                "water_comfort_penalty_sek": config.water_comfort_penalty_sek,
                "water_min_spacing_hours": config.water_min_spacing_hours,
                "water_spacing_penalty_sek": config.water_spacing_penalty_sek,
                "force_water_on_slots": config.force_water_on_slots,
                "water_block_start_penalty_sek": config.water_block_start_penalty_sek,
                "defer_up_to_hours": config.defer_up_to_hours,
                "enable_export": config.enable_export,
            },
        }

        # 2. Write to Temp File
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp_in:
            json.dump(payload, tmp_in)
            input_path = tmp_in.name

        output_path = input_path + ".out.json"

        try:
            # 3. Call Rust Binary
            subprocess.run(
                [str(self.binary_path), input_path, output_path], check=True, capture_output=True
            )

            # 4. Read Result
            with open(output_path, "r") as f:
                res_json = json.load(f)

            # 5. Parse back to KeplerResult (Simplified for benchmark stats)
            return KeplerResult(
                slots=[],  # We don't populate detailed slots for benchmarking to save time/mem
                total_cost_sek=res_json["total_cost_sek"],
                is_optimal=res_json["is_optimal"],
                status_msg=res_json["status_msg"],
                solve_time_ms=res_json["solve_time_ms"],
            )

        except subprocess.CalledProcessError as e:
            return KeplerResult([], 0.0, False, f"Rust Error: {e.stderr.decode()}")
        except Exception as e:
            return KeplerResult([], 0.0, False, f"Error: {str(e)}")
        finally:
            # Cleanup
            Path(input_path).unlink(missing_ok=True)
            Path(output_path).unlink(missing_ok=True)


def generate_scenario(
    name: str, slots: int, water_enabled: bool = False, spacing_enabled: bool = False
) -> dict[str, Any]:
    """Generate a benchmark scenario."""
    start = datetime(2025, 1, 1, 0, 0)
    input_slots = []

    for i in range(slots):
        s = start + timedelta(minutes=15 * i)  # 15 min slots
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
                load_kwh=load / 4,  # Adjusted for 15 min slots
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
        # Block start penalty (Rev K22)
        water_block_start_penalty_sek=0.5 if spacing_enabled else 0.0,
    )

    return {
        "name": name,
        "slots": slots,
        "input": input_data,
        "config": config,
        "features": {
            "Water": water_enabled,
            "Spacing": spacing_enabled,
            "Horizon": f"{slots/4:.1f}h",  # 15 min slots
        },
    }


def run_benchmark():
    print()
    print(colored("╭" + "─" * 78 + "╮", Colors.CYAN))
    print(
        colored("│", Colors.CYAN)
        + colored("  DARKSTAR SOLVER BENCHMARK", Colors.BOLD).center(78)
        + colored("│", Colors.CYAN)
    )
    print(colored("│" + " " * 78 + "│", Colors.CYAN))
    print(
        colored("│", Colors.CYAN)
        + colored("  Comparing Python (PuLP/CBC) vs Rust (Highs)", Colors.YELLOW).center(78)
        + colored("│", Colors.CYAN)
    )
    print(colored("╰" + "─" * 78 + "╯", Colors.CYAN))
    print()
    print(f"  {colored('Platform:', Colors.GRAY)} {platform.system()} {platform.release()}")
    # print(f"  {colored('Python:', Colors.GRAY)}   {sys.version.split()[0]}")
    # print(f"  {colored('PuLP:', Colors.GRAY)}     {pulp.__version__}")

    # Check Solvers
    glpk_ok = pulp.GLPK_CMD(msg=False).available()
    cbc_ok = pulp.PULP_CBC_CMD(msg=False).available()

    # Check Rust Binary
    rust_bin_path = (
        Path(__file__).parent.parent / "experimental/rust_solver/target/release/rust-kepler-solver"
    )
    rust_ok = rust_bin_path.exists()

    print(f"  {colored('Backend Check:', Colors.BLUE)}")
    print(
        f"    {'GLPK':<10} {colored('✅ Available', Colors.GREEN) if glpk_ok else colored('❌ Not Found', Colors.RED)}"  # noqa: E501
    )
    print(
        f"    {'CBC':<10} {colored('✅ Available', Colors.GREEN) if cbc_ok else colored('❌ Not Found', Colors.RED)}"  # noqa: E501
    )
    print(
        f"    {'Rust':<10} {colored('✅ Available', Colors.GREEN) if rust_ok else colored('❌ Not Found', Colors.RED)}"  # noqa: E501
    )

    print()
    print(colored("─" * 80, Colors.GRAY))
    print(f"  {'SCENARIO':<30} {'SLOTS':<6} {'PYTHON':>10} {'RUST':>10} {'SPEEDUP':>10}")
    print(colored("─" * 80, Colors.GRAY))

    scenarios = [
        generate_scenario("Baseline (24h)", 96, water_enabled=False),
        generate_scenario("Baseline (48h)", 192, water_enabled=False),
        generate_scenario("Water Heat (48h)", 192, water_enabled=True, spacing_enabled=False),
        generate_scenario("Water + Spacing (48h)", 192, water_enabled=True, spacing_enabled=True),
        generate_scenario("Water + Spacing (72h)", 288, water_enabled=True, spacing_enabled=True),
        # Extreme Case: 4 Days
        generate_scenario("Extreme (4 Days)", 384, water_enabled=True, spacing_enabled=True),
    ]

    py_solver = KeplerSolver()
    rust_solver = RustSolverAdapter(rust_bin_path) if rust_ok else None

    for sc in scenarios:
        # Run Python
        t_py = 0.0
        try:
            start = time.time()
            res_py = py_solver.solve(sc["input"], sc["config"])
            t_py = time.time() - start
            if not res_py.is_optimal:
                t_py = -1.0  # Error
        except Exception:
            t_py = -1.0

        # Run Rust
        t_rust = 0.0
        if rust_solver:
            try:
                start = time.time()
                res_rust = rust_solver.solve(sc["input"], sc["config"])
                t_rust = time.time() - start  # Total time including I/O
                if not res_rust.is_optimal:
                    t_rust = -1.0
            except Exception:
                t_rust = -1.0

        # Formatting
        def fmt_time(t):
            if t < 0:
                return colored("FAIL", Colors.RED)
            c = Colors.GREEN
            if t > 0.5:
                c = Colors.YELLOW
            if t > 2.0:
                c = Colors.RED
            return colored(f"{t:>9.4f}s", c)

        speedup_str = "-"
        if t_rust > 0 and t_py > 0:
            speedup = t_py / t_rust
            speedup_str = colored(f"{speedup:>9.1f}x", Colors.CYAN)

        print(
            f"  {sc['name']:<30} {sc['slots']:<6} {fmt_time(t_py)} {fmt_time(t_rust)} {speedup_str}"  # noqa: E501
        )

    print(colored("─" * 80, Colors.GRAY))
    print()


if __name__ == "__main__":
    run_benchmark()
