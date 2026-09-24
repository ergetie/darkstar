from datetime import UTC, datetime

from backend.core.ha_timestamps import reading_timestamp

REPORTED = "2026-09-24T10:00:05+00:00"
UPDATED = "2026-09-24T09:59:00+00:00"
CHANGED = "2026-09-24T09:58:00+00:00"


def test_prefers_last_reported():
    state = {"last_reported": REPORTED, "last_updated": UPDATED, "last_changed": CHANGED}
    assert reading_timestamp(state) == datetime.fromisoformat(REPORTED)


def test_falls_back_to_last_updated():
    state = {"last_updated": UPDATED, "last_changed": CHANGED}
    assert reading_timestamp(state) == datetime.fromisoformat(UPDATED)


def test_falls_back_to_last_changed():
    assert reading_timestamp({"last_changed": CHANGED}) == datetime.fromisoformat(CHANGED)


def test_unparseable_value_is_skipped():
    state = {"last_reported": "not-a-date", "last_updated": UPDATED}
    assert reading_timestamp(state) == datetime.fromisoformat(UPDATED)


def test_z_suffix_parsed():
    assert reading_timestamp({"last_reported": "2026-09-24T10:00:05Z"}) == datetime(
        2026, 9, 24, 10, 0, 5, tzinfo=UTC
    )


def test_naive_interpreted_as_utc():
    ts = reading_timestamp({"last_reported": "2026-09-24T10:00:05"})
    assert ts == datetime(2026, 9, 24, 10, 0, 5, tzinfo=UTC)


def test_no_usable_timestamp():
    assert reading_timestamp(None) is None
    assert reading_timestamp({}) is None
    assert reading_timestamp({"state": "1", "last_reported": None, "last_updated": "bad"}) is None
