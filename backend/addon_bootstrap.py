"""Home Assistant add-on bootstrap, invoked by ``run.sh`` as ``python3 -m backend.addon_bootstrap``.

Single writer of the add-on managed parts of ``secrets.yaml`` and ``config.yaml``:

- ``secrets.yaml``: ``home_assistant.token`` is always refreshed (the Supervisor token
  rotates), ``home_assistant.url`` is only set when missing or empty. Every other key and
  comment is preserved and no ``notifications`` section is ever created.
- ``config.yaml``: the add-on ``timezone`` option is applied only when non-empty.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping, MutableMapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

SUPERVISOR_URL = "http://supervisor/core"
_TAG = "[addon-bootstrap]"


def _log(message: str) -> None:
    sys.stdout.write(f"{_TAG} {message}\n")
    sys.stdout.flush()


def _make_yaml() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096  # Never wrap long entity ids
    return yaml


def _load(path: Path, yaml: YAML) -> Any:
    with path.open(encoding="utf-8") as handle:
        return yaml.load(handle)  # type: ignore


def _dump(data: Any, path: Path, yaml: YAML) -> None:
    with path.open("w", encoding="utf-8") as handle:
        yaml.dump(data, handle)  # type: ignore


def merge_ha_secrets(secrets_path: Path, supervisor_token: str) -> bool:
    """Set the Supervisor token and default URL in ``secrets.yaml``.

    Returns True when the file was written. An unparseable file, or one whose structure
    is not a mapping, is never rewritten.
    """
    yaml = _make_yaml()
    data: Any = None
    if secrets_path.exists():
        try:
            data = _load(secrets_path, yaml)
        except Exception as exc:
            _log(f"ERROR: cannot parse {secrets_path}, leaving it untouched: {type(exc).__name__}")
            return False
    if data is None:
        data = CommentedMap()
    if not isinstance(data, MutableMapping):
        _log(f"ERROR: {secrets_path} is not a mapping, leaving it untouched")
        return False
    root = cast("MutableMapping[str, Any]", data)

    section_raw: Any = root.get("home_assistant")
    if section_raw is None:
        section_raw = CommentedMap()
        root["home_assistant"] = section_raw
    elif not isinstance(section_raw, MutableMapping):
        _log(f"ERROR: home_assistant in {secrets_path} is not a mapping, leaving it untouched")
        return False
    section = cast("MutableMapping[str, Any]", section_raw)

    modified = False
    if section.get("token") != supervisor_token:
        section["token"] = supervisor_token
        modified = True
    if not section.get("url"):
        section["url"] = SUPERVISOR_URL
        modified = True

    if not modified:
        return False
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    _dump(data, secrets_path, yaml)
    _log("Updated secrets.yaml (Supervisor token)")
    return True


def apply_addon_options(config_path: Path, options: Mapping[str, Any]) -> bool:
    """Apply the add-on ``timezone`` option to ``config.yaml`` when non-empty and different.

    Returns True when the file was written.
    """
    timezone = options.get("timezone")
    if not isinstance(timezone, str) or not timezone.strip():
        return False
    timezone = timezone.strip()

    yaml = _make_yaml()
    try:
        config = _load(config_path, yaml)
    except Exception as exc:
        _log(f"ERROR: cannot read {config_path}, timezone option not applied: {type(exc).__name__}")
        return False
    if not isinstance(config, MutableMapping):
        _log(f"ERROR: {config_path} is not a mapping, timezone option not applied")
        return False
    mapping = cast("MutableMapping[str, Any]", config)
    if mapping.get("timezone") == timezone:
        return False

    mapping["timezone"] = timezone
    _dump(mapping, config_path, yaml)
    _log(f"Updated timezone from Add-on Config: {timezone}")
    return True


def _read_options(options_path: Path) -> dict[str, Any]:
    if not options_path.exists():
        return {}
    try:
        loaded = json.loads(options_path.read_text(encoding="utf-8"))
    except Exception as exc:
        _log(f"ERROR: cannot read {options_path}: {type(exc).__name__}")
        return {}
    return cast("dict[str, Any]", loaded) if isinstance(loaded, dict) else {}


def _run_migration(config_path: Path, default_path: Path) -> None:
    try:
        from backend.config_migration import migrate_config

        asyncio.run(migrate_config(str(config_path), str(default_path), strict_validation=False))
        _log("Config migration completed")
    except Exception as exc:
        _log(f"WARNING: config migration failed: {type(exc).__name__}: {exc}")


def _print_status(config_path: Path, app_version_path: Path, has_supervisor: bool) -> None:
    config: Any = None
    try:
        config = _load(config_path, _make_yaml())
    except Exception as exc:
        _log(f"WARNING: cannot read {config_path} for status: {type(exc).__name__}")
    cfg: Mapping[str, Any] = (
        cast("Mapping[str, Any]", config) if isinstance(config, Mapping) else {}
    )

    def shown(value: Any) -> str:
        return "not set" if value in (None, "") else str(value)

    prefix = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"
    version = "unknown"
    if app_version_path.exists():
        version = app_version_path.read_text(encoding="utf-8").strip() or "unknown"
    auth = "Supervisor Token (auto)" if has_supervisor else "Manual token (secrets.yaml)"
    lines = (
        "==========================================",
        f"  Darkstar Energy Manager {version}",
        "==========================================",
        f"  Timezone:      {shown(cfg.get('timezone'))}",
        f"  Log Level:     {shown(os.environ.get('LOG_LEVEL'))}",
        f"  HA Auth:       {auth}",
        "  Web UI:        http://localhost:5000",
        "==========================================",
    )
    for line in lines:
        sys.stdout.write(f"{prefix} {line}\n")
    sys.stdout.flush()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Darkstar add-on bootstrap")
    parser.add_argument("--config", type=Path, default=Path("/config/darkstar/config.yaml"))
    parser.add_argument("--default-config", type=Path, default=Path("/app/config.default.yaml"))
    parser.add_argument("--secrets", type=Path, default=Path("/config/darkstar/secrets.yaml"))
    parser.add_argument("--options", type=Path, default=Path("/data/options.json"))
    parser.add_argument("--version-file", type=Path, default=Path("/app/VERSION"))
    args = parser.parse_args(argv)

    supervisor_token = os.environ.get("SUPERVISOR_TOKEN", "")

    _run_migration(args.config, args.default_config)
    if supervisor_token:
        merge_ha_secrets(args.secrets, supervisor_token)
    apply_addon_options(args.config, _read_options(args.options))
    _print_status(args.config, args.version_file, bool(supervisor_token))
    return 0


if __name__ == "__main__":
    sys.exit(main())
