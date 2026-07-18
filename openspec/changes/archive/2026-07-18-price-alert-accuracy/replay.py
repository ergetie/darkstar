# pyright: basic
"""Replay of Module 3 price floor addon + analyst price alerts against prod data.

Faithful re-implementation of:
- planner/pipeline.py::_fetch_price_floor_inputs_sync (input construction)
- planner/strategy/s_index.py::calculate_price_floor_addon (addon math)
- backend/api/routers/analyst.py::_get_price_advice (Part C: legacy rule re-implementation)

Part D drives the actual `_get_price_advice()` from backend/api/routers/analyst.py
directly (imported, not re-implemented) against a historical simulation of its inputs,
to verify the price-alert-accuracy rewrite's real fire rates.

One simulated planner run per day at 07:00 local (forecasts issue ~03:00-06:00).

Data export (run from the darkstar prod host, see reference_prod_server memory):
    docker exec darkstar python3 -c "
    import sqlite3, csv, sys
    conn = sqlite3.connect('file:/app/data/planner_learning.db?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('SELECT slot_start, export_price_sek_kwh FROM slot_observations WHERE export_price_sek_kwh IS NOT NULL ORDER BY slot_start')
    w = csv.writer(sys.stdout)
    w.writerow(['slot_start', 'export_price_sek_kwh'])
    for row in cur.fetchall():
        w.writerow([row['slot_start'], row['export_price_sek_kwh']])
    " > spot_actuals.csv

    docker exec darkstar python3 -c "
    import sqlite3, csv, sys
    conn = sqlite3.connect('file:/app/data/planner_learning.db?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('SELECT slot_start, issue_timestamp, spot_p50 FROM price_forecasts WHERE spot_p50 IS NOT NULL ORDER BY slot_start')
    w = csv.writer(sys.stdout)
    w.writerow(['slot_start', 'issue_timestamp', 'spot_p50'])
    for row in cur.fetchall():
        w.writerow([row['slot_start'], row['issue_timestamp'], row['spot_p50']])
    " > price_forecasts.csv

Both `slot_start` values come back tz-aware (explicit +01:00/+02:00 offset), not naive
local wall-clock — parse with `datetime.fromisoformat(...).astimezone(TZ)`.
"""

# ruff: noqa: T201 -- this is a console-report analysis script; print is the output mechanism

import csv
import random
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.api.routers.analyst import _get_price_advice  # noqa: E402

TZ = ZoneInfo("Europe/Stockholm")
CAPACITY = 27.0
RISK_FRACTION = {1: 0.15, 2: 0.12, 3: 0.10, 4: 0.05, 5: 0.02}
HALF_LIFE = 2.0
SCRATCH = "/tmp/claude-1000/-home-s-sync-documents-projects-darkstar/46f399e2-7753-44c1-8369-e323f2812670/scratchpad"

# ---------- load actuals ----------
actual_slots = []  # (dt_local, price)
with Path(f"{SCRATCH}/spot_actuals.csv").open() as f:
    for row in csv.DictReader(f):
        try:
            dt = datetime.fromisoformat(row["slot_start"]).astimezone(TZ)
            actual_slots.append((dt, float(row["export_price_sek_kwh"])))
        except (ValueError, TypeError):
            pass
actual_slots.sort()
actual_by_date = defaultdict(list)
for dt, p in actual_slots:
    actual_by_date[dt.date()].append((dt, p))
actual_day_avg = {d: statistics.mean(p for _, p in v) for d, v in actual_by_date.items()}


def actual_overnight_ratio(d):
    """Actual 22:00(d)-06:00(d+1) avg vs actual day(d+1) avg."""
    night = [p for dt, p in actual_by_date.get(d, []) if dt.hour >= 22]
    night += [p for dt, p in actual_by_date.get(d + timedelta(days=1), []) if dt.hour < 6]
    nxt = actual_day_avg.get(d + timedelta(days=1))
    if not night or not nxt or nxt <= 0:
        return None
    return statistics.mean(night) / nxt


