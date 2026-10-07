"""Local, evidence-backed comparison-history annotations.

The CLI wrapper is explicit and offline. This module never discovers production
targets or connects to Home Assistant; it only operates on a caller-supplied SQLite
file and caller-supplied JSON manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from itertools import pairwise
from typing import TYPE_CHECKING, Any, cast

from backend.battery_comparison import RecordedObservation, calibration_eligible
from backend.measurement_provenance import (
    ENERGY_SEMANTICS,
    is_sha256,
    measurement_value_digest,
    metadata_object,
)

if TYPE_CHECKING:
    from pathlib import Path

MANIFEST_VERSION = 1
MEASUREMENT_COLUMNS = (
    "slot_start",
    "import_kwh",
    "export_kwh",
    "pv_kwh",
    "load_kwh",
    "water_kwh",
    "ev_charging_kwh",
    "batt_charge_kwh",
    "batt_discharge_kwh",
    "soc_start_percent",
    "soc_end_percent",
    "import_price_sek_kwh",
    "export_price_sek_kwh",
)
REQUIRED_METHODS = (
    "import",
    "export",
    "pv",
    "load",
    "water",
    "ev",
    "battery_charge",
    "battery_discharge",
)
LEGACY_METHODS = {"cumulative_meter_energy", "power_history_energy"}


class ManifestError(ValueError):
    """The manifest or target does not satisfy the annotation contract."""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _flags(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        raise ManifestError("malformed quality_flags cannot be safely annotated") from None
    if not isinstance(value, dict):
        raise ManifestError("quality_flags must be an object for safe annotation")
    return cast("dict[str, Any]", value)


def _utc_interval(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ManifestError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ManifestError(f"{label} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ManifestError(f"{label} must include a timezone offset")
    return parsed.astimezone(UTC)


def _digest_rows(rows: list[tuple[Any, ...]]) -> str:
    return _sha256(_canonical(rows))


def _metadata_preimage(rows: list[tuple[Any, ...]]) -> str:
    relevant: list[tuple[Any, ...]] = []
    for row in rows:
        flags = _flags(row[-1])
        relevant.append(
            (
                row[0],
                flags.get("source"),
                flags.get("exclude") is True,
                flags.get("recording"),
            )
        )
    return _digest_rows(relevant)


def database_identity(connection: sqlite3.Connection, database_path: Path) -> dict[str, Any]:
    count = int(connection.execute("SELECT COUNT(*) FROM slot_observations").fetchone()[0])
    rows = connection.execute(
        "SELECT " + ",".join(MEASUREMENT_COLUMNS) + " FROM slot_observations ORDER BY slot_start"
    ).fetchall()
    return {
        "path_sha256": _sha256(str(database_path.resolve()).encode()),
        "row_count": count,
        "measurement_digest": _digest_rows(rows),
        "measurement_columns_version": 1,
    }


def _interval_rows(
    connection: sqlite3.Connection, interval: dict[str, Any]
) -> list[tuple[Any, ...]]:
    start = _utc_interval(interval.get("start"), "interval.start")
    end = _utc_interval(interval.get("end"), "interval.end")
    if start >= end:
        raise ManifestError("interval start must be before interval end")
    rows = connection.execute(
        "SELECT " + ",".join(MEASUREMENT_COLUMNS) + ",quality_flags FROM slot_observations"
    ).fetchall()
    selected: list[tuple[Any, ...]] = []
    for row in rows:
        try:
            slot = _utc_interval(str(row[0]), "stored slot_start")
        except ManifestError:
            continue
        if start <= slot < end:
            selected.append(row)
    selected.sort(key=lambda row: _utc_interval(str(row[0]), "stored slot_start"))
    return selected


def _validate_evidence(interval: dict[str, Any], manifest_path: Path) -> str:
    evidence = interval.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ManifestError("each interval requires at least one evidence file")
    identities: list[dict[str, str]] = []
    for raw_item in cast("list[Any]", evidence):
        item = metadata_object(raw_item)
        if not isinstance(raw_item, dict):
            raise ManifestError("evidence items must be objects")
        relative = item.get("path")
        expected = item.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str) or len(expected) != 64:
            raise ManifestError("evidence items require a local path and SHA-256 digest")
        evidence_path = (manifest_path.parent / relative).resolve()
        if not evidence_path.is_file():
            raise ManifestError(f"evidence file is missing: {relative}")
        actual = _sha256(evidence_path.read_bytes())
        if actual != expected.lower():
            raise ManifestError(f"evidence digest does not match: {relative}")
        identities.append({"sha256": actual})
    return _sha256(_canonical(sorted(identities, key=lambda item: item["sha256"])))


def validate_manifest(
    manifest: Any,
    manifest_path: Path,
    connection: sqlite3.Connection,
    database_path: Path,
    *,
    require_identity: bool = False,
    require_preimage: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    manifest = metadata_object(manifest)
    if type(manifest.get("version")) is not int or manifest.get("version") != MANIFEST_VERSION:
        raise ManifestError("manifest version must be 1")
    actual_identity = database_identity(connection, database_path)
    declared_identity = manifest.get("database_identity")
    if declared_identity is None and not require_identity:
        pass
    elif declared_identity != actual_identity:
        raise ManifestError("manifest database identity is stale or targets another database")
    intervals = manifest.get("intervals")
    if not isinstance(intervals, list) or not intervals:
        raise ManifestError("manifest must contain at least one interval")
    normalized: list[tuple[datetime, datetime, dict[str, Any]]] = []
    errors: list[str] = []
    ids: set[str] = set()
    for raw_interval in cast("list[Any]", intervals):
        interval = metadata_object(raw_interval)
        if not isinstance(raw_interval, dict):
            raise ManifestError("interval entries must be objects")
        interval_id = interval.get("id")
        if not isinstance(interval_id, str) or not interval_id.strip() or interval_id in ids:
            raise ManifestError("interval ids must be unique non-empty strings")
        ids.add(interval_id)
        start = _utc_interval(interval.get("start"), "interval.start")
        end = _utc_interval(interval.get("end"), "interval.end")
        if start >= end:
            raise ManifestError(f"interval {interval_id} has an empty or reversed range")
        disposition = interval.get("disposition")
        if not isinstance(disposition, str) or disposition not in {
            "exclude_from_comparison",
            "verified_measured_energy",
        }:
            raise ManifestError(f"interval {interval_id} has an unsupported disposition")
        if require_preimage and interval.get("preimage_digest") is None:
            raise ManifestError(f"interval {interval_id} requires a preimage_digest from dry run")
        if require_preimage and interval.get("metadata_preimage_digest") is None:
            raise ManifestError(
                f"interval {interval_id} requires metadata_preimage_digest from dry run"
            )
        evidence_digest = _validate_evidence(interval, manifest_path)
        if disposition == "verified_measured_energy":
            if interval.get("semantics") != ENERGY_SEMANTICS:
                raise ManifestError(f"interval {interval_id} declares unsupported semantics")
            boundary = interval.get("boundary_fingerprint")
            if not is_sha256(boundary):
                raise ManifestError(f"interval {interval_id} requires a boundary fingerprint")
            methods = metadata_object(interval.get("methods"))
            if set(methods) != set(REQUIRED_METHODS) or any(
                not isinstance(methods.get(key), str) or methods.get(key) not in LEGACY_METHODS
                for key in REQUIRED_METHODS
            ):
                raise ManifestError(
                    f"interval {interval_id} requires supported method for every component"
                )
            if (
                interval.get("fallback_treatment")
                != "all-components-full-slot-measured-no-snapshot-fallback"
            ):
                raise ManifestError(f"interval {interval_id} does not establish fallback treatment")
            if interval.get("soc_method") != "live_soc_history":
                raise ManifestError(
                    f"interval {interval_id} does not establish non-cached SoC history"
                )
            claims = interval.get("evidence_scope")
            required_claims = {
                "configured_paths",
                "full_slot_energy",
                "boundary_compatibility",
                "fallback_treatment",
                "live_soc_history",
            }
            if (
                not isinstance(claims, list)
                or not all(isinstance(claim, str) for claim in cast("list[Any]", claims))
                or not required_claims.issubset(set(cast("list[str]", claims)))
            ):
                raise ManifestError(
                    f"interval {interval_id} lacks required evidence scope declarations"
                )
        rows = _interval_rows(connection, interval)
        measurement_rows = [tuple(row[:-1]) for row in rows]
        current_digest = _digest_rows(measurement_rows)
        if (
            interval.get("preimage_digest") is not None
            and current_digest != interval["preimage_digest"]
        ):
            raise ManifestError(f"interval {interval_id} measurement preimage is stale")
        if not rows:
            raise ManifestError(f"interval {interval_id} affects no observations")
        metadata_digest = _metadata_preimage(rows)
        if (
            interval.get("metadata_preimage_digest") is not None
            and metadata_digest != interval["metadata_preimage_digest"]
        ):
            raise ManifestError(f"interval {interval_id} comparison metadata preimage is stale")
        for row in rows:
            flags = _flags(row[-1])
            expected_keys = _expected_comparison_keys(
                item=interval, evidence_digest=evidence_digest, row=row
            )
            current_keys = _comparison_keys(flags)
            if current_keys and current_keys != expected_keys:
                errors.append(
                    f"{interval_id}: existing comparison annotation conflicts with this manifest"
                )
            if disposition == "verified_measured_energy":
                if flags.get("source") == "backfill":
                    errors.append(f"{interval_id}: backfill-owned row cannot be promoted")
                if "recording" in flags:
                    errors.append(f"{interval_id}: observed modern provenance cannot be replaced")
                comparison = metadata_object(flags.get("comparison_history"))
                if comparison.get("disposition") == "exclude_from_comparison":
                    errors.append(f"{interval_id}: explicitly excluded row cannot be included")
        item = dict(interval)
        item["preimage_digest"] = current_digest
        item["metadata_preimage_digest"] = metadata_digest
        item["evidence_digest"] = evidence_digest
        item["rows"] = rows
        item["measurement_rows"] = measurement_rows
        normalized.append((start, end, item))
    normalized.sort(key=lambda entry: entry[0])
    for previous, current in pairwise(normalized):
        if current[0] < previous[1]:
            raise ManifestError(f"intervals overlap: {previous[2]['id']} and {current[2]['id']}")
    return actual_identity, [entry[2] for entry in normalized], errors


def _classify(flags: dict[str, Any]) -> str:
    comparison = metadata_object(flags.get("comparison_history"))
    if comparison.get("disposition") == "exclude_from_comparison":
        return "excluded"
    if isinstance(flags.get("recording"), dict):
        return "observed_provenance"
    if isinstance(flags.get("legacy_attestation"), dict):
        return "previous_attestation"
    if flags.get("source") == "backfill":
        return "backfill"
    return "unknown"


def dry_run_report(
    manifest: Any, manifest_path: Path, connection: sqlite3.Connection, database_path: Path
) -> dict[str, Any]:
    identity, intervals, conflicts = validate_manifest(
        manifest, manifest_path, connection, database_path
    )
    summaries: list[dict[str, Any]] = []
    for interval in intervals:
        counts: dict[str, int] = {}
        for row in interval["rows"]:
            label = _classify(_flags(row[-1]))
            counts[label] = counts.get(label, 0) + 1
        summaries.append(
            {
                "id": interval["id"],
                "disposition": interval["disposition"],
                "affected_count": len(interval["rows"]),
                "preimage_digest": interval["preimage_digest"],
                "metadata_preimage_digest": interval["metadata_preimage_digest"],
                "current_classifications": counts,
                "expected_eligible_count": (
                    sum(
                        calibration_eligible(
                            _row_observation(
                                row,
                                _write_comparison_keys(
                                    _flags(row[-1]),
                                    _expected_comparison_keys(
                                        interval, interval["evidence_digest"], row
                                    ),
                                ),
                            )
                        )
                        for row in interval["rows"]
                    )
                    if interval["disposition"] == "verified_measured_energy" and not conflicts
                    else 0
                ),
                "evidence_digest": interval["evidence_digest"],
            }
        )
    return {
        "mode": "dry_run",
        "database_identity": identity,
        "intervals": summaries,
        "conflicts": conflicts,
    }


def _comparison_keys(flags: dict[str, Any]) -> dict[str, Any]:
    return {key: flags[key] for key in ("comparison_history", "legacy_attestation") if key in flags}


def _expected_comparison_keys(
    item: dict[str, Any], evidence_digest: str, row: tuple[Any, ...]
) -> dict[str, Any]:
    if item["disposition"] == "exclude_from_comparison":
        return {
            "comparison_history": {
                "schema_version": 1,
                "disposition": "exclude_from_comparison",
                "interval_id": item["id"],
                "evidence_digest": evidence_digest,
            }
        }
    return {
        "comparison_history": {
            "schema_version": 1,
            "disposition": "verified_measured_energy",
            "interval_id": item["id"],
            "evidence_digest": evidence_digest,
        },
        "legacy_attestation": {
            "schema_version": 1,
            "disposition": "verified_measured_energy",
            "semantics": item["semantics"],
            "boundary_fingerprint": item["boundary_fingerprint"],
            "methods": item["methods"],
            "soc_method": item["soc_method"],
            "evidence_digest": evidence_digest,
            "affected_measurement_digest": _row_value_digest(row),
        },
    }


def _write_comparison_keys(flags: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    if set(values) - {"comparison_history", "legacy_attestation"}:
        raise ManifestError("audit contains keys outside comparison metadata ownership")
    result = dict(flags)
    for key in ("comparison_history", "legacy_attestation"):
        result.pop(key, None)
    result.update(values)
    return result


def _row_value_digest(row: tuple[Any, ...]) -> str:
    return measurement_value_digest(tuple(row[: len(MEASUREMENT_COLUMNS)]))


def apply_manifest(
    manifest: Any,
    manifest_path: Path,
    connection: sqlite3.Connection,
    database_path: Path,
    audit_path: Path,
) -> tuple[dict[str, Any], Path]:
    identity, _intervals, conflicts = validate_manifest(
        manifest,
        manifest_path,
        connection,
        database_path,
        require_identity=True,
        require_preimage=True,
    )
    if conflicts:
        raise ManifestError("; ".join(sorted(set(conflicts))))
    protected_paths = {database_path.resolve(), manifest_path.resolve()}
    protected_paths.update(
        (manifest_path.parent / evidence["path"]).resolve()
        for interval in manifest["intervals"]
        for evidence in interval.get("evidence", [])
    )
    audit_path = audit_path.resolve()
    if audit_path in protected_paths or audit_path.exists():
        raise ManifestError("audit output path already exists or collides with an input file")
    if not audit_path.parent.is_dir():
        raise ManifestError("audit output directory does not exist")
    backup_path = database_path.with_name(
        database_path.name
        + f".comparison-history-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex}.bak"
    )
    if backup_path.resolve() in protected_paths or backup_path.exists():
        raise ManifestError("backup path collides with an input file")
    backup_descriptor = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(backup_descriptor)
    with sqlite3.connect(backup_path) as backup:
        connection.backup(backup)
    audit_rows: list[dict[str, Any]] = []
    connection.execute("BEGIN IMMEDIATE")
    audit_created = False
    try:
        current_identity, current_intervals, current_conflicts = validate_manifest(
            manifest,
            manifest_path,
            connection,
            database_path,
            require_identity=True,
            require_preimage=True,
        )
        if current_identity != identity or current_conflicts:
            raise ManifestError("database metadata changed after backup; no annotation was applied")
        for interval in current_intervals:
            # Reread under the reserved write lock and compare interval preimage.
            current_rows = _interval_rows(connection, interval)
            current_digest = _digest_rows([tuple(row[:-1]) for row in current_rows])
            if current_digest != interval["preimage_digest"]:
                raise ManifestError(f"interval {interval['id']} changed after dry run")
            if _metadata_preimage(current_rows) != interval["metadata_preimage_digest"]:
                raise ManifestError(
                    f"interval {interval['id']} comparison metadata changed after dry run"
                )
            for row in current_rows:
                slot_start = str(row[0])
                flags = _flags(row[-1])
                expected_keys = _expected_comparison_keys(
                    interval, interval["evidence_digest"], row
                )
                pre_keys = _comparison_keys(flags)
                if pre_keys != expected_keys:
                    new_flags = _write_comparison_keys(flags, expected_keys)
                    connection.execute(
                        "UPDATE slot_observations SET quality_flags = ? WHERE slot_start = ?",
                        (json.dumps(new_flags, sort_keys=True), slot_start),
                    )
                audit_rows.append(
                    {
                        "slot_start": slot_start,
                        "measurement_digest": _row_value_digest(row),
                        "pre_comparison_keys": pre_keys,
                        "post_comparison_keys": expected_keys,
                    }
                )
        audit = {
            "version": 1,
            "database_path_sha256": identity["path_sha256"],
            "manifest_digest": _sha256(_canonical(manifest)),
            "evidence_digests": sorted({item["evidence_digest"] for item in current_intervals}),
            "rows": audit_rows,
        }
        # Write and fsync a complete audit before the SQLite commit. If writing
        # fails, the transaction rolls back; if commit fails, the audit is removed.
        with audit_path.open("x", encoding="utf-8") as audit_file:
            audit_created = True
            audit_file.write(json.dumps(audit, indent=2, sort_keys=True) + "\n")
            audit_file.flush()
            os.fsync(audit_file.fileno())
        directory_descriptor = os.open(audit_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        connection.commit()
    except Exception:
        connection.rollback()
        if audit_created:
            audit_path.unlink(missing_ok=True)
        raise
    return {
        "mode": "apply",
        "updated_count": len(audit_rows),
        "backup_path": str(backup_path),
        "audit_path": str(audit_path),
    }, backup_path


def undo_audit(audit: Any, connection: sqlite3.Connection, database_path: Path) -> dict[str, Any]:
    audit = metadata_object(audit)
    if audit.get("version") != 1 or not isinstance(audit.get("rows"), list):
        raise ManifestError("undo audit version or rows are invalid")
    path_hash = _sha256(str(database_path.resolve()).encode())
    if audit.get("database_path_sha256") != path_hash:
        raise ManifestError("undo audit targets another database")
    connection.execute("BEGIN IMMEDIATE")
    restored = 0
    try:
        for raw_item in cast("list[Any]", audit["rows"]):
            item = metadata_object(raw_item)
            slot_start = item.get("slot_start")
            if not isinstance(slot_start, str):
                raise ManifestError("undo audit contains an invalid slot identity")
            row = connection.execute(
                "SELECT "
                + ",".join(MEASUREMENT_COLUMNS)
                + ",quality_flags FROM slot_observations WHERE slot_start = ?",
                (slot_start,),
            ).fetchone()
            if row is None or _row_value_digest(row) != item.get("measurement_digest"):
                raise ManifestError(f"measurement changed since annotation: {slot_start}")
            flags = _flags(row[-1])
            if _comparison_keys(flags) != item.get("post_comparison_keys"):
                raise ManifestError(f"comparison metadata changed since annotation: {slot_start}")
            preimage = item.get("pre_comparison_keys")
            if not isinstance(preimage, dict):
                raise ManifestError("undo audit contains an invalid comparison preimage")
            restored_flags = _write_comparison_keys(flags, cast("dict[str, Any]", preimage))
            connection.execute(
                "UPDATE slot_observations SET quality_flags = ? WHERE slot_start = ?",
                (json.dumps(restored_flags, sort_keys=True), slot_start),
            )
            restored += 1
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return {"mode": "undo", "restored_count": restored}


def _row_observation(row: tuple[Any, ...], flags: dict[str, Any]) -> RecordedObservation:
    return RecordedObservation(
        start=_utc_interval(str(row[0]), "stored slot_start"),
        import_kwh=row[1],
        export_kwh=row[2],
        pv_kwh=row[3],
        load_kwh=row[4],
        water_kwh=row[5],
        ev_kwh=row[6],
        charge_kwh=row[7],
        discharge_kwh=row[8],
        soc_start_percent=row[9],
        soc_end_percent=row[10],
        import_price=row[11],
        export_price=row[12],
        quality_flags=flags,
    )
