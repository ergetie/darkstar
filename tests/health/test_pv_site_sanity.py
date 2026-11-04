"""Informational PV site plausibility notice and its acknowledgement."""

import json
import re
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
import pytz

from backend import health
from backend.core import onboarding_state
from backend.core.onboarding_state import (
    OnboardingUpdate,
    acknowledge_warning,
    read_state,
    write_state,
)
from backend.health import HealthChecker
from backend.learning.pv_site_sanity import compute_pv_site_ratio

TZ = pytz.timezone("Europe/Stockholm")
CONFIG = {
    "timezone": "Europe/Stockholm",
    "system": {
        "location": {"latitude": 59.3, "longitude": 18.1},
        "solar_arrays": [{"kwp": 10.0}],
    },
}
LOW = "pv_site_ratio_low"
HIGH = "pv_site_ratio_high"
FIRST_DAY = datetime(2026, 5, 2)  # 60 days ending 2026-06-30


def _window(ratio: float, clear_days: int) -> pd.DataFrame:
    """60 pinned days of 96 slots; the first ``clear_days`` are clear, the rest overcast."""
    rows = []
    for d in range(60):
        clear = d < clear_days
        for i in range(96):
            start = TZ.localize(FIRST_DAY + timedelta(days=d, minutes=15 * i))
            daytime = 8 <= start.hour < 18
            baseline = (0.5 if clear else 0.1) if daytime else 0.0
            rows.append(
                {
                    "slot_start": start.isoformat(),
                    "actual": baseline * ratio,
                    "baseline": baseline,
                    "soc_end_percent": 50.0,
                    "export_kwh": 0.5,
                }
            )
    return pd.DataFrame(rows)


def _store(df: pd.DataFrame) -> MagicMock:
    store = MagicMock()
    store.get_pv_actual_vs_baseline = AsyncMock(return_value=df)
    return store


class TestComputeRatio:
    @pytest.mark.asyncio
    async def test_ratio_over_clear_days(self):
        result = await compute_pv_site_ratio(_store(_window(0.40, 20)), CONFIG)

        assert result is not None
        ratio, clear_days = result
        assert ratio == pytest.approx(0.40)
        assert clear_days == 20

    @pytest.mark.asyncio
    async def test_fewer_than_14_clear_days_gives_none(self):
        assert await compute_pv_site_ratio(_store(_window(0.40, 9)), CONFIG) is None

    @pytest.mark.asyncio
    async def test_no_data_gives_none(self):
        assert await compute_pv_site_ratio(_store(pd.DataFrame()), CONFIG) is None

    @pytest.mark.asyncio
    async def test_curtailed_clear_slots_do_not_count(self):
        df = _window(0.80, 20)
        curtailed = df["baseline"] > 0
        df.loc[curtailed & (df.index % 2 == 0), ["actual", "soc_end_percent", "export_kwh"]] = [
            0.05,
            100.0,
            0.0,
        ]

        result = await compute_pv_site_ratio(_store(df), CONFIG)

        assert result is not None
        assert result[0] == pytest.approx(0.80)


def _checker() -> HealthChecker:
    checker = HealthChecker()
    checker._config = CONFIG
    return checker


async def _issues(ratio: float | None, tmp_path) -> list:
    """Run the check with a fixed measured ratio (cache cleared first)."""
    health._pv_site_ratio_cache = None
    db = tmp_path / "learning.db"
    db.touch()
    measured = None if ratio is None else (ratio, 20)
    with (
        patch("backend.core.forecasts.get_forecast_db_path", return_value=str(db)),
        patch("backend.learning.store.LearningStore", return_value=MagicMock(close=AsyncMock())),
        patch(
            "backend.learning.pv_site_sanity.compute_pv_site_ratio",
            new=AsyncMock(return_value=measured),
        ),
    ):
        return await _checker().check_pv_site_sanity()


