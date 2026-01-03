"""
Dashboard Performance Test Suite

Production-grade performance testing for all Dashboard API endpoints.
Measures response times, establishes baselines, and generates reports.

Usage:
    PYTHONPATH=. python -m pytest tests/performance/ -v --tb=short
"""

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

# Ensure backend can be imported
sys.path.insert(0, str(Path.cwd()))


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

# Endpoint definitions with thresholds (in milliseconds)
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

# Total dashboard load time thresholds
TOTAL_THRESHOLD_WARN_MS = 2000
TOTAL_THRESHOLD_ERROR_MS = 5000


# -----------------------------------------------------------------------------
# Data Classes
# -----------------------------------------------------------------------------


@dataclass
class EndpointResult:
    """Result of timing a single endpoint."""

    endpoint: str
    response_time_ms: float
    status_code: int
    threshold_warn: int
    threshold_error: int
    critical: bool
    success: bool = True
    error: str | None = None

    @property
    def status(self) -> str:
        if not self.success:
            return "ERROR"
        if self.response_time_ms >= self.threshold_error:
            return "SLOW"
        if self.response_time_ms >= self.threshold_warn:
            return "WARN"
        return "OK"

    @property
    def status_emoji(self) -> str:
        return {"OK": "✓", "WARN": "⚠", "SLOW": "❌", "ERROR": "💥"}.get(
            self.status, "?"
        )


@dataclass
class PerformanceReport:
    """Complete performance report for the dashboard."""

    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    endpoints: list[EndpointResult] = field(default_factory=list)
    total_time_ms: float = 0.0
    parallel_time_ms: float = 0.0

    @property
    def slowest_endpoint(self) -> EndpointResult | None:
        if not self.endpoints:
            return None
        return max(self.endpoints, key=lambda e: e.response_time_ms)

    @property
    def failed_endpoints(self) -> list[EndpointResult]:
        return [e for e in self.endpoints if not e.success]

    @property
    def slow_endpoints(self) -> list[EndpointResult]:
        return [e for e in self.endpoints if e.status in ("SLOW", "WARN")]

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "summary": {
                "total_time_ms": round(self.total_time_ms, 2),
                "parallel_time_ms": round(self.parallel_time_ms, 2),
                "endpoint_count": len(self.endpoints),
                "failed_count": len(self.failed_endpoints),
                "slow_count": len(self.slow_endpoints),
            },
            "endpoints": [
                {
                    "endpoint": e.endpoint,
                    "response_time_ms": round(e.response_time_ms, 2),
                    "status_code": e.status_code,
                    "status": e.status,
                    "critical": e.critical,
                    "error": e.error,
                }
                for e in sorted(self.endpoints, key=lambda x: -x.response_time_ms)
            ],
            "thresholds": {
                "total_warn_ms": TOTAL_THRESHOLD_WARN_MS,
                "total_error_ms": TOTAL_THRESHOLD_ERROR_MS,
            },
        }

    def print_report(self) -> None:
        """Print a human-readable report to stdout."""
        print("\n" + "=" * 70)
        print("  DARKSTAR DASHBOARD PERFORMANCE REPORT")
        print("=" * 70)
        print(f"  Timestamp: {self.timestamp}")
        print(f"  Total Sequential Time: {self.total_time_ms:.0f}ms")
        print(f"  Simulated Parallel Time: {self.parallel_time_ms:.0f}ms")
        print("-" * 70)
        print(f"  {'Endpoint':<40} {'Time (ms)':>10} {'Status':>10}")
        print("-" * 70)

        for e in sorted(self.endpoints, key=lambda x: -x.response_time_ms):
            status_str = f"{e.status_emoji} {e.status}"
            crit = " [CRIT]" if e.critical else ""
            print(f"  {e.endpoint:<40} {e.response_time_ms:>10.0f} {status_str:>10}{crit}")

        print("-" * 70)
        if self.slow_endpoints:
            print(f"  ⚠ {len(self.slow_endpoints)} endpoint(s) are slow")
        if self.failed_endpoints:
            print(f"  ❌ {len(self.failed_endpoints)} endpoint(s) failed")
        if not self.slow_endpoints and not self.failed_endpoints:
            print("  ✓ All endpoints within thresholds")
        print("=" * 70 + "\n")


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    """Create a FastAPI TestClient for the backend."""
    from fastapi.testclient import TestClient

    from backend.main import create_app

    app = create_app()
    # Unwrap Socket.IO wrapper to get raw FastAPI app
    fastapi_app = app.other_asgi_app if hasattr(app, "other_asgi_app") else app
    return TestClient(fastapi_app)


