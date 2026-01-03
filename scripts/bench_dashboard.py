#!/usr/bin/env python3
"""
Dashboard Performance Benchmark CLI

A standalone tool to benchmark Dashboard API endpoints against a running
Darkstar instance. Outputs colored terminal report and JSON file.

Usage:
    # Against local dev server
    python scripts/bench_dashboard.py

    # Against custom URL
    python scripts/bench_dashboard.py --url http://localhost:8080

    # Save JSON report to specific location
    python scripts/bench_dashboard.py --output results.json
"""

import argparse
import contextlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    print("Error: 'requests' package required. Install with: pip install requests")
    sys.exit(1)


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

DEFAULT_URL = "http://localhost:5173"

# Same thresholds as test suite for consistency
DASHBOARD_ENDPOINTS = {
    "/api/status": {"threshold_warn": 200, "threshold_error": 500, "critical": True},
    "/api/config": {"threshold_warn": 100, "threshold_error": 300, "critical": True},
    "/api/ha/average": {"threshold_warn": 500, "threshold_error": 2000, "critical": False},
    "/api/schedule": {"threshold_warn": 200, "threshold_error": 500, "critical": True},
    "/api/learning/status": {"threshold_warn": 200, "threshold_error": 500, "critical": False},
    "/api/scheduler/status": {"threshold_warn": 100, "threshold_error": 300, "critical": False},
    "/api/energy/today": {"threshold_warn": 500, "threshold_error": 2000, "critical": False},
    "/api/ha/water_today": {"threshold_warn": 300, "threshold_error": 1000, "critical": False},
    "/api/aurora/dashboard": {"threshold_warn": 800, "threshold_error": 3000, "critical": False},
    "/api/executor/status": {"threshold_warn": 100, "threshold_error": 300, "critical": True},
    "/api/schedule/today_with_history": {"threshold_warn": 300, "threshold_error": 1000, "critical": False},
}


# -----------------------------------------------------------------------------
# ANSI Colors
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


# -----------------------------------------------------------------------------
# Data Classes
# -----------------------------------------------------------------------------

@dataclass
class EndpointResult:
    endpoint: str
    response_time_ms: float
    status_code: int
    threshold_warn: int
    threshold_error: int
    critical: bool
    success: bool = True
    error: str | None = None
    server_time_ms: float | None = None  # From X-Response-Time header

    @property
    def status(self) -> str:
        if not self.success:
            return "ERROR"
        if self.response_time_ms >= self.threshold_error:
            return "SLOW"
        if self.response_time_ms >= self.threshold_warn:
            return "WARN"
        return "OK"


# -----------------------------------------------------------------------------
# Benchmark Functions
# -----------------------------------------------------------------------------

