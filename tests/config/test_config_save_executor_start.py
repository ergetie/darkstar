"""Config save starts an enabled executor; disabling leaves the loop idle."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.api.routers import config


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    defaults = Path("config.default.yaml").read_text()
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.default.yaml").write_text(defaults)
    path = tmp_path / "config.yaml"
    path.write_text(defaults)
    monkeypatch.setattr(config, "_phase_sensor_units_for_config", AsyncMock(return_value={}))
    return path


def _executor(enabled: bool, alive: bool) -> MagicMock:
    executor = MagicMock()
    executor.config = SimpleNamespace(enabled=enabled)
    executor._thread = SimpleNamespace(is_alive=lambda: alive)
    return executor


async def _save(executor, enabled: bool):
    with patch.object(config, "peek_executor_instance", return_value=executor):
        return await config.save_config({"executor": {"enabled": enabled}})


@pytest.mark.asyncio
async def test_save_enabled_starts_stopped_executor(cfg_path):
    executor = _executor(enabled=True, alive=False)
    await _save(executor, True)
    executor.reload_config.assert_called_once()
    executor.start.assert_called_once()


@pytest.mark.asyncio
async def test_save_enabled_does_not_start_second_thread(cfg_path):
    executor = _executor(enabled=True, alive=True)
    await _save(executor, True)
    executor.reload_config.assert_called_once()
    executor.start.assert_not_called()


@pytest.mark.asyncio
async def test_save_disabled_does_not_start_or_stop(cfg_path):
    executor = _executor(enabled=False, alive=True)
    await _save(executor, False)
    executor.start.assert_not_called()
    executor.stop.assert_not_called()


@pytest.mark.asyncio
async def test_save_without_instance_creates_nothing(cfg_path):
    with (
        patch.object(config, "peek_executor_instance", return_value=None),
        patch("backend.api.routers.executor.get_executor_instance") as create,
    ):
        await config.save_config({"executor": {"enabled": True}})
    create.assert_not_called()


@pytest.mark.asyncio
async def test_start_failure_does_not_fail_save(cfg_path):
    executor = _executor(enabled=True, alive=False)
    executor.start.side_effect = RuntimeError("boom")
    await _save(executor, True)  # must not raise
    executor.start.assert_called_once()


def test_loop_idles_without_ticking_when_disabled(tmp_path, monkeypatch):
    """The loop that config save leaves running idles on enabled=false: no tick, no writes."""
    from executor.engine import ExecutorEngine

    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    engine = ExecutorEngine(config_path="config.yaml")
    engine.reload_config = MagicMock()  # keep the in-memory disabled config
    engine.config.enabled = False
    engine.ha_client = MagicMock(close=AsyncMock())
    engine._tick = AsyncMock()
    engine.dispatcher = MagicMock()
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        engine._stop_event.set()

    with patch("executor.engine.asyncio.sleep", fake_sleep):
        asyncio.run(engine._async_run_loop())

    engine._tick.assert_not_called()
    engine.dispatcher.execute.assert_not_called()
    engine.dispatcher.clear_baselines.assert_called_once()  # idle drops revert baselines
    assert sleeps == [10]
