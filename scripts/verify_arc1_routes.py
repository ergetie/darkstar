#!/usr/bin/env python3
"""
ARC1 Route Verification Script
Compares all routes from the old Flask webapp.py against the new FastAPI routers.
Reports missing, broken, or incomplete routes.

Usage: python scripts/verify_arc1_routes.py
"""

import asyncio
import sys

import httpx

# All routes from the old Flask webapp.py (main branch)
OLD_ROUTES = [
    # Themes
    ("GET", "/api/themes"),
    ("POST", "/api/theme"),
    # Forecast
    ("GET", "/api/forecast/eval"),
    ("GET", "/api/forecast/day"),
    ("GET", "/api/forecast/horizon"),
    ("POST", "/api/forecast/run_eval"),
    ("POST", "/api/forecast/run_forward"),
    # Schedule
    ("GET", "/api/schedule"),
    ("GET", "/api/schedule/today_with_history"),
    ("POST", "/api/schedule/save"),
    # System
    ("GET", "/api/health"),
    ("GET", "/api/status"),
    ("GET", "/api/version"),
    ("GET", "/api/scheduler/status"),
    ("GET", "/api/ha-socket"),
    # Config
    ("GET", "/api/config"),
    ("POST", "/api/config/save"),
    ("POST", "/api/config/reset"),
    ("GET", "/api/initial_state"),
    # Energy
    ("GET", "/api/energy/today"),
    ("GET", "/api/energy/range"),
    # Executor
    ("GET", "/api/executor/status"),
    ("POST", "/api/executor/toggle"),
    ("POST", "/api/executor/run"),
    ("GET", "/api/executor/quick-action"),
    ("POST", "/api/executor/quick-action"),
    ("DELETE", "/api/executor/quick-action"),
    ("GET", "/api/executor/history"),
    ("GET", "/api/executor/stats"),
    ("GET", "/api/executor/config"),
    ("PUT", "/api/executor/config"),
    ("GET", "/api/executor/notifications"),
    ("POST", "/api/executor/notifications"),
    ("POST", "/api/executor/notifications/test"),
    ("GET", "/api/executor/live"),
    ("POST", "/api/executor/pause"),
    ("POST", "/api/executor/resume"),
    # Water
    ("GET", "/api/water/boost"),
    ("POST", "/api/water/boost"),
    ("DELETE", "/api/water/boost"),
    # DB
    ("GET", "/api/db/current_schedule"),
    ("POST", "/api/db/push_current"),
    # HA
    ("POST", "/api/ha/test"),
    ("GET", "/api/ha/entities"),
    ("GET", "/api/ha/services"),
    ("GET", "/api/ha/entity/sensor.test"),
    ("GET", "/api/ha/average"),
    ("GET", "/api/ha/water_today"),
    # Learning
    ("GET", "/api/learning/status"),
    ("GET", "/api/learning/history"),
    ("POST", "/api/learning/run"),
    ("GET", "/api/learning/loops"),
    ("GET", "/api/learning/daily_metrics"),
    ("GET", "/api/learning/changes"),
    ("POST", "/api/learning/record_observation"),
    # Analyst
    ("GET", "/api/analyst/advice"),
    ("GET", "/api/analyst/run"),
    # Debug
    ("GET", "/api/debug"),
    ("GET", "/api/debug/logs"),
    # History
    ("GET", "/api/history/soc"),
    # Performance
    ("GET", "/api/performance/data"),
    ("GET", "/api/performance/metrics"),
    # Planner
    ("POST", "/api/run_planner"),
    # Simulate
    ("POST", "/api/simulate"),
    # Aurora
    ("GET", "/api/aurora/dashboard"),
    ("POST", "/api/aurora/briefing"),
    ("POST", "/api/aurora/config/toggle_reflex"),
]

BASE_URL = "http://localhost:5000"


async def check_route(
    client: httpx.AsyncClient, method: str, path: str
) -> tuple[str, str, int, str]:
    """Check if a route responds."""
    url = f"{BASE_URL}{path}"
    try:
        if method == "GET":
            resp = await client.get(url, timeout=5.0)
        elif method == "POST":
            resp = await client.post(url, json={}, timeout=5.0)
        elif method == "PUT":
            resp = await client.put(url, json={}, timeout=5.0)
        elif method == "DELETE":
            resp = await client.delete(url, timeout=5.0)
        else:
            return method, path, -1, f"Unknown method: {method}"

        return method, path, resp.status_code, ""
    except Exception as e:
        return method, path, -1, str(e)


async def main():
    print("=" * 60)
    print("ARC1 Route Verification")
    print("=" * 60)
    print(f"Base URL: {BASE_URL}")
    print(f"Total routes to check: {len(OLD_ROUTES)}")
    print("-" * 60)

    async with httpx.AsyncClient() as client:
        tasks = [check_route(client, m, p) for m, p in OLD_ROUTES]
        results = await asyncio.gather(*tasks)

    # Categorize results
    ok = []
    not_found = []
    server_error = []
    other = []

    for method, path, status, error in results:
        if status == 200:
            ok.append((method, path))
        elif status == 404:
            not_found.append((method, path))
        elif status >= 500:
            server_error.append((method, path, status, error))
        else:
            other.append((method, path, status, error))

    print(f"\n✅ OK (200): {len(ok)}")
    print(f"❌ NOT FOUND (404): {len(not_found)}")
    print(f"💥 SERVER ERROR (5xx): {len(server_error)}")
    print(f"⚠️ OTHER: {len(other)}")

    if not_found:
        print("\n" + "=" * 60)
        print("MISSING ROUTES (404)")
        print("=" * 60)
        for method, path in not_found:
            print(f"  {method:6} {path}")

    if server_error:
        print("\n" + "=" * 60)
        print("SERVER ERRORS (5xx)")
        print("=" * 60)
        for method, path, status, error in server_error:
            print(f"  {method:6} {path} -> {status}")
            if error:
                print(f"         Error: {error[:100]}")

    if other:
        print("\n" + "=" * 60)
        print("OTHER ISSUES")
        print("=" * 60)
        for method, path, status, error in other:
            print(f"  {method:6} {path} -> {status}")
            if error:
                print(f"         Error: {error[:100]}")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    total = len(OLD_ROUTES)
    print(f"Routes working: {len(ok)}/{total} ({100 * len(ok) / total:.1f}%)")
    print(f"Routes missing: {len(not_found)}/{total}")
    print(f"Routes broken:  {len(server_error)}/{total}")

    # Return exit code based on results
    if not_found or server_error:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
