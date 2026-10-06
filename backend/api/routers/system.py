import asyncio
import contextlib
import json
import logging
import os
import sqlite3
import tempfile
import zipfile
from collections.abc import Coroutine  # noqa: TC003
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from backend.api.deps import get_learning_store
from backend.api.models.system import (
    LogInfoResponse,
    StatusResponse,
    SystemHealthResponse,
    VersionResponse,
)
from backend.core.ev_plug import DEFAULT_EV_PLUGGED_IN_STATES
from backend.core.ha_client import get_ha_bool, get_ha_sensor_float, get_ha_sensor_kw_normalized
from backend.core.secrets import load_yaml
from backend.core.version import get_version as _get_git_version
from backend.learning.store import LearningStore

logger = logging.getLogger("darkstar.api.system")
router = APIRouter(tags=["system"])


def _get_learning_engine() -> Any:
    """Get the learning engine instance."""
    from backend.learning import get_learning_engine

    return get_learning_engine()


@router.get(
    "/api/version",
    summary="Get System Version",
    description="Returns the current version, commit hash, and build date.",
    response_model=VersionResponse,
)
async def get_version() -> VersionResponse:
    """Return the current system version."""
    return VersionResponse(version=_get_git_version())


@router.get(
    "/api/status",
    summary="Get System Status",
    description="Get instantaneous system status (SoC, Power Flow) in parallel.",
    response_model=StatusResponse,
)
async def get_system_status() -> StatusResponse:
    """Get instantaneous system status (SoC, Power Flow) using parallel async fetching."""
    config = load_yaml("config.yaml")
    sensors: dict[str, Any] = config.get("input_sensors", {})

    # Define keys to fetch
    keys = ["battery_soc", "pv_power", "load_power", "battery_power", "grid_power"]
    tasks: list[Coroutine[Any, Any, float | None]] = []
    for key in keys:
        eid = sensors.get(key)
        if eid:
            if key == "battery_soc":
                tasks.append(get_ha_sensor_float(str(eid)))
            else:
                tasks.append(get_ha_sensor_kw_normalized(str(eid)))
        else:
            tasks.append(asyncio.sleep(0, result=0.0))

    # Fetch EV states
    ev_configs: list[dict[str, Any]] = []
    if config.get("system", {}).get("has_ev_charger", False):
        for ev in config.get("ev_chargers", []):
            if ev.get("enabled", True):
                ev_configs.append(ev)

    for ev in ev_configs:
        sensor = ev.get("sensor")
        tasks.append(
            get_ha_sensor_kw_normalized(str(sensor)) if sensor else asyncio.sleep(0, result=0.0)
        )

        soc_sensor = ev.get("soc_sensor")
        tasks.append(
            get_ha_sensor_float(str(soc_sensor)) if soc_sensor else asyncio.sleep(0, result=None)
        )

        plug_sensor = ev.get("plug_sensor")
        tasks.append(
            get_ha_bool(
                str(plug_sensor),
                ev.get("plugged_in_states") or DEFAULT_EV_PLUGGED_IN_STATES,
            )
            if plug_sensor
            else asyncio.sleep(0, result=False)
        )

    results: list[Any] = await asyncio.gather(*tasks)

    soc = results[0] or 0.0
    pv_pow = results[1] or 0.0
    load_pow = results[2] or 0.0
    batt_pow = results[3] or 0.0
    grid_pow = results[4] or 0.0

    # Apply inversion if configured
    if sensors.get("grid_power_inverted", False):
        grid_pow = -grid_pow
    if sensors.get("battery_power_inverted", False):
        batt_pow = -batt_pow

    # Extract EV results
    ev_chargers: list[dict[str, Any]] = []
    base_idx = len(keys)
    total_ev_kw = 0.0
    any_plugged = False

    for i, ev in enumerate(ev_configs):
        idx = base_idx + i * 3
        kw = results[idx] or 0.0
        # If in Watts, convert to kW (best effort if HA provides numeric only, inputs.py float doesn't convert W to kW but ha_socket does)
        # Assuming inputs.py get_ha_sensor_float returns exact numeric value
        # But wait, ha_socket converts W to kW if unit_of_measurement is 'W'. Let's not duplicate that complexity unless needed.
        # Typically people set kW for EVs.
        ev_soc = results[idx + 1]
        plugged = results[idx + 2] or False

        ev_chargers.append(
            {
                "id": ev.get("id"),
                "name": ev.get("name", f"EV {i + 1}"),
                "kw": round(kw, 3),
                "soc": round(ev_soc, 1) if ev_soc is not None else None,
                "plugged_in": plugged,
            }
        )
        total_ev_kw += kw
        if plugged:
            any_plugged = True

    return StatusResponse(
        status="online",
        mode="fastapi",
        rev="ARC1",
        soc_percent=round(soc, 1),
        pv_power_kw=round(pv_pow, 3),
        load_power_kw=round(load_pow, 3),
        battery_power_kw=round(batt_pow, 3),
        grid_power_kw=round(grid_pow, 3),
        ev_kw=round(total_ev_kw, 3),
        ev_plugged_in=any_plugged,
        ev_chargers=ev_chargers,
    )