def actual_midday_ratio(d):
    """Actual 10:00-16:00(d) avg vs actual full-day(d) avg."""
    midday = [p for dt, p in actual_by_date.get(d, []) if 10 <= dt.hour < 16]
    full = actual_day_avg.get(d)
    if not midday or not full or full <= 0:
        return None
    return statistics.mean(midday) / full


# ---------- load forecasts ----------
# per slot_start: list of (issue_timestamp, spot_p50) — pick latest issue <= run time
fc = defaultdict(list)
with Path(f"{SCRATCH}/price_forecasts.csv").open() as f:
    for row in csv.DictReader(f):
        try:
            slot = datetime.fromisoformat(row["slot_start"]).astimezone(TZ)
            issue = datetime.fromisoformat(row["issue_timestamp"]).astimezone(TZ)
            fc[slot].append((issue, float(row["spot_p50"])))
        except (ValueError, TypeError):
            pass
for v in fc.values():
    v.sort()
fc_slots_sorted = sorted(fc.keys())


def forecast_daily_avgs(run_dt):
    """offset (1..7) -> daily avg of latest-issue spot_p50 as of run_dt; also per-day slot values."""
    today = run_dt.date()
    per_day = defaultdict(list)
    for slot in fc_slots_sorted:
        off = (slot.date() - today).days
        if off < 1 or off > 7:
            continue
        best = None
        for issue, p in fc[slot]:
            if issue <= run_dt:
                best = p
            else:
                break
        if best is not None:
            per_day[off].append(best)
    return {o: statistics.mean(v) for o, v in per_day.items()}, per_day


def trailing_avg(run_dt):
    """14-day trailing avg of actual spot: slot_start >= (today-14d) 00:00, observed before run."""
    start = datetime.combine(run_dt.date() - timedelta(days=14), time.min, TZ)
    vals = [p for dt, p in actual_slots if start <= dt < run_dt]
    days = {dt.date() for dt, p in actual_slots if start <= dt < run_dt}
    if len(days) >= 2 and vals:
        return statistics.mean(vals)
    return None


def addon(daily_avgs, trail, risk, mode="peak"):
    """Faithful calculate_price_floor_addon; mode top2 averages the two highest weighted spreads."""
    if not daily_avgs or trail is None or trail <= 0:
        return None
    spreads = sorted(
        (
            (s - trail) * 0.5 ** ((d - 1) / HALF_LIFE)
            for d, s in daily_avgs.items()
            if d >= 1 and s >= 0
        ),
        reverse=True,
    )
    if not spreads:
        return None
    w = spreads[0] if mode == "peak" or len(spreads) < 2 else (spreads[0] + spreads[1]) / 2
    return CAPACITY * w * RISK_FRACTION[risk]


# ---------- Part A: Apr-Jul replay with real forecasts ----------
fc_dates = sorted({s.date() for s in fc_slots_sorted})
run_days = [d for d in fc_dates if d >= date(2026, 4, 8) and d <= date(2026, 7, 16)]

rows = []
err_by_offset = defaultdict(list)  # offset -> forecast - actual (daily avg)
for d in run_days:
    run_dt = datetime.combine(d, time(7, 0), TZ)
    davgs, _ = forecast_daily_avgs(run_dt)
    trail = trailing_avg(run_dt)
    if not davgs or trail is None:
        continue
    # perfect-foresight daily avgs from actuals
    pf = {
        o: actual_day_avg[d + timedelta(days=o)]
        for o in range(1, 8)
        if d + timedelta(days=o) in actual_day_avg
    }
    for o, v in davgs.items():
        if o in pf:
            err_by_offset[o].append(v - pf[o])
    row = {"date": d, "trail": trail}
    for mode in ("peak", "top2"):
        row[f"fc_{mode}"] = addon(davgs, trail, 3, mode)
        row[f"pf_{mode}"] = addon(pf, trail, 3, mode) if pf else None
    for r in (1, 2, 3, 4, 5):
        row[f"fc_peak_r{r}"] = addon(davgs, trail, r, "peak")
    rows.append(row)

