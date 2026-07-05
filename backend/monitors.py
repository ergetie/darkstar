"""Runtime invariant monitors (stabilization-review-2, spec: runtime-invariant-monitors).

Read-only observers: every evaluation opens the learning DB with a
``mode=ro`` SQLite URI, issues SELECTs only, and never touches Home Assistant.
A defect in this module must never degrade the planner/executor/recorder loops
(design D4): every evaluator is individually fenced, an evaluator crash yields
a ``skipped`` result and marks the monitor unhealthy, and the scheduling loop
swallows all exceptions.

Thresholds (task 7.1) are constants derived from the 8-month production
evidence phase (openspec/changes/stabilization-review-2/findings.md):

- SLOT_GAP_GRACE_MINUTES / slot continuity: production showed 0 gaps in the 7
  months since 2025-12-04 (#10.1), so ANY missing 15-min slot in the trailing
  24 h is a violation. The most recent 45 min are grace: the recorder writes
  slot T at T+15 min, plus scheduling jitter.
- ENERGY_RESIDUAL_KWH = 2.0 and ENERGY_VIOLATION_COUNT = 3: the healthy
  residual distribution is median +0.001, p5/p95 -0.47/+0.26, p99.9 ≈ 1.5 kWh
  (#10.2); isolated 1-2 kWh sensor-timing skews occur ~1/day. Three slots
  beyond 2.0 kWh inside 24 h matches the January import-outage signature (#8)
  while staying silent on normal skew.
- SOC_MARGIN_PERCENT = 5: SoC is a BMS-reported percentage; the planning floor
  (battery.min_soc_percent) is a soft target the BMS may legitimately
  undershoot slightly during load spikes. 5 % under floor / over 100 is beyond
  anything seen in 8 months of history (#10.3).
- PLAN_AGE_MAX_HOURS = 3: the planner runs hourly and slot_plans.created_at
  refreshes on every successful run (store.py upsert). 3 h tolerates a restart
  plus one missed run; the only historical breach was the 31 h DST outage (#6)
  this invariant exists to catch.
- COMMAND_SUCCESS_MIN = 0.99 over trailing 24 h: monthly success has been
  ≥ 99.7 % since 2026-03 (#4); 1 % headroom absorbs a normal HA restart
  (~1-2 failed ticks) without alerting, while the Jan/Feb-style episodes
  (2.5-3.7 % daily failure) trip it within hours.
- PV_FORECAST_CEILING_KWH = 7.11 * 0.25: physical array limit per 15-min slot
  (7.11 kWp); best slot ever observed is 1.43 kWh (#13.4). Any stored future
  forecast above the ceiling is a regression of the 2026-06-17 fix.
- DATA_QUALITY_MAX_BAD_FRACTION = 0.05 over trailing 24 h: computed directly
  from slot_observations because data_quality_daily is dead (#9). A recorded
  slot is "bad" when its SoC or import price is missing; NULL-price rows
  should not exist at all in steady state (#2 pre-seeding), so 5 % (≈ 5 slots)
  is generous.
"""

import asyncio
import contextlib
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytz
import yaml

logger = logging.getLogger("darkstar.monitors")

# --- thresholds (see module docstring for derivations) -----------------------
SLOT_GAP_GRACE_MINUTES = 45
ENERGY_RESIDUAL_KWH = 2.0
ENERGY_VIOLATION_COUNT = 3
SOC_MARGIN_PERCENT = 5.0
PLAN_AGE_MAX_HOURS = 3.0
COMMAND_SUCCESS_MIN = 0.99
PV_FORECAST_CEILING_KWH = 7.11 * 0.25
DATA_QUALITY_MAX_BAD_FRACTION = 0.05

DEFAULT_INTERVAL_MINUTES = 15  # at most once per recorder cycle (spec)

INVARIANT_NAMES = [
    "slot_continuity",
    "energy_balance",
    "soc_bounds",
    "plan_freshness",
    "command_success",
    "forecast_sanity",
    "data_quality",
]


@dataclass
class InvariantResult:
    name: str
    status: str  # "pass" | "violation" | "skipped"
    detail: str
    evaluated_at: str = ""

    def __post_init__(self) -> None:
        if not self.evaluated_at:
            self.evaluated_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "evaluated_at": self.evaluated_at,
        }


@dataclass
class ViolationEpisode:
    """Tracks an active violation for alert dedup (one alert per episode)."""

    invariant: str
    first_detected_at: str
    detail: str


@dataclass
class MonitorState:
    running: bool = False
    healthy: bool = True
    last_cycle_at: str | None = None
    last_error: str | None = None
    results: dict[str, InvariantResult] = field(default_factory=dict[str, InvariantResult])
    episodes: dict[str, ViolationEpisode] = field(default_factory=dict[str, ViolationEpisode])


