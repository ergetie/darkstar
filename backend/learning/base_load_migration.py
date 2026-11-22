"""One-time flagging of historical ``slot_observations`` rows with an untrusted base load.

Sets ``quality_flags.base_load = {"reliable": false, "reasons": [...], "source": "migration"}``
without changing any column value or the schema:

* (a) Rows without ``quality_flags.recording`` (the marker of every row written by the
  current recorder or backfill; the old counter-based recorder wrote none) with
  ``load_kwh = 0`` and ``water_kwh > 0`` get ``legacy_counter_clamp``, and the slot that
  starts 15 minutes later gets ``legacy_counter_after_clamp``. No date is compared:
  installations switched recorders at different times.
* (b) Rows whose water component is ``disabled_zero`` while the current configuration
  lists a water heater with a power sensor get ``device_disabled_but_configured``.

Existing flag keys are preserved and reasons are unioned, so a second run changes nothing.
Completion is recorded in ``system_state`` (``STATE_KEY``), set in the same transaction as
the updates. The row counts per rule are logged.

Rollback: remove ``base_load`` from ``quality_flags`` where its ``source`` is ``migration``
(``json_remove(quality_flags, '$.base_load')``), then delete the ``system_state`` row.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from backend.measurement_provenance import (
    BASE_LOAD_DISABLED_CONFIGURED,
    BASE_LOAD_LEGACY_AFTER_CLAMP,
    BASE_LOAD_LEGACY_CLAMP,
    metadata_object,
)

logger = logging.getLogger("darkstar.learning.base_load_migration")

STATE_KEY = "base_load_integrity_v1"
MIGRATION_SOURCE = "migration"
SLOT = timedelta(minutes=15)
BATCH_SIZE = 1000


def _instant(raw: object) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo=UTC)


def _has_configured_water_sensor(config: dict[str, Any]) -> bool:
    heaters: Any = config.get("water_heaters")
    return isinstance(heaters, list) and any(
        isinstance(heater, dict) and cast("dict[str, Any]", heater).get("sensor")
        for heater in cast("list[Any]", heaters)
    )


def _add_reason(flags: dict[str, Any], reason: str) -> bool:
    """Union ``reason`` into ``flags['base_load']``; True when the flags changed."""
    existing = metadata_object(flags.get("base_load"))
    raw_reasons = existing.get("reasons")
    reasons = (
        [str(r) for r in cast("list[Any]", raw_reasons)] if isinstance(raw_reasons, list) else []
    )
    if reason in reasons and existing.get("reliable") is False:
        return False
    updated = dict(existing)
    updated["reliable"] = False
    updated["reasons"] = sorted({*reasons, reason})
    updated.setdefault("source", MIGRATION_SOURCE)
    flags["base_load"] = updated
    return True


def _is_zero_load_with_water(load_kwh: object, water_kwh: object) -> bool:
    return (
        isinstance(load_kwh, int | float)
        and isinstance(water_kwh, int | float)
        and load_kwh == 0
        and water_kwh > 0
    )


def flag_historical_base_load(db_path: str, config: dict[str, Any]) -> dict[str, int] | None:
    """Flag existing rows once. Returns the flagged-row counts per rule.

    None when already done or when the schema does not exist yet (fresh install).

    Counts: ``a`` (clamp rows), ``after_clamp`` (following slots), ``b`` (disabled but
    configured), ``skipped_unparseable`` (rows whose flags are not a JSON object).
    """
    configured_water = _has_configured_water_sensor(config)
    counts = {"a": 0, "after_clamp": 0, "b": 0, "skipped_unparseable": 0}

    conn = sqlite3.connect(db_path, timeout=30.0, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            tables = {
                name
                for (name,) in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name IN ('system_state', 'slot_observations')"
                )
            }
            if len(tables) < 2:
                # Fresh database without schema yet: nothing to flag, retried next start.
                conn.execute("ROLLBACK")
                logger.debug("Base-load integrity migration skipped: tables not created yet")
                return None

            done = conn.execute("SELECT 1 FROM system_state WHERE key = ?", (STATE_KEY,)).fetchone()
            if done:
                conn.execute("ROLLBACK")
                return None

            rows = conn.execute(
                "SELECT slot_start, load_kwh, water_kwh, quality_flags "
                "FROM slot_observations ORDER BY slot_start"
            ).fetchall()

            flags_by_slot: dict[str, dict[str, Any] | None] = {}
            for slot_start, _load, _water, raw in rows:
                if raw is None or (isinstance(raw, str) and not raw.strip()):
                    flags_by_slot[slot_start] = {}
                    continue
                try:
                    decoded = json.loads(raw)
                except (TypeError, ValueError):
                    decoded = None
                if isinstance(decoded, dict):
                    flags_by_slot[slot_start] = cast("dict[str, Any]", decoded)
                else:
                    flags_by_slot[slot_start] = None
                    counts["skipped_unparseable"] += 1
                    logger.warning(
                        "Skipping row %s: quality_flags is not a JSON object", slot_start
                    )

            slot_by_instant = {
                moment: slot_start
                for slot_start, *_ in rows
                if (moment := _instant(slot_start)) is not None
            }

            changed: set[str] = set()

            def apply(slot_start: str, reason: str, counter: str) -> None:
                flags = flags_by_slot.get(slot_start)
                if flags is not None and _add_reason(flags, reason):
                    changed.add(slot_start)
                    counts[counter] += 1

            for slot_start, load_kwh, water_kwh, _raw in rows:
                flags = flags_by_slot[slot_start]
                if flags is None:
                    continue
                if "recording" not in flags and _is_zero_load_with_water(load_kwh, water_kwh):
                    apply(slot_start, BASE_LOAD_LEGACY_CLAMP, "a")
                    moment = _instant(slot_start)
                    following = slot_by_instant.get(moment + SLOT) if moment else None
                    if following is not None:
                        apply(following, BASE_LOAD_LEGACY_AFTER_CLAMP, "after_clamp")
                if configured_water:
                    water = metadata_object(
                        metadata_object(
                            metadata_object(flags.get("recording")).get("components")
                        ).get("water")
                    )
                    if water.get("method") == "disabled_zero":
                        apply(slot_start, BASE_LOAD_DISABLED_CONFIGURED, "b")

            updates = [
                (json.dumps(flags_by_slot[slot_start], sort_keys=True), slot_start)
                for slot_start in sorted(changed)
            ]
            for offset in range(0, len(updates), BATCH_SIZE):
                conn.executemany(
                    "UPDATE slot_observations SET quality_flags = ? WHERE slot_start = ?",
                    updates[offset : offset + BATCH_SIZE],
                )
            conn.execute(
                "INSERT INTO system_state (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (STATE_KEY, json.dumps(counts, sort_keys=True), datetime.now(UTC).isoformat()),
            )
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()

    logger.info(
        "Base-load integrity migration flagged rows: a=%d after_clamp=%d b=%d "
        "(skipped unparseable=%d)",
        counts["a"],
        counts["after_clamp"],
        counts["b"],
        counts["skipped_unparseable"],
    )
    return counts
