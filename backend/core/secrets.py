import logging
from pathlib import Path
from typing import Any, cast

import yaml

logger = logging.getLogger("darkstar.core.secrets")


def load_home_assistant_config() -> dict[str, Any]:
    """Read Home Assistant configuration from secrets.yaml."""
    try:
        with Path("secrets.yaml").open() as file:
            raw_data: Any = yaml.safe_load(file)
            secrets: dict[str, Any] = (
                cast("dict[str, Any]", raw_data) if isinstance(raw_data, dict) else {}
            )
    except FileNotFoundError:
        return {}
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Could not load secrets.yaml: %s", exc)
        return {}

    ha_config: Any = secrets.get("home_assistant")
    if not isinstance(ha_config, dict):
        return {}
    return cast("dict[str, Any]", ha_config)


def load_notifications_config() -> dict[str, Any]:
    """Read notification secrets (e.g., Discord webhook) from secrets.yaml."""
    try:
        with Path("secrets.yaml").open() as file:
            raw_data: Any = yaml.safe_load(file)
            secrets: dict[str, Any] = (
                cast("dict[str, Any]", raw_data) if isinstance(raw_data, dict) else {}
            )
    except FileNotFoundError:
        return {}
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Could not load secrets.yaml: %s", exc)
        return {}

    notif_secrets: Any = secrets.get("notifications")
    if not isinstance(notif_secrets, dict):
        return {}
    return cast("dict[str, Any]", notif_secrets)


def load_yaml(path: str) -> dict[str, Any]:
    try:
        with Path(path).open() as f:
            raw_data: Any = yaml.safe_load(f)
            return cast("dict[str, Any]", raw_data) if isinstance(raw_data, dict) else {}
    except FileNotFoundError:
        return {}