class InvariantMonitors:
    """Evaluates the invariant catalog against the learning DB, read-only."""

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.state = MonitorState()
        self._task: asyncio.Task[None] | None = None
        self._config: dict[str, Any] = {}

    # -- config / db access ---------------------------------------------------

    def _load_config(self) -> dict[str, Any]:
        try:
            with Path(self.config_path).open(encoding="utf-8") as f:
                loaded: Any = yaml.safe_load(f)
                self._config = loaded if isinstance(loaded, dict) else {}
        except Exception as e:
            logger.warning("monitors: could not load config: %s", e)
            self._config = {}
        return self._config

    def _db_path(self) -> str:
        env = os.environ.get("DB_PATH")
        if env:
            return env
        learning: dict[str, Any] = self._config.get("learning", {}) or {}
        return str(learning.get("sqlite_path", "data/planner_learning.db"))

    def _connect_ro(self) -> sqlite3.Connection:
        path = self._db_path()
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)

    def _tz(self) -> Any:
        return pytz.timezone(str(self._config.get("timezone", "Europe/Stockholm")))

    # -- individual evaluators (each runs inside the fenced executor) ---------

    def _eval_slot_continuity(self, con: sqlite3.Connection, now: datetime) -> InvariantResult:
        grace = now - timedelta(minutes=SLOT_GAP_GRACE_MINUTES)
        start = now - timedelta(hours=24)
        rows = con.execute(
            "SELECT slot_start FROM slot_observations "
            "WHERE soc_end_percent IS NOT NULL AND slot_start >= ? AND slot_start < ? "
            "ORDER BY slot_start",
            (start.isoformat(), grace.isoformat()),
        ).fetchall()
        if len(rows) < 2:
            return InvariantResult(
                "slot_continuity", "skipped", f"only {len(rows)} recorded slots in window"
            )
        missing: list[str] = []
        prev = datetime.fromisoformat(rows[0][0])
        for (s,) in rows[1:]:
            cur = datetime.fromisoformat(s)
            gap = (cur - prev).total_seconds()
            if gap != 900:
                missing.append(f"{prev.isoformat()} -> {cur.isoformat()} ({gap / 60:.0f} min)")
            prev = cur
        if missing:
            return InvariantResult(
                "slot_continuity", "violation", f"{len(missing)} gap(s): " + "; ".join(missing[:5])
            )
        return InvariantResult("slot_continuity", "pass", f"{len(rows)} contiguous slots")

    def _eval_energy_balance(self, con: sqlite3.Connection, now: datetime) -> InvariantResult:
        start = now - timedelta(hours=24)
        rows = con.execute(
            "SELECT slot_start, COALESCE(pv_kwh,0)+COALESCE(import_kwh,0)+COALESCE(batt_discharge_kwh,0)"
            " - COALESCE(load_kwh,0)-COALESCE(water_kwh,0)-COALESCE(ev_charging_kwh,0)"
            " - COALESCE(export_kwh,0)-COALESCE(batt_charge_kwh,0) AS residual "
            "FROM slot_observations "
            "WHERE soc_end_percent IS NOT NULL AND slot_start >= ?",
            (start.isoformat(),),
        ).fetchall()
        if not rows:
            return InvariantResult("energy_balance", "skipped", "no recorded slots in window")
        offenders = [(s, r) for s, r in rows if abs(r) > ENERGY_RESIDUAL_KWH]
        if len(offenders) >= ENERGY_VIOLATION_COUNT:
            worst = sorted(offenders, key=lambda x: -abs(x[1]))[:3]
            detail = ", ".join(f"{s}: {r:+.2f} kWh" for s, r in worst)
            return InvariantResult(
                "energy_balance",
                "violation",
                f"{len(offenders)} slots with |residual| > {ENERGY_RESIDUAL_KWH} kWh: {detail}",
            )
        return InvariantResult(
            "energy_balance", "pass", f"{len(rows)} slots, {len(offenders)} above threshold"
        )

    def _eval_soc_bounds(self, con: sqlite3.Connection, now: datetime) -> InvariantResult:
        battery: dict[str, Any] = self._config.get("battery", {}) or {}
        floor = float(battery.get("min_soc_percent", 10.0)) - SOC_MARGIN_PERCENT
        ceiling = 100.0 + 0.001  # SoC is a percentage; >100 means a broken sensor
        start = now - timedelta(hours=24)
        row = con.execute(
            "SELECT MIN(soc_end_percent), MAX(soc_end_percent), COUNT(*) FROM slot_observations "
            "WHERE soc_end_percent IS NOT NULL AND slot_start >= ?",
            (start.isoformat(),),
        ).fetchone()
        lo, hi, n = row
        if not n:
            return InvariantResult("soc_bounds", "skipped", "no recorded slots in window")
        if lo < floor or hi > ceiling:
            return InvariantResult(
                "soc_bounds",
                "violation",
                f"SoC range [{lo:.1f}, {hi:.1f}] outside [{floor:.1f}, 100]",
            )
        return InvariantResult(
            "soc_bounds", "pass", f"SoC range [{lo:.1f}, {hi:.1f}] over {n} slots"
        )

    def _eval_plan_freshness(self, con: sqlite3.Connection, now: datetime) -> InvariantResult:
        # slot_plans.created_at is naive UTC (findings.md #20c)
        row = con.execute("SELECT MAX(created_at) FROM slot_plans").fetchone()
        if not row or not row[0]:
            return InvariantResult("plan_freshness", "skipped", "no plans stored")
        last_write = datetime.fromisoformat(row[0]).replace(tzinfo=UTC)
        age_h = (datetime.now(UTC) - last_write).total_seconds() / 3600.0
        if age_h > PLAN_AGE_MAX_HOURS:
            return InvariantResult(
                "plan_freshness",
                "violation",
                f"last successful plan write {age_h:.1f} h ago (max {PLAN_AGE_MAX_HOURS} h)",
            )
        return InvariantResult("plan_freshness", "pass", f"last plan write {age_h:.1f} h ago")

    def _eval_command_success(self, con: sqlite3.Connection, now: datetime) -> InvariantResult:
        start = now - timedelta(hours=24)
        row = con.execute(
            "SELECT COUNT(*), SUM(success = 1) FROM execution_log WHERE executed_at >= ?",
            (start.isoformat(),),
        ).fetchone()
        total, ok = row[0], row[1] or 0
        if not total:
            return InvariantResult("command_success", "skipped", "no ticks in window")
        rate = ok / total
        if rate < COMMAND_SUCCESS_MIN:
            return InvariantResult(
                "command_success",
                "violation",
                f"tick success {rate:.2%} over 24 h ({total - ok}/{total} failed)",
            )
        return InvariantResult(
            "command_success", "pass", f"tick success {rate:.2%} ({total} ticks)"
        )

    def _eval_forecast_sanity(self, con: sqlite3.Connection, now: datetime) -> InvariantResult:
        row = con.execute(
            "SELECT MAX(pv_forecast_kwh), COUNT(*) FROM slot_forecasts WHERE slot_start >= ?",
            (now.isoformat(),),
        ).fetchone()
        max_pv, n = row
        if not n:
            return InvariantResult("forecast_sanity", "skipped", "no future forecasts stored")
        if max_pv is not None and max_pv > PV_FORECAST_CEILING_KWH:
            return InvariantResult(
                "forecast_sanity",
                "violation",
                f"future PV forecast {max_pv:.3f} kWh/slot exceeds physical ceiling "
                f"{PV_FORECAST_CEILING_KWH:.3f}",
            )
        return InvariantResult(
            "forecast_sanity", "pass", f"max future PV forecast {max_pv or 0:.3f} kWh/slot"
        )

    def _eval_data_quality(self, con: sqlite3.Connection, now: datetime) -> InvariantResult:
        # data_quality_daily is dead (findings.md #9) — compute live instead.
        grace = now - timedelta(minutes=SLOT_GAP_GRACE_MINUTES)
        start = now - timedelta(hours=24)
        row = con.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN soc_end_percent IS NULL OR import_price_sek_kwh IS NULL THEN 1 ELSE 0 END) "
            "FROM slot_observations WHERE slot_start >= ? AND slot_start < ?",
            (start.isoformat(), grace.isoformat()),
        ).fetchone()
        total, bad = row[0], row[1] or 0
        if not total:
            return InvariantResult("data_quality", "skipped", "no slots in window")
        frac = bad / total
        if frac > DATA_QUALITY_MAX_BAD_FRACTION:
            return InvariantResult(
                "data_quality",
                "violation",
                f"{bad}/{total} slots missing SoC or price ({frac:.1%})",
            )
        return InvariantResult(
            "data_quality", "pass", f"{bad}/{total} incomplete slots ({frac:.1%})"
        )

    # -- evaluation cycle ------------------------------------------------------

    def _evaluate_all_sync(self) -> list[InvariantResult]:
        """Run every evaluator, each individually fenced. Never raises."""
        self._load_config()
        results: list[InvariantResult] = []
        try:
            con = self._connect_ro()
        except Exception as e:
            self.state.healthy = False
            self.state.last_error = f"db open failed: {e}"
            return [
                InvariantResult(name, "skipped", f"db unavailable: {e}") for name in INVARIANT_NAMES
            ]
        try:
            now = datetime.now(self._tz())
            evaluators = {
                "slot_continuity": self._eval_slot_continuity,
                "energy_balance": self._eval_energy_balance,
                "soc_bounds": self._eval_soc_bounds,
                "plan_freshness": self._eval_plan_freshness,
                "command_success": self._eval_command_success,
                "forecast_sanity": self._eval_forecast_sanity,
                "data_quality": self._eval_data_quality,
            }
            healthy = True
            for name, fn in evaluators.items():
                try:
                    results.append(fn(con, now))
                except Exception as e:
                    logger.error("monitor evaluator %s crashed: %s", name, e)
                    healthy = False
                    results.append(InvariantResult(name, "skipped", f"evaluator error: {e}"))
            self.state.healthy = healthy
            self.state.last_error = None if healthy else "one or more evaluators crashed"
        finally:
            with contextlib.suppress(Exception):
                con.close()
        return results

    async def evaluate_all(self) -> list[InvariantResult]:
        """Async entry: run the read-only evaluation off the event loop."""
        results = await asyncio.to_thread(self._evaluate_all_sync)
        self._apply_results(results)
        return results

    def _apply_results(self, results: list[InvariantResult]) -> None:
        """Update state + violation episodes (one alert per episode, spec)."""
        for r in results:
            previous = self.state.results.get(r.name)
            self.state.results[r.name] = r
            if r.status == "violation":
                if r.name not in self.state.episodes:
                    self.state.episodes[r.name] = ViolationEpisode(
                        invariant=r.name,
                        first_detected_at=r.evaluated_at,
                        detail=r.detail,
                    )
                    logger.warning("invariant violation (new episode): %s — %s", r.name, r.detail)
                else:
                    # still violated: update detail, keep first_detected_at (dedup)
                    self.state.episodes[r.name].detail = r.detail
            elif r.status == "pass" and r.name in self.state.episodes:
                logger.info("invariant recovered: %s", r.name)
                del self.state.episodes[r.name]
            _ = previous
        self.state.last_cycle_at = datetime.now(UTC).isoformat()

    # -- surfaces ---------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self.state.running,
            "healthy": self.state.healthy,
            "last_cycle_at": self.state.last_cycle_at,
            "last_error": self.state.last_error,
            "invariants": {name: r.to_dict() for name, r in self.state.results.items()},
            "active_violations": [
                {
                    "invariant": e.invariant,
                    "first_detected_at": e.first_detected_at,
                    "detail": e.detail,
                }
                for e in self.state.episodes.values()
            ],
        }

    def health_issues(self) -> list[dict[str, Any]]:
        """Active violations as HealthIssue-shaped dicts for the SystemAlert banner."""
        issues: list[dict[str, Any]] = []
        for ep in self.state.episodes.values():
            issues.append(
                {
                    "category": "monitors",
                    "severity": "warning",
                    "message": f"Invariant violated: {ep.invariant} — {ep.detail}",
                    "guidance": "See /api/system/monitors for evidence; check findings ledger.",
                    "code": f"INVARIANT_{ep.invariant.upper()}",
                    "details": {"first_detected_at": ep.first_detected_at},
                }
            )
        if not self.state.healthy:
            issues.append(
                {
                    "category": "monitors",
                    "severity": "warning",
                    "message": "Invariant monitor unhealthy (evaluator error)",
                    "guidance": "Check backend logs for 'monitor evaluator' errors.",
                    "code": "MONITOR_UNHEALTHY",
                    "details": {"last_error": self.state.last_error},
                }
            )
        return issues

    # -- background loop ---------------------------------------------------------

    def _interval_seconds(self) -> float:
        self._load_config()
        monitoring: dict[str, Any] = self._config.get("monitoring", {}) or {}
        minutes = float(monitoring.get("interval_minutes", DEFAULT_INTERVAL_MINUTES))
        return max(60.0, minutes * 60.0)

    async def start(self) -> None:
        if self._task is not None:
            return
        self.state.running = True
        self._task = asyncio.create_task(self._loop(), name="invariant_monitors")
        logger.info("Invariant monitors started (interval %ss)", self._interval_seconds())

    async def stop(self) -> None:
        self.state.running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        # small startup delay so first cycle sees a settled app
        await asyncio.sleep(30)
        while self.state.running:
            try:
                await self.evaluate_all()
            except Exception as e:  # absolute fail-open backstop (design D4)
                logger.error("monitor cycle failed: %s", e)
                self.state.healthy = False
                self.state.last_error = str(e)
            await asyncio.sleep(self._interval_seconds())


invariant_monitors = InvariantMonitors()
