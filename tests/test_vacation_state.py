"""
Unit tests for the vacation_state module.
Rev K19: Anti-legionella cycle tracking.
"""

import os
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from planner.vacation_state import (
    load_last_anti_legionella,
    save_last_anti_legionella,
)


@pytest.fixture
def temp_db():
    """Create a temporary database file for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    Path(path).unlink()


def test_load_returns_none_when_no_record(temp_db):
    """load_last_anti_legionella returns None when no record exists."""
    result = load_last_anti_legionella(temp_db)
    assert result is None


def test_save_and_load_roundtrip(temp_db):
    """Saving and loading a timestamp should roundtrip correctly."""
    test_time = datetime(2024, 12, 20, 14, 30, 0)

    save_last_anti_legionella(temp_db, test_time)
    loaded = load_last_anti_legionella(temp_db)

    assert loaded is not None
    assert loaded.year == 2024
    assert loaded.month == 12
    assert loaded.day == 20
    assert loaded.hour == 14
    assert loaded.minute == 30


def test_save_overwrites_previous_value(temp_db):
    """Saving a new timestamp should overwrite the previous one."""
    first_time = datetime(2024, 12, 10, 10, 0, 0)
    second_time = datetime(2024, 12, 20, 15, 0, 0)

    save_last_anti_legionella(temp_db, first_time)
    save_last_anti_legionella(temp_db, second_time)

    loaded = load_last_anti_legionella(temp_db)

    assert loaded is not None
    assert loaded.day == 20  # Should be second timestamp
