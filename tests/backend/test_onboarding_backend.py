"""Contract tests for onboarding discovery, matching, persistence and isolation."""

import copy
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routers import ha, setup
from backend.config_migration import _migrate_synthetic_load
from backend.core import ha_registry, onboarding_state, readiness
from backend.core.entity_matcher import build_suggestions, rank_brands, rank_candidates
from backend.core.entity_roles import ROLE_PATHS, ROLE_RULES
from backend.core.ha_client import get_dummy_load_profile
from backend.core.secrets import load_yaml
from executor.profiles import load_profile, parse_profile


@pytest.fixture
def config():
    return copy.deepcopy(load_yaml("config.default.yaml"))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(onboarding_state, "STATE_FILE_PATH", tmp_path / "onboarding.json")
    app = FastAPI()
    app.include_router(ha.router)
    app.include_router(setup.router)
    return TestClient(app)


def entity(eid="sensor.battery_soc", **kwargs):
    return {
        "entity_id": eid,
        "domain": eid.split(".")[0],
        "friendly_name": "Battery state of charge",
        "platform": "solarman",
        "device_class": "battery",
        "unit_of_measurement": "%",
        "state": "50",
        **kwargs,
    }


def test_independent_weights_and_domain():
    rules = {
        "domain": ["sensor"],
        "integration": ["other"],
        "device_class": ["battery"],
        "unit": ["%"],
    }
    result = rank_candidates([entity(), entity("number.battery_soc")], rules)
    assert len(result) == 1
    assert result[0]["score"] == 35
    assert result[0]["reasons"] == ["device_class", "unit"]


def test_confidence_top_five_and_margin():
    rules = {**ROLE_RULES["battery_soc"], "integration": ["solarman"]}
    assert rank_candidates([entity()], rules)[0]["confidence"] == "high"
    candidates = rank_candidates([entity(f"sensor.battery_soc_{i}") for i in range(7)], rules)
    assert len(candidates) == 5
    assert all(c["confidence"] == "medium" for c in candidates)


def test_cumulative_counter_roles_are_gone():
    assert not [role for role in ROLE_RULES if role.startswith("total_")]
    assert not [role for role in ROLE_PATHS if role.startswith("total_")]


def test_nested_patch_current_and_missing():
    rules = {**ROLE_RULES["battery_soc"], "integration": ["solarman"]}
    definitions = {
        "input_sensors.battery_soc": {"rules": rules, "required": True},
        "executor.inverter.work_mode": {"rules": {"domain": ["select"]}, "required": True},
    }
    result = build_suggestions(
        {"input_sensors": {"battery_soc": "sensor.old"}}, [entity()], definitions
    )
    assert result["patch"] == {"input_sensors": {"battery_soc": "sensor.battery_soc"}}
    assert result["current"]["input_sensors.battery_soc"] == "sensor.old"
    assert result["missing_required"] == ["executor.inverter.work_mode"]


def test_load_power_suggestions_exclude_phase_sensors(config):
    definitions = {
        "input_sensors.load_power": {
            "rules": ROLE_RULES["load_power"],
            "required": True,
            "exclude_phase_specific": True,
        }
    }
    aggregate = entity(
        "sensor.inverter_load_power",
        friendly_name="Inverter Load Power",
        device_class="power",
        unit_of_measurement="W",
    )
    phase = entity(
        "sensor.inverter_load_l1_power",
        friendly_name="Inverter Load L1 Power",
        device_class="power",
        unit_of_measurement="W",
    )

    result = build_suggestions(config, [phase, aggregate], definitions)
    assert [c["entity_id"] for c in result["candidates"]["input_sensors.load_power"]] == [
        aggregate["entity_id"]
    ]

    phase_only = build_suggestions(config, [phase], definitions)
    assert phase_only["candidates"]["input_sensors.load_power"] == []
    assert phase_only["missing_required"] == ["input_sensors.load_power"]


