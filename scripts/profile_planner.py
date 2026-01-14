#!/usr/bin/env python3
"""
Planner Performance Profiler

Run this on the server to measure actual execution times.
Usage: python scripts/profile_planner.py
"""

import sys
import time
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.resolve()))

import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("profiler")


def profile_planner():
    """Profile the planner execution with detailed timings."""
    
    print("\n" + "=" * 80)
    print("PLANNER PERFORMANCE PROFILE")
    print("=" * 80)
    print(f"Start Time: {datetime.now().isoformat()}")
    print("=" * 80 + "\n")
    
    timings = {}
    overall_start = time.time()
    
    # Step 1: Import planner
    step_start = time.time()
    try:
        from bin.run_planner import main as planner_main
        timings["1_import_planner"] = time.time() - step_start
        print(f"✓ Import planner: {timings['1_import_planner']:.4f}s")
    except Exception as e:
        print(f"✗ Import planner FAILED: {e}")
        return
    
    # Step 2: Import LearningEngine
    step_start = time.time()
    try:
        from backend.learning import get_learning_engine
        timings["2_import_learning"] = time.time() - step_start
        print(f"✓ Import learning engine: {timings['2_import_learning']:.4f}s")
    except Exception as e:
        print(f"✗ Import learning engine FAILED: {e}")
        return
    
    # Step 3: Initialize LearningEngine
    step_start = time.time()
    try:
        engine = get_learning_engine()
        timings["3_init_learning_engine"] = time.time() - step_start
        print(f"✓ Initialize learning engine: {timings['3_init_learning_engine']:.4f}s")
    except Exception as e:
        print(f"✗ Initialize learning engine FAILED: {e}")
        return
    
    # Step 4: Initialize LearningStore directly
    step_start = time.time()
    try:
        import pytz
        from backend.learning.store import LearningStore
        
        db_path = "data/planner_learning.db"
        tz = pytz.timezone("Europe/Stockholm")
        store = LearningStore(db_path, tz)
        
        timings["4_init_learning_store"] = time.time() - step_start
        print(f"✓ Initialize learning store: {timings['4_init_learning_store']:.4f}s")
    except Exception as e:
        print(f"✗ Initialize learning store FAILED: {e}")
        return
    
    # Step 5: Run full planner
    step_start = time.time()
    try:
        print("\n--- Running Full Planner ---")
        planner_main()
        timings["5_run_planner"] = time.time() - step_start
        print(f"✓ Run planner: {timings['5_run_planner']:.4f}s")
    except Exception as e:
        print(f"✗ Run planner FAILED: {e}")
        return
    
    # Overall
    timings["total"] = time.time() - overall_start
    
    # Print Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    for key, value in timings.items():
        print(f"{key:.<40} {value:>10.4f}s")
    print("=" * 80)
    
    # Analysis
    print("\nANALYSIS:")
    if timings.get("3_init_learning_engine", 0) > 1.0:
        print("⚠️  WARNING: Learning engine init > 1s (expected ~0.05s with fix)")
    if timings.get("4_init_learning_store", 0) > 1.0:
        print("⚠️  WARNING: Learning store init > 1s (expected ~0.05s with fix)")
    if timings.get("5_run_planner", 0) > 30.0:
        print("⚠️  WARNING: Planner execution > 30s (may indicate DB I/O bottleneck)")
    
    print(f"\nEnd Time: {datetime.now().isoformat()}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    profile_planner()
