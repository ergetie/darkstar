"""Learned-parameter API: parameters, history, lock, unlock and recompute."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from backend.api.routers import learning as router_module
from backend.learning import learned_parameters as lp
from backend.learning.battery_estimators import (
    KEY_CHARGE_LOSS,
    KEY_DISCHARGE_EFFICIENCY,
    KEY_RTE,
    KEY_STANDBY_W,
)
from backend.learning.models import Base
from backend.learning.store import LearningStore
from backend.services import learned_parameters_service as service_module
from tests.learning.battery_synth import CAPACITY_KWH, TZ

CONFIG = {
    "timezone": "Europe/Stockholm",
    "system": {
        "battery": {
            "capacity_kwh": CAPACITY_KWH,
            "charge_efficiency": 0.92,
            "discharge_efficiency": 0.95,
        }
    },
}


@pytest_asyncio.fixture
async def api(tmp_path, monkeypatch):
    store = LearningStore(str(tmp_path / "learning.db"), TZ)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(router_module, "_get_learning_engine", lambda: SimpleNamespace(store=store))
    monkeypatch.setattr(router_module, "load_yaml", lambda _path: CONFIG)
    app = FastAPI()
    app.include_router(router_module.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        client.store = store  # type: ignore[attr-defined]
        yield client
    await store.close()


def _by_key(payload: dict) -> dict[str, dict]:
    return {item["key"]: item for item in payload["parameters"]}


async def _seed_learned(store: LearningStore, age_days: float) -> None:
    now = datetime.now(TZ)
    parameters = lp.LearnedParameterStore(store)
    for key, value in ((KEY_RTE, 0.962), (KEY_CHARGE_LOSS, 0.075)):
        stamp = now - timedelta(days=age_days)
        await parameters.save_state(
            lp.ParameterState(
                key=key,
                learned_value=value,
                applied_value=value,
                confidence=0.9,
                evidence={"days": 35},
                estimated_at=stamp,
                applied_at=stamp,
            ),
            now,
        )


@pytest.mark.asyncio
async def test_fresh_install_reports_fallback_sources(api) -> None:
    payload = (await api.get("/api/learning/parameters")).json()

    parameters = _by_key(payload)
    assert set(parameters) == {KEY_RTE, KEY_CHARGE_LOSS, KEY_STANDBY_W, KEY_DISCHARGE_EFFICIENCY}
    assert parameters[KEY_RTE]["source"] == "config"
    assert parameters[KEY_RTE]["learned_value"] is None
    assert parameters[KEY_DISCHARGE_EFFICIENCY]["source"] == "default"
    assert parameters[KEY_DISCHARGE_EFFICIENCY]["effective_value"] == 0.97
    assert parameters[KEY_DISCHARGE_EFFICIENCY]["bounds"] == {"min": 0.85, "max": 1.0}
    assert payload["effective"]["basis"] == "config"
    assert payload["effective"]["charge_efficiency"] == 0.92
    assert payload["effective"]["missing"] == [KEY_RTE, KEY_CHARGE_LOSS]


@pytest.mark.asyncio
async def test_learned_values_are_reported_with_evidence(api) -> None:
    await _seed_learned(api.store, 1)

    payload = (await api.get("/api/learning/parameters")).json()

    rte = _by_key(payload)[KEY_RTE]
    assert (rte["source"], rte["effective_value"], rte["learned_value"]) == (
        "learned",
        0.962,
        0.962,
    )
    assert rte["confidence"] == 0.9 and rte["evidence"] == {"days": 35}
    assert rte["estimated_at"] and rte["expires_at"]
    assert payload["effective"]["basis"] == "learned"
    assert payload["effective"]["charge_efficiency"] == pytest.approx(0.907, abs=0.001)


@pytest.mark.asyncio
async def test_expired_source_and_text_fields(api) -> None:
    await _seed_learned(api.store, 45)

    payload = (await api.get("/api/learning/parameters")).json()

    rte = _by_key(payload)[KEY_RTE]
    assert rte["source"] == "expired"
    assert rte["effective_value"] is None
    assert rte["learned_value"] == 0.962
    assert datetime.fromisoformat(rte["expires_at"]) < datetime.now(TZ)
    assert payload["effective"]["basis"] == "config"


@pytest.mark.asyncio
async def test_unknown_key_gives_404_everywhere(api) -> None:
    assert (
        await api.put("/api/learning/parameters/nope/lock", json={"value": 0.9})
    ).status_code == 404
    assert (await api.delete("/api/learning/parameters/nope/lock")).status_code == 404
    assert (
        await api.get("/api/learning/parameters/history", params={"key": "nope"})
    ).status_code == 404


@pytest.mark.asyncio
async def test_out_of_bounds_lock_is_rejected_and_changes_nothing(api) -> None:
    response = await api.put(
        f"/api/learning/parameters/{KEY_DISCHARGE_EFFICIENCY}/lock", json={"value": 0.5}
    )

    assert response.status_code == 422
    payload = (await api.get("/api/learning/parameters")).json()
    assert _by_key(payload)[KEY_DISCHARGE_EFFICIENCY]["locked"] is False
    assert (await api.get("/api/learning/parameters/history")).json()["history"] == []


@pytest.mark.asyncio
async def test_lock_shows_locked_then_unlock_restores_the_learned_value(api) -> None:
    await _seed_learned(api.store, 1)

    locked = await api.put(f"/api/learning/parameters/{KEY_RTE}/lock", json={"value": 0.95})
    assert locked.status_code == 200
    body = locked.json()
    assert (body["source"], body["effective_value"], body["locked"]) == ("locked", 0.95, True)
    assert body["learned_value"] == 0.962
    payload = (await api.get("/api/learning/parameters")).json()
    assert _by_key(payload)[KEY_RTE]["source"] == "locked"

    unlocked = await api.delete(f"/api/learning/parameters/{KEY_RTE}/lock")
    assert unlocked.json()["source"] == "learned"
    assert unlocked.json()["effective_value"] == 0.962


@pytest.mark.asyncio
async def test_inverter_discharge_efficiency_can_be_locked_without_an_estimator(api) -> None:
    response = await api.put(
        f"/api/learning/parameters/{KEY_DISCHARGE_EFFICIENCY}/lock", json={"value": 0.95}
    )

    body = response.json()
    assert (body["source"], body["effective_value"], body["learnable"]) == ("locked", 0.95, False)


@pytest.mark.asyncio
async def test_history_limit_validation_filter_and_order(api) -> None:
    for value in (0.95, 0.96):
        await api.put(
            f"/api/learning/parameters/{KEY_DISCHARGE_EFFICIENCY}/lock", json={"value": value}
        )
    await api.delete(f"/api/learning/parameters/{KEY_DISCHARGE_EFFICIENCY}/lock")

    for bad in (0, 201, -1):
        assert (
            await api.get("/api/learning/parameters/history", params={"limit": bad})
        ).status_code == 422
    full = (await api.get("/api/learning/parameters/history", params={"limit": 200})).json()[
        "history"
    ]
    assert [h["event"] for h in full] == ["unlocked", "lock_changed", "locked"]
    one = (await api.get("/api/learning/parameters/history", params={"limit": 1})).json()["history"]
    assert len(one) == 1
    other = (await api.get("/api/learning/parameters/history", params={"key": KEY_RTE})).json()[
        "history"
    ]
    assert other == []


@pytest.mark.asyncio
async def test_recompute_runs_the_service_and_lists_changes(api, monkeypatch) -> None:
    async def fake_run_once(_store):
        return [lp.AppliedChange(KEY_RTE, lp.EVENT_LEARNED, None, 0.962, 0.9)]

    monkeypatch.setattr(service_module.learned_parameters_service, "run_once", fake_run_once)

    response = await api.post("/api/learning/parameters/recompute")

    assert response.json() == {
        "changes": [
            {
                "key": KEY_RTE,
                "event": "learned",
                "old_value": None,
                "new_value": 0.962,
                "confidence": 0.9,
            }
        ]
    }


@pytest.mark.asyncio
async def test_recompute_error_is_a_500_not_a_crash(api, monkeypatch) -> None:
    async def boom(_store):
        raise RuntimeError("estimator exploded")

    monkeypatch.setattr(service_module.learned_parameters_service, "run_once", boom)

    response = await api.post("/api/learning/parameters/recompute")

    assert response.status_code == 500
