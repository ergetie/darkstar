#!/usr/bin/env python3
"""
Test runner script for the Darkstar Planner test suite.
"""
import subprocess
import sys
import os


def run_pytest():
    """Run pytest on the test suite."""
    test_dir = os.path.dirname(os.path.abspath(__file__))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_dir, "-v", "--tb=short"],
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
    test_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), test_file)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_path, "-v", "--tb=short"],
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
