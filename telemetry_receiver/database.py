"""SQLite storage and aggregate statistics for the standalone receiver."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Callable

BREAKDOWN_FIELDS = (
    "version",
    "release_channel",
    "installation_type",
    "architecture",
    "inverter_profile",
    "execution_mode",
)
METADATA_BREAKDOWN_FIELDS = tuple(field for field in BREAKDOWN_FIELDS if field != "execution_mode")
DB_BUSY_TIMEOUT_MS = 5_000
DB_CONCURRENCY = 4
DB_QUEUE_WAIT_SECONDS = 0.25
T = TypeVar("T")


class DatabaseBusyError(Exception):
    """All bounded SQLite worker slots are occupied."""


class TelemetryDatabase:
    """Run SQLite operations off-loop with a bounded number of workers."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._slots = asyncio.Semaphore(DB_CONCURRENCY)

    async def run(self, operation: Callable[[], T]) -> T:
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=DB_QUEUE_WAIT_SECONDS)
        except TimeoutError as exc:
            raise DatabaseBusyError from exc
        worker = asyncio.create_task(asyncio.to_thread(operation))

        def completed(task: asyncio.Task[T]) -> None:
            # Cancelling the caller cannot stop an already-running thread.
            # Keep its slot occupied until the actual operation has finished.
            self._slots.release()
            if not task.cancelled():
                task.exception()

        worker.add_done_callback(completed)
        return await asyncio.shield(worker)

    async def initialize(self) -> None:
        await self.run(self._initialize_sync)

    async def upsert(self, payload: dict[str, str], last_seen: datetime) -> None:
        await self.run(lambda: self._upsert_sync(payload, last_seen))

    async def collect_snapshot_and_cleanup(self, as_of: datetime) -> None:
        await self.run(lambda: self._collect_snapshot_and_cleanup_sync(as_of))

    async def stats(self, as_of: datetime) -> dict[str, object]:
        return await self.run(lambda: self._stats_sync(as_of))

    def _initialize_sync(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=DB_BUSY_TIMEOUT_MS / 1000)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS}")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS installations (
                    installation_id TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    release_channel TEXT NOT NULL,
                    installation_type TEXT NOT NULL,
                    architecture TEXT NOT NULL,
                    inverter_profile TEXT NOT NULL,
                    execution_mode TEXT NOT NULL DEFAULT 'unknown',
                    last_seen_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_installations_last_seen
                    ON installations(last_seen_utc);
                CREATE TABLE IF NOT EXISTS daily_snapshots (
                    sample_date_utc TEXT PRIMARY KEY,
                    sampled_at_utc TEXT NOT NULL,
                    active_7_days INTEGER NOT NULL,
                    active_30_days INTEGER NOT NULL,
                    breakdowns_7_days_json TEXT NOT NULL,
                    breakdowns_30_days_json TEXT NOT NULL,
                    execution_modes_7_days_json TEXT NOT NULL,
                    execution_modes_30_days_json TEXT NOT NULL
                );
                """
            )
            installation_columns = {
                str(row["name"]) for row in connection.execute("PRAGMA table_info(installations)")
            }
            if "execution_mode" not in installation_columns:
                connection.execute(
                    "ALTER TABLE installations ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'unknown'"
                )

            snapshot_columns = {
                str(row["name"]) for row in connection.execute("PRAGMA table_info(daily_snapshots)")
            }
            if "execution_modes_7_days_json" not in snapshot_columns:
                connection.execute(
                    "ALTER TABLE daily_snapshots ADD COLUMN execution_modes_7_days_json TEXT"
                )
            if "execution_modes_30_days_json" not in snapshot_columns:
                connection.execute(
                    "ALTER TABLE daily_snapshots ADD COLUMN execution_modes_30_days_json TEXT"
                )
            # Snapshots predating execution-mode reporting remain immutable in their
            # original fields. Their new mode dimensions describe the unknown state
            # at the time of sampling, based on the already-recorded totals.
            legacy_snapshots = connection.execute(
                """
                SELECT sample_date_utc, active_7_days, active_30_days,
                       execution_modes_7_days_json, execution_modes_30_days_json
                FROM daily_snapshots
                WHERE execution_modes_7_days_json IS NULL
                   OR execution_modes_30_days_json IS NULL
                """
            ).fetchall()
            for row in legacy_snapshots:
                mode_7 = row["execution_modes_7_days_json"]
                mode_30 = row["execution_modes_30_days_json"]
                connection.execute(
                    """
                    UPDATE daily_snapshots
                    SET execution_modes_7_days_json = COALESCE(?, execution_modes_7_days_json),
                        execution_modes_30_days_json = COALESCE(?, execution_modes_30_days_json)
                    WHERE sample_date_utc = ?
                    """,
                    (
                        mode_7 or _unknown_mode_breakdown(int(row["active_7_days"])),
                        mode_30 or _unknown_mode_breakdown(int(row["active_30_days"])),
                        row["sample_date_utc"],
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=DB_BUSY_TIMEOUT_MS / 1000)
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS}")
        return connection

    def _upsert_sync(self, payload: dict[str, str], last_seen: datetime) -> None:
        timestamp = _utc(last_seen).isoformat(timespec="microseconds")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO installations (
                    installation_id, version, release_channel, installation_type,
                    architecture, inverter_profile, execution_mode, last_seen_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(installation_id) DO UPDATE SET
                    version=excluded.version,
                    release_channel=excluded.release_channel,
                    installation_type=excluded.installation_type,
                    architecture=excluded.architecture,
                    inverter_profile=excluded.inverter_profile,
                    execution_mode=excluded.execution_mode,
                    last_seen_utc=excluded.last_seen_utc
                WHERE excluded.last_seen_utc >= installations.last_seen_utc
                """,
                (
                    payload["installation_id"],
                    payload["version"],
                    payload["release_channel"],
                    payload["installation_type"],
                    payload["architecture"],
                    payload["inverter_profile"],
                    payload.get("execution_mode", "unknown"),
                    timestamp,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _collect_snapshot_and_cleanup_sync(self, as_of: datetime) -> None:
        sample_time = _utc(as_of)
        sample_date = sample_time.date().isoformat()
        timestamp = sample_time.isoformat(timespec="microseconds")
        cutoff = (sample_time - timedelta(days=60)).isoformat(timespec="microseconds")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM installations WHERE last_seen_utc < ?", (cutoff,))
            active_7 = self._window(connection, sample_time, 7)
            active_30 = self._window(connection, sample_time, 30)
            connection.execute(
                """
                INSERT OR IGNORE INTO daily_snapshots (
                    sample_date_utc, sampled_at_utc, active_7_days, active_30_days,
                    breakdowns_7_days_json, breakdowns_30_days_json,
                    execution_modes_7_days_json, execution_modes_30_days_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sample_date,
                    timestamp,
                    active_7["total"],
                    active_30["total"],
                    json.dumps(_metadata_breakdowns(active_7["breakdowns"]), separators=(",", ":")),
                    json.dumps(
                        _metadata_breakdowns(active_30["breakdowns"]), separators=(",", ":")
                    ),
                    json.dumps(
                        _execution_mode_breakdown(active_7["breakdowns"]), separators=(",", ":")
                    ),
                    json.dumps(
                        _execution_mode_breakdown(active_30["breakdowns"]), separators=(",", ":")
                    ),
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _window(
        self, connection: sqlite3.Connection, as_of: datetime, days: int
    ) -> dict[str, object]:
        lower_bound = (as_of - timedelta(days=days)).isoformat(timespec="microseconds")
        upper_bound = as_of.isoformat(timespec="microseconds")
        where = "last_seen_utc >= ? AND last_seen_utc <= ?"
        total_row = connection.execute(
            f"SELECT COUNT(*) AS total FROM installations WHERE {where}",
            (lower_bound, upper_bound),
        ).fetchone()
        breakdowns: dict[str, dict[str, int]] = {}
        for field in BREAKDOWN_FIELDS:
            rows = connection.execute(
                f"SELECT {field}, COUNT(*) AS count FROM installations WHERE {where} GROUP BY {field}",
                (lower_bound, upper_bound),
            ).fetchall()
            breakdowns[field] = {str(row[field]): int(row["count"]) for row in rows}
        return {"total": int(total_row["total"]), "breakdowns": breakdowns}

    def _stats_sync(self, as_of: datetime) -> dict[str, object]:
        sample_time = _utc(as_of)
        connection = self._connect()
        try:
            # All totals, breakdowns and history must describe one consistent
            # SQLite snapshot even while other workers commit new pings.
            connection.execute("BEGIN")
            active_7 = self._window(connection, sample_time, 7)
            active_30 = self._window(connection, sample_time, 30)
            rows = connection.execute(
                """
                SELECT sample_date_utc, sampled_at_utc, active_7_days, active_30_days,
                       breakdowns_7_days_json, breakdowns_30_days_json,
                       execution_modes_7_days_json, execution_modes_30_days_json
                FROM daily_snapshots ORDER BY sample_date_utc
                """
            ).fetchall()
            history: list[dict[str, object]] = []
            for row in rows:
                breakdowns_7 = json.loads(str(row["breakdowns_7_days_json"]))
                breakdowns_30 = json.loads(str(row["breakdowns_30_days_json"]))
                breakdowns_7["execution_mode"] = json.loads(str(row["execution_modes_7_days_json"]))
                breakdowns_30["execution_mode"] = json.loads(
                    str(row["execution_modes_30_days_json"])
                )
                history.append(
                    {
                        "sample_date_utc": str(row["sample_date_utc"]),
                        "sampled_at_utc": str(row["sampled_at_utc"]),
                        "active_7_days": {
                            "total": int(row["active_7_days"]),
                            "breakdowns": breakdowns_7,
                        },
                        "active_30_days": {
                            "total": int(row["active_30_days"]),
                            "breakdowns": breakdowns_30,
                        },
                    }
                )
        finally:
            connection.close()
        return {
            "label": "Active reporting installations",
            "sample_date_utc": sample_time.date().isoformat(),
            "sampled_at_utc": sample_time.isoformat(timespec="microseconds"),
            "sample_is_partial": True,
            "active_7_days": active_7,
            "active_30_days": active_30,
            "history": history,
        }


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("receiver timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _unknown_mode_breakdown(total: int) -> str:
    return json.dumps({"unknown": total} if total else {}, separators=(",", ":"))


def _metadata_breakdowns(value: object) -> dict[str, dict[str, int]]:
    breakdowns = cast("dict[str, dict[str, int]]", value)
    return {field: breakdowns[field] for field in METADATA_BREAKDOWN_FIELDS}


def _execution_mode_breakdown(value: object) -> dict[str, int]:
    breakdowns = cast("dict[str, dict[str, int]]", value)
    return breakdowns["execution_mode"]
