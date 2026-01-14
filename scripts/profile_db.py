#!/usr/bin/env python3
"""
Database Performance Profiler

Measures SQLite operation performance.
Usage: python scripts/profile_db.py
"""

import sys
import time
import sqlite3
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.resolve()))


def profile_db():
    """Profile database operations."""
    
    db_path = "data/planner_learning.db"
    
    print("\n" + "=" * 80)
    print("DATABASE PERFORMANCE PROFILE")
    print("=" * 80)
    print(f"Database: {db_path}")
    print("=" * 80 + "\n")
    
    # Check file size
    db_file = Path(db_path)
    if not db_file.exists():
        print(f"✗ Database not found: {db_path}")
        return
    
    size_mb = db_file.stat().st_size / (1024 * 1024)
    print(f"Database Size: {size_mb:.2f} MB\n")
    
    # Connect
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Test 1: Table sizes
    print("TABLE SIZES:")
    print("-" * 80)
    cursor.execute("""
        SELECT name, SUM(pgsize) as size 
        FROM dbstat 
        GROUP BY name 
        ORDER BY size DESC 
        LIMIT 10
    """)
    
    for row in cursor.fetchall():
        table_name, size_bytes = row
        size_mb = size_bytes / (1024 * 1024)
        print(f"{table_name:.<40} {size_mb:>10.2f} MB")
    
    print()
    
    # Test 2: Row counts
    print("ROW COUNTS:")
    print("-" * 80)
    
    tables = [
        "training_episodes",
        "slot_forecasts",
        "slot_plans",
        "slot_observations",
        "execution_log",
    ]
    
    for table in tables:
        try:
            start = time.time()
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            elapsed = time.time() - start
            print(f"{table:.<40} {count:>10,} rows ({elapsed:.4f}s)")
        except sqlite3.OperationalError:
            print(f"{table:.<40} (table not found)")
    
    print()
    
    # Test 3: NULL count in slot_forecasts
    print("CHECKING FOR NULLs IN slot_forecasts:")
    print("-" * 80)
    
    start = time.time()
    cursor.execute("""
        SELECT COUNT(*) FROM slot_forecasts 
        WHERE pv_correction_kwh IS NULL 
           OR load_correction_kwh IS NULL 
           OR correction_source IS NULL
    """)
    null_count = cursor.fetchone()[0]
    elapsed = time.time() - start
    
    print(f"Rows with NULLs: {null_count:,} ({elapsed:.4f}s)")
    
    if null_count > 0:
        print("⚠️  WARNING: Found NULLs - the WHERE clause optimization is not effective!")
    else:
        print("✓ No NULLs found - WHERE clause should make UPDATE instant")
    
    print()
    
    # Test 4: Simulate _init_schema UPDATE
    print("SIMULATING _init_schema UPDATE:")
    print("-" * 80)
    
    print("Testing UPDATE with WHERE clause (should be instant)...")
    start = time.time()
    cursor.execute("""
        UPDATE slot_forecasts
        SET
            pv_correction_kwh = COALESCE(pv_correction_kwh, 0.0),
            load_correction_kwh = COALESCE(load_correction_kwh, 0.0),
            correction_source = COALESCE(correction_source, 'none')
        WHERE pv_correction_kwh IS NULL
           OR load_correction_kwh IS NULL
           OR correction_source IS NULL
    """)
    conn.rollback()  # Don't actually commit
    elapsed = time.time() - start
    
    print(f"UPDATE execution time: {elapsed:.4f}s")
    
    if elapsed > 0.5:
        print("⚠️  WARNING: UPDATE took > 0.5s even with WHERE clause!")
        print("   This suggests DB I/O is slow or the query plan is inefficient.")
    else:
        print("✓ UPDATE is fast as expected")
    
    print()
    
    # Test 5: Write test
    print("WRITE PERFORMANCE TEST:")
    print("-" * 80)
    
    print("Inserting 100 test rows...")
    start = time.time()
    
    for i in range(100):
        cursor.execute("""
            INSERT INTO slot_observations (slot_start, slot_end, pv_kwh, load_kwh)
            VALUES (?, ?, ?, ?)
        """, (
            f"2099-01-01T{i//10:02d}:{i%10*6:02d}:00",
            f"2099-01-01T{i//10:02d}:{i%10*6+15:02d}:00",
            1.0,
            2.0
        ))
    
    conn.rollback()  # Don't actually commit
    elapsed = time.time() - start
    
    print(f"100 INSERTs: {elapsed:.4f}s ({elapsed/100*1000:.2f}ms per insert)")
    
    if elapsed > 1.0:
        print("⚠️  WARNING: Write performance is degraded (expected < 0.5s for 100 inserts)")
        print("   Consider running VACUUM or investigating disk I/O")
    else:
        print("✓ Write performance is acceptable")
    
    conn.close()
    
    print("\n" + "=" * 80)
    print("RECOMMENDATIONS:")
    print("=" * 80)
    
    if size_mb > 500:
        print("• Database > 500MB - consider archiving old training_episodes")
    
    if null_count > 0:
        print("• Run one-time migration to backfill NULLs")
    
    print("• Run VACUUM to reclaim space and improve performance:")
    print("  sqlite3 data/planner_learning.db 'VACUUM;'")
    
    print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    profile_db()
