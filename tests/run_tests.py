#!/usr/bin/env python3
"""
Test runner script for the Darkstar Planner test suite.
"""

import subprocess
import sys
from pathlib import Path


def run_pytest():
    """Run pytest on the test suite."""
    test_dir = Path(__file__).parent.resolve()
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_dir), "-v", "--tb=short"],
        capture_output=True,
        text=True,
    )

    print("STDOUT:")
    print(result.stdout)
    if result.stderr:
        print("STDERR:")
        print(result.stderr)

    return result.returncode


def run_specific_test(test_file):
    """Run a specific test file."""
    test_path = Path(__file__).parent.resolve() / test_file
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_path), "-v", "--tb=short"],
        capture_output=True,
        text=True,
    )

    print(f"Running {test_file}:")
    print("STDOUT:")
    print(result.stdout)
    if result.stderr:
        print("STDERR:")
        print(result.stderr)

    return result.returncode


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Run specific test file
        test_file = sys.argv[1]
        exit_code = run_specific_test(test_file)
    else:
        # Run all tests
        print("Running Darkstar Planner test suite...")
        exit_code = run_pytest()

    sys.exit(exit_code)
