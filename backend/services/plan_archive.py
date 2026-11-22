"""Per-run archive of planner inputs, plan and diagnostics.

One gzip JSON file per planner service run under ``data/plan_archive/`` (success and
failure), so a past run can be re-solved offline and handed over for support. Pure file
store: no database tables. Archive failures never reach the planner.

Capture model: the planner service starts a capture before a run; the pipeline records
values with :func:`capture` (a no-op when no capture is active, so CLI and test callers
are unaffected); the service writes the record once the run has ended.
"""

import asyncio
import contextlib
import copy
import gzip
import json
import logging
import math
import os
import re
import tempfile
import zipfile
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from backend.core.redaction import is_secret_key, redact_text

logger = logging.getLogger("darkstar.services.plan_archive")

ARCHIVE_DIR = Path("data/plan_archive")
FORMAT_VERSION = 1

DEFAULT_RETENTION_DAYS = 60
MIN_RETENTION_DAYS = 7
MAX_EXECUTOR_ERRORS = 50
DEFAULT_EXECUTOR_LOOKBACK = timedelta(hours=24)
_STALE_TEMP_AGE = timedelta(hours=1)

_NAME_RE = re.compile(r"^(?P<stamp>\d{8}T\d{6}Z)-(?P<outcome>ok|err)\.json\.gz$")
_STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_DOWNLOAD_PREFIX = ".download-"
_DOWNLOAD_SUFFIX = ".zip"
_TEMP_SUFFIX = ".tmp"


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def _parse_retention(value: object) -> int:
    """Retention in days: invalid, zero or negative -> 60; below 7 -> 7."""
    number: float | None = None
    if isinstance(value, bool):
        number = None
    elif isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str):
        with contextlib.suppress(ValueError):
            number = float(value.strip())
    if number is None or not math.isfinite(number):
        return DEFAULT_RETENTION_DAYS
    days = int(number)
    if days <= 0:
        return DEFAULT_RETENTION_DAYS
    return max(days, MIN_RETENTION_DAYS)


def _debug_section(config: dict[str, Any] | None) -> dict[str, Any]:
    section = (config or {}).get("debug")
    return cast("dict[str, Any]", section) if isinstance(section, dict) else {}


def is_enabled(config: dict[str, Any] | None) -> bool:
    """``debug.plan_archive_enabled`` (default true)."""
    return bool(_debug_section(config).get("plan_archive_enabled", True))


def retention_days(config: dict[str, Any] | None) -> int:
    """``debug.plan_archive_retention_days`` after validation."""
    return _parse_retention(_debug_section(config).get("plan_archive_retention_days"))


def _directory(directory: Path | None) -> Path:
    return directory if directory is not None else ARCHIVE_DIR


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


@dataclass
class RunCapture:
    """Values gathered while one planner run executes."""

    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = field(default_factory=dict[str, Any])
    token: "Token[RunCapture | None] | None" = field(default=None, repr=False)


_current: ContextVar[RunCapture | None] = ContextVar("plan_archive_capture", default=None)


def start_capture() -> RunCapture:
    """Begin capturing for the current task and return the capture."""
    run = RunCapture()
    run.token = _current.set(run)
    return run


def capture(key: str, value: Any) -> None:
    """Record ``value`` under ``key`` in the active capture (no-op without one).

    The value is snapshotted so later mutation by the pipeline does not change the record.
    """
    run = _current.get()
    if run is None:
        return
    try:
        run.data[key] = copy.deepcopy(value)
    except Exception:
        run.data[key] = value


def end_capture() -> None:
    """Stop capturing for the current task."""
    run = _current.get()
    if run is not None and run.token is not None:
        token = run.token
        run.token = None
        _current.reset(token)
    else:
        _current.set(None)


# ---------------------------------------------------------------------------
# File names
# ---------------------------------------------------------------------------


def _file_name(started_at: datetime, outcome: str) -> str:
    suffix = "ok" if outcome == "ok" else "err"
    return f"{started_at.astimezone(UTC).strftime(_STAMP_FORMAT)}-{suffix}.json.gz"