print(f"=== A. Apr-Jul replay ({len(rows)} run days, risk 3 unless noted) ===")
valid = [r for r in rows if r["fc_peak"] is not None and r["pf_peak"] is not None]
for mode in ("peak", "top2"):
    fired = [r for r in valid if r[f"fc_{mode}"] >= 0.5]
    fp = [r for r in fired if r[f"pf_{mode}"] is not None and r[f"pf_{mode}"] < 0.25]
    mae = statistics.mean(abs(r[f"fc_{mode}"] - r[f"pf_{mode}"]) for r in valid)
    print(
        f"{mode:5s}: addon fired (>=0.5kWh) {len(fired)}/{len(valid)} days; "
        f"false-fire (perfect-foresight <0.25) {len(fp)}; MAE vs perfect {mae:.2f} kWh; "
        f"max addon {max(r[f'fc_{mode}'] for r in valid):.2f}"
    )
missed = [r for r in valid if r["fc_peak"] < 0.5 and r["pf_peak"] >= 0.5]
print(f"missed events (perfect>=0.5, forecast<0.5): {len(missed)}")
print("\nRisk-level addon stats (peak mode, kWh):")
for r in (1, 2, 3, 4, 5):
    vals = [x[f"fc_peak_r{r}"] for x in valid]
    pos = [v for v in vals if v >= 0.5]
    print(
        f"  risk {r}: fired {len(pos):3d} days, mean-when-fired {statistics.mean(pos) if pos else 0:.2f}, "
        f"max {max(vals):.2f}, as %cap max {max(vals) / CAPACITY * 100:.1f}%"
    )

print("\nForecast daily-avg error by offset (SEK/kWh):")
for o in sorted(err_by_offset):
    e = err_by_offset[o]
    print(
        f"  D+{o}: bias {statistics.mean(e):+.3f}, MAE {statistics.mean(map(abs, e)):.3f}, n={len(e)}"
    )

# top-5 biggest addon days risk3 peak
print("\nTop-5 addon days (risk 3, peak): date fc pf trail")
for r in sorted(valid, key=lambda x: -x["fc_peak"])[:5]:
    print(f"  {r['date']} fc={r['fc_peak']:.2f} pf={r['pf_peak']:.2f} trail={r['trail']:.2f}")

# ---------- Part B: winter simulation (perfect foresight + degraded) ----------
winter_days = [d for d in sorted(actual_day_avg) if date(2025, 11, 18) <= d <= date(2026, 3, 31)]
mae_by_offset = {o: statistics.mean(map(abs, e)) for o, e in err_by_offset.items()}
bias_by_offset = {o: statistics.mean(e) for o, e in err_by_offset.items()}
rng = random.Random(42)

print(f"\n=== B. Winter Nov18-Mar31 simulation ({len(winter_days)} days) ===")
wrows = []
for d in winter_days:
    run_dt = datetime.combine(d, time(7, 0), TZ)
    trail = trailing_avg(run_dt)
    pf = {
        o: actual_day_avg[d + timedelta(days=o)]
        for o in range(1, 8)
        if d + timedelta(days=o) in actual_day_avg
    }
    if trail is None or not pf:
        continue
    wrows.append(
        {
            "date": d,
            "trail": trail,
            "pf": pf,
            **{f"r{r}": addon(pf, trail, r, "peak") for r in (1, 2, 3, 4, 5)},
            "top2_r3": addon(pf, trail, 3, "top2"),
        }
    )
print("Perfect-foresight addon per risk level (kWh):")
for r in (1, 2, 3, 4, 5):
    vals = [w[f"r{r}"] for w in wrows if w[f"r{r}"] is not None]
    pos = [v for v in vals if v >= 0.5]
    capped = [v for v in vals if v > 0.8 * CAPACITY]
    print(
        f"  risk {r}: fired {len(pos):3d}/{len(vals)} days, mean-when-fired {statistics.mean(pos) if pos else 0:.2f}, "
        f"p95 {sorted(vals)[int(len(vals) * 0.95)]:.2f}, max {max(vals):.2f} ({max(vals) / CAPACITY * 100:.0f}% cap)"
    )
