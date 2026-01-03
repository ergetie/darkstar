#!/usr/bin/env python3
import asyncio
import sys

import httpx

OLD_ROUTES = [
    ("GET", "/api/themes"),
    ("POST", "/api/theme"),
    ("GET", "/api/forecast/eval"),
    ("GET", "/api/forecast/day"),
    ("GET", "/api/forecast/horizon"),
    ("POST", "/api/forecast/run_eval"),
    ("POST", "/api/forecast/run_forward"),
    ("GET", "/api/schedule"),
    ("GET", "/api/schedule/today_with_history"),
    ("POST", "/api/schedule/save"),
    ("GET", "/api/health"),
    ("GET", "/api/status"),
    ("GET", "/api/version"),
    ("GET", "/api/scheduler/status"),
    ("GET", "/api/ha-socket"),
    ("GET", "/api/config"),
    ("POST", "/api/config/save"),
    ("POST", "/api/config/reset"),
    ("GET", "/api/initial_state"),
    ("GET", "/api/energy/today"),
    ("GET", "/api/energy/range"),
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
    ("GET", "/api/water/boost"),
    ("POST", "/api/water/boost"),
    ("DELETE", "/api/water/boost"),
    ("GET", "/api/db/current_schedule"),
    ("POST", "/api/db/push_current"),
    ("POST", "/api/ha/test"),
    ("GET", "/api/ha/entities"),
    ("GET", "/api/ha/services"),
    ("GET", "/api/ha/entity/sensor.test"),
    ("GET", "/api/ha/average"),
    ("GET", "/api/ha/water_today"),
    ("GET", "/api/learning/status"),
    ("GET", "/api/learning/history"),
    ("POST", "/api/learning/run"),
    ("GET", "/api/learning/loops"),
    ("GET", "/api/learning/daily_metrics"),
    ("GET", "/api/learning/changes"),
    ("POST", "/api/learning/record_observation"),
    ("GET", "/api/analyst/advice"),
    ("GET", "/api/analyst/run"),
    ("GET", "/api/debug"),
    ("GET", "/api/debug/logs"),
    ("GET", "/api/history/soc"),
    ("GET", "/api/performance/data"),
    ("GET", "/api/performance/metrics"),
    ("POST", "/api/run_planner"),
    ("POST", "/api/simulate"),
    ("GET", "/api/aurora/dashboard"),
    ("POST", "/api/aurora/briefing"),
    ("POST", "/api/aurora/config/toggle_reflex"),
]

BASE_URL = "http://localhost:5000"

async def check_route(client, method, path, semaphore):
    async with semaphore:
        url = f"{BASE_URL}{path}"
        try:
            if method == "GET":
                resp = await client.get(url, timeout=10.0)
            elif method == "POST":
                resp = await client.post(url, json={}, timeout=10.0)
            elif method == "PUT":
                resp = await client.put(url, json={}, timeout=10.0)
            elif method == "DELETE":
                resp = await client.delete(url, timeout=10.0)
            else:
                return method, path, -1, f"Unknown method: {method}"
            return method, path, resp.status_code, ""
        except Exception as e:
            return method, path, -1, str(e)

async def main():
    semaphore = asyncio.Semaphore(3) # Very conservative
    async with httpx.AsyncClient() as client:
        tasks = [check_route(client, m, p, semaphore) for m, p in OLD_ROUTES]
        results = await asyncio.gather(*tasks)

    ok = []
    failed = []
    for m, p, s, e in results:
        if s == 200:
            ok.append((m, p))
        else:
            failed.append((m, p, s, e))

    print(f"Results: {len(ok)} OK, {len(failed)} FAILED")
    for m, p, s, e in failed:
        print(f"  {m:6} {p} -> {s} ({e})")

    if not failed:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
