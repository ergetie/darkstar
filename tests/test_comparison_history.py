from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from backend.comparison_history import (
    ManifestError,
    apply_manifest,
    dry_run_report,
    undo_audit,
)
from backend.measurement_provenance import ENERGY_SEMANTICS

if TYPE_CHECKING:
    from pathlib import Path

COLUMNS = (
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


def create_database(path: Path, flags: dict | None = None) -> tuple[sqlite3.Connection, list[str]]:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE slot_observations (slot_start TEXT PRIMARY KEY, import_kwh REAL, "
        "export_kwh REAL, pv_kwh REAL, load_kwh REAL, water_kwh REAL, ev_charging_kwh REAL, "
        "batt_charge_kwh REAL, batt_discharge_kwh REAL, soc_start_percent REAL, "
        "soc_end_percent REAL, import_price_sek_kwh REAL, export_price_sek_kwh REAL, quality_flags TEXT)"
    )
    starts = []
    start = datetime(2026, 10, 1, tzinfo=UTC)
    for index in range(2):
        slot = (start + timedelta(minutes=15 * index)).isoformat()
        starts.append(slot)
        values = [slot, 0.2, 0.0, 0.3, 0.2, 0.0, 0.0, 0.1, 0.0, 50.0, 50.0, 1.0, 0.5]
        connection.execute(
            f"INSERT INTO slot_observations ({','.join(COLUMNS)}, quality_flags) VALUES ({','.join('?' for _ in range(len(COLUMNS) + 1))})",
            (*values, json.dumps(flags or {"source": "recorder", "custom": {"keep": True}})),
        )
    connection.commit()
    return connection, starts


def make_manifest(
    connection: sqlite3.Connection,
    database: Path,
    directory: Path,
    disposition: str = "exclude_from_comparison",
) -> tuple[dict, Path]:
    evidence_path = directory / "evidence.txt"
    evidence_path.write_text("reviewed local evidence\n", encoding="utf-8")
    evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    start = "2026-10-01T00:00:00+00:00"
    end = "2026-10-01T00:30:00+00:00"
    manifest = {
        "version": 1,
        "intervals": [
            {
                "id": "interval-a",
                "start": start,
                "end": end,
                "disposition": disposition,
                "evidence": [{"path": evidence_path.name, "sha256": evidence_digest}],
            }
        ],
    }
    if disposition == "verified_measured_energy":
        interval = manifest["intervals"][0]
        interval.update(
            {
                "semantics": ENERGY_SEMANTICS,
                "boundary_fingerprint": "a" * 64,
                "methods": dict.fromkeys(
                    (
                        "import",
                        "export",
                        "pv",
                        "load",
                        "water",
                        "ev",
                        "battery_charge",
                        "battery_discharge",
                    ),
                    "cumulative_meter_energy",
                ),
                "fallback_treatment": "all-components-full-slot-measured-no-snapshot-fallback",
                "soc_method": "live_soc_history",
                "evidence_scope": [
                    "configured_paths",
                    "full_slot_energy",
                    "boundary_compatibility",
                    "fallback_treatment",
                    "live_soc_history",
                ],
            }
        )
    return manifest, directory / "manifest.json"


def reviewed_manifest(
    connection: sqlite3.Connection,
    database: Path,
    directory: Path,
    disposition: str = "exclude_from_comparison",
) -> tuple[dict, Path]:
    manifest, path = make_manifest(connection, database, directory, disposition)
    first = dry_run_report(manifest, path, connection, database)
    manifest["database_identity"] = first["database_identity"]
    manifest["intervals"][0]["preimage_digest"] = first["intervals"][0]["preimage_digest"]
    manifest["intervals"][0]["metadata_preimage_digest"] = first["intervals"][0][
        "metadata_preimage_digest"
    ]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest, path


def measurement_values(connection: sqlite3.Connection) -> list[tuple]:
    return connection.execute(
        f"SELECT {','.join(COLUMNS)} FROM slot_observations ORDER BY slot_start"
    ).fetchall()


def test_dry_run_reports_identity_and_does_not_mutate_database(tmp_path):
    database = tmp_path / "local.sqlite"
    connection, _ = create_database(database)
    before_values = measurement_values(connection)
    before_flags = connection.execute(
        "SELECT quality_flags FROM slot_observations ORDER BY slot_start"
    ).fetchall()
    manifest, manifest_path = make_manifest(connection, database, tmp_path)
    report = dry_run_report(manifest, manifest_path, connection, database)
    after_flags = connection.execute(
        "SELECT quality_flags FROM slot_observations ORDER BY slot_start"
    ).fetchall()
    assert report["mode"] == "dry_run"
    assert report["intervals"][0]["affected_count"] == 2
    assert len(report["intervals"][0]["preimage_digest"]) == 64
    assert measurement_values(connection) == before_values
    assert after_flags == before_flags
    connection.close()


def test_apply_is_metadata_only_idempotent_and_undo_preserves_unrelated_flags(tmp_path):
    database = tmp_path / "local.sqlite"
    connection, _ = create_database(database)
    before_values = measurement_values(connection)
    manifest, manifest_path = reviewed_manifest(connection, database, tmp_path)
    audit_path = tmp_path / "audit.json"
    report, backup_path = apply_manifest(manifest, manifest_path, connection, database, audit_path)
    assert backup_path.exists()
    assert report["updated_count"] == 2
    assert measurement_values(connection) == before_values
    flags = json.loads(
        connection.execute("SELECT quality_flags FROM slot_observations LIMIT 1").fetchone()[0]
    )
    assert flags["custom"] == {"keep": True}
    assert flags["comparison_history"]["disposition"] == "exclude_from_comparison"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    second_audit = tmp_path / "second-audit.json"
    apply_manifest(manifest, manifest_path, connection, database, second_audit)
    assert (
        json.loads(
            connection.execute("SELECT quality_flags FROM slot_observations LIMIT 1").fetchone()[0]
        )
        == flags
    )
    undo_audit(audit, connection, database)
    restored = json.loads(
        connection.execute("SELECT quality_flags FROM slot_observations LIMIT 1").fetchone()[0]
    )
    assert restored == {"source": "recorder", "custom": {"keep": True}}
    assert measurement_values(connection) == before_values
    connection.close()


def test_apply_and_undo_inclusion_write_distinct_evidence_backed_attestation(tmp_path):
    database = tmp_path / "local.sqlite"
    connection, _ = create_database(database)
    manifest, manifest_path = reviewed_manifest(
        connection, database, tmp_path, "verified_measured_energy"
    )
    audit_path = tmp_path / "audit.json"
    apply_manifest(manifest, manifest_path, connection, database, audit_path)
    flags = json.loads(
        connection.execute("SELECT quality_flags FROM slot_observations LIMIT 1").fetchone()[0]
    )
    assert "recording" not in flags
    assert flags["legacy_attestation"]["soc_method"] == "live_soc_history"
    assert flags["legacy_attestation"]["boundary_fingerprint"] == "a" * 64
    undo_audit(json.loads(audit_path.read_text()), connection, database)
    flags = json.loads(
        connection.execute("SELECT quality_flags FROM slot_observations LIMIT 1").fetchone()[0]
    )
    assert "legacy_attestation" not in flags
    connection.close()


def test_manifest_rejects_bad_evidence_wrong_database_overlap_and_stale_measurements(tmp_path):
    database = tmp_path / "local.sqlite"
    connection, _ = create_database(database)
    manifest, manifest_path = reviewed_manifest(connection, database, tmp_path)
    manifest["intervals"][0]["evidence"][0]["sha256"] = "0" * 64
    with pytest.raises(ManifestError, match="evidence digest"):
        dry_run_report(manifest, manifest_path, connection, database)
    manifest, manifest_path = reviewed_manifest(connection, database, tmp_path)
    manifest["database_identity"]["path_sha256"] = "f" * 64
    with pytest.raises(ManifestError, match="another database"):
        apply_manifest(manifest, manifest_path, connection, database, tmp_path / "audit.json")
    manifest, manifest_path = reviewed_manifest(connection, database, tmp_path)
    overlap = dict(manifest["intervals"][0])
    overlap["id"] = "interval-b"
    manifest["intervals"].append(overlap)
    with pytest.raises(ManifestError, match="overlap"):
        dry_run_report(manifest, manifest_path, connection, database)
    manifest, manifest_path = reviewed_manifest(connection, database, tmp_path)
    connection.execute(
        "UPDATE slot_observations SET pv_kwh = 9 WHERE slot_start = ?",
        ("2026-10-01T00:00:00+00:00",),
    )
    connection.commit()
    with pytest.raises(ManifestError, match="identity is stale"):
        apply_manifest(manifest, manifest_path, connection, database, tmp_path / "audit.json")
    connection.close()


def test_inclusion_rejects_backfill_or_observed_modern_provenance(tmp_path):
    database = tmp_path / "local.sqlite"
    connection, _ = create_database(database, {"source": "backfill"})
    manifest, manifest_path = reviewed_manifest(
        connection, database, tmp_path, "verified_measured_energy"
    )
    report = dry_run_report(manifest, manifest_path, connection, database)
    manifest["database_identity"] = report["database_identity"]
    manifest["intervals"][0]["preimage_digest"] = report["intervals"][0]["preimage_digest"]
    with pytest.raises(ManifestError, match="backfill-owned"):
        apply_manifest(manifest, manifest_path, connection, database, tmp_path / "audit.json")
    connection.close()


def test_transaction_failure_rolls_back_all_annotation_updates(tmp_path):
    database = tmp_path / "local.sqlite"
    connection, _ = create_database(database)
    manifest, manifest_path = reviewed_manifest(connection, database, tmp_path)
    before = connection.execute(
        "SELECT quality_flags FROM slot_observations ORDER BY slot_start"
    ).fetchall()
    connection.execute(
        "CREATE TRIGGER fail_annotation BEFORE UPDATE OF quality_flags ON slot_observations "
        "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
    )
    connection.commit()
    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        apply_manifest(manifest, manifest_path, connection, database, tmp_path / "audit.json")
    after = connection.execute(
        "SELECT quality_flags FROM slot_observations ORDER BY slot_start"
    ).fetchall()
    assert after == before
    connection.close()


def test_undo_refuses_measurement_changes_after_annotation(tmp_path):
    database = tmp_path / "local.sqlite"
    connection, _ = create_database(database)
    manifest, manifest_path = reviewed_manifest(connection, database, tmp_path)
    audit_path = tmp_path / "audit.json"
    apply_manifest(manifest, manifest_path, connection, database, audit_path)
    connection.execute(
        "UPDATE slot_observations SET load_kwh = 0.9 WHERE slot_start = ?",
        ("2026-10-01T00:00:00+00:00",),
    )
    connection.commit()
    with pytest.raises(ManifestError, match="measurement changed"):
        undo_audit(json.loads(audit_path.read_text()), connection, database)
    connection.close()


@pytest.mark.parametrize(
    "column,value", [("pv_kwh", -1), ("soc_end_percent", 101), ("export_price_sek_kwh", None)]
)
def test_dry_run_eligibility_respects_numeric_checks(tmp_path, column, value):
    database = tmp_path / "local.sqlite"
    connection, starts = create_database(database)
    connection.execute(
        f"UPDATE slot_observations SET {column} = ? WHERE slot_start = ?", (value, starts[0])
    )
    connection.commit()
    manifest, path = make_manifest(connection, database, tmp_path, "verified_measured_energy")
    report = dry_run_report(manifest, path, connection, database)
    assert report["intervals"][0]["affected_count"] == 2
    assert report["intervals"][0]["expected_eligible_count"] == 1
    connection.close()


@pytest.mark.parametrize("raw", ["opaque flag text", "[1,2]", "null"])
def test_malformed_metadata_is_never_erased_by_annotation(tmp_path, raw):
    database = tmp_path / "local.sqlite"
    connection, _ = create_database(database)
    connection.execute("UPDATE slot_observations SET quality_flags = ?", (raw,))
    connection.commit()
    manifest, path = make_manifest(connection, database, tmp_path)
    with pytest.raises(ManifestError, match="quality_flags"):
        dry_run_report(manifest, path, connection, database)
    assert connection.execute(
        "SELECT DISTINCT quality_flags FROM slot_observations"
    ).fetchall() == [(raw,)]
    connection.close()


def test_undo_retains_later_unrelated_flags_and_rejects_outside_owned_keys(tmp_path):
    database = tmp_path / "local.sqlite"
    connection, starts = create_database(database)
    manifest, path = reviewed_manifest(connection, database, tmp_path)
    audit_path = tmp_path / "audit.json"
    apply_manifest(manifest, path, connection, database, audit_path)
    flags = json.loads(
        connection.execute("SELECT quality_flags FROM slot_observations LIMIT 1").fetchone()[0]
    )
    flags["later_note"] = "retain me"
    connection.execute(
        "UPDATE slot_observations SET quality_flags=? WHERE slot_start=?",
        (json.dumps(flags), starts[0]),
    )
    connection.commit()
    audit = json.loads(audit_path.read_text())
    audit["rows"][0]["pre_comparison_keys"]["source"] = "backfill"
    with pytest.raises(ManifestError, match="outside comparison"):
        undo_audit(audit, connection, database)
    audit["rows"][0]["pre_comparison_keys"].pop("source")
    undo_audit(audit, connection, database)
    restored = json.loads(
        connection.execute(
            "SELECT quality_flags FROM slot_observations WHERE slot_start=?", (starts[0],)
        ).fetchone()[0]
    )
    assert restored["later_note"] == "retain me"
    assert restored["source"] == "recorder"
    connection.close()


@pytest.mark.parametrize("claim", ["fallback_treatment", "soc_method", "evidence_scope"])
def test_inclusion_requires_every_evidence_claim(tmp_path, claim):
    database = tmp_path / "local.sqlite"
    connection, _ = create_database(database)
    manifest, path = make_manifest(connection, database, tmp_path, "verified_measured_energy")
    manifest["intervals"][0].pop(claim)
    with pytest.raises(ManifestError):
        dry_run_report(manifest, path, connection, database)
    connection.close()


def test_annotation_rechecks_ownership_after_backup_under_write_lock(tmp_path):
    database = tmp_path / "local.sqlite"
    connection, _ = create_database(database)
    manifest, path = reviewed_manifest(connection, database, tmp_path, "verified_measured_energy")
    connection.close()

    class ConcurrentOwnerChange(sqlite3.Connection):
        def backup(self, target, **kwargs):
            super().backup(target, **kwargs)
            with sqlite3.connect(database) as other:
                other.execute(
                    "UPDATE slot_observations SET quality_flags=?",
                    (json.dumps({"source": "backfill", "custom": {"keep": True}}),),
                )

    connection = sqlite3.connect(database, factory=ConcurrentOwnerChange)
    with pytest.raises(ManifestError, match="metadata preimage is stale"):
        apply_manifest(manifest, path, connection, database, tmp_path / "audit.json")
    flags = [
        json.loads(row[0])
        for row in connection.execute("SELECT quality_flags FROM slot_observations")
    ]
    assert all(flag["source"] == "backfill" and "legacy_attestation" not in flag for flag in flags)
    assert not (tmp_path / "audit.json").exists()
    connection.close()


def test_failed_audit_durability_rolls_back_and_removes_partial_output(tmp_path, monkeypatch):
    from backend import comparison_history

    database = tmp_path / "local.sqlite"
    connection, _ = create_database(database)
    manifest, path = reviewed_manifest(connection, database, tmp_path)
    before = connection.execute("SELECT quality_flags FROM slot_observations").fetchall()

    def fail(_descriptor):
        raise OSError("injected audit durability failure")

    monkeypatch.setattr(comparison_history.os, "fsync", fail)
    with pytest.raises(OSError, match="audit durability"):
        apply_manifest(manifest, path, connection, database, tmp_path / "audit.json")
    assert connection.execute("SELECT quality_flags FROM slot_observations").fetchall() == before
    assert not (tmp_path / "audit.json").exists()
    connection.close()


@pytest.mark.asyncio
async def test_real_wal_annotation_undo_and_numeric_correction_change_cache_identity(tmp_path):
    from types import SimpleNamespace

    from backend.api.routers import energy
    from backend.baseline import BaselineBattery
    from backend.comparison_history import _row_observation

    database = tmp_path / "history-wal.db"
    connection, _starts = create_database(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA wal_autocheckpoint=0")
    manifest, manifest_path = reviewed_manifest(
        connection, database, tmp_path, "verified_measured_energy"
    )
    initial_stat = database.stat()

    def observations():
        return [
            _row_observation(row, json.loads(row[-1]))
            for row in connection.execute(
                "SELECT "
                + ",".join(COLUMNS)
                + ",quality_flags FROM slot_observations ORDER BY slot_start"
            ).fetchall()
        ]

    rows = observations()
    end = rows[-1].start + timedelta(minutes=15)
    battery = BaselineBattery(10, 10, 95, 4000, 4000)
    store = SimpleNamespace(db_path=str(database))
    energy._BATTERY_FIT_CACHE.clear()
    try:
        original = await energy._calibrated_fit(
            store, battery, {}, rows, end, rows[-1].start, "a" * 64
        )
        assert original.history["eligible_count"] == 0
        audit_path = tmp_path / "wal.audit.json"
        _report, _backup = apply_manifest(manifest, manifest_path, connection, database, audit_path)
        assert database.stat().st_mtime_ns == initial_stat.st_mtime_ns
        assert database.stat().st_size == initial_stat.st_size
        annotated_rows = observations()
        annotated = await energy._calibrated_fit(
            store, battery, {}, annotated_rows, end, rows[-1].start, "a" * 64
        )
        assert annotated is not original and annotated.history["eligible_count"] == 2
        undo_audit(json.loads(audit_path.read_text()), connection, database)
        assert database.stat().st_mtime_ns == initial_stat.st_mtime_ns
        restored = await energy._calibrated_fit(
            store, battery, {}, observations(), end, rows[-1].start, "a" * 64
        )
        assert restored is original and restored.history["eligible_count"] == 0
        connection.execute("UPDATE slot_observations SET pv_kwh=pv_kwh+.1")
        connection.commit()
        assert database.stat().st_mtime_ns == initial_stat.st_mtime_ns
        corrected = await energy._calibrated_fit(
            store, battery, {}, observations(), end, rows[-1].start, "a" * 64
        )
        assert corrected is not restored
    finally:
        energy._BATTERY_FIT_CACHE.clear()
        connection.close()
