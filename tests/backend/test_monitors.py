"""Tests for runtime invariant monitors (stabilization-review-2).

Covers: each invariant's pass/violation/skip path, alert-episode dedup and
recovery-clearing, failure isolation (evaluator crash never propagates), and
API/health exposure.
"""

import contextlib
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
import pytz
import yaml
from sqlalchemy import create_engine

from backend.learning.models import Base
from backend.monitors import (
    ENERGY_VIOLATION_COUNT,
    PV_FORECAST_CEILING_KWH_PER_KWP,
    InvariantMonitors,
    InvariantResult,
)

TZ = pytz.timezone("Europe/Stockholm")

# config.yaml's real solar_arrays (Roof 3.16 + Garage 3.95 kWp) sum to 7.11 kWp,
# matching the old hardcoded reference-install ceiling constant.
REFERENCE_INSTALL_KWP = 7.11
REFERENCE_INSTALL_CEILING_KWH = REFERENCE_INSTALL_KWP * PV_FORECAST_CEILING_KWH_PER_KWP


def write_config(tmp_path: Path, solar_arrays: list[dict] | None) -> str:
    """Write a minimal config.yaml with the given system.solar_arrays (or none)."""
    system: dict = {}
    if solar_arrays is not None:
        system["solar_arrays"] = solar_arrays
    config = {"system": system}
    path = tmp_path / "monitor_config.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return str(path)


