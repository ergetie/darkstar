#!/usr/bin/env python
"""
Diagnostic: compare the two PV *physics* paths, NO ML involved.

  Path A  (Aurora baseline) : open-meteo GHI (shortwave_radiation)
                              -> Darkstar's OWN tilt transposition + efficiency
                              [ml.weather.calculate_physics_pv]
  Path B  (open-meteo lib)  : open-meteo global_tilted_irradiance (GTI)
                              -> library PV model (temp derate + AC clip)
                              [open_meteo_solar_forecast.OpenMeteoSolarForecast]

Both read the SAME solar_arrays + location from config.yaml. We compare daily
kWh totals and the A/B ratio. If Path A ≈ Path B for a config, the transposition
is fine for that geometry; a large ratio points at the GHI->tilt step.

READ-ONLY: no DB writes, no config writes, no app state touched. Throwaway tool.

Usage:
    uv run python scripts/compare_pv_paths.py [path/to/config.yaml]
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import pytz
import yaml

from ml.weather import calculate_physics_pv, get_weather_series


def load_cfg(path: str) -> dict:
    with Path(path).open() as f:
        return yaml.safe_load(f)


def get_arrays_and_location(cfg: dict):
    system = cfg.get("system", {}) or {}
    arrays = system.get("solar_arrays") or cfg.get("solar_arrays") or []
    loc = system.get("location", {}) or {}
    lat = float(loc.get("latitude", 59.3))
    lon = float(loc.get("longitude", 18.1))
    # normalize to the dict shape calculate_physics_pv expects (HA azimuth convention)
    norm = [
        {
            "name": a.get("name", f"Array {i}"),
            "kwp": float(a.get("kwp", 0.0) or 0.0),
            "tilt": float(a.get("tilt", 30.0) or 30.0),
            "azimuth": float(a.get("azimuth", 180.0) or 180.0),  # HA: 0=N,180=S
        }
        for i, a in enumerate(arrays)
        if float(a.get("kwp", 0.0) or 0.0) > 0.0
    ]
    return norm, lat, lon


def path_a_daily(cfg: dict, arrays: list, lat: float, lon: float, days: int) -> dict:
    """Darkstar GHI -> own POA transposition. Hourly radiation, slot_hours=1.0."""
    tz = pytz.timezone(cfg.get("timezone", "Europe/Stockholm"))
    start = datetime.now(tz)
    end = start + timedelta(days=days)
    daily: dict[str, float] = defaultdict(float)

    wdf = None
    for attempt in range(4):
        wdf = get_weather_series(start, end, config=cfg, forecast_days=days + 1)
        if not wdf.empty:
            break
        if attempt < 3:
            print(f"  … Path A: open-meteo gave no data (likely 502), retrying ({attempt + 1}/3)…")
            time.sleep(3 * (attempt + 1))
    if wdf is None or wdf.empty:
        print(
            "  ! Path A: open-meteo unreachable after retries (their server, not the script). Try again later."
        )
        return daily
    for ts, row in wdf.iterrows():
        rad = row.get("shortwave_radiation_w_m2")
        if rad is None:
            continue
        kwh, _ = calculate_physics_pv(
            radiation_w_m2=float(rad),
            solar_arrays=arrays,
            slot_start=ts.to_pydatetime(),
            latitude=lat,
            longitude=lon,
            slot_hours=1.0,  # hourly radiation, hourly energy
        )
        if kwh:
            day = ts.astimezone(tz).date().isoformat()
            daily[day] += kwh
    return daily


async def path_b_daily(arrays: list, lat: float, lon: float, days: int) -> dict:
    """open-meteo library: GTI -> library PV model."""
    from open_meteo_solar_forecast import OpenMeteoSolarForecast

    n = len(arrays)
    # library/open-meteo azimuth convention: 0=S, -90=E, 90=W  (convert from HA)
    azis = [(a["azimuth"] % 360) - 180 for a in arrays]
    tilts = [a["tilt"] for a in arrays]
    kwps = [a["kwp"] for a in arrays]
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            async with OpenMeteoSolarForecast(
                latitude=[lat] * n,
                longitude=[lon] * n,
                declination=tilts,
                azimuth=azis,
                dc_kwp=kwps,
                forecast_days=days + 1,
                past_days=0,
            ) as f:
                est = await f.estimate()
            # est.wh_days: dict[date] -> Wh
            return {d.isoformat(): wh / 1000.0 for d, wh in est.wh_days.items()}
        except Exception as e:  # open-meteo 502s are common; retry
            last_err = e
            if attempt < 3:
                print(f"  … Path B: open-meteo error (likely 502), retrying ({attempt + 1}/3)…")
                await asyncio.sleep(3 * (attempt + 1))
    print(
        f"  ! Path B: open-meteo unreachable after retries (their server, not the script): {last_err}"
    )
    return {}


def main() -> None:
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    days = 3
    cfg = load_cfg(cfg_path)
    arrays, lat, lon = get_arrays_and_location(cfg)

    print(f"\nConfig: {cfg_path}")
    print(f"Location: {lat:.4f}, {lon:.4f}")
    print("Arrays:")
    for a in arrays:
        print(f"  - {a['name']}: {a['kwp']} kWp, tilt {a['tilt']}°, azimuth {a['azimuth']}° (HA)")
    if not arrays:
        print("  ! No valid solar arrays found in config.")
        return

    print("\nFetching both paths (live open-meteo)...")
    a_daily = path_a_daily(cfg, arrays, lat, lon, days)
    b_daily = asyncio.run(path_b_daily(arrays, lat, lon, days))

    if not a_daily or not b_daily:
        print(
            "\nOne or both paths returned nothing (see messages above). "
            "If it was a 502, open-meteo is flaky right now — just rerun in a bit.\n"
        )
        return

    all_days = sorted(set(a_daily) | set(b_daily))
    print(f"\n{'Date':<12}{'A: own (kWh)':>15}{'B: open-meteo':>16}{'ratio A/B':>12}")
    print("-" * 55)
    for d in all_days:
        a = a_daily.get(d, 0.0)
        b = b_daily.get(d, 0.0)
        ratio = f"{a / b:.2f}x" if b > 0.01 else "n/a"
        print(f"{d:<12}{a:>15.2f}{b:>16.2f}{ratio:>12}")
    print("-" * 55)
    print("Path A = Darkstar's own GHI->tilt transposition (the 'Aurora' baseline, no ML)")
    print("Path B = open-meteo's global_tilted_irradiance PV model (the library)")
    print("A close A/B ratio => transposition is fine for this geometry.\n")


if __name__ == "__main__":
    main()