@pytest.fixture(scope="module")
def performance_report() -> PerformanceReport:
    """Shared report object for collecting results."""
    return PerformanceReport()


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------


def time_endpoint(client: Any, endpoint: str, config: dict[str, Any]) -> EndpointResult:
    """Time a single endpoint request."""
    start = time.perf_counter()
    try:
        response = client.get(endpoint)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return EndpointResult(
            endpoint=endpoint,
            response_time_ms=elapsed_ms,
            status_code=response.status_code,
            threshold_warn=config["threshold_warn"],
            threshold_error=config["threshold_error"],
            critical=config["critical"],
            success=response.status_code == 200,
            error=None if response.status_code == 200 else f"HTTP {response.status_code}",
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


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------


class TestDashboardPerformance:
    """Performance tests for Dashboard API endpoints."""

    def test_endpoint_response_times(self, client: Any, performance_report: PerformanceReport) -> None:
        """Measure response time for each Dashboard endpoint."""
        total_start = time.perf_counter()

        for endpoint, config in DASHBOARD_ENDPOINTS.items():
            result = time_endpoint(client, endpoint, config)
            performance_report.endpoints.append(result)

            # Assert critical endpoints don't fail
            if result.critical:
                assert result.success, f"Critical endpoint {endpoint} failed: {result.error}"

        performance_report.total_time_ms = (time.perf_counter() - total_start) * 1000

        # Calculate simulated parallel time (max of all)
        if performance_report.endpoints:
            performance_report.parallel_time_ms = max(
                e.response_time_ms for e in performance_report.endpoints
            )

    def test_no_critically_slow_endpoints(self, performance_report: PerformanceReport) -> None:
        """Ensure no endpoint exceeds the error threshold."""
        for result in performance_report.endpoints:
            if result.critical:
                assert result.response_time_ms < result.threshold_error, (
                    f"Critical endpoint {result.endpoint} is too slow: "
                    f"{result.response_time_ms:.0f}ms > {result.threshold_error}ms threshold"
                )

    def test_total_load_time(self, performance_report: PerformanceReport) -> None:
        """Test that total dashboard load time is acceptable."""
        # In a real browser, requests are parallel, so we use parallel_time_ms
        assert performance_report.parallel_time_ms < TOTAL_THRESHOLD_ERROR_MS, (
            f"Dashboard load time too slow: {performance_report.parallel_time_ms:.0f}ms "
            f"> {TOTAL_THRESHOLD_ERROR_MS}ms threshold"
        )

    def test_generate_performance_report(self, performance_report: PerformanceReport) -> None:
        """Generate and save the performance report."""
        # Print human-readable report
        performance_report.print_report()

        # Save JSON report
        report_dir = Path("tests/performance/reports")
        report_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = report_dir / f"performance_{timestamp}.json"

        with report_path.open("w") as f:
            json.dump(performance_report.to_dict(), f, indent=2)

        print(f"  Report saved to: {report_path}")

        # Also save as latest.json for easy access
        latest_path = report_dir / "latest.json"
        with latest_path.open("w") as f:
            json.dump(performance_report.to_dict(), f, indent=2)


# -----------------------------------------------------------------------------
# Standalone Runner
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    # Allow running directly: python tests/performance/test_dashboard_performance.py
    pytest.main([__file__, "-v", "--tb=short"])
