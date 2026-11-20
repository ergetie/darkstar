"""docker-compose.yml invariants for the updater sidecar."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def _volumes(service: str) -> list[str]:
    data = cast("dict[str, Any]", yaml.safe_load(COMPOSE.read_text(encoding="utf-8")))
    return [str(v) for v in data["services"][service]["volumes"]]


def test_updater_data_mount_is_writable() -> None:
    mounts = [m for m in _volumes("updater") if m.split(":")[1:2] == ["/data"]]
    assert mounts == ["./data:/data"]


def test_darkstar_has_no_docker_socket() -> None:
    assert not any("docker.sock" in m for m in _volumes("darkstar"))