@pytest.mark.parametrize(
    "name,integration,manufacturer",
    [
        ("deye", "solarman", "Deye"),
        ("fronius", "fronius", "Fronius"),
        ("sungrow", "sungrow", "Sungrow"),
    ],
)
def test_shipped_profiles_and_brand_fixtures(name, integration, manufacturer):
    profiles = [load_profile(n) for n in ("deye", "fronius", "sungrow", "generic")]
    selected = next(p for p in profiles if p.metadata.name == name)
    assert all(e.match for e in selected.get_required_entities().values())
    assert (
        rank_brands([entity(platform=integration, manufacturer=manufacturer)], profiles)[0]["name"]
        == name
    )
    if name == "fronius":
        assert all(e.default_entity is None for e in selected.entities.values())
    if name == "deye":
        assert selected.behavior.write_threshold_a == 5
    assert rank_brands([entity(platform="unknown", manufacturer="unknown")], profiles) == []


@pytest.mark.parametrize("rules", [{"bogus": []}, {"entity_id_regex": "("}, {"unit": "W"}])
def test_profile_rules_validation(rules):
    data = load_yaml("profiles/deye.yaml")
    data["entities"]["work_mode"]["match"] = rules
    valid, errors = parse_profile(data).validate()
    assert not valid
    assert any("work_mode" in error for error in errors)


def test_migration_and_synthetic_precedence(config):
    cfg = {"input_sensors": {"total_load_consumption": "18"}}
    _, changed = _migrate_synthetic_load(cfg)
    assert changed and cfg["input_sensors"] == {
        "total_load_consumption": "",
        "synthetic_daily_load_kwh": 18,
    }
    assert not _migrate_synthetic_load(cfg)[1]
    config["input_sensors"] = {"synthetic_daily_load_kwh": 20, "total_load_consumption": ""}
    assert sum(get_dummy_load_profile(config)) == pytest.approx(20)
    config["input_sensors"]["total_load_consumption"] = "sensor.house_energy"
    assert not _migrate_synthetic_load(config)[1]
    # The synthetic estimate is the fallback whenever load power history is unusable
    assert sum(get_dummy_load_profile(config)) == pytest.approx(20)


def test_onboarding_roundtrip_validation_and_corruption(client, tmp_path):
    assert client.get("/api/setup/onboarding").json()["status"] == "not_started"
    update = {
        "status": "in_progress",
        "current_step": "pricing",
        "completed_steps": ["connect", "system"],
    }
    assert client.put("/api/setup/onboarding", json=update).status_code == 200
    saved = client.get("/api/setup/onboarding").json()
    assert saved["completed_steps"] == update["completed_steps"]
    assert saved["current_step"] == "pricing" and saved["updated_at"]
    assert client.put("/api/setup/onboarding", json={"status": "invalid"}).status_code == 422
    assert client.get("/api/setup/onboarding").json() == saved
    (tmp_path / "onboarding.json").write_text("{broken")
    assert client.get("/api/setup/onboarding").json()["status"] == "not_started"


async def test_registry_protocol_join_cache_and_token_scope(monkeypatch):
    ha_registry._CACHE.clear()
    socket = MagicMock()
    socket.recv = AsyncMock(
        side_effect=[
            json.dumps(x)
            for x in [
                {"type": "auth_required"},
                {"type": "auth_ok"},
                {
                    "id": 1,
                    "type": "result",
                    "success": True,
                    "result": [
                        {"entity_id": "sensor.x", "platform": "solarman", "device_id": "dev"}
                    ],
                },
                {
                    "id": 2,
                    "type": "result",
                    "success": True,
                    "result": [{"id": "dev", "manufacturer": "Deye", "model": "SUN"}],
                },
            ]
        ]
    )
    socket.send = AsyncMock()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=socket)
    context.__aexit__ = AsyncMock(return_value=False)
    with patch("backend.core.ha_registry.websockets.connect", return_value=context) as connect:
        first = await ha_registry.get_registry("http://ha/", "token")
        second = await ha_registry.get_registry("http://ha", "token")
        assert first == second and first[1]
        assert first[0]["sensor.x"]["manufacturer"] == "Deye"
        connect.assert_called_once_with("ws://ha/api/websocket", max_size=10485760)
        assert [json.loads(call.args[0]).get("id") for call in socket.send.call_args_list] == [
            None,
            1,
            2,
        ]
    with patch(
        "backend.core.ha_registry._fetch_registry", new=AsyncMock(side_effect=TimeoutError)
    ) as fetch:
        assert await ha_registry.get_registry("http://ha", "different") == ({}, False)
        fetch.assert_awaited_once()
    ha_registry._CACHE.clear()