@router.get(
    "/api/system/log-info",
    summary="Get Log File Info",
    description="Returns metadata about the main log file (size, date).",
    response_model=LogInfoResponse,
)
async def get_log_info() -> LogInfoResponse:
    """Return metadata about the main log file."""
    log_path = Path("data/darkstar.log")
    if not log_path.exists():
        return LogInfoResponse(filename="darkstar.log", size_bytes=0, last_modified="never")

    stats = log_path.stat()
    return LogInfoResponse(
        filename="darkstar.log",
        size_bytes=stats.st_size,
        last_modified=datetime.fromtimestamp(stats.st_mtime, tz=UTC).isoformat(),
    )


@router.get(
    "/api/system/logs",
    summary="Download Log File",
    description="Returns the main log file as a downloadable attachment.",
)
async def download_logs():
    """Download the main log file."""
    from fastapi.responses import FileResponse

    log_path = Path("data/darkstar.log")
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Log file not found")

    return FileResponse(path=log_path, filename="darkstar.log", media_type="text/plain")


@router.delete(
    "/api/system/logs",
    summary="Clear/Truncate Log File",
    description="Truncates the main log file to zero bytes.",
)
async def clear_logs():
    """Clear/Truncate the main log file."""
    log_path = Path("data/darkstar.log")
    try:
        if log_path.exists():
            with log_path.open("w") as f:
                f.truncate(0)
        return {"status": "ok", "message": "Logs cleared"}
    except Exception as e:
        logger.error(f"Failed to clear logs: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/api/system/monitors",
    summary="Get Runtime Invariant Monitor Status",
    description=(
        "Latest evaluation result for each runtime invariant (slot continuity, "
        "energy balance, SoC bounds, plan freshness, command success, forecast "
        "sanity, data quality), active violation episodes, and monitor health."
    ),
)
async def get_invariant_monitors() -> dict[str, Any]:
    """Expose runtime invariant monitor status (stabilization-review-2)."""
    from backend.monitors import invariant_monitors

    return invariant_monitors.get_status()


