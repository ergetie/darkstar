import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from ruamel.yaml import YAML

from backend.addon_bootstrap import apply_addon_options, merge_ha_secrets

ROOT = Path(__file__).resolve().parents[1]

SECRETS = """\
# my secrets
home_assistant:
  url: "{url}"
  token: "old-token"  # rotated

notifications:
  discord_webhook_url: "https://discord.com/api/webhooks/1/abc"

openrouter_api_key: "sk-or-keep"
"""


def _write_secrets(tmp_path: Path, url: str = "http://ha.local:8123") -> Path:
    path = tmp_path / "secrets.yaml"
    path.write_text(SECRETS.format(url=url), encoding="utf-8")
    return path


def test_merge_preserves_user_keys_and_rotates_token(tmp_path):
    path = _write_secrets(tmp_path)
    assert merge_ha_secrets(path, "new-token") is True
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert data["home_assistant"]["token"] == "new-token"
    assert data["notifications"]["discord_webhook_url"] == "https://discord.com/api/webhooks/1/abc"
    assert data["openrouter_api_key"] == "sk-or-keep"
    assert "# my secrets" in text


def test_merge_keeps_user_url(tmp_path):
    path = _write_secrets(tmp_path)
    merge_ha_secrets(path, "new-token")
    assert (
        yaml.safe_load(path.read_text(encoding="utf-8"))["home_assistant"]["url"]
        == "http://ha.local:8123"
    )


def test_merge_sets_url_when_empty(tmp_path):
    path = _write_secrets(tmp_path, url="")
    merge_ha_secrets(path, "new-token")
    assert (
        yaml.safe_load(path.read_text(encoding="utf-8"))["home_assistant"]["url"]
        == "http://supervisor/core"
    )


def test_merge_noop_when_unchanged(tmp_path):
    path = _write_secrets(tmp_path)
    merge_ha_secrets(path, "new-token")
    assert merge_ha_secrets(path, "new-token") is False


def test_merge_creates_missing_file_without_notifications(tmp_path):
    path = tmp_path / "sub" / "secrets.yaml"
    assert merge_ha_secrets(path, "tok") is True
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {
        "home_assistant": {"token": "tok", "url": "http://supervisor/core"}
    }


def test_merge_does_not_add_notifications_to_existing_file(tmp_path):
    path = tmp_path / "secrets.yaml"
    path.write_text("home_assistant:\n  token: old\n", encoding="utf-8")
    merge_ha_secrets(path, "tok")
    assert "notifications" not in yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("content", ["home_assistant: [unclosed\n  - : :\n", "- a\n- b\n"])
def test_merge_does_not_overwrite_unparseable_file(tmp_path, content):
    path = tmp_path / "secrets.yaml"
    path.write_text(content, encoding="utf-8")
    assert merge_ha_secrets(path, "tok") is False
    assert path.read_text(encoding="utf-8") == content


def _config(tmp_path: Path, tz: str = "Europe/Stockholm") -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(f"# keep me\ntimezone: {tz}\nsystem:\n  has_solar: true\n", encoding="utf-8")
    return path


def test_timezone_option_applied_when_different(tmp_path):
    path = _config(tmp_path)
    assert apply_addon_options(path, {"timezone": "Europe/Oslo"}) is True
    text = path.read_text(encoding="utf-8")
    assert yaml.safe_load(text)["timezone"] == "Europe/Oslo"
    assert "# keep me" in text


@pytest.mark.parametrize("options", [{"timezone": ""}, {"timezone": "  "}, {}, {"timezone": None}])
def test_timezone_option_ignored_when_empty_or_absent(tmp_path, options):
    path = _config(tmp_path)
    before = path.read_text(encoding="utf-8")
    assert apply_addon_options(path, options) is False
    assert path.read_text(encoding="utf-8") == before


def test_timezone_option_same_value_not_rewritten(tmp_path):
    path = _config(tmp_path, "Europe/Oslo")
    assert apply_addon_options(path, {"timezone": "Europe/Oslo"}) is False


def test_module_end_to_end(tmp_path):
    config = _config(tmp_path)
    secrets = _write_secrets(tmp_path)
    options = tmp_path / "options.json"
    options.write_text(
        json.dumps({"timezone": "Europe/Oslo", "log_level": "info"}), encoding="utf-8"
    )
    default = tmp_path / "config.default.yaml"
    default.write_text(config.read_text(encoding="utf-8"), encoding="utf-8")
    env = {**os.environ, "SUPERVISOR_TOKEN": "sup-tok", "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.addon_bootstrap",
            "--config",
            str(config),
            "--default-config",
            str(default),
            "--secrets",
            str(secrets),
            "--options",
            str(options),
            "--version-file",
            str(tmp_path / "VERSION"),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert yaml.safe_load(config.read_text(encoding="utf-8"))["timezone"] == "Europe/Oslo"
    data = yaml.safe_load(secrets.read_text(encoding="utf-8"))
    assert data["home_assistant"]["token"] == "sup-tok"
    assert data["openrouter_api_key"] == "sk-or-keep"
    assert "Darkstar Energy Manager" in result.stdout


def test_run_sh_files_identical():
    assert (ROOT / "darkstar/run.sh").read_bytes() == (ROOT / "darkstar-dev/run.sh").read_bytes()


@pytest.mark.parametrize("name", ["darkstar", "darkstar-dev"])
def test_addon_config_timezone_optional(name):
    data = YAML(typ="safe").load((ROOT / name / "config.yaml").read_text(encoding="utf-8"))
    assert data["schema"]["timezone"] == "str?"
    assert "timezone" not in data["options"]


def test_run_sh_no_longer_overwrites_secrets_or_uses_dead_options():
    text = (ROOT / "darkstar/run.sh").read_text(encoding="utf-8")
    assert "cat > /config/darkstar/secrets.yaml" not in text
    assert "python3 -m backend.addon_bootstrap" in text
    for dead in ("price_area", "PRICE_AREA", "battery_soc_sensor", "has_solar", "Europe/Stockholm"):
        assert dead not in text


@pytest.mark.parametrize("name", ["darkstar/run.sh", "darkstar-dev/run.sh"])
def test_run_sh_syntax(name):
    result = subprocess.run(
        ["bash", "-n", str(ROOT / name)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("dockerfile", ["Dockerfile", "darkstar/Dockerfile"])
def test_dockerfile_ships_backend_package(dockerfile):
    assert "COPY backend/ ./backend/" in (ROOT / dockerfile).read_text(encoding="utf-8")
    assert (ROOT / "backend/addon_bootstrap.py").is_file()