@pytest.mark.parametrize("available", [True, False])
async def test_discovery_with_and_without_registry(available):
    response = httpx.Response(
        200,
        json=[
            {
                "entity_id": "sensor.x",
                "state": "7",
                "attributes": {"state_class": "total", "unit_of_measurement": "kWh"},
            }
        ],
        request=httpx.Request("GET", "http://ha/api/states"),
    )
    with (
        patch(
            "backend.core.ha_registry.load_home_assistant_config",
            return_value={"url": "http://ha", "token": "secret"},
        ),
        patch(
            "backend.core.ha_registry.get_ha_http_client",
            return_value=MagicMock(get=AsyncMock(return_value=response)),
        ),
        patch(
            "backend.core.ha_registry.get_registry",
            new=AsyncMock(
                return_value=(
                    {"sensor.x": {"platform": "solarman", "manufacturer": "Deye"}}
                    if available
                    else {},
                    available,
                )
            ),
        ),
    ):
        result = await ha_registry.discover_entities()
    assert result["registry_available"] == available
    assert result["entities"][0]["state_class"] == "total"
    assert result["entities"][0]["platform"] == ("solarman" if available else None)


@pytest.mark.parametrize(
    "addon,body,expected",
    [
        (False, None, "http://saved"),
        (False, {"url": "http://typed", "token": "typed"}, "http://typed"),
        (True, {"url": "http://typed", "token": "typed"}, "http://saved"),
    ],
)
def test_connection_body_and_addon(client, monkeypatch, addon, body, expected):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "supervisor") if addon else monkeypatch.delenv(
        "SUPERVISOR_TOKEN", raising=False
    )
    responses = [
        httpx.Response(200, json={"message": "API running"}),
        httpx.Response(200, json={"version": "2026.10"}),
    ]
    get = AsyncMock(side_effect=responses)
    with (
        patch(
            "backend.api.routers.ha.load_home_assistant_config",
            return_value={"url": "http://saved", "token": "saved"},
        ),
        patch("backend.api.routers.ha.get_ha_http_client", return_value=MagicMock(get=get)),
        patch("backend.core.ha_registry.get_registry", new=AsyncMock(return_value=({}, True))),
    ):
        result = client.post("/api/ha/test", json=body) if body else client.post("/api/ha/test")
    assert result.json()["ha_version"] == "2026.10"
    assert get.call_args_list[0].args[0] == expected + "/api/"


@pytest.mark.parametrize(
    "country,currency,expected", [("SE", None, "SEK"), ("NO", None, None), ("NO", "NOK", "NOK")]
)
def test_core_config_currency(client, country, currency, expected):
    response = httpx.Response(
        200,
        json={"country": country, "currency": currency, "latitude": 60},
        request=httpx.Request("GET", "http://ha/api/config"),
    )
    with (
        patch(
            "backend.api.routers.ha.load_home_assistant_config",
            return_value={"url": "http://ha", "token": "t"},
        ),
        patch(
            "backend.core.ha_client.get_ha_http_client",
            return_value=MagicMock(get=AsyncMock(return_value=response)),
        ),
    ):
        result = client.get("/api/ha/core-config")
    assert result.json()["currency"] == expected
    assert len(result.json()) == 6 and "price_area" not in result.json()


def test_core_config_unreachable(client):
    with (
        patch(
            "backend.api.routers.ha.load_home_assistant_config",
            return_value={"url": "http://ha", "token": "t"},
        ),
        patch(
            "backend.core.ha_client.get_ha_http_client",
            return_value=MagicMock(get=AsyncMock(side_effect=httpx.ConnectError("offline"))),
        ),
    ):
        assert client.get("/api/ha/core-config").status_code == 502


