"""POST /api/setup/sensor-units: draft config in, unit_needed out, no planner, nothing saved."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routers import setup

STATES = {
    "sensor.pv_a": {"state": "1200", "attributes": {}},
    "sensor.pv_b": {"state": "3", "attributes": {"unit_of_measurement": "kW"}},
    "sensor.load": {"state": "800", "attributes": {"unit_of_measurement": "W"}},
    "sensor.dead": {"state": "unavailable", "attributes": {}},
}


class FakeHA:
    """Mocked httpx client recording every request.

    With ``rendezvous`` set, each request waits (bounded) until that many requests are in
    flight at once, so overlap is observed structurally instead of through elapsed time.
    """

    def __init__(self):
        self.urls: list[str] = []
        self.rendezvous = 0
        self.in_flight = 0
        self.max_in_flight = 0
        self._gate: asyncio.Event | None = None

    async def get(self, url, **_kwargs):
        self.urls.append(url)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.rendezvous:
                if self._gate is None:
                    self._gate = asyncio.Event()
                if self.in_flight >= self.rendezvous:
                    self._gate.set()
                try:
                    await asyncio.wait_for(self._gate.wait(), timeout=2.0)
                except TimeoutError:
                    pass  # sequential reads never meet; max_in_flight stays below target
        finally:
            self.in_flight -= 1
        entity_id = url.rsplit("/", 1)[-1]
        response = MagicMock()
        if entity_id not in STATES:
            response.raise_for_status.side_effect = RuntimeError("404")
            return response
        response.json.return_value = {"entity_id": entity_id, **STATES[entity_id]}
        return response


@pytest.fixture
def ha():
    fake = FakeHA()
    with (
        patch(
            "backend.core.ha_client.secrets.load_home_assistant_config",
            return_value={"url": "http://ha.local", "token": "tok"},
        ),
        patch("backend.core.ha_client.get_ha_http_client", return_value=fake),
        patch("backend.core.readiness.run_isolated_plan", new=AsyncMock()) as planner,
    ):
        fake.planner = planner
        yield fake


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(setup.router)
    return TestClient(app)


def draft(pv, **extra):
    return {
        "config": {
            "system": {"has_solar": True, "has_battery": False},
            "input_sensors": {"pv_power": pv, "load_power": "sensor.load"},
            **extra,
        }
    }


def test_the_list_reflects_the_draft_selection(client, ha):
    first = client.post("/api/setup/sensor-units", json=draft("sensor.pv_a"))
    assert first.status_code == 200
    assert first.json() == {
        "unit_needed": [
            {
                "entity_id": "sensor.pv_a",
                "settings_path": "input_sensors.pv_power",
                "live_value": 1200.0,
                "override": None,
            }
        ]
    }
    second = client.post("/api/setup/sensor-units", json=draft("sensor.pv_b"))
    assert second.json() == {"unit_needed": []}


def test_override_in_the_draft_is_listed_with_its_value(client, ha):
    body = draft("sensor.pv_a", sensor_unit_overrides={"sensor.pv_a": "W"})
    assert client.post("/api/setup/sensor-units", json=body).json() == {
        "unit_needed": [
            {
                "entity_id": "sensor.pv_a",
                "settings_path": "input_sensors.pv_power",
                "live_value": 1200.0,
                "override": "W",
            }
        ]
    }


def test_unreadable_or_non_numeric_sensors_are_not_listed(client, ha):
    assert client.post("/api/setup/sensor-units", json=draft("sensor.dead")).json() == {
        "unit_needed": []
    }
    assert client.post("/api/setup/sensor-units", json=draft("sensor.missing")).json() == {
        "unit_needed": []
    }


def test_cost_is_one_state_read_per_referenced_entity_and_no_planner(client, ha, tmp_path):
    body = draft("sensor.pv_a")
    body["config"]["input_sensors"]["grid_power"] = "sensor.pv_a"  # same entity twice
    client.post("/api/setup/sensor-units", json=body)
    # Two distinct entities: one GET /api/states/<id> each, never the full /api/states list.
    assert sorted(ha.urls) == [
        "http://ha.local/api/states/sensor.load",
        "http://ha.local/api/states/sensor.pv_a",
    ]
    ha.planner.assert_not_awaited()


def test_reads_run_concurrently(client, ha):
    ha.rendezvous = 4
    body = draft("sensor.pv_a")
    body["config"]["input_sensors"].update(battery_power="sensor.pv_b", grid_power="sensor.dead")
    body["config"]["system"]["has_battery"] = True
    client.post("/api/setup/sensor-units", json=body)
    assert len(ha.urls) == 4
    # All four reads were in flight together; sequential reads would peak at 1.
    assert ha.max_in_flight == 4


def test_nothing_is_saved(client, ha, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client.post("/api/setup/sensor-units", json=draft("sensor.pv_a"))
    assert list(tmp_path.iterdir()) == []


def test_malformed_body_is_rejected(client, ha):
    assert client.post("/api/setup/sensor-units", json={"config": "x"}).status_code == 422
    assert client.post("/api/setup/sensor-units", json={}).status_code == 422
    assert ha.urls == []


def test_entity_ids_that_are_not_entity_ids_are_never_requested(client, ha):
    client.post("/api/setup/sensor-units", json=draft("sensor.x/../../config"))
    assert all("../" not in url for url in ha.urls)
