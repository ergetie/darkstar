#!/usr/bin/env python3
"""Dry-run-first local annotation of historical battery-comparison provenance."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.comparison_history import (
    ManifestError,
    apply_manifest,
    dry_run_report,
    undo_audit,
)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ManifestError(f"could not read JSON file: {path}") from error


def _connect(database_path: Path, *, writable: bool) -> sqlite3.Connection:
    if not database_path.exists() or not database_path.is_file():
        raise ManifestError("database must be an existing local SQLite file")
    if writable:
        return sqlite3.connect(database_path, timeout=30.0)
    uri = database_path.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=30.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", required=True, type=Path, help="explicit local SQLite database path"
    )
    parser.add_argument("--manifest", type=Path, help="versioned JSON annotation manifest")
    parser.add_argument("--apply", action="store_true", help="apply a previously dry-run manifest")
    parser.add_argument(
        "--reviewed", action="store_true", help="confirm the manifest was reviewed before apply"
    )
    parser.add_argument("--audit", type=Path, help="audit/undo output path for --apply")
    parser.add_argument("--undo", type=Path, help="undo an earlier audit record")
    args = parser.parse_args(argv)

    try:
        if args.apply and (not args.manifest or not args.reviewed or args.undo):
            raise ManifestError(
                "--apply requires --manifest and --reviewed; it cannot be combined with --undo"
            )
        if args.undo and (args.manifest or args.apply):
            raise ManifestError("--undo cannot be combined with a manifest or --apply")
        if not args.undo and not args.manifest:
            raise ManifestError("--manifest is required unless --undo is used")

        database_path = args.database.resolve(strict=True)
        if args.undo:
            audit_path = args.undo.resolve(strict=True)
            with _connect(database_path, writable=True) as connection:
                report = undo_audit(_read_json(audit_path), connection, database_path)
        else:
            manifest_path = args.manifest.resolve(strict=True)
            manifest = _read_json(manifest_path)
            with _connect(database_path, writable=args.apply) as connection:
                if args.apply:
                    audit_path = args.audit or manifest_path.with_suffix(".audit.json")
                    report, _backup_path = apply_manifest(
                        manifest, manifest_path, connection, database_path, audit_path.resolve()
                    )
                else:
                    report = dry_run_report(manifest, manifest_path, connection, database_path)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (ManifestError, OSError, sqlite3.Error) as error:
        print(json.dumps({"error": str(error)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
