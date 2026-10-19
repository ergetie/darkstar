"""Live config reload reaches the ActionDispatcher at tick boundaries."""

import os
import threading
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from executor.actions import ActionDispatcher, ActionResult
from executor.config import load_executor_config
from executor.engine import ExecutorEngine
from executor.override import SystemState
from executor.profiles import ModeAction, load_profile

HELPER = "input_number.master_soc_target"
PROGRAM_6 = "number.inverter_program_6_soc"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_config(path: Path, soc_target: str, mtime: int) -> None:
    path.write_text(
        "system:\n"
        "  inverter_profile: deye\n"
        "executor:\n"
        "  shadow_mode: false\n"
        "  inverter:\n"
        f"    soc_target: {soc_target}\n"
    )
    os.utime(path, (mtime, mtime))


def _ha_client() -> MagicMock:
    ha = MagicMock()
    written: dict[str, float] = {}

    async def get_state_value(entity_id: str) -> str:
        return str(written.get(entity_id, 10))

    async def set_number(entity_id: str, value: float) -> bool:
        written[entity_id] = value
        return True

    ha.get_state_value = AsyncMock(side_effect=get_state_value)
    ha.set_number = AsyncMock(side_effect=set_number)
    ha.send_notification = AsyncMock(return_value=True)
    return ha


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.chdir(REPO_ROOT)  # profiles/ is resolved relative to cwd
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, HELPER, 1000)
    secrets_path = tmp_path / "secrets.yaml"
    secrets_path.write_text("home_assistant:\n  url: http://test\n  token: test\n")
    engine = ExecutorEngine(str(config_path), str(secrets_path))
    engine.reload_config()  # prime mtime cache
    engine.ha_client = _ha_client()
    engine.dispatcher = ActionDispatcher(
        engine.ha_client,
        engine.config,
        shadow_mode=engine.config.shadow_mode,
        profile=engine.inverter_profile,
    )
    engine._gather_system_state = AsyncMock(return_value=SystemState())
    engine._get_planner_decision = AsyncMock(return_value=MagicMock())
    engine.history = MagicMock()
    return engine


async def _soc_write(dispatcher: ActionDispatcher, decision: Any = None) -> ActionResult:
    return await dispatcher._execute_action(  # type: ignore[protected-access]
        ModeAction(entity="soc_target", value=55),
        decision if decision is not None else MagicMock(),
        "charge",
    )


def _written_entities(engine: ExecutorEngine) -> list[str]:
    return [call.args[0] for call in engine.ha_client.set_number.await_args_list]


def _install_soc_write(engine: ExecutorEngine, before_write: Any = None) -> None:
    dispatcher = engine.dispatcher
    assert dispatcher is not None

    async def execute(decision: Any) -> list[ActionResult]:
        if before_write is not None:
            before_write()
        return [await _soc_write(dispatcher, decision)]

    dispatcher.execute = execute  # type: ignore[method-assign]


@pytest.mark.asyncio
async def test_soc_target_change_applies_on_next_tick(engine, tmp_path):
    _install_soc_write(engine)
    await engine._tick()
    assert _written_entities(engine) == [HELPER]

    _write_config(tmp_path / "config.yaml", PROGRAM_6, 2000)
    engine.reload_config()
    engine.ha_client = _ha_client()
    engine.dispatcher.ha = engine.ha_client

    await engine._tick()
    assert _written_entities(engine) == [PROGRAM_6]


def test_unchanged_config_does_not_replace_dispatcher_config(engine):
    dispatcher_config = engine.dispatcher.config
    engine.reload_config()
    engine.dispatcher.update_config(engine.config)
    assert engine.dispatcher.config is dispatcher_config


@pytest.mark.asyncio
async def test_reload_mid_tick_does_not_leak_into_running_tick(engine, tmp_path):
    def reload_from_api_thread() -> None:
        _write_config(tmp_path / "config.yaml", PROGRAM_6, 2000)
        worker = threading.Thread(target=engine.reload_config)
        worker.start()
        worker.join(timeout=5)
        assert not worker.is_alive()
        assert engine.config.inverter.soc_target == PROGRAM_6

    _install_soc_write(engine, before_write=reload_from_api_thread)
    await engine._tick()
    assert _written_entities(engine) == [HELPER]

    _install_soc_write(engine)
    engine.ha_client = _ha_client()
    engine.dispatcher.ha = engine.ha_client
    await engine._tick()
    assert _written_entities(engine) == [PROGRAM_6]


@pytest.mark.asyncio
async def test_deye_config_with_soc_helper_still_writes_helper(tmp_path, monkeypatch):
    monkeypatch.chdir(REPO_ROOT)
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, HELPER, 1000)
    config = load_executor_config(str(config_path))
    profile = load_profile("deye")
    valid, errors = profile.validate()
    assert valid, errors
    ha = _ha_client()
    result = await _soc_write(ActionDispatcher(ha, config, profile=profile))
    assert result.success
    assert [call.args[0] for call in ha.set_number.await_args_list] == [HELPER]
