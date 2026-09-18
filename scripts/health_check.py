#!/usr/bin/env python3
"""
🏥 Darkstar System Health Check
===============================
Comprehensive system health monitoring with beautiful terminal UI.

Usage:
    python scripts/health_check.py
    python scripts/health_check.py --quick    # Skip detailed checks
    python scripts/health_check.py --json     # JSON output for automation
"""

import asyncio
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.resolve()))


# Terminal colors and formatting
class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    END = "\033[0m"
    DIM = "\033[2m"


# Unicode symbols
class Symbols:
    CHECK = "✅"
    CROSS = "❌"
    WARNING = "⚠️"
    INFO = "i"
    ROCKET = "🚀"
    GEAR = "⚙️"
    DATABASE = "🗄️"
    NETWORK = "🌐"
    BRAIN = "🧠"
    BATTERY = "🔋"
    CLOCK = "⏰"
    CHART = "📊"
    SHIELD = "🛡️"


class HealthChecker:
    def __init__(self, base_url: str = "http://localhost:5000", quick_mode: bool = False):
        self.base_url = base_url
        self.quick_mode = quick_mode
        self.results: dict[str, Any] = {}
        self.start_time = time.time()

    def print_header(self):
        """Print beautiful header with system info."""
        print(f"\n{Colors.CYAN}{'=' * 80}{Colors.END}")
        print(f"{Colors.BOLD}{Colors.CYAN}🏥 DARKSTAR SYSTEM HEALTH CHECK{Colors.END}")
        print(f"{Colors.CYAN}{'=' * 80}{Colors.END}")
        print(f"{Colors.DIM}Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{Colors.END}")
        print(f"{Colors.DIM}Base URL:  {self.base_url}{Colors.END}")
        print(
            f"{Colors.DIM}Mode:      {'Quick' if self.quick_mode else 'Comprehensive'}{Colors.END}"
        )
        print()

    def print_section(self, title: str, icon: str):
        """Print section header."""
        print(f"\n{Colors.BOLD}{Colors.BLUE}{icon} {title}{Colors.END}")
        print(f"{Colors.BLUE}{'─' * (len(title) + 4)}{Colors.END}")

    def print_spinner(self, message: str, duration: float = 1.0):
        """Show spinning animation."""
        if "--json" in sys.argv:
            return

        spinners = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        end_time = time.time() + duration
        i = 0

        while time.time() < end_time:
            print(
                f"\r{Colors.CYAN}{spinners[i % len(spinners)]}{Colors.END} {message}",
                end="",
                flush=True,
            )
            time.sleep(0.1)
            i += 1
        print(f"\r{' ' * (len(message) + 3)}\r", end="")

    def print_progress_bar(self, current: int, total: int, prefix: str = "Progress"):
        """Show progress bar."""
        if "--json" in sys.argv:
            return

        percent = (current / total) * 100
        filled = int(50 * current // total)
        bar = "█" * filled + "░" * (50 - filled)
        print(
            f"\r{Colors.CYAN}{prefix}: |{bar}| {percent:.1f}% ({current}/{total}){Colors.END}",
            end="",
            flush=True,
        )
        if current == total:
            print()

    def print_table(self, headers: list[str], rows: list[list[str]], title: str = ""):
        """Print formatted table."""
        if title:
            print(f"\n{Colors.BOLD}{title}{Colors.END}")

        # Calculate column widths
        widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                if i < len(widths):
                    widths[i] = max(widths[i], len(str(cell)))

        # Print header
        header_line = (
            "│ " + " │ ".join(h.ljust(w) for h, w in zip(headers, widths, strict=False)) + " │"
        )
        separator = "├" + "┼".join("─" * (w + 2) for w in widths) + "┤"
        top_line = "┌" + "┬".join("─" * (w + 2) for w in widths) + "┐"
        bottom_line = "└" + "┴".join("─" * (w + 2) for w in widths) + "┘"

        print(f"{Colors.DIM}{top_line}{Colors.END}")
        print(f"{Colors.BOLD}{header_line}{Colors.END}")
        print(f"{Colors.DIM}{separator}{Colors.END}")

        # Print rows
        for row in rows:
            formatted_row: list[str] = []
            for i, cell in enumerate(row):
                cell_str = str(cell)
                if i < len(widths):
                    # Color code status cells
                    if cell_str in ["✅", "HEALTHY", "ONLINE", "SUCCESS"]:
                        cell_str = f"{Colors.GREEN}{cell_str}{Colors.END}"
                    elif cell_str in ["❌", "ERROR", "OFFLINE", "FAILED"]:
                        cell_str = f"{Colors.RED}{cell_str}{Colors.END}"
                    elif cell_str in ["⚠️", "WARNING", "DEGRADED"]:
                        cell_str = f"{Colors.YELLOW}{cell_str}{Colors.END}"
                    formatted_row.append(
                        cell_str.ljust(widths[i] + (len(cell_str) - len(str(cell))))
                    )
                else:
                    formatted_row.append(cell_str)

            row_line = "│ " + " │ ".join(formatted_row) + " │"
            print(row_line)

        print(f"{Colors.DIM}{bottom_line}{Colors.END}")

    async def check_api_endpoints(self) -> dict[str, Any]:
        """Check critical API endpoints."""
        self.print_section("API Endpoints Health", Symbols.NETWORK)

        endpoints = [
            ("GET", "/api/status", "System Status"),
            ("GET", "/api/health", "Health Check"),
            ("GET", "/api/version", "Version Info"),
            ("GET", "/api/aurora/dashboard", "Aurora Dashboard"),
            ("GET", "/api/executor/status", "Executor Status"),
            ("GET", "/api/schedule", "Current Schedule"),
            ("GET", "/api/config", "Configuration"),
            ("GET", "/api/learning/status", "Learning Engine"),
            ("GET", "/api/performance/data", "Performance Data"),
        ]

        results: list[list[str]] = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for i, (method, path, name) in enumerate(endpoints):
                self.print_progress_bar(i, len(endpoints), "Checking endpoints")

                try:
                    url = f"{self.base_url}{path}"
                    response = await client.request(method, url)

                    if response.status_code == 200:
                        status = Symbols.CHECK
                        health = "HEALTHY"
                        response_time = response.elapsed.total_seconds() * 1000
                    else:
                        status = Symbols.CROSS
                        health = f"HTTP {response.status_code}"
                        response_time = 0

                except Exception:
                    status = Symbols.CROSS
                    health = "ERROR"
                    response_time = 0

                results.append(
                    [status, name, health, f"{response_time:.0f}ms" if response_time else "N/A"]
                )

        self.print_progress_bar(len(endpoints), len(endpoints), "Checking endpoints")
        self.print_table(["Status", "Endpoint", "Health", "Response Time"], results)

        healthy_count = sum(1 for r in results if r[0] == Symbols.CHECK)
        return {
            "total_endpoints": len(endpoints),
            "healthy_endpoints": healthy_count,
            "health_percentage": (healthy_count / len(endpoints)) * 100,
            "details": results,
        }

    def check_database_health(self) -> dict[str, Any]:
        """Check database health and statistics."""
        self.print_section("Database Health", Symbols.DATABASE)

        try:
            # Load config to get DB path
            with Path("config.yaml").open() as f:
                config = yaml.safe_load(f)
            db_path = config.get("learning", {}).get("sqlite_path", "data/planner_learning.db")

            if not Path(db_path).exists():
                self.print_table(
                    ["Status", "Check", "Result"], [[Symbols.CROSS, "Database File", "NOT FOUND"]]
                )
                return {"status": "error", "message": "Database file not found"}

            # Get file size
            db_size = Path(db_path).stat().st_size / (1024 * 1024)  # MB

            # Connect and check tables
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()

                # Check critical tables
                tables_to_check = [
                    ("learning_runs", "Learning Runs"),
                    ("slot_observations", "Slot Observations"),
                    ("slot_forecasts", "Slot Forecasts"),
                    ("slot_plans", "Slot Plans"),
                    ("execution_log", "Execution Log"),
                ]

                results: list[list[str]] = []
                total_records = 0

                for table, display_name in tables_to_check:
                    try:
                        cursor.execute(f"SELECT COUNT(*) FROM {table}")
                        count = cursor.fetchone()[0]
                        total_records += count

                        if count > 0:
                            status = Symbols.CHECK
                            health = "HEALTHY"
                        else:
                            status = Symbols.WARNING
                            health = "EMPTY"

                        results.append([status, display_name, f"{count:,}", health])
                    except sqlite3.OperationalError:
                        results.append([Symbols.CROSS, display_name, "N/A", "MISSING"])

                # Check recent activity (last 24h)
                try:
                    cursor.execute("""
                        SELECT COUNT(*) FROM slot_observations
                        WHERE created_at > datetime('now', '-1 day')
                    """)
                    recent_obs = cursor.fetchone()[0]
                except Exception:
                    recent_obs = 0

                self.print_table(["Status", "Table", "Records", "Health"], results)

                # Summary stats
                summary_data = [
                    [Symbols.DATABASE, "Database Size", f"{db_size:.1f} MB", ""],
                    [Symbols.CHART, "Total Records", f"{total_records:,}", ""],
                    [Symbols.CLOCK, "Recent Activity (24h)", f"{recent_obs:,} observations", ""],
                ]

                self.print_table(["", "Metric", "Value", ""], summary_data, "Database Summary")

                return {
                    "status": "healthy" if total_records > 0 else "warning",
                    "size_mb": round(db_size, 1),
                    "total_records": total_records,
                    "recent_activity": recent_obs,
                    "tables": {
                        table: count
                        for (table, _), [_, _, count_str, _] in zip(
                            tables_to_check, results, strict=False
                        )
                        if count_str != "N/A"
                        for count in [int(count_str.replace(",", ""))]
                    },
                }

        except Exception as e:
            self.print_table(
                ["Status", "Check", "Result"], [[Symbols.CROSS, "Database Check", f"ERROR: {e!s}"]]
            )
            return {"status": "error", "message": str(e)}

    def check_ml_models(self) -> dict[str, Any]:
        """Check ML model availability and freshness."""
        self.print_section("Machine Learning Models", Symbols.BRAIN)

        models_dir = Path("data/ml/models")
        if not models_dir.exists():
            self.print_table(
                ["Status", "Check", "Result"], [[Symbols.CROSS, "Models Directory", "NOT FOUND"]]
            )
            return {"status": "error", "message": "Models directory not found"}

        expected_models = [
            "load_model.lgb",
            "load_model_p10.lgb",
            "load_model_p50.lgb",
            "load_model_p90.lgb",
            "pv_model.lgb",
            "pv_model_p10.lgb",
            "pv_model_p50.lgb",
            "pv_model_p90.lgb",
        ]

        optional_models = [
            "pv_error.lgb",
            "load_error.lgb",
        ]

        results: list[list[str]] = []
        found_models = 0

        # Check core models
        for model in expected_models:
            model_path = models_dir / model
            if model_path.exists():
                # Get model age
                age = datetime.now() - datetime.fromtimestamp(model_path.stat().st_mtime)
                age_str = f"{age.days}d ago" if age.days > 0 else f"{age.seconds // 3600}h ago"
                size_mb = model_path.stat().st_size / (1024 * 1024)

                results.append([Symbols.CHECK, model, f"{size_mb:.1f}MB", age_str])
                found_models += 1
            else:
                results.append([Symbols.CROSS, model, "MISSING", "N/A"])

        # Check optional models
        for model in optional_models:
            model_path = models_dir / model
            if model_path.exists():
                age = datetime.now() - datetime.fromtimestamp(model_path.stat().st_mtime)
                age_str = f"{age.days}d ago" if age.days > 0 else f"{age.seconds // 3600}h ago"
                size_mb = model_path.stat().st_size / (1024 * 1024)
                results.append([Symbols.CHECK, f"{model} (optional)", f"{size_mb:.1f}MB", age_str])
            else:
                results.append([Symbols.WARNING, f"{model} (optional)", "MISSING", "N/A"])

        self.print_table(["Status", "Model", "Size", "Last Modified"], results)

        model_health = "healthy" if found_models == len(expected_models) else "degraded"

        return {
            "status": model_health,
            "core_models_found": found_models,
            "core_models_expected": len(expected_models),
            "model_coverage": (found_models / len(expected_models)) * 100,
        }

    def check_system_files(self) -> dict[str, Any]:
        """Check critical system files."""
        self.print_section("System Files", Symbols.GEAR)

        critical_files = [
            ("config.yaml", "Main Configuration"),
            ("secrets.yaml", "Secrets Configuration"),
            ("data/schedule.json", "Current Schedule"),
            ("data/planner_learning.db", "Learning Database"),
            ("data/ml/models/", "ML Models Directory"),
        ]

        results: list[list[str]] = []
        files_ok = 0

        for file_path, description in critical_files:
            path = Path(file_path)

            if path.exists():
                if path.is_file():
                    size = path.stat().st_size
                    if size > 0:
                        size_str = (
                            f"{size / 1024:.1f}KB"
                            if size < 1024 * 1024
                            else f"{size / (1024 * 1024):.1f}MB"
                        )
                        results.append([Symbols.CHECK, description, "EXISTS", size_str])
                        files_ok += 1
                    else:
                        results.append([Symbols.WARNING, description, "EMPTY", "0B"])
                else:  # Directory
                    file_count = len(list(path.iterdir())) if path.is_dir() else 0
                    results.append([Symbols.CHECK, description, "EXISTS", f"{file_count} files"])
                    files_ok += 1
            else:
                results.append([Symbols.CROSS, description, "MISSING", "N/A"])

        self.print_table(["Status", "File", "Status", "Size"], results)

        return {
            "status": "healthy" if files_ok == len(critical_files) else "degraded",
            "files_found": files_ok,
            "files_expected": len(critical_files),
        }

    def check_schedule_freshness(self) -> dict[str, Any]:
        """Check if schedule is recent and valid."""
        self.print_section("Schedule Health", Symbols.CLOCK)

        schedule_path = Path("data/schedule.json")
        if not schedule_path.exists():
            self.print_table(
                ["Status", "Check", "Result"], [[Symbols.CROSS, "Schedule File", "NOT FOUND"]]
            )
            return {"status": "error", "message": "Schedule file not found"}

        try:
            # Check file age
            mtime = datetime.fromtimestamp(schedule_path.stat().st_mtime)
            age = datetime.now() - mtime

            # Load and validate schedule
            with schedule_path.open() as f:
                schedule_data = json.load(f)

            schedule_slots = schedule_data.get("schedule", [])
            metadata = schedule_data.get("metadata", {})

            # Check if schedule is recent (< 2 hours old)
            if age.total_seconds() < 7200:  # 2 hours
                freshness_status = Symbols.CHECK
                freshness = "FRESH"
            elif age.total_seconds() < 86400:  # 24 hours
                freshness_status = Symbols.WARNING
                freshness = "STALE"
            else:
                freshness_status = Symbols.CROSS
                freshness = "OLD"

            results = [
                [
                    freshness_status,
                    "Schedule Freshness",
                    freshness,
                    f"{age.total_seconds() / 3600:.1f}h ago",
                ],
                [
                    Symbols.CHECK if schedule_slots else Symbols.CROSS,
                    "Schedule Slots",
                    f"{len(schedule_slots)} slots",
                    "",
                ],
                [
                    Symbols.CHECK if metadata else Symbols.WARNING,
                    "Metadata",
                    "Present" if metadata else "Missing",
                    "",
                ],
            ]

            self.print_table(["Status", "Check", "Result", "Details"], results)

            return {
                "status": "healthy"
                if age.total_seconds() < 7200 and schedule_slots
                else "degraded",
                "age_hours": age.total_seconds() / 3600,
                "slot_count": len(schedule_slots),
                "has_metadata": bool(metadata),
            }

        except Exception as e:
            self.print_table(
                ["Status", "Check", "Result"],
                [[Symbols.CROSS, "Schedule Validation", f"ERROR: {e!s}"]],
            )
            return {"status": "error", "message": str(e)}

    def print_summary(self, all_results: dict[str, Any]) -> dict[str, Any]:
        """Print comprehensive summary."""
        self.print_section("Health Summary", Symbols.SHIELD)

        health_scores: list[float] = []
        for _component, result in all_results.items():
            if isinstance(result, dict) and "status" in result:
                if result["status"] in ["healthy", "success"]:
                    health_scores.append(100)
                elif result["status"] in ["warning", "degraded"]:
                    health_scores.append(70)
                else:
                    health_scores.append(0)
            elif isinstance(result, dict) and "health_percentage" in result:
                health_scores.append(result["health_percentage"])  # type: ignore[arg-type]

        overall_health = sum(health_scores) / len(health_scores) if health_scores else 0

        # Determine overall status
        if overall_health >= 90:
            overall_status = f"{Colors.GREEN}EXCELLENT{Colors.END}"
            status_icon = Symbols.CHECK
        elif overall_health >= 70:
            overall_status = f"{Colors.YELLOW}GOOD{Colors.END}"
            status_icon = Symbols.WARNING
        else:
            overall_status = f"{Colors.RED}NEEDS ATTENTION{Colors.END}"
            status_icon = Symbols.CROSS

        # Summary table
        summary_rows: list[list[str]] = []
        for component, result in all_results.items():
            if isinstance(result, dict):
                if "health_percentage" in result:
                    score = f"{result['health_percentage']:.1f}%"
                    status = Symbols.CHECK if result["health_percentage"] >= 80 else Symbols.WARNING
                elif "status" in result:
                    if result["status"] in ["healthy", "success"]:
                        score = "100%"
                        status = Symbols.CHECK
                    elif result["status"] in ["warning", "degraded"]:
                        score = "70%"
                        status = Symbols.WARNING
                    else:
                        score = "0%"
                        status = Symbols.CROSS
                else:
                    score = "N/A"
                    status = Symbols.INFO

                summary_rows.append([status, component.replace("_", " ").title(), score])

        self.print_table(["Status", "Component", "Health Score"], summary_rows)

        # Overall summary
        elapsed_time = time.time() - self.start_time

        print(
            f"\n{Colors.BOLD}🎯 OVERALL SYSTEM HEALTH: {status_icon} {overall_status} ({overall_health:.1f}%){Colors.END}"
        )
        print(f"{Colors.DIM}Health check completed in {elapsed_time:.1f}s{Colors.END}")

        if overall_health < 70:
            print(f"\n{Colors.YELLOW}⚠️  RECOMMENDATIONS:{Colors.END}")
            if all_results.get("api_endpoints", {}).get("health_percentage", 100) < 80:
                print("  • Check if Darkstar service is running properly")
            if all_results.get("database_health", {}).get("status") != "healthy":
                print("  • Verify database integrity and recent data collection")
            if all_results.get("ml_models", {}).get("status") != "healthy":
                print("  • Run ML training to generate missing models")
            if all_results.get("schedule_health", {}).get("status") != "healthy":
                print("  • Check planner service and schedule generation")

        return {
            "overall_health": overall_health,
            "overall_status": overall_status.replace(Colors.GREEN, "")
            .replace(Colors.YELLOW, "")
            .replace(Colors.RED, "")
            .replace(Colors.END, ""),
            "components": all_results,
            "elapsed_time": elapsed_time,
        }

    async def run_health_check(self) -> dict[str, Any]:
        """Run complete health check."""
        self.print_header()

        # Initialize results
        all_results: dict[str, Any] = {}

        # Run checks
        self.print_spinner("Initializing health check...", 0.5)

        if not self.quick_mode:
            all_results["api_endpoints"] = await self.check_api_endpoints()
            all_results["database_health"] = self.check_database_health()
            all_results["ml_models"] = self.check_ml_models()
            all_results["system_files"] = self.check_system_files()
            all_results["schedule_health"] = self.check_schedule_freshness()
        else:
            # Quick mode - just API and basic checks
            all_results["api_endpoints"] = await self.check_api_endpoints()
            all_results["system_files"] = self.check_system_files()

        # Print summary
        summary = self.print_summary(all_results)

        return summary


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Darkstar System Health Check")
    parser.add_argument("--quick", action="store_true", help="Run quick health check")
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    parser.add_argument("--url", default="http://localhost:5000", help="Base URL for API checks")

    args = parser.parse_args()

    checker = HealthChecker(base_url=args.url, quick_mode=args.quick)

    try:
        results = await checker.run_health_check()

        if args.json:
            print(json.dumps(results, indent=2, default=str))

        # Exit with appropriate code
        overall_health = results.get("overall_health", 0)
        if overall_health >= 90:
            sys.exit(0)  # Excellent
        elif overall_health >= 70:
            sys.exit(1)  # Good but with warnings
        else:
            sys.exit(2)  # Needs attention

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Health check interrupted by user{Colors.END}")
        sys.exit(130)
    except Exception as e:
        print(f"\n{Colors.RED}Health check failed: {e!s}{Colors.END}")
        sys.exit(3)


if __name__ == "__main__":
    asyncio.run(main())