def time_endpoint(base_url: str, endpoint: str, config: dict[str, Any]) -> EndpointResult:
    """Time a single endpoint request."""
    url = f"{base_url.rstrip('/')}{endpoint}"
    start = time.perf_counter()

    try:
        response = requests.get(url, timeout=30)
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Try to get server-side timing
        server_time = None
        if "X-Response-Time" in response.headers:
            with contextlib.suppress(ValueError):
                server_time = float(response.headers["X-Response-Time"].replace("ms", ""))

        return EndpointResult(
            endpoint=endpoint,
            response_time_ms=elapsed_ms,
            status_code=response.status_code,
            threshold_warn=config["threshold_warn"],
            threshold_error=config["threshold_error"],
            critical=config["critical"],
            success=response.status_code == 200,
            error=None if response.status_code == 200 else f"HTTP {response.status_code}",
            server_time_ms=server_time,
        )
    except requests.exceptions.ConnectionError:
        return EndpointResult(
            endpoint=endpoint,
            response_time_ms=0,
            status_code=0,
            threshold_warn=config["threshold_warn"],
            threshold_error=config["threshold_error"],
            critical=config["critical"],
            success=False,
            error="Connection refused",
        )
    except requests.exceptions.Timeout:
        return EndpointResult(
            endpoint=endpoint,
            response_time_ms=30000,
            status_code=0,
            threshold_warn=config["threshold_warn"],
            threshold_error=config["threshold_error"],
            critical=config["critical"],
            success=False,
            error="Timeout (30s)",
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return EndpointResult(
            endpoint=endpoint,
            response_time_ms=elapsed_ms,
            status_code=0,
            threshold_warn=config["threshold_warn"],
            threshold_error=config["threshold_error"],
            critical=config["critical"],
            success=False,
            error=str(e),
        )


def run_sequential_benchmark(base_url: str) -> tuple[list[EndpointResult], float]:
    """Run benchmarks sequentially and return results with total time."""
    results = []
    total_start = time.perf_counter()

    for endpoint, config in DASHBOARD_ENDPOINTS.items():
        result = time_endpoint(base_url, endpoint, config)
        results.append(result)

    total_ms = (time.perf_counter() - total_start) * 1000
    return results, total_ms


def run_parallel_benchmark(base_url: str) -> tuple[list[EndpointResult], float]:
    """Run benchmarks in parallel (simulating browser behavior)."""
    results = []
    total_start = time.perf_counter()

    with ThreadPoolExecutor(max_workers=11) as executor:
        futures = {
            executor.submit(time_endpoint, base_url, ep, cfg): ep
            for ep, cfg in DASHBOARD_ENDPOINTS.items()
        }
        for future in as_completed(futures):
            results.append(future.result())

    total_ms = (time.perf_counter() - total_start) * 1000
    return results, total_ms


def print_report(
    results: list[EndpointResult],
    sequential_time_ms: float,
    parallel_time_ms: float,
    base_url: str,
) -> None:
    """Print a colored terminal report."""
    print()
    print(colored("╭" + "─" * 68 + "╮", Colors.CYAN))
    print(colored("│", Colors.CYAN) + colored("  DARKSTAR DASHBOARD PERFORMANCE REPORT", Colors.BOLD).center(76) + colored("│", Colors.CYAN))
    print(colored("╰" + "─" * 68 + "╯", Colors.CYAN))
    print()
    print(f"  {colored('Target:', Colors.GRAY)} {base_url}")
    print(f"  {colored('Time:', Colors.GRAY)} {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    print(f"  {colored('Sequential Total:', Colors.GRAY)} {sequential_time_ms:.0f}ms")
    print(f"  {colored('Parallel Total:', Colors.GRAY)} {parallel_time_ms:.0f}ms {colored('(browser behavior)', Colors.GRAY)}")
    print()
    print(colored("─" * 70, Colors.GRAY))
    print(f"  {'Endpoint':<40} {'Time':>8} {'Server':>8} {'Status':>10}")
    print(colored("─" * 70, Colors.GRAY))

    # Sort by response time descending
    for r in sorted(results, key=lambda x: -x.response_time_ms):
        # Color based on status
        if r.status == "OK":
            status_str = colored("✓ OK", Colors.GREEN)
            time_color = Colors.GREEN
        elif r.status == "WARN":
            status_str = colored("⚠ WARN", Colors.YELLOW)
            time_color = Colors.YELLOW
        elif r.status == "SLOW":
            status_str = colored("❌ SLOW", Colors.RED)
            time_color = Colors.RED
        else:
            status_str = colored("💥 ERR", Colors.RED)
            time_color = Colors.RED

        time_str = colored(f"{r.response_time_ms:>6.0f}ms", time_color)
        server_str = f"{r.server_time_ms:>6.0f}ms" if r.server_time_ms else colored("    N/A", Colors.GRAY)

        crit = colored(" [CRIT]", Colors.CYAN) if r.critical else ""
        print(f"  {r.endpoint:<40} {time_str} {server_str} {status_str}{crit}")

    print(colored("─" * 70, Colors.GRAY))

    # Summary
    slow = [r for r in results if r.status in ("SLOW", "WARN")]
    failed = [r for r in results if not r.success]

    if failed:
        print(colored(f"  ❌ {len(failed)} endpoint(s) failed", Colors.RED))
    if slow:
        print(colored(f"  ⚠ {len(slow)} endpoint(s) are slow", Colors.YELLOW))
    if not slow and not failed:
        print(colored("  ✓ All endpoints within thresholds", Colors.GREEN))

    print()


def save_json_report(
    results: list[EndpointResult],
    sequential_time_ms: float,
    parallel_time_ms: float,
    output_path: Path,
) -> None:
    """Save JSON report to file."""
    report = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "sequential_time_ms": round(sequential_time_ms, 2),
            "parallel_time_ms": round(parallel_time_ms, 2),
            "endpoint_count": len(results),
            "failed_count": len([r for r in results if not r.success]),
            "slow_count": len([r for r in results if r.status in ("SLOW", "WARN")]),
        },
        "endpoints": [
            {
                "endpoint": r.endpoint,
                "response_time_ms": round(r.response_time_ms, 2),
                "server_time_ms": round(r.server_time_ms, 2) if r.server_time_ms else None,
                "status_code": r.status_code,
                "status": r.status,
                "critical": r.critical,
                "error": r.error,
            }
            for r in sorted(results, key=lambda x: -x.response_time_ms)
        ],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        json.dump(report, f, indent=2)

    print(f"  {colored('Report saved:', Colors.GRAY)} {output_path}")
    print()


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark Darkstar Dashboard API endpoints",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"Base URL of Darkstar instance (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("tests/performance/reports/bench_latest.json"),
        help="Output path for JSON report",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Only run parallel benchmark (faster)",
    )
    args = parser.parse_args()

    print()
    print(colored("  Benchmarking Darkstar Dashboard...", Colors.CYAN))
    print()

    # Run benchmarks
    if args.parallel:
        results, parallel_time = run_parallel_benchmark(args.url)
        sequential_time = sum(r.response_time_ms for r in results)
    else:
        # Run sequential first
        results, sequential_time = run_sequential_benchmark(args.url)
        # Then parallel
        _, parallel_time = run_parallel_benchmark(args.url)

    # Check for connection errors
    if all(r.error == "Connection refused" for r in results):
        print(colored(f"  ❌ Cannot connect to {args.url}", Colors.RED))
        print(colored("     Is the server running?", Colors.GRAY))
        print()
        return 1

    # Print report
    print_report(results, sequential_time, parallel_time, args.url)

    # Save JSON
    save_json_report(results, sequential_time, parallel_time, args.output)

    # Return exit code based on results
    if any(not r.success for r in results):
        return 1
    if any(r.status == "SLOW" for r in results):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
