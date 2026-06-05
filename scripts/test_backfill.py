#!/usr/bin/env python
"""
Diagnostic: how feasible is an N-day open-meteo backfill?

For each requested day-count it measures:
  - how long the open-meteo fetch takes (all arrays, via past_days, one call/array)
  - how many 15-min slots / days come back
  - how many of those days you actually have production data for (the auto-shrink cap)
  - the effective backfill = min(api days, your actual-production days)

READ-ONLY: one historical fetch per N + a read-only query of slot_observations.
No DB writes, no config writes. Throwaway tool.

Usage:
    PYTHONPATH=. uv run python scripts/test_backfill.py [10 30 90] [path/to/config.yaml]
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
import time
from pathlib import Path

import yaml

PAST_DAYS_MAX = 92  # open-meteo forecast API limit for the cheap one-call method


def load_cfg(path: str) -> dict:
    with Path(path).open() as f:
        return yaml.safe_load(f)


def get_arrays_and_location(cfg: dict):
    system = cfg.get("system", {}) or {}
    arrays = system.get("solar_arrays") or cfg.get("solar_arrays") or []
    loc = system.get("location", {}) or {}
    lat = float(loc.get("latitude", 59.3))
    lon = float(loc.get("longitude", 18.1))
    norm = [
        {
            "kwp": float(a.get("kwp", 0.0) or 0.0),
            "tilt": float(a.get("tilt", 30.0) or 30.0),
            "azimuth": float(a.get("azimuth", 180.0) or 180.0),
        }
        for a in arrays
        if float(a.get("kwp", 0.0) or 0.0) > 0.0
    ]
    return norm, lat, lon


def db_path() -> Path:
    return Path("data/planner_learning.db").resolve()


def actual_production_coverage() -> tuple[int, str | None, str | None, set[str]]:
    """Return (distinct_days_with_pv, min_date, max_date, set_of_day_strings)."""
    p = db_path()
    if not p.exists():
        print(f"  ! DB not found at {p}")
        return 0, None, None, set()
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT DISTINCT substr(slot_start,1,10) AS d "
            "FROM slot_observations WHERE pv_kwh IS NOT NULL AND pv_kwh > 0.0 "
            "ORDER BY d"
        ).fetchall()
    except sqlite3.Error as e:
        print(f"  ! Could not read slot_observations: {e}")
        return 0, None, None, set()
    finally:
        con.close()
    days = {r[0] for r in rows if r[0]}
    if not days:
        return 0, None, None, set()
    return len(days), min(days), max(days), days


async def fetch_n_days(arrays: list, lat: float, lon: float, n: int):
    """Fetch n past days of open-meteo solar forecast for all arrays; time it."""
    from open_meteo_solar_forecast import OpenMeteoSolarForecast

    k = len(arrays)
    azis = [(a["azimuth"] % 360) - 180 for a in arrays]
    tilts = [a["tilt"] for a in arrays]
    kwps = [a["kwp"] for a in arrays]
    t0 = time.perf_counter()
    async with OpenMeteoSolarForecast(
        latitude=[lat] * k,
        longitude=[lon] * k,
        declination=tilts,
        azimuth=azis,
        dc_kwp=kwps,
        forecast_days=0,
        past_days=n,
    ) as f:
        est = await f.estimate()
    elapsed = time.perf_counter() - t0
    slots = len(est.watts)
    api_days = {d.isoformat() for d in est.wh_days}
    return elapsed, slots, api_days


def main() -> None:
    args = list(sys.argv[1:])
    ns = [int(a) for a in args if a.isdigit()] or [10, 30, 90]
    cfg_path = next((a for a in args if not a.isdigit()), "config.yaml")

    cfg = load_cfg(cfg_path)
    arrays, lat, lon = get_arrays_and_location(cfg)
    print(f"\nConfig: {cfg_path}  ({len(arrays)} array(s), {lat:.3f},{lon:.3f})")

    n_days, dmin, dmax, actual_days = actual_production_coverage()
    print(f"Your production history: {n_days} days with PV data ({dmin or '?'} … {dmax or '?'})\n")

    print(
        f"{'N req':>6}{'api days':>10}{'api slots':>11}{'fetch s':>9}"
        f"{'actuals in window':>20}{'effective':>11}"
    )
    print("-" * 67)
    for n in ns:
        req = min(n, PAST_DAYS_MAX)
        note = "" if n <= PAST_DAYS_MAX else f"  (capped at {PAST_DAYS_MAX})"
        try:
            elapsed, slots, api_days = asyncio.run(fetch_n_days(arrays, lat, lon, req))
        except Exception as e:
            print(f"{n:>6}  fetch failed: {e}")
            continue
        # how many of the api days do we actually have production for?
        overlap = len(api_days & actual_days) if actual_days else 0
        effective = min(len(api_days), overlap) if actual_days else 0
        print(
            f"{n:>6}{len(api_days):>10}{slots:>11}{elapsed:>9.2f}{overlap:>20}{effective:>11}{note}"
        )
    print("-" * 67)
    print("effective = days where BOTH open-meteo history AND your production exist")
    print("(this is what the backfill would actually train on — it auto-shrinks)\n")


if __name__ == "__main__":
    main()