@router.get(
    "/api/system/health",
    summary="Get System Health",
    description="Returns comprehensive system health metrics (learning, database, planner).",
    response_model=SystemHealthResponse,
)
async def get_system_health() -> SystemHealthResponse:
    """Get comprehensive system health metrics."""
    from backend.api.models.system import (
        DatabaseHealth,
        ForecastHealth,
        LearningHealth,
        PlannerHealth,
        SystemHealthResponse,
        SystemMetrics,
    )
    from backend.health import get_forecast_status, get_load_forecast_status

    # 1. Learning Stats
    try:
        engine = _get_learning_engine()
        learning_stats = await engine.store.get_learning_stats()
        learning_health = LearningHealth(
            total_runs=learning_stats["total_runs"],
            status=learning_stats["status"],
            last_run=learning_stats["last_run"],
        )
    except Exception as e:
        logger.error(f"Error getting learning stats: {e}")
        learning_health = LearningHealth(total_runs=0, status="unknown", last_run=None)

    # 2. Database Stats
    try:
        engine = _get_learning_engine()
        db_stats = await engine.store.get_db_stats()
        database_health = DatabaseHealth(
            size_mb=db_stats["size_mb"],
            slot_plans_count=db_stats["slot_plans_count"],
            slot_observations_count=db_stats["slot_observations_count"],
            health=db_stats["health"],
        )
    except Exception as e:
        logger.error(f"Error getting DB stats: {e}")
        database_health = DatabaseHealth(
            size_mb=0.0, slot_plans_count=0, slot_observations_count=0, health="error"
        )

    # 3. Planner Stats
    planner_health = PlannerHealth(last_run=None, status="unknown", next_scheduled=None)
    try:
        status_path = Path("data/scheduler_status.json")
        if status_path.exists():
            with status_path.open() as f:
                data = json.load(f)

            planner_health = PlannerHealth(
                last_run=data.get("last_run_at"),
                status=data.get("last_run_status", "unknown"),
                next_scheduled=data.get("next_run_at"),
            )
    except Exception as e:
        logger.error(f"Error getting planner stats: {e}")

    # 4. System Metrics
    uptime_hours = 0.0
    try:
        with Path("/proc/uptime").open() as f:
            uptime_seconds = float(f.readline().split()[0])
            uptime_hours = round(uptime_seconds / 3600, 1)
    except Exception:
        pass

    errors_24h = 0
    # Simple grep for ERROR in logs? Skipping for now to avoid perf issues, hardcode 0
    # or check log size changes.

    system_metrics = SystemMetrics(
        errors_24h=errors_24h, uptime_hours=uptime_hours, version=_get_git_version()
    )

    # 5. Forecast Health (REV F65 Phase 5d)
    pv_info = get_forecast_status()
    load_info = get_load_forecast_status()
    forecast_health = ForecastHealth(
        pv_status=pv_info.get("status", "ok"),
        load_status=load_info.get("status", "ok"),
        load_reason=load_info.get("reason", ""),
    )

    return SystemHealthResponse(
        learning=learning_health,
        database=database_health,
        planner=planner_health,
        forecast=forecast_health,
        system=system_metrics,
    )


# ---------------------------------------------------------------------------
# Diagnostics export (database snapshot + diagnostics bundle)
# ---------------------------------------------------------------------------

_SQLITE_BUSY_TIMEOUT_S = 30.0
# One lock for the snapshot and the bundle, since both run the database backup.
_export_lock = asyncio.Lock()


def _utc_stamp(now: datetime) -> str:
    return now.strftime("%Y%m%d-%H%M%S")


def _remove_file(path: Path) -> None:
    """Delete a temporary file, ignoring a file that is already gone."""
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def _temp_file(directory: Path, prefix: str, suffix: str) -> Path:
    """Create an empty temporary file, preferably next to the database."""
    target_dir = directory if directory.is_dir() else None
    fd, name = tempfile.mkstemp(dir=target_dir, prefix=prefix, suffix=suffix)
    os.close(fd)
    return Path(name)


def _snapshot_database_sync(db_path: Path) -> Path:
    """Copy the database with SQLite's online backup into a temporary file.

    The live database is opened read-only. The returned file is a single,
    self-contained SQLite file; the caller must delete it.
    """
    if not db_path.is_file():
        raise FileNotFoundError(f"Database file not found: {db_path}")

    dest = _temp_file(db_path.parent, ".db-snapshot-", ".db")
    try:
        src = sqlite3.connect(
            f"{db_path.resolve().as_uri()}?mode=ro", uri=True, timeout=_SQLITE_BUSY_TIMEOUT_S
        )
        try:
            dst = sqlite3.connect(dest)
            try:
                src.backup(dst, pages=1024, sleep=0.01)
                # The copy inherits WAL mode from the source; make it one plain file.
                dst.execute("PRAGMA journal_mode=DELETE")
            finally:
                dst.close()
        finally:
            src.close()
    except BaseException:
        _remove_file(dest)
        _remove_file(dest.with_name(dest.name + "-wal"))
        _remove_file(dest.with_name(dest.name + "-shm"))
        raise
    return dest


async def _snapshot_database(db_path: Path) -> Path:
    """Run the backup in a worker thread (shared by the snapshot and the bundle)."""
    return await asyncio.to_thread(_snapshot_database_sync, db_path)


def _reject_if_busy() -> None:
    if _export_lock.locked():
        raise HTTPException(status_code=409, detail="Another export is already in progress")