async def test_isolated_plan_fresh_no_live_service(config):
    inputs = {"fresh": "input"}
    with (
        patch(
            "backend.core.forecasts.get_all_input_data", new=AsyncMock(return_value=inputs)
        ) as fetch,
        patch("planner.pipeline.generate_schedule", new=AsyncMock(return_value=[1, 2])) as generate,
        patch(
            "backend.services.planner_service.planner_service.run_once",
            new=AsyncMock(side_effect=AssertionError("live planner used")),
        ),
        patch(
            "executor.engine.ExecutorEngine.run_once",
            new=AsyncMock(side_effect=AssertionError("executor used")),
        ),
        patch(
            "executor.actions.HAClient.call_service",
            new=AsyncMock(side_effect=AssertionError("HA service called")),
        ) as services,
    ):
        assert await readiness.run_isolated_plan(config) == 2
        assert await readiness.run_isolated_plan(config) == 2
        assert fetch.await_count == 2
        assert generate.call_args.kwargs["save_to_file"] is False
        assert generate.call_args.kwargs["publish_state"] is False
        assert generate.call_args.kwargs["config"] is not config
        services.assert_not_awaited()


async def readiness_with(config, states, plan=3):
    with (
        patch(
            "backend.core.readiness.load_home_assistant_config",
            return_value={"url": "http://ha", "token": "t"},
        ),
        patch("backend.health.HealthChecker.check_ha_connection", new=AsyncMock(return_value=[])),
        patch(
            "backend.core.readiness.discover_entities",
            new=AsyncMock(return_value={"entities": states}),
        ),
        patch("backend.core.prices.get_nordpool_data", new=AsyncMock(return_value=[{}])),
        patch("backend.core.readiness.run_isolated_plan", new=AsyncMock(return_value=plan)),
    ):
        return await readiness.check_readiness(config)


async def test_readiness_sensor_hints_are_role_specific_and_only_for_issues(config):
    config["input_sensors"]["battery_soc"] = "sensor.battery_soc"
    config["system"]["has_battery"] = True
    battery_soc = entity("sensor.battery_soc", state="50", unit_of_measurement="%")

    passed = await readiness_with(config, [battery_soc])
    passed_check = next(check for check in passed["checks"] if check["id"] == "battery_soc")
    assert passed_check["status"] == "pass"
    assert passed_check["fix_hint"] == ""

    battery_soc.update(state="50", unit_of_measurement="W")
    warned = await readiness_with(config, [battery_soc])
    warned_check = next(check for check in warned["checks"] if check["id"] == "battery_soc")
    assert warned_check["status"] == "warn"
    assert "0 and 100 %" in warned_check["fix_hint"]
    assert "W or kW" not in warned_check["fix_hint"]


async def test_readiness_flags_dual_and_sensor_states(config):
    config["system"].update(
        has_battery=False,
        has_solar=False,
        has_water_heater=False,
        has_ev_charger=False,
        grid_meter_type="dual",
    )
    roles = ("load_power", "grid_import_power", "grid_export_power")
    config["input_sensors"].update({role: "sensor." + role for role in roles})
    states = [entity("sensor." + role, unit_of_measurement="W", state="300") for role in roles]
    result = await readiness_with(config, states)
    assert result["ready"]
    checks = {c["id"]: c for c in result["checks"]}
    assert checks["grid_power"]["status"] == checks["ev"]["status"] == "skipped"
    assert checks["plan"]["status"] == "pass"
    states[0]["state"] = "unavailable"
    assert not (await readiness_with(config, states))["ready"]
    states[0].update(state="3", unit_of_measurement="kWh")
    assert (
        next(
            c for c in (await readiness_with(config, states))["checks"] if c["id"] == "load_power"
        )["status"]
        == "warn"
    )


async def test_readiness_placeholder_and_battery_w(config):
    config["system"]["location"]["elevation"] = 100
    result = await readiness_with(config, [])
    checks = {c["id"]: c for c in result["checks"]}
    assert not result["ready"]
    assert checks["location"]["status"] == "fail"
    config["battery"]["max_charge_w"] = 0
    result = await readiness_with(config, [])
    assert next(c for c in result["checks"] if c["id"] == "battery_limits")["status"] == "fail"


@pytest.mark.parametrize("name", ["deye", "fronius", "sungrow"])
def test_profile_control_candidates_from_fixtures(name):
    from pathlib import Path

    entities = json.loads(Path(f"tests/fixtures/onboarding/{name}.json").read_text())
    profile = load_profile(name)
    for key, definition in profile.get_required_entities().items():
        candidates = rank_candidates(
            entities,
            {"domain": [definition.domain], **definition.match},
            default_entity=definition.default_entity,
        )
        expected = next(e["entity_id"] for e in entities if e["role_key"] == key)
        assert candidates[0]["entity_id"] == expected


