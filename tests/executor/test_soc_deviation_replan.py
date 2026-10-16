"""battery-plan-tracking: replan when live SoC deviates from the plan."""

import contextlib
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytz
from sqlalchemy import create_engine

from backend.learning.models import Base
from backend.services.scheduler_service import ReplanReason
from executor.config import ExecutorConfig
from executor.engine import ExecutorEngine
from executor.override import SlotPlan, SystemState

TZ = pytz.timezone("Europe/Stockholm")
T0 = TZ.localize(datetime(2026, 6, 1, 12, 0, 0))
REPLAN = "backend.services.scheduler_service.request_replan"


@pytest.fixture
def make_engine():
    paths: list[str] = []

    def _make(**overrides):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        paths.append(db_path)
        Base.metadata.create_all(create_engine(f"sqlite:///{db_path}"))
        config = ExecutorConfig(enabled=True, timezone="Europe/Stockholm", **overrides)
        with patch("executor.engine.load_executor_config", return_value=config):
            with patch("executor.engine.load_yaml", return_value={}):
                with patch.object(ExecutorEngine, "_get_db_path", return_value=db_path):
                    return ExecutorEngine("config.yaml")

    yield _make
    for path in paths:
        with contextlib.suppress(OSError):
            Path(path).unlink()


@pytest.fixture
def engine(make_engine):
    return make_engine()


def plan_slot(entry=15, projected=15) -> SlotPlan:
    return SlotPlan(
        soc_entry=entry,
        soc_projected=projected,
        slot_start=T0 - timedelta(minutes=5),
        slot_end=T0 + timedelta(minutes=10),
    )


def live(soc: float, available: bool = True, manual: bool = False) -> SystemState:
    return SystemState(
        current_soc_percent=soc, soc_available=available, manual_override_active=manual
    )


def track(engine, state, minutes, slot=None, override=False):
    engine._track_soc_deviation(
        state, slot or plan_slot(), T0 + timedelta(minutes=minutes), override
    )


class TestExpectedSoc:
    def test_interpolates_within_slot(self):
        slot = SlotPlan(
            soc_entry=10,
            soc_projected=20,
            slot_start=T0,
            slot_end=T0 + timedelta(minutes=15),
        )
        assert ExecutorEngine._expected_soc(slot, T0 + timedelta(minutes=7.5)) == pytest.approx(15)

    def test_unknown_entry_gives_none(self):
        assert ExecutorEngine._expected_soc(SlotPlan(), T0) is None


class TestDeviationReplan:
    def test_fires_after_five_minutes(self, engine):
        with patch(REPLAN) as replan:
            track(engine, live(3), 0)
            track(engine, live(3), 4.9)
            replan.assert_not_called()
            track(engine, live(3), 5)
            replan.assert_called_once_with(ReplanReason.SOC_DEVIATION)

    def test_gap_in_ticks_restarts_persistence(self, engine):
        with patch(REPLAN) as replan:
            track(engine, live(3), 0)
            track(engine, live(3), 30)  # ticks were missing for 30 minutes
            replan.assert_not_called()
            track(engine, live(3), 35)
            replan.assert_called_once_with(ReplanReason.SOC_DEVIATION)

    def test_short_deviation_does_not_fire(self, engine):
        with patch(REPLAN) as replan:
            track(engine, live(3), 0)
            track(engine, live(3), 3)
            track(engine, live(14), 4)  # back within threshold
            track(engine, live(3), 5)
            track(engine, live(3), 9)
            replan.assert_not_called()

    def test_disabled_at_zero(self, make_engine):
        engine = make_engine(soc_deviation_replan_percent=0.0)
        with patch(REPLAN) as replan:
            track(engine, live(3), 0)
            track(engine, live(3), 30)
            replan.assert_not_called()

    def test_threshold_is_exclusive(self, engine):
        with patch(REPLAN) as replan:
            track(engine, live(5), 0)  # deviation exactly 10
            track(engine, live(5), 10)
            replan.assert_not_called()

    def test_rate_limited_to_one_per_15_minutes(self, engine):
        with patch(REPLAN) as replan:
            track(engine, live(3), 0)
            track(engine, live(3), 5)
            assert replan.call_count == 1
            track(engine, live(3), 10)
            track(engine, live(3), 19.9)
            assert replan.call_count == 1
            track(engine, live(3), 20)
            assert replan.call_count == 2

    def test_unavailable_soc_never_fires(self, engine):
        with patch(REPLAN) as replan:
            track(engine, live(3, available=False), 0)
            track(engine, live(3, available=False), 10)
            replan.assert_not_called()

    def test_unavailable_soc_resets_persistence(self, engine):
        with patch(REPLAN) as replan:
            track(engine, live(3), 0)
            track(engine, live(3, available=False), 4)
            track(engine, live(3), 6)
            replan.assert_not_called()

    def test_override_skips(self, engine):
        with patch(REPLAN) as replan:
            track(engine, live(3), 0, override=True)
            track(engine, live(3), 10, override=True)
            replan.assert_not_called()

    def test_manual_override_skips(self, engine):
        with patch(REPLAN) as replan:
            track(engine, live(3, manual=True), 0)
            track(engine, live(3, manual=True), 10)
            replan.assert_not_called()

    def test_shadow_mode_only_logs(self, make_engine, caplog):
        engine = make_engine(shadow_mode=True)
        with patch(REPLAN) as replan, caplog.at_level("INFO"):
            track(engine, live(3), 0)
            track(engine, live(3), 5)
            replan.assert_not_called()
        assert "would request soc_deviation replan" in caplog.text

    def test_log_names_live_expected_and_threshold(self, engine, caplog):
        with patch(REPLAN), caplog.at_level("INFO"):
            track(engine, live(3), 0)
            track(engine, live(3), 5)
        assert "live 3.0%" in caplog.text
        assert "expected 15.0%" in caplog.text
        assert "threshold 10" in caplog.text

    def test_unknown_plan_entry_never_fires(self, engine):
        with patch(REPLAN) as replan:
            track(engine, live(3), 0, slot=SlotPlan())
            track(engine, live(3), 10, slot=SlotPlan())
            replan.assert_not_called()


class TestLimitersIndependent:
    def test_deviation_replan_does_not_consume_balancer_limit(self, engine):
        engine._request_balancer_replan = MagicMock()
        with patch(REPLAN):
            track(engine, live(3), 0)
            track(engine, live(3), 5)
        assert engine._last_soc_deviation_replan_at is not None
        assert engine._last_balancer_replan_at is None
        assert engine._executor_replan_allowed(T0 + timedelta(minutes=6)) is True

    def test_balancer_replan_does_not_consume_deviation_limit(self, engine):
        assert engine._executor_replan_allowed(T0) is True
        with patch(REPLAN) as replan:
            track(engine, live(3), 0)
            track(engine, live(3), 5)
            replan.assert_called_once_with(ReplanReason.SOC_DEVIATION)


class TestReportedScenario:
    def test_live_3_expected_15_requests_one_replan(self, engine):
        with patch(REPLAN) as replan:
            for minute in range(0, 14):
                track(engine, live(3), minute)
            replan.assert_called_once_with(ReplanReason.SOC_DEVIATION)
