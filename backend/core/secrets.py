import copy
import logging
import threading
from pathlib import Path
from typing import Any, cast

import yaml

logger = logging.getLogger("darkstar.core.secrets")

# Thread-safe in-memory cache for parsed YAML files
_yaml_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_yaml_cache_lock = threading.Lock()


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
