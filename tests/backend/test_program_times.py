"""Deye program-time derivation, verification, health check and dismissal persistence."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core import onboarding_state
from backend.core.program_times import derive_program_time_entities, verify_program_times
from backend.health import HealthChecker

SOLARMAN_TIMES = [f"time.inverter_program_{n}_time" for n in range(1, 7)]


@pytest.mark.parametrize("program", range(1, 7))
def test_derives_solarman_names_from_any_program(program):
    assert derive_program_time_entities(f"number.inverter_program_{program}_soc") == SOLARMAN_TIMES


@pytest.mark.parametrize(
    "entity,expected",
    [
        ("number.inverter_prog6_soc", [f"time.inverter_prog{n}_time" for n in range(1, 7)]),
        ("number.deye_prog_6_soc_value", [f"time.deye_prog_{n}_time_value" for n in range(1, 7)]),
        ("input_number.program_6_soc", [f"time.program_{n}_time" for n in range(1, 7)]),
    ],
)
def test_derivation_variants(entity, expected):
    assert derive_program_time_entities(entity) == expected


@pytest.mark.parametrize(
    "entity",
    [
        "input_number.master_soc_target",
        "number.inverter_battery_soc",
        "number.inverter_program_7_soc",
        "number.inverter_prog6_capacity",
        "sensor.inverter_program_6_soc",
        "",
        None,
    ],
)
def test_underivable_entities_return_none(entity):
    assert derive_program_time_entities(entity) is None


def _states(values: dict[str, str | None]):
    async def fetch(entity_id: str) -> dict[str, Any] | None:
        value = values.get(entity_id, "00:00:00")
        return None if value is None else {"entity_id": entity_id, "state": value}

    return fetch


async def test_verify_ok_mismatch_unverifiable():
    soc = "number.inverter_program_6_soc"
    assert (await verify_program_times(soc, _states({})))["status"] == "ok"
    assert (
        await verify_program_times(soc, _states({SOLARMAN_TIMES[0]: "00:00"}))
    )["status"] == "ok"
    mismatch = await verify_program_times(soc, _states({SOLARMAN_TIMES[2]: "05:00:00"}))
    assert mismatch["status"] == "mismatch"
    assert mismatch["mismatches"] == [{"entity_id": SOLARMAN_TIMES[2], "value": "05:00:00"}]
    for missing in (None, "unavailable", "unknown"):
        result = await verify_program_times(soc, _states({SOLARMAN_TIMES[5]: missing}))
        assert result["status"] == "unverifiable"
    helper = await verify_program_times("input_number.master_soc_target", _states({}))
    assert helper["status"] == "unverifiable"


def _checker(soc_target: str, profile: str = "deye") -> HealthChecker:
    checker = HealthChecker()
    checker._config = {
        "system": {"inverter_profile": profile},
        "executor": {"inverter": {"soc_target": soc_target}},
    }
    checker._secrets = {"home_assistant": {"url": "http://ha", "token": "t"}}
    return checker


async def _run_health(checker: HealthChecker, states: dict[str, str | None]):
    async def get(url: str, **_kwargs: Any) -> MagicMock:
        entity_id = url.rsplit("/", 1)[-1]
        value = states.get(entity_id, "00:00:00")
        response = MagicMock()
        response.status_code = 404 if value is None else 200
        response.json.return_value = {"entity_id": entity_id, "state": value}
        return response

    client = MagicMock()
    client.get = get
    with patch("backend.core.ha_client.get_ha_http_client", return_value=client):
        return await checker.check_program_times()


async def test_health_all_midnight_reports_nothing():
    assert await _run_health(_checker("number.inverter_program_6_soc"), {}) == []


async def test_health_mismatch_is_warning_naming_entity_and_value():
    issues = await _run_health(
        _checker("number.inverter_program_6_soc"), {"time.inverter_program_3_time": "05:00:00"}
    )
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert "time.inverter_program_3_time" in issues[0].message
    assert "05:00:00" in issues[0].message


@pytest.mark.parametrize(
    "soc_target,states",
    [
        ("input_number.master_soc_target", {}),
        ("number.inverter_program_6_soc", {"time.inverter_program_1_time": None}),
        ("number.inverter_program_6_soc", {"time.inverter_program_4_time": "unavailable"}),
    ],
)
async def test_health_unverifiable_reports_nothing(soc_target, states):
    assert await _run_health(_checker(soc_target), states) == []


async def test_health_skips_other_profiles():
    issues = await _run_health(
        _checker("number.inverter_program_6_soc", profile="sungrow"),
        {"time.inverter_program_3_time": "05:00:00"},
    )
    assert issues == []


@pytest.fixture
def client(tmp_path, monkeypatch):
    from backend.api.routers import setup

    monkeypatch.setattr(onboarding_state, "STATE_FILE_PATH", tmp_path / "onboarding.json")
    app = FastAPI()
    app.include_router(setup.router)
    return TestClient(app)


def test_notice_dismissal_persists_and_survives_progress_saves(client):
    notice = "deye.program_times_unverified"
    response = client.post("/api/setup/onboarding/dismissed-notices", json={"id": notice})
    assert response.status_code == 200
    assert response.json()["dismissed_notices"] == [notice]
    client.post("/api/setup/onboarding/dismissed-notices", json={"id": notice})
    client.put(
        "/api/setup/onboarding",
        json={"status": "in_progress", "current_step": "profile", "completed_steps": []},
    )
    state = client.get("/api/setup/onboarding").json()
    assert state["dismissed_notices"] == [notice]
    assert state["current_step"] == "profile"
    assert onboarding_state.read_state().dismissed_notices == [notice]


def test_notice_dismissal_rejects_invalid_id(client):
    response = client.post("/api/setup/onboarding/dismissed-notices", json={"id": "Bad Id!"})
    assert response.status_code == 422


def test_program_times_endpoint_uses_query_entity(client):
    async def fetch(entity_id: str) -> dict[str, Any]:
        return {"state": "00:00:00"}

    with patch("backend.core.ha_client.get_ha_entity_state", new=fetch):
        response = client.get(
            "/api/setup/program-times", params={"soc_target": "number.inverter_program_6_soc"}
        )
    assert response.json()["status"] == "ok"