print("\nTop-5 winter spike days (risk 3 peak, perfect foresight):")
for w in sorted(wrows, key=lambda x: -(x["r3"] or 0))[:5]:
    print(
        f"  {w['date']} addon r1={w['r1']:.1f} r3={w['r3']:.1f} r5={w['r5']:.1f} top2r3={w['top2_r3']:.1f} trail={w['trail']:.2f}"
    )

# degraded: 200 Monte Carlo reps adding offset-dependent noise (bias + N(0, MAE*1.2533) ~ matching MAE)
print("\nDegraded-forecast winter (200 reps, offset-scaled noise), risk 3 peak:")
fire_rates, maes = [], []
for _ in range(200):
    fired = tp = fp = miss = 0
    errs = []
    for w in wrows:
        noisy = {
            o: max(
                0.0,
                v + bias_by_offset.get(o, 0) + rng.gauss(0, mae_by_offset.get(o, 0.15) * 1.2533),
            )
            for o, v in w["pf"].items()
        }
        a = addon(noisy, w["trail"], 3, "peak")
        if a is None or w["r3"] is None:
            continue
        errs.append(abs(a - w["r3"]))
        if a >= 0.5:
            fired += 1
            tp += 1 if w["r3"] >= 0.25 else 0
            fp += 1 if w["r3"] < 0.25 else 0
        elif w["r3"] >= 0.5:
            miss += 1
    fire_rates.append((fired, fp, miss))
    maes.append(statistics.mean(errs))
mf = statistics.mean(f for f, _, _ in fire_rates)
mfp = statistics.mean(fp for _, fp, _ in fire_rates)
mm = statistics.mean(m for _, _, m in fire_rates)
print(
    f"  fired {mf:.0f} days avg (perfect: {sum(1 for w in wrows if (w['r3'] or 0) >= 0.5)}), "
    f"false-fires {mfp:.1f}, missed {mm:.1f}, addon MAE {statistics.mean(maes):.2f} kWh"
)

# ---------- Part C: alert rules replay ----------
print(f"\n=== C. Analyst price alerts replay (Apr-Jul, {len(run_days)} days) ===")
r1 = r2 = r3 = 0
r1_correct = r3_correct = 0
r1_checked = r3_checked = 0
for d in run_days:
    run_dt = datetime.combine(d, time(7, 0), TZ)
    davgs, per_day = forecast_daily_avgs(run_dt)
    if 1 not in davgs:
        continue
    today_avg = davgs[1]  # code bug: D+1 used as 'today'
    # Rule 1
    drops = [
        (o, (today_avg - v) / today_avg * 100)
        for o, v in davgs.items()
        if v > 0 and v < today_avg * 0.70
    ]
    if drops and max(dr for _, dr in drops) >= 30:
        r1 += 1
        o = max(drops, key=lambda x: x[1])[0]
        ad, ref = (
            actual_day_avg.get(d + timedelta(days=o)),
            actual_day_avg.get(d + timedelta(days=1)),
        )
        if ad and ref:
            r1_checked += 1
            r1_correct += 1 if ad < ref * 0.80 else 0  # generous: actually >=20% cheaper
    # Rule 2 (dead: compares D+1 against itself)
    d123 = [davgs.get(o) for o in (1, 2, 3)]
    if all(v is not None and v > today_avg for v in d123):
        r2 += 1
    # Rule 3
    minp = min(per_day[1]) if per_day.get(1) else 0
    if minp > 0 and davgs[1] > 0 and minp < davgs[1] * 0.75:
        r3 += 1
        ratio = actual_overnight_ratio(d)
        if ratio is not None:
            r3_checked += 1
            r3_correct += 1 if ratio < 0.85 else 0
print(
    f"Rule 1 (cheapest day ahead): fired {r1} days; correct (actual >=20% cheaper) {r1_correct}/{r1_checked}"
)
print(f"Rule 2 (prices rising): fired {r2} days  <- structurally dead (today proxy = D+1)")
print(
    f"Rule 3 (cheap overnight): fired {r3} days; correct (actual night <85% of day) {r3_correct}/{r3_checked}"
)