@router.get(
    "/api/system/db-snapshot",
    summary="Download Database Snapshot",
    description=(
        "Returns a transactionally consistent snapshot of planner_learning.db taken with "
        "SQLite's online backup, while Darkstar keeps running."
    ),
)
async def download_db_snapshot(
    store: LearningStore = Depends(get_learning_store),
) -> FileResponse:
    """Download a consistent snapshot of the learning database."""
    _reject_if_busy()
    async with _export_lock:
        try:
            snapshot = await _snapshot_database(Path(store.db_path))
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail="Database file not found") from e
        except Exception as e:
            logger.error(f"Database snapshot failed: {e}")
            raise HTTPException(status_code=500, detail=f"Database snapshot failed: {e}") from e

    filename = f"planner_learning-{_utc_stamp(datetime.now(UTC))}.db"
    return FileResponse(
        path=snapshot,
        filename=filename,
        media_type="application/vnd.sqlite3",
        background=BackgroundTask(_remove_file, snapshot),
    )


def _json_bytes(data: Any) -> bytes:
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    return json.dumps(data, indent=2, default=str).encode("utf-8")


def _read_file(path: Path) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found")
    return path.read_bytes()


def _write_bundle_sync(
    zip_path: Path,
    snapshot: Path | None,
    json_payloads: dict[str, bytes],
    manifest_base: dict[str, Any],
    items: dict[str, str],
) -> None:
    """Write the zip. ``items`` maps item name to ``included`` or an error text."""
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if snapshot is not None:
            zf.write(snapshot, "planner_learning.db")
        for name, path in (
            ("config.yaml", Path("config.yaml")),
            ("darkstar.log", Path("data/darkstar.log")),
            ("schedule.json", Path("data/schedule.json")),
        ):
            try:
                zf.writestr(name, _read_file(path))
                items[name] = "included"
            except Exception as e:
                items[name] = f"error: {e}"
        for name, payload in json_payloads.items():
            zf.writestr(name, payload)
        manifest = {**manifest_base, "items": items}
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))


@router.get(
    "/api/system/diagnostics",
    summary="Export Diagnostics Bundle",
    description=(
        "Returns one zip with a consistent database snapshot, config.yaml as stored on disk, "
        "the log, schedule.json, version/status/health/monitors output and a manifest. "
        "Never includes secrets.yaml."
    ),
)
async def export_diagnostics(
    store: LearningStore = Depends(get_learning_store),
) -> FileResponse:
    """Download a diagnostics bundle. Every item fails independently."""
    _reject_if_busy()
    async with _export_lock:
        now = datetime.now(UTC)
        version = _get_git_version()
        items: dict[str, str] = {}

        snapshot: Path | None = None
        try:
            snapshot = await _snapshot_database(Path(store.db_path))
            items["planner_learning.db"] = "included"
        except Exception as e:
            logger.error(f"Diagnostics: database snapshot failed: {e}")
            items["planner_learning.db"] = f"error: {e}"

        try:
            json_payloads: dict[str, bytes] = {}
            sources: dict[str, Any] = {
                "version.json": get_version,
                "status.json": get_system_status,
                "health.json": get_system_health,
                "monitors.json": get_invariant_monitors,
            }
            for name, handler in sources.items():
                try:
                    json_payloads[name] = _json_bytes(await handler())
                    items[name] = "included"
                except Exception as e:
                    logger.error(f"Diagnostics: {name} failed: {e}")
                    items[name] = f"error: {e}"

            zip_path = _temp_file(Path(store.db_path).parent, ".diagnostics-", ".zip")
            try:
                await asyncio.to_thread(
                    _write_bundle_sync,
                    zip_path,
                    snapshot,
                    json_payloads,
                    {"version": version, "exported_at_utc": now.isoformat()},
                    items,
                )
            except Exception as e:
                _remove_file(zip_path)
                logger.error(f"Diagnostics bundle failed: {e}")
                raise HTTPException(
                    status_code=500, detail=f"Diagnostics export failed: {e}"
                ) from e
        finally:
            if snapshot is not None:
                _remove_file(snapshot)

    safe_version = "".join(c if c.isalnum() or c in ".-_" else "_" for c in str(version))
    return FileResponse(
        path=zip_path,
        filename=f"darkstar-diagnostics-{safe_version}-{_utc_stamp(now)}.zip",
        media_type="application/zip",
        background=BackgroundTask(_remove_file, zip_path),
    )
