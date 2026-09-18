#!/usr/bin/env python3
"""
Database Optimizer

Compacts the learning database after creating a safety backup.
"""

import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.resolve()))


def optimize_db():
    """Optimize the database by reclaiming unused SQLite pages."""

    db_path = Path("data/planner_learning.db")

    print("\n" + "=" * 80)
    print("DATABASE OPTIMIZER")
    print("=" * 80)
    print(f"Target Database: {db_path}")
    print("Policy: Reclaim unused SQLite pages")
    print("=" * 80 + "\n")

    if not db_path.exists():
        print(f"✗ Database not found: {db_path}")
        return

    # --------------------------------------------------------------------------
    # Step 1: Create Backup
    # --------------------------------------------------------------------------
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.with_name(f"{db_path.name}.bak.{timestamp}")

    print(f"1. Creating backup -> {backup_path} ...")
    start = time.time()
    try:
        shutil.copy2(db_path, backup_path)
        elapsed = time.time() - start

        # Verify backup size
        original_size = db_path.stat().st_size
        backup_size = backup_path.stat().st_size

        if original_size != backup_size:
            print(f"✗ Backup failed: Size mismatch ({original_size} vs {backup_size})")
            return

        print(f"✓ Backup complete ({backup_size / (1024 * 1024):.2f} MB) in {elapsed:.2f}s")

    except Exception as e:
        print(f"✗ Backup failed: {e}")
        return

    # --------------------------------------------------------------------------
    # Step 2: Vacuum
    # --------------------------------------------------------------------------
    conn = sqlite3.connect(db_path)
    print("\n2. Running VACUUM (Reclaiming disk space)...")
    print("   This may take a minute...")

    try:
        start = time.time()
        conn.execute("VACUUM")
        elapsed = time.time() - start
        print(f"✓ VACUUM complete in {elapsed:.2f}s")

    except Exception as e:
        print(f"✗ VACUUM failed: {e}")
        conn.close()
        return

    conn.close()

    # --------------------------------------------------------------------------
    # Step 3: Verify
    # --------------------------------------------------------------------------
    print("\n4. Verification")

    new_size = db_path.stat().st_size
    reduction = original_size - new_size
    reduction_mb = reduction / (1024 * 1024)
    new_size_mb = new_size / (1024 * 1024)

    print("-" * 40)
    print(f"Original Size: {original_size / (1024 * 1024):.2f} MB")
    print(f"New Size:      {new_size_mb:.2f} MB")
    print(f"Space Saved:   {reduction_mb:.2f} MB")
    print("-" * 40)

    if new_size_mb > 300:
        print("\n⚠️  WARNING: DB is still larger than 300MB.")
    else:
        print("\nSUCCESS: Database successfully optimized for performance.")

    print(f"\nBackup is available at:\n{backup_path}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    optimize_db()
