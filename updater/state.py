"""Persistent updater state (channel, last check, last apply) in the state volume."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, cast


class StateStore:
    def __init__(self, state_dir: str, default_channel: str) -> None:
        self._dir = Path(state_dir)
        self._file = self._dir / "state.json"
        self._lock = threading.RLock()
        self._default_channel = default_channel
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def log_path(self) -> Path:
        return self._dir / "apply.log"

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self._file.read_text())
        except (OSError, ValueError):
            return {}
        return cast("dict[str, Any]", data) if isinstance(data, dict) else {}

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._load().get(key, default)

    def update(self, **values: Any) -> None:
        with self._lock:
            data = self._load()
            data.update(values)
            tmp = self._file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            tmp.replace(self._file)

    @property
    def channel(self) -> str:
        value = self.get("channel")
        return value if value in ("dev", "stable") else self._default_channel
