"""POST /api/system/health/acknowledge records the measured ratio for an active notice."""

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import health
from backend.api.routers import system
from backend.core.onboarding_state import read_state

LOW = "pv_site_ratio_low"
HIGH = "pv_site_ratio_high"
URL = "/api/system/health/acknowledge"


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(system.router)
    return TestClient(app)


def _measured(ratio: float | None) -> None:
    health._pv_site_ratio_cache = (time.monotonic(), ratio)


def test_acknowledge_stores_the_cached_ratio(client):
    _measured(0.40)

    response = client.post(URL, json={"id": LOW})

    assert response.status_code == 200
    assert response.json() == {"id": LOW}
    assert read_state().acknowledged_warnings == {LOW: 0.40}


def test_acknowledge_without_active_notice_is_rejected_and_stores_nothing(client):
    _measured(0.80)
    assert client.post(URL, json={"id": LOW}).status_code == 409

    _measured(None)
    assert client.post(URL, json={"id": LOW}).status_code == 409

    assert read_state().acknowledged_warnings == {}


def test_acknowledge_other_side_than_active_notice_is_rejected(client):
    _measured(0.40)

    assert client.post(URL, json={"id": HIGH}).status_code == 409
    assert read_state().acknowledged_warnings == {}


def test_acknowledge_with_unknown_cache_is_rejected(client):
    health._pv_site_ratio_cache = None

    assert client.post(URL, json={"id": LOW}).status_code == 409


@pytest.mark.parametrize("body", [{"id": "Not A Valid Id!"}, {"id": ""}, {}, {"id": LOW, "x": 1}])
def test_invalid_body_is_rejected(client, body):
    _measured(0.40)

    assert client.post(URL, json=body).status_code == 422
    assert read_state().acknowledged_warnings == {}


def test_repeated_acknowledge_overwrites_the_ratio(client):
    _measured(0.40)
    client.post(URL, json={"id": LOW})
    _measured(0.30)
    client.post(URL, json={"id": LOW})

    assert read_state().acknowledged_warnings == {LOW: 0.30}
