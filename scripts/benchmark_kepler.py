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

import argparse
import contextlib
import json
import logging
import os
import platform
import random
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psutil
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.resolve()))

from planner.solver.kepler import KeplerSolver  # noqa: E402
from planner.solver.types import (  # noqa: E402
    KeplerConfig,
    KeplerInput,
    KeplerInputSlot,
    KeplerResult,
)

# Configure nice logging
logging.basicConfig(level=logging.ERROR, format="%(message)s")  # Silence most logs
logger = logging.getLogger("benchmark")
logging.getLogger("darkstar.performance").setLevel(logging.CRITICAL)
logging.getLogger("planner").setLevel(logging.CRITICAL)


def get_sys_info() -> dict[str, str]:
    """Get summarized system hardware info."""
    try:
        cpu_info = f"{platform.processor()} ({psutil.cpu_count(logical=False)} Cores)"
        if platform.system() == "Linux":
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if "model name" in line:
                        cpu_info = line.split(":")[1].strip()
                        break

        mem = psutil.virtual_memory()
        return {
            "CPU": cpu_info,
            "RAM": f"{mem.total / (1024**3):.1f} GB",
            "Arch": f"{platform.machine()} ({platform.system()})",
            "Python": sys.version.split()[0],
        }
    except Exception:
        return {"Error": "Hardare info not available"}


console = Console()


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
            with open(output_path) as f:
                res_json = json.load(f)

            # 5. Parse back to KeplerResult (Simplified for benchmark stats)
            return KeplerResult(
                slots=[],
                total_cost_sek=res_json["total_cost_sek"],
                is_optimal=res_json["is_optimal"],
                status_msg=res_json["status_msg"],
                solve_time_ms=res_json["solve_time_ms"],
                peak_memory_mb=res_json.get("peak_memory_mb", 0.0),
            )

        except subprocess.CalledProcessError as e:
            return KeplerResult([], 0.0, False, f"Rust Error: {e.stderr.decode()}")
        except Exception as e:
            return KeplerResult([], 0.0, False, f"Error: {e!s}")
        finally:
            # Cleanup
            Path(input_path).unlink(missing_ok=True)
            Path(output_path).unlink(missing_ok=True)


