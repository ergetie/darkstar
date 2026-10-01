import contextlib
import copy
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, cast

import yaml

logger = logging.getLogger("darkstar.core.secrets")

# Thread-safe in-memory cache for parsed YAML files
_yaml_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_yaml_cache_lock = threading.Lock()
_secrets_write_lock = threading.Lock()
SECRETS_PATH = Path("secrets.yaml")


def load_home_assistant_config() -> dict[str, Any]:
    """Read Home Assistant configuration from secrets.yaml."""
    secrets = load_yaml("secrets.yaml")
    ha_config: Any = secrets.get("home_assistant")
    if not isinstance(ha_config, dict):
        return {}
    return cast("dict[str, Any]", ha_config)


def load_notifications_config() -> dict[str, Any]:
    """Read notification secrets (e.g., Discord webhook) from secrets.yaml."""
    secrets = load_yaml("secrets.yaml")
    notif_secrets: Any = secrets.get("notifications")
    if not isinstance(notif_secrets, dict):
        return {}
    return cast("dict[str, Any]", notif_secrets)


def save_home_assistant_config(url: str, token: str) -> None:
    """Atomically save validated Home Assistant credentials without changing other secrets."""
    if not url.strip() or not token.strip():
        raise ValueError("Home Assistant URL and token are required")

    from ruamel.yaml import YAML

    path = SECRETS_PATH
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096

    with _secrets_write_lock:
        if path.exists():
            with path.open(encoding="utf-8") as handle:
                data: Any = cast("Any", yaml).load(handle)
        else:
            data = {}
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ValueError("secrets.yaml must contain a YAML mapping")

        home_assistant: Any = cast("Any", data).get("home_assistant")
        if not isinstance(home_assistant, dict):
            home_assistant = {}
            data["home_assistant"] = home_assistant
        home_assistant["url"] = url.strip().rstrip("/")
        home_assistant["token"] = token.strip()

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=".secrets.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                temp_path.chmod(0o600)
                cast("Any", yaml).dump(data, handle)
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.replace(path)
            try:
                directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                logger.debug("Directory fsync is unavailable for %s", path.parent)
        finally:
            if temp_path is not None:
                with contextlib.suppress(FileNotFoundError):
                    temp_path.unlink()

        with _yaml_cache_lock:
            _yaml_cache.pop(str(path), None)
            _yaml_cache.pop("secrets.yaml", None)


def load_yaml(path: str) -> dict[str, Any]:
    try:
        p = Path(path)
        mtime = p.stat().st_mtime
    except FileNotFoundError:
        return {}

    with _yaml_cache_lock:
        if path in _yaml_cache:
            cached_mtime, cached_data = _yaml_cache[path]
            if cached_mtime == mtime:
                return copy.deepcopy(cached_data)

        try:
            with p.open() as f:
                raw_data: Any = yaml.safe_load(f)
                parsed = cast("dict[str, Any]", raw_data) if isinstance(raw_data, dict) else {}
        except FileNotFoundError:
            return {}

        _yaml_cache[path] = (mtime, parsed)
        return copy.deepcopy(parsed)