@pytest.fixture
def mon_db(monkeypatch):
    """Temp DB with full schema, pinned via DB_PATH (the monitors honour it)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    monkeypatch.setenv("DB_PATH", db_path)
    yield db_path
    with contextlib.suppress(OSError):
        Path(db_path).unlink()


def seed_healthy(db_path: str, hours: int = 25) -> None:
    """Seed a fully healthy trailing window: contiguous slots, balanced energy,
    sane SoC, fresh plan, successful ticks, sane future forecast."""
    import sqlite3

    con = sqlite3.connect(db_path)
    now = datetime.now(TZ).replace(minute=0, second=0, microsecond=0)
    for i in range(hours * 4):
        start = now - timedelta(minutes=15 * (i + 1))
        end = start + timedelta(minutes=15)
        con.execute(
            "INSERT OR REPLACE INTO slot_observations "
            "(slot_start, slot_end, import_kwh, export_kwh, pv_kwh, load_kwh, water_kwh, "
            " ev_charging_kwh, batt_charge_kwh, batt_discharge_kwh, soc_start_percent, "
            " soc_end_percent, import_price_sek_kwh, export_price_sek_kwh) "
            "VALUES (?, ?, 0.5, 0, 0, 0.5, 0, 0, 0, 0, 50, 50, 1.0, 0.5)",
            (start.isoformat(), end.isoformat()),
        )
        con.execute(
            "INSERT INTO execution_log "
            "(executed_at, slot_start, override_active, success, source, commanded_unit) "
            "VALUES (?, ?, 0, 1, 'native', 'A')",
            (start.isoformat(), start.isoformat()),
        )
    # fresh plan write (created_at is naive UTC per production convention)
    con.execute(
        "INSERT INTO slot_plans (slot_start, planned_charge_kwh, planned_discharge_kwh, "
        "planned_soc_percent, created_at) VALUES (?, 0, 0, 50, ?)",
        (
            now.isoformat(),
            datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds"),
        ),
    )
    # sane future forecast
    con.execute(
        "INSERT INTO slot_forecasts (slot_start, pv_forecast_kwh, load_forecast_kwh, "
        "forecast_version, created_at) VALUES (?, 1.0, 0.2, 'test', ?)",
        (
            (now + timedelta(hours=2)).isoformat(),
            datetime.now(UTC).replace(tzinfo=None).isoformat(),
        ),
    )
    con.commit()
    con.close()


@pytest.fixture
def monitors(mon_db):
    m = InvariantMonitors(config_path="config.yaml")
    return m


class TestHealthyPasses:
    @pytest.mark.asyncio
    async def test_all_invariants_pass_on_healthy_data(self, mon_db, monitors):
        seed_healthy(mon_db)
        results = await monitors.evaluate_all()
        by_name = {r.name: r for r in results}
        for name in (
            "slot_continuity",
            "energy_balance",
            "soc_bounds",
            "plan_freshness",
            "command_success",
            "forecast_sanity",
            "data_quality",
        ):
            assert by_name[name].status == "pass", f"{name}: {by_name[name].detail}"
        assert monitors.state.healthy is True
        assert monitors.state.episodes == {}


class TestViolations:
    @pytest.mark.asyncio
    async def test_slot_gap_detected(self, mon_db, monitors):
        import sqlite3

        seed_healthy(mon_db)
        con = sqlite3.connect(mon_db)
        # remove a slot 3 h ago -> gap
        target = datetime.now(TZ).replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)
        con.execute("DELETE FROM slot_observations WHERE slot_start = ?", (target.isoformat(),))
        con.commit()
        con.close()

        results = await monitors.evaluate_all()
        r = next(x for x in results if x.name == "slot_continuity")
        assert r.status == "violation"
        assert "gap" in r.detail

    @pytest.mark.asyncio
    async def test_energy_balance_violation(self, mon_db, monitors):
        import sqlite3

        seed_healthy(mon_db)
        con = sqlite3.connect(mon_db)
        now = datetime.now(TZ).replace(minute=0, second=0, microsecond=0)
        # inject ENERGY_VIOLATION_COUNT big residuals (import 10, load 0.5)
        for i in range(ENERGY_VIOLATION_COUNT):
            t = now - timedelta(hours=2, minutes=15 * i)
            con.execute(
                "UPDATE slot_observations SET import_kwh = 10.0 WHERE slot_start = ?",
                (t.isoformat(),),
            )
        con.commit()
        con.close()

        results = await monitors.evaluate_all()
        r = next(x for x in results if x.name == "energy_balance")
        assert r.status == "violation"

    @pytest.mark.asyncio
    async def test_soc_out_of_bounds(self, mon_db, monitors):
        import sqlite3

        seed_healthy(mon_db)
        con = sqlite3.connect(mon_db)
        t = datetime.now(TZ).replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
        con.execute(
            "UPDATE slot_observations SET soc_end_percent = 1.0 WHERE slot_start = ?",
            (t.isoformat(),),
        )
        con.commit()
        con.close()

        results = await monitors.evaluate_all()
        r = next(x for x in results if x.name == "soc_bounds")
        assert r.status == "violation"

    @pytest.mark.asyncio
    async def test_stale_plan_detected(self, mon_db, monitors):
        import sqlite3

        seed_healthy(mon_db)
        con = sqlite3.connect(mon_db)
        old = (datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=10)).isoformat(
            sep=" ", timespec="seconds"
        )
        con.execute("UPDATE slot_plans SET created_at = ?", (old,))
        con.commit()
        con.close()

        results = await monitors.evaluate_all()
        r = next(x for x in results if x.name == "plan_freshness")
        assert r.status == "violation"

    @pytest.mark.asyncio
    async def test_command_failure_rate_detected(self, mon_db, monitors):
        import sqlite3

        seed_healthy(mon_db)
        con = sqlite3.connect(mon_db)
        con.execute("UPDATE execution_log SET success = 0 WHERE rowid % 10 = 0")  # 10% failures
        con.commit()
        con.close()

        results = await monitors.evaluate_all()
        r = next(x for x in results if x.name == "command_success")
        assert r.status == "violation"

    @pytest.mark.asyncio
    async def test_pv_forecast_over_ceiling_detected(self, mon_db, tmp_path):
        import sqlite3

        config_path = write_config(tmp_path, [{"name": "A", "kwp": REFERENCE_INSTALL_KWP}])
        m = InvariantMonitors(config_path=config_path)
        seed_healthy(mon_db)
        con = sqlite3.connect(mon_db)
        future = datetime.now(TZ) + timedelta(hours=3)
        con.execute(
            "INSERT INTO slot_forecasts (slot_start, pv_forecast_kwh, load_forecast_kwh, "
            "forecast_version, created_at) VALUES (?, ?, 0.2, 'test', ?)",
            (
                future.isoformat(),
                REFERENCE_INSTALL_CEILING_KWH + 0.5,
                datetime.now(UTC).replace(tzinfo=None).isoformat(),
            ),
        )
        con.commit()
        con.close()

        results = await m.evaluate_all()
        r = next(x for x in results if x.name == "forecast_sanity")
        assert r.status == "violation"
        assert f"{REFERENCE_INSTALL_CEILING_KWH:.3f}" in r.detail

    @pytest.mark.asyncio
    async def test_large_array_forecast_within_config_derived_ceiling_passes(
        self, mon_db, tmp_path
    ):
        """14.94 kWp system: 2.781 kWh/slot forecast is well within physical reach."""
        import sqlite3

        config_path = write_config(tmp_path, [{"name": "A", "kwp": 14.94}])
        m = InvariantMonitors(config_path=config_path)
        seed_healthy(mon_db)
        con = sqlite3.connect(mon_db)
        future = datetime.now(TZ) + timedelta(hours=3)
        con.execute(
            "INSERT INTO slot_forecasts (slot_start, pv_forecast_kwh, load_forecast_kwh, "
            "forecast_version, created_at) VALUES (?, 2.781, 0.2, 'test', ?)",
            (future.isoformat(), datetime.now(UTC).replace(tzinfo=None).isoformat()),
        )
        con.commit()
        con.close()

        results = await m.evaluate_all()
        r = next(x for x in results if x.name == "forecast_sanity")
        assert r.status == "pass", r.detail

    @pytest.mark.asyncio
    async def test_small_array_forecast_above_config_derived_ceiling_violates(
        self, mon_db, tmp_path
    ):
        """7.11 kWp system: forecast above 1.778 kWh/slot violates."""
        import sqlite3

        config_path = write_config(tmp_path, [{"name": "A", "kwp": 7.11}])
        m = InvariantMonitors(config_path=config_path)
        seed_healthy(mon_db)
        con = sqlite3.connect(mon_db)
        future = datetime.now(TZ) + timedelta(hours=3)
        con.execute(
            "INSERT INTO slot_forecasts (slot_start, pv_forecast_kwh, load_forecast_kwh, "
            "forecast_version, created_at) VALUES (?, 1.9, 0.2, 'test', ?)",
            (future.isoformat(), datetime.now(UTC).replace(tzinfo=None).isoformat()),
        )
        con.commit()
        con.close()

        results = await m.evaluate_all()
        r = next(x for x in results if x.name == "forecast_sanity")
        assert r.status == "violation"

    @pytest.mark.asyncio
    async def test_no_solar_arrays_configured_skips_forecast_sanity(self, mon_db, tmp_path):
        import sqlite3

        config_path = write_config(tmp_path, [])
        m = InvariantMonitors(config_path=config_path)
        seed_healthy(mon_db)
        con = sqlite3.connect(mon_db)
        future = datetime.now(TZ) + timedelta(hours=3)
        con.execute(
            "INSERT INTO slot_forecasts (slot_start, pv_forecast_kwh, load_forecast_kwh, "
            "forecast_version, created_at) VALUES (?, 999.0, 0.2, 'test', ?)",
            (future.isoformat(), datetime.now(UTC).replace(tzinfo=None).isoformat()),
        )
        con.commit()
        con.close()

        results = await m.evaluate_all()
        r = next(x for x in results if x.name == "forecast_sanity")
        assert r.status == "skipped"
        assert "no solar arrays" in r.detail

    @pytest.mark.asyncio
    async def test_brief_outage_within_95_percent_passes(self, mon_db, monitors):
        """18/1321 failed ticks (98.64%) passes at the 95% threshold."""
        import sqlite3

        seed_healthy(mon_db)
        con = sqlite3.connect(mon_db)
        now = datetime.now(TZ)
        con.execute("DELETE FROM execution_log")
        for i in range(1321):
            t = now - timedelta(minutes=i)
            success = 0 if i < 18 else 1
            con.execute(
                "INSERT INTO execution_log "
                "(executed_at, slot_start, override_active, success, source, commanded_unit) "
                "VALUES (?, ?, 0, ?, 'native', 'A')",
                (t.isoformat(), t.isoformat(), success),
            )
        con.commit()
        con.close()

        results = await monitors.evaluate_all()
        r = next(x for x in results if x.name == "command_success")
        assert r.status == "pass", r.detail

    @pytest.mark.asyncio
    async def test_data_quality_violation_on_missing_prices(self, mon_db, monitors):
        import sqlite3

        seed_healthy(mon_db)
        con = sqlite3.connect(mon_db)
        con.execute(
            "UPDATE slot_observations SET import_price_sek_kwh = NULL WHERE rowid % 5 = 0"
        )  # 20% bad
        con.commit()
        con.close()

        results = await monitors.evaluate_all()
        r = next(x for x in results if x.name == "data_quality")
        assert r.status == "violation"


class TestSkipPaths:
    @pytest.mark.asyncio
    async def test_empty_db_skips_not_violates(self, mon_db, monitors):
        results = await monitors.evaluate_all()
        for r in results:
            assert r.status == "skipped", f"{r.name} should skip on empty DB, got {r.status}"

    @pytest.mark.asyncio
    async def test_missing_db_skips_and_marks_unhealthy(self, monitors, monkeypatch):
        monkeypatch.setenv("DB_PATH", "/nonexistent/nowhere.db")
        results = await monitors.evaluate_all()
        assert all(r.status == "skipped" for r in results)
        assert monitors.state.healthy is False


class TestEpisodeDedup:
    @pytest.mark.asyncio
    async def test_one_episode_across_repeated_violations_and_recovery_clears(
        self, mon_db, monitors
    ):
        import sqlite3

        seed_healthy(mon_db)
        con = sqlite3.connect(mon_db)
        old = (datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=10)).isoformat(
            sep=" ", timespec="seconds"
        )
        con.execute("UPDATE slot_plans SET created_at = ?", (old,))
        con.commit()
        con.close()

        await monitors.evaluate_all()
        first = monitors.state.episodes["plan_freshness"].first_detected_at
        await monitors.evaluate_all()  # still violated
        await monitors.evaluate_all()
        assert monitors.state.episodes["plan_freshness"].first_detected_at == first
        assert len([e for e in monitors.state.episodes if e == "plan_freshness"]) == 1

        # recovery: fresh plan write clears the episode
        con = sqlite3.connect(mon_db)
        con.execute(
            "UPDATE slot_plans SET created_at = ?",
            (datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds"),),
        )
        con.commit()
        con.close()
        await monitors.evaluate_all()
        assert "plan_freshness" not in monitors.state.episodes


class TestFailureIsolation:
    @pytest.mark.asyncio
    async def test_evaluator_crash_yields_skip_and_unhealthy_but_others_run(self, mon_db, monitors):
        seed_healthy(mon_db)

        def boom(con, now):
            raise RuntimeError("injected evaluator crash")

        with patch.object(monitors, "_eval_energy_balance", side_effect=boom):
            results = await monitors.evaluate_all()

        by_name = {r.name: r for r in results}
        assert by_name["energy_balance"].status == "skipped"
        assert "evaluator error" in by_name["energy_balance"].detail
        assert monitors.state.healthy is False
        # the others still evaluated normally
        assert by_name["slot_continuity"].status == "pass"
        assert by_name["command_success"].status == "pass"

    @pytest.mark.asyncio
    async def test_evaluate_all_never_raises(self, monitors, monkeypatch):
        monkeypatch.setenv("DB_PATH", "/nonexistent/nowhere.db")
        # even with everything broken, no exception may escape (design D4)
        await monitors.evaluate_all()


class TestSurfaces:
    @pytest.mark.asyncio
    async def test_health_issues_reflect_active_violations(self, mon_db, monitors):
        import sqlite3

        seed_healthy(mon_db)
        con = sqlite3.connect(mon_db)
        old = (datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=10)).isoformat(
            sep=" ", timespec="seconds"
        )
        con.execute("UPDATE slot_plans SET created_at = ?", (old,))
        con.commit()
        con.close()

        await monitors.evaluate_all()
        issues = monitors.health_issues()
        assert any(i["code"] == "INVARIANT_PLAN_FRESHNESS" for i in issues)
        assert all(i["category"] == "monitors" for i in issues)

    @pytest.mark.asyncio
    async def test_get_status_shape(self, mon_db, monitors):
        seed_healthy(mon_db)
        await monitors.evaluate_all()
        status = monitors.get_status()
        assert set(status) >= {
            "running",
            "healthy",
            "last_cycle_at",
            "invariants",
            "active_violations",
        }
        assert set(status["invariants"]) == {
            "slot_continuity",
            "energy_balance",
            "soc_bounds",
            "plan_freshness",
            "command_success",
            "forecast_sanity",
            "data_quality",
        }

    def test_result_serialization(self):
        r = InvariantResult("x", "pass", "ok")
        d = r.to_dict()
        assert d["name"] == "x" and d["status"] == "pass" and d["evaluated_at"]