def generate_scenario(sc_config: dict[str, Any]) -> dict[str, Any]:
    """Generate a benchmark scenario from config dict."""
    name = sc_config["name"]
    slots = sc_config["slots"]
    water_enabled = sc_config.get("water", False)
    spacing_enabled = sc_config.get("spacing", False)
    export_enabled = sc_config.get("export", True)
    profile = sc_config.get("profile", "default")

    start = datetime(2025, 1, 1, 0, 0)
    input_slots = []

    # Heavy Home Random Seed (deterministic for benchmark)
    rng = random.Random(42)

    for i in range(slots):
        s = start + timedelta(minutes=15 * i)
        e = s + timedelta(minutes=15)
        hour = s.hour
        base_price = 0.5
        if 6 <= hour <= 9:
            base_price = 2.0
        if 17 <= hour <= 20:
            base_price = 2.5
        if 0 <= hour <= 4:
            base_price = 0.1

        import_price = base_price + (i % 3) * 0.1
        export_price = import_price - 0.1
        if profile == "heavy_home":
            # Heavy Home: Heat Pump Base + EV Spikes
            # Base: 1.0 - 2.0 kW fluctuating
            base_load = 1.0 + rng.random()

            # EV 1: 17:00 - 20:00 (7kW)
            if 17 <= hour < 20:
                base_load += 7.0

            # EV 2: 19:00 - 23:00 (11kW)
            if 19 <= hour < 23:
                base_load += 11.0

            load = base_load
        else:
            # Default Profile
            load = 0.5
            if 18 <= hour <= 21:
                load = 2.0

        input_slots.append(
            KeplerInputSlot(
                start_time=s,
                end_time=e,
                load_kwh=load / 4,
                pv_kwh=0.0,
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
        water_heating_power_kw=3.0 if water_enabled else 0.0,
        water_heating_min_kwh=5.0 if water_enabled else 0.0,
        water_heating_max_gap_hours=12.0 if water_enabled else 0.0,
        water_comfort_penalty_sek=10.0 if water_enabled else 0.0,
        water_min_spacing_hours=4.0 if spacing_enabled else 0.0,
        water_block_start_penalty_sek=0.5 if spacing_enabled else 0.0,
        enable_export=export_enabled,
    )

    # Complexity Score: slots * (1 + water*1 + spacing*2 + profile_bonus)
    profile_bonus = 1 if profile == "heavy_home" else 0
    complexity = slots * (
        1 + (1 if water_enabled else 0) + (2 if spacing_enabled else 0) + profile_bonus
    )

    # Feature Matrix [W|S|E]
    f_list = []
    if water_enabled:
        f_list.append("W")
    if spacing_enabled:
        f_list.append("S")
    if export_enabled:
        f_list.append("E")
    feature_matrix = f"[{'|'.join(f_list)}]" if f_list else "[-]"

    return {
        "name": name,
        "slots": slots,
        "input": input_data,
        "config": config,
        "complexity": complexity,
        "feature_matrix": feature_matrix,
        "features": {
            "Water": water_enabled,
            "Spacing": spacing_enabled,
            "Horizon": f"{slots/4:.1f}h",
        },
    }


def save_markdown_report(results: list[dict[str, Any]], sys_info: dict[str, str]):
    """Generate or update BENCHMARK_REPORT.md with latest results."""
    report_path = Path(__file__).parent.parent / "BENCHMARK_REPORT.md"

    # 1. Prepare Header
    lines = [
        "# Kepler Solver Benchmark Report",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        "## System Context",
        f"- **CPU**: {sys_info['CPU']}",
        f"- **RAM**: {sys_info['RAM']}",
        f"- **OS**: {sys_info['Arch']}",
        f"- **Python**: {sys_info['Python']}\n",
        "## Results",
        "| Scenario | Complex | Python (s) | Rust (s) | Speedup | RAM (Py/Rs) | "
        "Correct | Economy |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]

    for r in results:
        py_time = f"{r['t_py']:.4f}s" if r["t_py"] > 0 else "FAIL"
        rust_time = f"{r['t_rust']:.4f}s" if r["t_rust"] > 0 else "FAIL"
        speedup = f"{r['t_py']/r['t_rust']:.1f}x" if r["t_py"] > 0 and r["t_rust"] > 0 else "-"
        correct = "✅" if r["diff"] < 0.01 else f"❌ ({r['diff']:.3f})"
        economy = f"{abs(r['cost']):.2f} SEK {'Cr' if r['cost'] < 0 else 'Dr'}"
        mem = f"{r['mem_py']:.1f}/{r['mem_rust']:.1f}"

        lines.append(
            f"| {r['name']} | {r['complexity']} | {py_time} | {rust_time} | {speedup} | {mem} | "
            f"{correct} | {economy} |"
        )

    with open(report_path, "w") as f:
        f.write("\n".join(lines) + "\n")


def get_process_memory() -> float:
    """Get current process memory in MB."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / (1024 * 1024)


def run_benchmark():
    parser = argparse.ArgumentParser(description="Kepler Solver Benchmark")
    parser.add_argument(
        "--solvers",
        type=str,
        default="python,rust",
        help="Solvers to compare (comma-separated: python,rust,cbc)",
    )
    args = parser.parse_args()

    enabled_solvers = [s.strip().lower() for s in args.solvers.split(",")]

    sys_info = get_sys_info()

    # Header Panel
    header_content = (
        f"[bold cyan]CPU:[/] {sys_info['CPU']}\n"
        f"[bold cyan]RAM:[/] {sys_info['RAM']} | [bold cyan]Python:[/] {sys_info['Python']}\n"
        f"[bold cyan]Arch:[/] {sys_info['Arch']}"
    )
    console.print(
        Panel(header_content, title="[bold yellow]KEPLER BENCHMARK v2.1[/]", expand=False)
    )

    # Check Solvers
    rust_bin_path = (
        Path(__file__).parent.parent / "experimental/rust_solver/target/release/rust-kepler-solver"
    )
    rust_ok = rust_bin_path.exists()

    # Load Scenarios
    yaml_path = Path(__file__).parent / "benchmarks.yaml"
    with open(yaml_path) as f:
        bench_data = yaml.safe_load(f)

    scenarios = [generate_scenario(s) for s in bench_data["benchmarks"]]

    # Results Table (Matching bench_dashboard airy style)
    table = Table(
        box=None,
        header_style="bold blue",
        show_header=True,
        padding=(0, 2),
        collapse_padding=True,
        title_justify="left",
    )
    table.add_column("Scenario", style="cyan", width=30)
    table.add_column("Matrix", justify="center", style="blue")
    table.add_column("Complex", justify="right", style="dim")
    table.add_column("Python (s)", justify="right")
    table.add_column("Rust (s)", justify="right")
    table.add_column("Speedup", justify="right", width=16)
    table.add_column("Memory (MB)", justify="right", style="dim")
    table.add_column("Economy (Profit)", justify="right")
    table.add_column("V", justify="center")  # Truth Check

    py_solver = KeplerSolver()
    rust_solver = RustSolverAdapter(rust_bin_path) if rust_ok else None

    progress_results = []
    total_time_py = 0.0
    total_time_rust = 0.0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=20),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[green]Audit in progress...", total=len(scenarios))

        for sc in scenarios:
            progress.update(task, description=f"[bold blue]Solving:[/] {sc['name']}")

            # 1. Run Python
            t_py, cost_py, mem_py = -1.0, 0.0, 0.0
            if "python" in enabled_solvers or "cbc" in enabled_solvers:
                try:
                    start_mem = get_process_memory()
                    start_time = time.time()
                    with contextlib.redirect_stdout(None):  # Silence solver noise
                        res_py = py_solver.solve(sc["input"], sc["config"])
                    t_py = time.time() - start_time
                    cost_py = res_py.total_cost_sek if res_py.is_optimal else 0.0
                    mem_py = max(0.0, get_process_memory() - start_mem)
                    total_time_py += t_py
                except Exception:
                    pass

            # 2. Run Rust
            t_rust, cost_rust, mem_rust = -1.0, 0.0, 0.0
            if "rust" in enabled_solvers and rust_solver:
                try:
                    start_time = time.time()
                    res_rust = rust_solver.solve(sc["input"], sc["config"])
                    t_rust = time.time() - start_time
                    cost_rust = res_rust.total_cost_sek if res_rust.is_optimal else 0.0
                    mem_rust = getattr(res_rust, "peak_memory_mb", 0.1)
                    total_time_rust += t_rust
                except Exception:
                    pass

            # Formatting Time
            def fmt_t(t):
                if t < 0:
                    return "[red]FAIL[/]"
                color = "green" if t < 0.2 else ("yellow" if t < 1.0 else "red")
                return f"[{color}]{t:>.4f}s[/{color}]"

            # Economy formatting (Combined into one column for neatness)
            final_cost = cost_rust if t_rust > 0 else cost_py
            if final_cost < 0:
                economy_str = f"[green]{abs(final_cost):.2f} SEK[/]"
            else:
                economy_str = f"[red]{final_cost:.2f} SEK[/]"

            # Correctness Check
            correct_icon = "[grey]-[/]"
            diff = 0.0
            if t_py > 0 and t_rust > 0:
                diff = abs(cost_py - cost_rust)
                if diff < 0.02:  # Slightly higher tolerance for solver diffs
                    correct_icon = "[green]✓[/]"
                else:
                    correct_icon = "[bold red]![/]"

            # Speedup & Visual Indicator
            speedup_str = "-"
            if t_rust > 0 and t_py > 0:
                speedup = t_py / t_rust
                bar_len = min(4, int(speedup / 500))
                bar_str = "█" * bar_len
                speedup_str = f"[bold cyan]{speedup:>8.1f}x[/] {bar_str}"

            # Memory String
            mem_str = f"{mem_py:>.1f}|{mem_rust:>.1f}" if t_py > 0 or t_rust > 0 else "-"

            if diff > 0.1 and t_py > 0 and t_rust > 0:
                console.print(f"\n[bold red]MISMATCH DETECTED for {sc['name']}![/]")
                console.print(
                    f"Py Cost: {cost_py:.4f}, Rust Cost: {cost_rust:.4f}, Diff: {diff:.4f}"
                )
                console.print("\n")

            table.add_row(
                sc["name"],
                sc["feature_matrix"],
                str(sc["complexity"]),
                fmt_t(t_py),
                fmt_t(t_rust),
                speedup_str,
                mem_str,
                economy_str,
                correct_icon,
            )

            progress_results.append(
                {
                    "name": sc["name"],
                    "complexity": sc["complexity"],
                    "t_py": t_py,
                    "t_rust": t_rust,
                    "cost": final_cost,
                    "diff": diff,
                    "mem_py": mem_py,
                    "mem_rust": mem_rust,
                }
            )

            progress.advance(task)

    console.print(table)

    # Save Report
    save_markdown_report(progress_results, sys_info)

    # Summary Footer
    time_saved = total_time_py - total_time_rust
    footer = (
        f"[bold green]Audit Complete.[/] Total Time Saved using Rust: "
        f"[bold cyan]{time_saved:.2f}s[/]\n"
        "[grey]Full report synced to BENCHMARK_REPORT.md[/]"
    )
    console.print(Panel(footer, border_style="green"))


if __name__ == "__main__":
    run_benchmark()