# ---------- Part D: new-rule replay, driving the real _get_price_advice() ----------
def forecast_window_avg(run_dt, start, end):
    """Latest-issue-as-of-run_dt p50 average over forecast slots in [start, end)."""
    vals = []
    for slot in fc_slots_sorted:
        if not (start <= slot < end):
            continue
        best = None
        for issue, p in fc[slot]:
            if issue <= run_dt:
                best = p
            else:
                break
        if best is not None:
            vals.append(best)
    return statistics.mean(vals) if vals else None


print(f"\n=== D. New-rule replay via real _get_price_advice() (Apr-Jul, {len(run_days)} days) ===")
nr1 = nr2 = nr_overnight = nr_midday = 0
nr1_correct = nr_overnight_correct = nr_midday_correct = 0
nr1_checked = nr_overnight_checked = nr_midday_checked = 0
skipped_no_today = 0
for d in run_days:
    run_dt = datetime.combine(d, time(7, 0), TZ)
    davgs, _ = forecast_daily_avgs(run_dt)
    if not davgs:
        continue

    today_avg_real = actual_day_avg.get(d)  # real today reference, not the D+1 proxy
    if today_avg_real is None or today_avg_real <= 0:
        skipped_no_today += 1
        continue

    daily_outlook = [
        {"day_label": (d + timedelta(days=o)).strftime("%a"), "days_ahead": o, "avg_spot_p50": v}
        for o, v in sorted(davgs.items())
    ]

    tomorrow = d + timedelta(days=1)
    overnight_start = datetime.combine(d, time(22, 0), TZ)
    overnight_end = datetime.combine(tomorrow, time(6, 0), TZ)
    midday_start = datetime.combine(tomorrow, time(10, 0), TZ)
    midday_end = datetime.combine(tomorrow, time(16, 0), TZ)

    overnight_avg = forecast_window_avg(run_dt, overnight_start, overnight_end)
    midday_avg = forecast_window_avg(run_dt, midday_start, midday_end)

    advice = _get_price_advice(daily_outlook, today_avg_real, overnight_avg, midday_avg)
    messages = [a["message"].lower() for a in advice]

    if any("drop" in m for m in messages):
        nr1 += 1
        cheapest = max(davgs.items(), key=lambda kv: (today_avg_real - kv[1]) / today_avg_real)
        o = cheapest[0]
        ad, ref = (
            actual_day_avg.get(d + timedelta(days=o)),
            actual_day_avg.get(d + timedelta(days=1)),
        )
        if ad and ref:
            nr1_checked += 1
            nr1_correct += 1 if ad < ref * 0.80 else 0
    if any("rising" in m for m in messages):
        nr2 += 1
    if any("tonight" in m for m in messages):
        nr_overnight += 1
        ratio = actual_overnight_ratio(d)
        if ratio is not None:
            nr_overnight_checked += 1
            nr_overnight_correct += 1 if ratio < 0.85 else 0
    if any("midday" in m for m in messages):
        nr_midday += 1
        ratio = actual_midday_ratio(tomorrow)
        if ratio is not None:
            nr_midday_checked += 1
            nr_midday_correct += 1 if ratio < 0.85 else 0

print(
    f"Rule 1 (cheapest day ahead): fired {nr1} days; correct (actual >=20% cheaper) {nr1_correct}/{nr1_checked}"
)
print(
    f"Rule 2 (prices rising): fired {nr2} days  <- now able to fire against the real today average"
)
print(
    f"Rule 3 overnight: fired {nr_overnight} days; correct (actual night <85% of day) {nr_overnight_correct}/{nr_overnight_checked}"
)
print(
    f"Rule 3 solar-midday: fired {nr_midday} days; correct (actual midday <85% of day) {nr_midday_correct}/{nr_midday_checked}"
)
print(f"(days skipped for missing today-actual reference: {skipped_no_today})")
