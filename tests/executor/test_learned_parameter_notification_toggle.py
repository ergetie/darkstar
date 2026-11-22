"""executor.notifications.on_learned_parameter_change: default, parse, API and save."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from ruamel.yaml import YAML

from backend.api.routers import executor as executor_router
from executor.config import NotificationConfig, load_executor_config

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_default_is_true_in_dataclass_and_template() -> None:
    assert NotificationConfig().on_learned_parameter_change is True
    template = yaml.safe_load((REPO_ROOT / "config.default.yaml").read_text(encoding="utf-8"))
    assert template["executor"]["notifications"]["on_learned_parameter_change"] is True


@pytest.mark.parametrize("value", [True, False])
def test_value_round_trips_through_the_executor_config(tmp_path: Path, value: bool) -> None:
    template = yaml.safe_load((REPO_ROOT / "config.default.yaml").read_text(encoding="utf-8"))
    template["executor"]["notifications"]["on_learned_parameter_change"] = value
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(template), encoding="utf-8")

    config = load_executor_config(str(path))

    assert config.notifications.on_learned_parameter_change is value


@pytest.mark.asyncio
async def test_get_reports_the_toggle_from_the_running_executor(monkeypatch) -> None:
    cfg = NotificationConfig(on_learned_parameter_change=False)
    executor = SimpleNamespace(config=SimpleNamespace(notifications=cfg))
    monkeypatch.setattr(executor_router, "get_executor_instance", lambda: executor)

    assert (await executor_router.get_notifications())["on_learned_parameter_change"] is False


@pytest.mark.asyncio
async def test_get_fallback_reads_the_file_and_defaults_true(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(executor_router, "get_executor_instance", lambda: None)
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump({"executor": {"notifications": {}}}), encoding="utf-8"
    )
    assert (await executor_router.get_notifications())["on_learned_parameter_change"] is True

    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump({"executor": {"notifications": {"on_learned_parameter_change": False}}}),
        encoding="utf-8",
    )
    assert (await executor_router.get_notifications())["on_learned_parameter_change"] is False


@pytest.mark.asyncio
async def test_key_survives_a_save(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(executor_router, "get_executor_instance", lambda: None)
    (tmp_path / "config.default.yaml").write_text(
        (REPO_ROOT / "config.default.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "config.yaml").write_text(
        (REPO_ROOT / "config.default.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )

    await executor_router.update_notifications(
        executor_router.FreeformBody.model_validate({"on_learned_parameter_change": False})
    )

    saved = YAML().load((tmp_path / "config.yaml").read_text())
    assert saved["executor"]["notifications"]["on_learned_parameter_change"] is False