class TestNotice:
    @pytest.mark.asyncio
    async def test_low_ratio_gives_info_notice_with_percentage(self, tmp_path):
        issues = await _issues(0.40, tmp_path)

        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == "info"
        assert issue.category == "forecast"
        assert issue.code == issue.acknowledge_id == LOW
        assert "much less than forecast on clear days (about 40 % of forecast)" in issue.message
        assert "shading" in issue.guidance
        assert "Darkstar still learns and adjusts the forecast" in issue.guidance

    @pytest.mark.asyncio
    async def test_high_ratio_gives_info_notice(self, tmp_path):
        (issue,) = await _issues(1.50, tmp_path)

        assert issue.code == issue.acknowledge_id == HIGH
        assert "much more than forecast on clear days (about 150 % of forecast)" in issue.message
        assert "measured twice" in issue.guidance

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ratio", [0.8, 0.55, 1.30, None])
    async def test_plausible_or_unknown_ratio_gives_no_notice(self, tmp_path, ratio):
        assert await _issues(ratio, tmp_path) == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ratio", [0.40, 1.50])
    async def test_wording_is_plain_language(self, tmp_path, ratio):
        (issue,) = await _issues(ratio, tmp_path)
        text = f"{issue.message} {issue.guidance}".lower()

        assert "error" not in text
        assert "failed" not in text
        assert "_" not in text
        assert not re.search(r"\w\.\w", text)  # no dotted identifiers

    @pytest.mark.asyncio
    async def test_store_error_gives_no_issue_and_no_exception(self, tmp_path):
        health._pv_site_ratio_cache = None
        db = tmp_path / "learning.db"
        db.touch()
        with (
            patch("backend.core.forecasts.get_forecast_db_path", return_value=str(db)),
            patch(
                "backend.learning.store.LearningStore", return_value=MagicMock(close=AsyncMock())
            ),
            patch(
                "backend.learning.pv_site_sanity.compute_pv_site_ratio",
                new=AsyncMock(side_effect=RuntimeError("db locked")),
            ),
        ):
            assert await _checker().check_pv_site_sanity() == []

    @pytest.mark.asyncio
    async def test_failed_computation_is_not_retried_on_every_poll(self, tmp_path):
        health._pv_site_ratio_cache = None
        db = tmp_path / "learning.db"
        db.touch()
        compute = AsyncMock(side_effect=RuntimeError("db locked"))
        with (
            patch("backend.core.forecasts.get_forecast_db_path", return_value=str(db)),
            patch(
                "backend.learning.store.LearningStore", return_value=MagicMock(close=AsyncMock())
            ),
            patch("backend.learning.pv_site_sanity.compute_pv_site_ratio", new=compute),
        ):
            checker = _checker()
            assert await checker.check_pv_site_sanity() == []
            assert await checker.check_pv_site_sanity() == []
        assert compute.await_count == 1

    @pytest.mark.asyncio
    async def test_second_call_within_six_hours_does_not_query_again(self, tmp_path):
        health._pv_site_ratio_cache = None
        db = tmp_path / "learning.db"
        db.touch()
        compute = AsyncMock(return_value=(0.40, 20))
        with (
            patch("backend.core.forecasts.get_forecast_db_path", return_value=str(db)),
            patch(
                "backend.learning.store.LearningStore", return_value=MagicMock(close=AsyncMock())
            ),
            patch("backend.learning.pv_site_sanity.compute_pv_site_ratio", new=compute),
        ):
            first = await _checker().check_pv_site_sanity()
            second = await _checker().check_pv_site_sanity()

        assert compute.await_count == 1
        assert len(first) == len(second) == 1

    @pytest.mark.asyncio
    async def test_missing_database_gives_no_issue(self, tmp_path):
        health._pv_site_ratio_cache = None
        with patch(
            "backend.core.forecasts.get_forecast_db_path", return_value=str(tmp_path / "none.db")
        ):
            assert await _checker().check_pv_site_sanity() == []
        assert not (tmp_path / "none.db").exists()


class TestAcknowledgement:
    @pytest.mark.asyncio
    async def test_low_acknowledged_stays_hidden_until_clearly_worse(self, tmp_path):
        acknowledge_warning(LOW, 0.40)

        assert await _issues(0.38, tmp_path) == []
        assert len(await _issues(0.30, tmp_path)) == 1
        # Slightly better is not a reason to reshow.
        assert await _issues(0.50, tmp_path) == []

    @pytest.mark.asyncio
    async def test_other_side_of_range_shows_again(self, tmp_path):
        acknowledge_warning(LOW, 0.40)

        (issue,) = await _issues(1.40, tmp_path)

        assert issue.code == HIGH

    @pytest.mark.asyncio
    async def test_high_acknowledged_hidden_until_clearly_worse(self, tmp_path):
        acknowledge_warning(HIGH, 1.50)

        assert await _issues(1.58, tmp_path) == []
        assert len(await _issues(1.60, tmp_path)) == 1

    @pytest.mark.asyncio
    async def test_high_acknowledged_then_low_shows(self, tmp_path):
        acknowledge_warning(HIGH, 1.50)

        (issue,) = await _issues(0.50, tmp_path)

        assert issue.code == LOW

    @pytest.mark.asyncio
    async def test_recovery_clears_acknowledgement_and_recurrence_shows(self, tmp_path):
        acknowledge_warning(LOW, 0.40)

        assert await _issues(0.80, tmp_path) == []
        assert read_state().acknowledged_warnings == {}
        assert len(await _issues(0.45, tmp_path)) == 1

    @pytest.mark.asyncio
    async def test_acknowledgement_survives_restart(self, tmp_path):
        acknowledge_warning(LOW, 0.40)
        # A new process only has the file; the in-memory cache starts empty.
        assert read_state().acknowledged_warnings == {LOW: 0.40}
        assert await _issues(0.38, tmp_path) == []


class TestOnboardingStatePersistence:
    def test_old_state_file_without_field_loads(self):
        onboarding_state.STATE_FILE_PATH.write_text(
            json.dumps({"version": 1, "status": "in_progress", "dismissed_notices": ["a.b"]})
        )

        state = read_state()

        assert state.acknowledged_warnings == {}
        assert state.dismissed_notices == ["a.b"]
        assert state.status == "in_progress"

    def test_write_state_keeps_acknowledgements(self):
        acknowledge_warning(LOW, 0.40)

        write_state(OnboardingUpdate(status="completed"))

        assert read_state().acknowledged_warnings == {LOW: 0.40}

    def test_acknowledge_overwrites_value(self):
        acknowledge_warning(LOW, 0.40)
        acknowledge_warning(LOW, 0.30)

        assert read_state().acknowledged_warnings == {LOW: 0.30}