async def test_readiness_timeout_warn(config):
    config["system"].update(
        has_battery=False, has_solar=False, has_water_heater=False, has_ev_charger=False
    )
    config["input_sensors"].update(load_power="sensor.load_power", grid_power="sensor.grid_power")
    states = [
        entity("sensor.load_power", unit_of_measurement="W"),
        entity("sensor.grid_power", unit_of_measurement="W"),
    ]
    with (
        patch(
            "backend.core.readiness.load_home_assistant_config",
            return_value={"url": "http://ha", "token": "t"},
        ),
        patch("backend.health.HealthChecker.check_ha_connection", new=AsyncMock(return_value=[])),
        patch(
            "backend.core.readiness.discover_entities",
            new=AsyncMock(return_value={"entities": states}),
        ),
        patch("backend.core.prices.get_nordpool_data", new=AsyncMock(return_value=[{}])),
        patch("backend.core.readiness.run_isolated_plan", new=AsyncMock(side_effect=TimeoutError)),
    ):
        result = await readiness.check_readiness(config)
    assert result["ready"]
    assert next(c for c in result["checks"] if c["id"] == "plan")["status"] == "warn"


async def test_connection_rejected_credentials(client, monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    with patch(
        "backend.api.routers.ha.get_ha_http_client",
        return_value=MagicMock(get=AsyncMock(return_value=httpx.Response(401))),
    ):
        result = client.post("/api/ha/test", json={"url": "http://typed", "token": "wrong"})
    assert result.json() == {"status": "error", "message": "Authentication failed"}


async def test_save_ha_connection_persists_only_after_success(client, tmp_path, monkeypatch):
    import yaml

    from backend.core import secrets

    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    secret_path = tmp_path / "secrets.yaml"
    secret_path.write_text("notifications:\n  api_key: keep-me\n", encoding="utf-8")
    monkeypatch.setattr(secrets, "SECRETS_PATH", secret_path)
    ok_client = MagicMock()
    ok_client.get = AsyncMock(
        side_effect=[
            httpx.Response(200, json={}),
            httpx.Response(200, json={"version": "2026.10"}),
        ]
    )
    with (
        patch("backend.api.routers.ha.get_ha_http_client", return_value=ok_client),
        patch(
            "backend.core.ha_registry.get_registry",
            new=AsyncMock(return_value=({}, False)),
        ),
    ):
        response = client.put(
            "/api/ha/config",
            json={"url": "http://typed-ha/", "token": "typed-token"},
        )
    assert response.status_code == 200
    assert yaml.safe_load(secret_path.read_text(encoding="utf-8")) == {
        "notifications": {"api_key": "keep-me"},
        "home_assistant": {"url": "http://typed-ha", "token": "typed-token"},
    }

    failure_path = tmp_path / "failure.yaml"
    failure_path.write_text("home_assistant:\n  url: http://old\n  token: old-token\n", encoding="utf-8")
    monkeypatch.setattr(secrets, "SECRETS_PATH", failure_path)
    failed_client = MagicMock()
    failed_client.get = AsyncMock(return_value=httpx.Response(401))
    with patch("backend.api.routers.ha.get_ha_http_client", return_value=failed_client):
        response = client.put(
            "/api/ha/config",
            json={"url": "http://typed-ha", "token": "rejected-token"},
        )
    assert response.status_code == 400
    assert yaml.safe_load(failure_path.read_text(encoding="utf-8")) == {
        "home_assistant": {"url": "http://old", "token": "old-token"}
    }


async def test_profile_and_role_endpoints_nested_patch(client, config):
    profile = load_profile("deye")
    control = entity(
        profile.entities["work_mode"].default_entity, friendly_name="Inverter work mode"
    )
    with (
        patch("backend.core.secrets.load_yaml", return_value=config),
        patch(
            "backend.core.ha_registry.discover_entities",
            new=AsyncMock(
                return_value={"entities": [control, entity()], "registry_available": True}
            ),
        ),
    ):
        roles = client.get("/api/setup/suggestions?roles=battery_soc").json()
        assert "patch" in roles and "current" in roles and roles["suggested_profile"] == "deye"
        assert client.get("/api/setup/suggestions?roles=bogus").status_code == 422
        from backend.api.routers.executor import get_profile_suggestions

        result = await get_profile_suggestions("deye")
        assert result["patch"]["executor"]["inverter"]["work_mode"] == control["entity_id"]


async def test_real_pipeline_does_not_publish_readiness_state(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from planner.pipeline import PlannerPipeline
    from tests.fault_injection.test_dst_transitions import make_inputs, planner_config

    monkeypatch.chdir(tmp_path)
    cfg = planner_config()
    cfg["system"]["has_ev_charger"] = True
    start = (datetime.now(UTC) + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
    inputs = make_inputs(start, hours=6)
    inputs["initial_state"].update(vacation_mode=True, water_heated_today_kwh=3)
    (tmp_path / "schedule.json").write_text('{"live":true}')
    with (
        patch("planner.pipeline.save_schedule_to_json", new=AsyncMock()) as schedule,
        patch("planner.pipeline._persist_ev_multi_day_state") as ev,
        patch("planner.pipeline.save_last_anti_legionella") as water,
        patch("planner.pipeline.load_last_anti_legionella", return_value=None),
        patch("backend.core.ev_state.read_ev_state", return_value={}),
    ):
        result = await PlannerPipeline(cfg).generate_schedule(
            inputs, mode="baseline", save_to_file=False, publish_state=False, now_override=start
        )
    assert len(result) > 0
    schedule.assert_not_awaited()
    ev.assert_not_called()
    water.assert_not_called()
    assert (tmp_path / "schedule.json").read_text() == '{"live":true}'


def test_device_role_domains_follow_existing_controls():
    assert set(ROLE_RULES["water_heater_control"]["domain"]) == {
        "switch",
        "input_boolean",
        "number",
        "input_number",
    }
    assert {"select", "input_select"} <= set(ROLE_RULES["ev_switch"]["domain"])


@pytest.mark.parametrize(
    "field,domain",
    [("ha_ready_by_entity", "input_datetime"), ("ha_target_soc_entity", "input_number")],
)
async def test_readiness_checks_configured_ev_goal_helpers(config, field, domain):
    config["system"].update(
        has_battery=False, has_solar=False, has_water_heater=False, has_ev_charger=True
    )
    config["input_sensors"].update(load_power="sensor.load_power", grid_power="sensor.grid_power")
    charger = config["ev_chargers"][0]
    charger.update(
        enabled=True,
        switch_entity="switch.ev",
        soc_sensor="sensor.ev_soc",
        plug_sensor="binary_sensor.ev_plug",
    )
    charger[field] = f"{domain}.ev_goal"
    states = [
        entity("sensor.load_power", unit_of_measurement="W"),
        entity("sensor.grid_power", unit_of_measurement="W"),
        entity("switch.ev"),
        entity("sensor.ev_soc"),
        entity("binary_sensor.ev_plug"),
    ]
    result = await readiness_with(config, states)
    check = next(c for c in result["checks"] if c["id"] == f"ev_0_{field}")
    assert check["status"] == "fail" and not result["ready"]
    states.append(entity(charger[field]))
    result = await readiness_with(config, states)
    assert next(c for c in result["checks"] if c["id"] == f"ev_0_{field}")["status"] == "pass"


async def test_readiness_fully_configured_battery_profile(config):
    config["system"].update(inverter_profile="deye", has_water_heater=False, has_ev_charger=False)
    config["system"]["location"]["latitude"] = 60
    states = []
    for role in ("load_power", "grid_power", "battery_power", "pv_power", "battery_soc"):
        config["input_sensors"][role] = f"sensor.{role}"
        states.append(
            entity(f"sensor.{role}", unit_of_measurement="%" if role == "battery_soc" else "W")
        )
    profile = load_profile("deye")
    for definition in profile.get_required_entities().values():
        states.append(entity(definition.default_entity))
    result = await readiness_with(config, states)
    assert result["ready"]
    assert all(c["status"] in ("pass", "skipped") for c in result["checks"])
    config["input_sensors"]["battery_soc"] = ""
    result = await readiness_with(config, states)
    assert not result["ready"]
    assert next(c for c in result["checks"] if c["id"] == "battery_soc")["status"] == "fail"
