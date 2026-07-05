"""Shared fault-injection fixtures (stabilization-review-2, spec: fault-injection-testing).

Everything here is hermetic: no network, no live system. The FakeHAClient mimics
the real ``executor.actions.HAClient`` error contract — service calls raise
``HACallError``, ``get_state`` returns ``None`` on failure — so the real
dispatcher/engine error paths are exercised, not mocked away.
"""

import contextlib
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import pytz
from sqlalchemy import create_engine

from backend.learning.models import Base
from executor.actions import HACallError
from executor.config import ExecutorConfig
from executor.engine import ExecutorEngine

TZ = pytz.timezone("Europe/Stockholm")


class FakeHAClient:
    """Scriptable stand-in for executor.actions.HAClient.

    ``mode`` selects the failure behavior for all calls; ``entity_modes`` overrides
    per entity. Modes: "ok", "conn_refused", "timeout", "not_found", "server_error",
    "bad_request". All calls are recorded in ``calls``.
    """

    def __init__(self, states: dict[str, Any] | None = None):
        self.states: dict[str, Any] = states or {}
        self.mode = "ok"
        self.entity_modes: dict[str, str] = {}
        self.calls: list[tuple[str, str, Any]] = []

    def _fail(self, entity_id: str) -> None:
        mode = self.entity_modes.get(entity_id, self.mode)
        if mode == "ok":
            return
        messages = {
            "conn_refused": "Cannot connect to host 192.0.2.1:8123 (Connection refused) | (ClientConnectorError)",
            "timeout": "HA API call timed out after 3 attempts | (TimeoutError)",
            "not_found": f"404, message='Not Found', url='http://192.0.2.1:8123/api/states/{entity_id}'",
            "server_error": "HTTP 500 | Response: Internal Server Error | (ClientResponseError)",
            "bad_request": f"Failed to call service on {entity_id} | HTTP 400 | Response: Bad Request | (ClientResponseError)",
        }
        raise HACallError(messages[mode])

    async def get_state(self, entity_id: str) -> dict[str, Any] | None:
        self.calls.append(("get_state", entity_id, None))
        try:
            self._fail(entity_id)
        except HACallError:
            return None  # mirrors HAClient.get_state which swallows HACallError
        if entity_id not in self.states:
            return None
        return {"entity_id": entity_id, "state": str(self.states[entity_id]), "attributes": {}}

    async def get_state_value(self, entity_id: str) -> str | None:
        state = await self.get_state(entity_id)
        return None if state is None else state["state"]

    async def set_select_option(self, entity_id: str, option: str) -> bool:
        self.calls.append(("set_select_option", entity_id, option))
        self._fail(entity_id)
        self.states[entity_id] = option
        return True

    async def set_switch(self, entity_id: str, state: bool) -> bool:
        self.calls.append(("set_switch", entity_id, state))
        self._fail(entity_id)
        self.states[entity_id] = "on" if state else "off"
        return True

    async def set_number(self, entity_id: str, value: float) -> bool:
        self.calls.append(("set_number", entity_id, value))
        self._fail(entity_id)
        self.states[entity_id] = value
        return True

    async def set_input_number(self, entity_id: str, value: float) -> bool:
        self.calls.append(("set_input_number", entity_id, value))
        self._fail(entity_id)
        self.states[entity_id] = value
        return True

    async def call_service(self, domain: str, service: str, data: dict[str, Any]) -> None:
        self.calls.append((f"call_service:{domain}.{service}", str(data.get("entity_id")), data))
        self._fail(str(data.get("entity_id")))

    async def send_notification(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("send_notification", "", args))

    async def close(self) -> None:
        pass


@pytest.fixture
def temp_schedule():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        schedule_path = f.name
    yield schedule_path
    with contextlib.suppress(OSError):
        Path(schedule_path).unlink()


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    yield db_path
    with contextlib.suppress(OSError):
        Path(db_path).unlink()


def make_slot(start: datetime, **overrides: Any) -> dict[str, Any]:
    end = start + timedelta(minutes=15)
    slot = {
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "end_time_kepler": end.isoformat(),
        "battery_charge_kw": 0,
        "battery_discharge_kw": 0,
        "export_kwh": 0,
        "water_heating_kw": 0,
        "soc_target_percent": 50,
        "projected_soc_percent": 45,
    }
    slot.update(overrides)
    return slot


def write_schedule(
    path: str,
    slots: list[dict[str, Any]],
    generated_at: datetime | None = None,
    include_meta: bool = True,
) -> None:
    payload: dict[str, Any] = {"schedule": slots}
    if include_meta:
        payload["meta"] = {"generated_at": (generated_at or datetime.now(TZ)).isoformat()}
    Path(path).write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def fi_engine(temp_schedule, temp_db):
    """ExecutorEngine wired to a FakeHAClient (also injected into the real dispatcher)."""
    with patch("executor.engine.load_executor_config") as mock_config:
        mock_config.return_value = ExecutorConfig(
            schedule_path=temp_schedule,
            timezone="Europe/Stockholm",
        )
        with patch("executor.engine.load_yaml") as mock_yaml:
            mock_yaml.return_value = {}
            with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                engine = ExecutorEngine("config.yaml")
                engine.config.schedule_path = temp_schedule
                fake = FakeHAClient(
                    states={
                        "sensor.inverter_battery": "55",
                        "select.inverter_work_mode": "Zero Export To CT",
                        "switch.inverter_battery_grid_charging": "off",
                    }
                )
                engine.ha_client = fake  # type: ignore[assignment]
                if engine.dispatcher is not None:
                    engine.dispatcher.ha = fake  # type: ignore[assignment]
                engine.fake_ha = fake  # type: ignore[attr-defined]
                yield engine