def _parse_name(name: str) -> tuple[datetime, str] | None:
    match = _NAME_RE.match(name)
    if match is None:
        return None
    try:
        moment = datetime.strptime(match.group("stamp"), _STAMP_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None
    return moment, "ok" if match.group("outcome") == "ok" else "error"


def list_records(
    days: int | None = None,
    directory: Path | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Archive files (oldest first) with name time, outcome and size; no decompression."""
    root = _directory(directory)
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days) if days is not None else None
    records: list[dict[str, Any]] = []
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                parsed = _parse_name(entry.name)
                if parsed is None or not entry.is_file():
                    continue
                moment, outcome = parsed
                if cutoff is not None and moment < cutoff:
                    continue
                records.append(
                    {
                        "name": entry.name,
                        "time": moment,
                        "outcome": outcome,
                        "size": entry.stat().st_size,
                    }
                )
    except FileNotFoundError:
        return []
    records.sort(key=lambda r: r["name"])
    return records


# ---------------------------------------------------------------------------
# Record building and writing
# ---------------------------------------------------------------------------


def _strip_secrets(value: Any) -> Any:
    """Copy of ``value`` without entries whose key names denote secrets (any depth)."""
    if isinstance(value, dict):
        mapping = cast("dict[Any, Any]", value)
        return {k: _strip_secrets(v) for k, v in mapping.items() if not is_secret_key(k)}
    if isinstance(value, list):
        return [_strip_secrets(v) for v in cast("list[Any]", value)]
    return value


def _executor_db_path() -> Path:
    return Path(os.getenv("DB_PATH") or Path("data") / "planner_learning.db")


def _load_executor_errors(since: datetime, timezone: str) -> tuple[list[dict[str, Any]], int]:
    """Failed executor actions since ``since`` (empty when the database does not exist)."""
    db_path = _executor_db_path()
    if not db_path.exists():
        return [], 0
    from executor.history import ExecutionHistory

    history = ExecutionHistory(str(db_path), timezone=timezone)
    try:
        return history.get_failures_since(since.isoformat(), limit=MAX_EXECUTOR_ERRORS)
    finally:
        history.engine.dispose()


def _build_record(
    run: RunCapture,
    outcome: str,
    error: dict[str, Any] | None,
    config: dict[str, Any],
    finished_at: datetime,
    executor_errors: list[dict[str, Any]],
    executor_errors_total: int,
) -> dict[str, Any]:
    from backend.core.version import get_version

    data = run.data
    return {
        "format_version": FORMAT_VERSION,
        "run_id": run.started_at.astimezone(UTC).strftime(_STAMP_FORMAT),
        "started_at": run.started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "outcome": "ok" if outcome == "ok" else "error",
        "planner_version": get_version(),
        "config_version": config.get("config_version"),
        "config": _strip_secrets(config),
        "inputs": data.get("inputs") or {},
        "schedule": data.get("schedule"),
        "initial_soc_kwh": data.get("initial_soc_kwh"),
        "initial_soc_percent": data.get("initial_soc_percent"),
        "safety_floor": data.get("safety_floor"),
        "solver_status": data.get("solver_status"),
        "time_limit_hit": data.get("time_limit_hit"),
        "battery_parameters": data.get("battery_parameters"),
        "error": error,
        "executor_errors": executor_errors,
        "executor_errors_truncated": max(0, executor_errors_total - len(executor_errors)),
    }


def _json_default(value: Any) -> str:
    """Timestamps as ISO text (as in schedule.json), anything else as ``str``."""
    isoformat = getattr(value, "isoformat", None)
    return str(isoformat()) if callable(isoformat) else str(value)


def _encode(record: dict[str, Any]) -> bytes:
    text = redact_text(json.dumps(record, default=_json_default, separators=(",", ":")))
    return gzip.compress(text.encode("utf-8"))


def _write_file(directory: Path, name: str, payload: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / name
    temp = directory / f".{name}{_TEMP_SUFFIX}"
    try:
        with temp.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(final)
    except BaseException:
        with contextlib.suppress(OSError):
            temp.unlink(missing_ok=True)
        raise
    return final


def _since(directory: Path, now: datetime) -> datetime:
    """``finished_at`` of the newest archived run, else 24 hours back.

    Failures logged while a run was still executing therefore belong to the record that
    run wrote, never to the next one. If the newest file cannot be read, its name time
    (the run's start) is used, which can only repeat failures, never lose them.
    """
    records = list_records(directory=directory)
    if not records:
        return now - DEFAULT_EXECUTOR_LOOKBACK
    newest = records[-1]
    try:
        with gzip.open(directory / newest["name"], "rt", encoding="utf-8") as handle:
            finished = datetime.fromisoformat(str(json.load(handle)["finished_at"]))
        return finished if finished.tzinfo else finished.replace(tzinfo=UTC)
    except Exception as exc:
        logger.warning("Plan archive: could not read finished_at of %s: %s", newest["name"], exc)
        return cast("datetime", newest["time"])


async def write_record(
    run: RunCapture,
    outcome: str,
    error: dict[str, Any] | None,
    config: dict[str, Any],
    directory: Path | None = None,
) -> Path | None:
    """Write the run's archive record and prune; never raises.

    Returns the file path, or ``None`` when archiving is disabled or failed.
    """
    try:
        if not is_enabled(config):
            return None
        root = _directory(directory)
        finished_at = datetime.now(UTC)

        executor_errors: list[dict[str, Any]] = []
        executor_total = 0
        try:
            timezone = str(config.get("timezone") or "Europe/Stockholm")
            since = _since(root, finished_at)
            executor_errors, executor_total = await asyncio.to_thread(
                _load_executor_errors, since, timezone
            )
        except Exception as exc:
            logger.warning("Plan archive: executor error lookup failed: %s", exc)
            executor_errors, executor_total = [], 0

        def _serialize_and_write() -> Path:
            record = _build_record(
                run, outcome, error, config, finished_at, executor_errors, executor_total
            )
            return _write_file(root, _file_name(run.started_at, outcome), _encode(record))

        path = await asyncio.to_thread(_serialize_and_write)
        try:
            await asyncio.to_thread(prune, retention_days(config), None, root)
        except Exception as exc:
            logger.warning("Plan archive: pruning failed: %s", exc)
        return path
    except Exception as exc:
        logger.warning("Plan archive: could not write record: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Retention, summary, clear
# ---------------------------------------------------------------------------


def _is_temp_name(name: str) -> bool:
    return (name.startswith(".") and name.endswith(_TEMP_SUFFIX)) or (
        name.startswith(_DOWNLOAD_PREFIX) and name.endswith(_DOWNLOAD_SUFFIX)
    )


def prune(
    retention: int,
    now: datetime | None = None,
    directory: Path | None = None,
) -> int:
    """Delete records older than ``retention`` days and stale temp files; return deleted records."""
    root = _directory(directory)
    moment = now or datetime.now(UTC)
    cutoff = moment - timedelta(days=retention)
    deleted = 0
    try:
        with os.scandir(root) as entries:
            for entry in list(entries):
                parsed = _parse_name(entry.name)
                try:
                    if parsed is not None:
                        if parsed[0] < cutoff:
                            Path(entry.path).unlink(missing_ok=True)
                            deleted += 1
                    elif _is_temp_name(entry.name) and entry.is_file():
                        age = moment - datetime.fromtimestamp(entry.stat().st_mtime, UTC)
                        if age > _STALE_TEMP_AGE:
                            Path(entry.path).unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning("Plan archive: could not delete %s: %s", entry.name, exc)
    except FileNotFoundError:
        return 0
    return deleted


def summary(config: dict[str, Any] | None, directory: Path | None = None) -> dict[str, Any]:
    """Enabled state, retention and record statistics from file names and sizes."""
    records = list_records(directory=directory)
    return {
        "enabled": is_enabled(config),
        "retention_days": retention_days(config),
        "count": len(records),
        "total_bytes": sum(int(r["size"]) for r in records),
        "oldest": records[0]["time"].isoformat() if records else None,
        "newest": records[-1]["time"].isoformat() if records else None,
    }


def clear(directory: Path | None = None) -> int:
    """Delete all archive records (other files are untouched); return how many."""
    root = _directory(directory)
    deleted = 0
    for record in list_records(directory=root):
        try:
            (root / record["name"]).unlink(missing_ok=True)
            deleted += 1
        except OSError as exc:
            logger.warning("Plan archive: could not delete %s: %s", record["name"], exc)
    return deleted


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def build_download_zip(days: int | None = None, directory: Path | None = None) -> Path:
    """Zip (stored, no recompression) the records plus ``manifest.json``.

    Raises ``FileNotFoundError`` when no record matches. The caller removes the file.
    """
    root = _directory(directory)
    records = list_records(days=days, directory=root)
    if not records:
        raise FileNotFoundError("The plan archive holds no records")

    fd, name = tempfile.mkstemp(dir=root, prefix=_DOWNLOAD_PREFIX, suffix=_DOWNLOAD_SUFFIX)
    os.close(fd)
    zip_path = Path(name)
    manifest = [
        {
            "name": r["name"],
            "time": r["time"].isoformat(),
            "outcome": r["outcome"],
            "size": r["size"],
        }
        for r in records
    ]
    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as bundle:
            for record in records:
                bundle.write(root / record["name"], arcname=record["name"])
            bundle.writestr(
                "manifest.json",
                json.dumps(manifest, indent=2),
            )
    except BaseException:
        with contextlib.suppress(OSError):
            zip_path.unlink(missing_ok=True)
        raise
    return zip_path
