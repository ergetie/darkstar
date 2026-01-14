import collections
from unittest.mock import MagicMock

import pytest

from executor.actions import ActionResult
from executor.config import ExecutorConfig
from executor.engine import ExecutorEngine


@pytest.fixture
def mock_config():
    return ExecutorConfig()


@pytest.fixture
def engine(mock_config):
    # Mocking components to avoid real HA/MQTT interaction
    engine = ExecutorEngine(config_path="config.yaml")
    engine.config = mock_config
    engine.recent_errors = collections.deque(maxlen=10)
    return engine


def test_executor_engine_status_includes_recent_errors(engine):
    error = {
        "timestamp": "2026-01-14T12:00:00Z",
        "type": "test_action",
        "message": "Test error message",
    }
    engine.recent_errors.append(error)

    status = engine.get_status()
    assert "recent_errors" in status
    assert len(status["recent_errors"]) == 1
    assert status["recent_errors"][0] == error


def test_executor_engine_captures_action_errors(engine):
    # Mock dispatcher to return an error result
    engine.dispatcher = MagicMock()
    error_result = ActionResult(
        action_type="set_work_mode", success=False, message="HA API Error", skipped=False
    )
    engine.dispatcher.execute.return_value = [error_result]

    # Run a tick
    # We need to mock other parts of _tick to avoid failures before action execution
    engine._load_config = MagicMock()
    engine._gather_system_state = MagicMock()
    engine._get_planner_decision = MagicMock(return_value=MagicMock())
    engine.history = MagicMock()  # Mock history to avoid DB errors

    engine._tick()

    # It might have 2 errors if _tick itself failed somehow,
    # but we want at least the one from the action result.
    assert any(e["message"] == "HA API Error" for e in engine.recent_errors)


def test_executor_engine_ignores_skipped_actions(engine):
    engine.dispatcher = MagicMock()
    skipped_result = ActionResult(
        action_type="set_work_mode", success=False, message="Entity not configured", skipped=True
    )
    engine.dispatcher.execute.return_value = [skipped_result]

    engine._load_config = MagicMock()
    engine._gather_system_state = MagicMock()
    engine._get_planner_decision = MagicMock(return_value=MagicMock())
    engine.history = MagicMock()

    engine._tick()

    # Should not have the skipped error
    assert not any(e["message"] == "Entity not configured" for e in engine.recent_errors)
