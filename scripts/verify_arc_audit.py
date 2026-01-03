#!/usr/bin/env python3
import os
import re
import sys


def check_file_exists(path, description):
    if os.path.exists(path):
        print(f"✅ {description} found: {path}")
        return True
    print(f"❌ {description} MISSING: {path}")
    return False

def check_content(path, pattern, description, expected_count=None, invert=False):
    if not os.path.exists(path):
         print(f"❌ {description} SKIPPED (File missing): {path}")
         return False

    with open(path) as f:
        content = f.read()

    matches = len(re.findall(pattern, content))

    if invert:
        if matches == 0:
             print(f"✅ {description}: Pattern '{pattern}' NOT found (Clean)")
             return True
        else:
             print(f"❌ {description}: Pattern '{pattern}' FOUND {matches} times (Should be 0)")
             return False

    if expected_count is not None:
        if matches == expected_count:
            print(f"✅ {description}: Found {matches} matches (Exact)")
            return True
        else:
            print(f"❌ {description}: Found {matches} matches (Expected {expected_count})")
            return False

    if matches > 0:
        print(f"✅ {description}: Found {matches} matches")
        return True

    print(f"❌ {description}: Pattern '{pattern}' in {path} NOT found")
    return False

def main():
    print("="*60)
    print("ARC Revision Audit")
    print("="*60)

    failed = 0

    # ARC1: FastAPI Migration
    print("\n--- ARC1 ---")
    if not check_file_exists("backend/main.py", "FastAPI Entry Point"): failed += 1
    if not check_content("backend/main.py", "other_asgi_app", "Socket.IO ASGI Wrapper"): failed += 1
    if not check_content("docs/architecture.md", "Backend API Architecture", "Architecture Docs"): failed += 1

    # ARC2: Critical Bugs
    print("\n--- ARC2 ---")
    # Slot append bug (should verify logic, but pattern check is proxy)
    if not check_content("backend/api/routers/schedule.py", "merged_slots.append", "Slot Append", expected_count=1): failed += 1
    if not check_content("backend/main.py", "HealthChecker", "HealthChecker Integration"): failed += 1

    # ARC3: logging & exceptions
    print("\n--- ARC3 ---")
    if not check_content("backend/api/routers/services.py", r"print\(", "No print() in routers", invert=True): failed += 1
    # We allow 'except Exception' but not bare 'except:'
    # Regex for bare except: except:\s*$
    if not check_content("backend/api/routers/forecast.py", r"except:\s*$", "No bare except in forecast.py", invert=True): failed += 1

    # ARC4: Best Practices
    print("\n--- ARC4 ---")
    if not check_content("backend/api/models/health.py", "BaseModel", "Pydantic Models"): failed += 1
    if not check_file_exists(".github/workflows/ci.yml", "CI Workflow"): failed += 1

    print("="*60)
    if failed == 0:
        print("\n✅ ALL ARC CHECKS PASSED")
        sys.exit(0)
    else:
        print(f"\n❌ {failed} CHECKS FAILED")
        sys.exit(1)

if __name__ == "__main__":
    main()
