"""EV goal entity wiring regression tests.

Covers the three failure modes behind a report of "Darkstar plans no charging
at all", where the planner logged `no active deadline` on every run while the
user's ready-by was correctly set in Home Assistant:

1. A config save never re-armed the HA websocket listener, so an entity added
   in settings stayed unmonitored until a restart (the reload call was lost
   with backend/webapp.py in 2c9e0386).
2. A ready-by pointed at a non-``input_datetime`` entity parsed as ``None``
   and silently disabled goal charging, with no validation warning.
3. A ready-by stored without a target SoC was dropped whole by the goal
   merge, which is indistinguishable downstream from having no goal.
"""

import logging

import pytest

from backend.api.routers.config import _validate_config_for_save


def _ev_config(**charger_overrides):
    """A minimal config_version 2 config with one valid EV charger."""
    charger = {
        "id": "ev_charger_1",
        "name": "Zoe",
        "enabled": True,
        "battery_capacity_kwh": 22,
        "sensor": "sensor.ev_power",
        "type": "current",
        "current_entity": "number.ev_amp",
        "switch_entity": "switch.ev_allow",
        "max_current_a": 16,
        "min_current_a": 6,
        "phases": [1, 2, 3],
    }
    charger.update(charger_overrides)
    return {
        "config_version": 2,
        "system": {
            "has_solar": False,
            "has_battery": False,
            "has_water_heater": False,
            "has_ev_charger": True,
            "solar_arrays": [],
        },
        "executor": {"enabled": False},
        "ev_chargers": [charger],
    }


def _messages(issues, needle):
    return [i for i in issues if needle in i["message"]]


class TestGoalEntityValidation:
    """Fix 2: a wrong-domain goal entity is reported instead of failing mute."""

    def test_input_number_ready_by_warns(self):
        issues = _validate_config_for_save(
            _ev_config(ha_ready_by_entity="input_number.zoe_charged_by")
        )
        found = _messages(issues, "ha_ready_by_entity is not an input_datetime")
        assert len(found) == 1
        assert found[0]["severity"] == "warning"
        # The guidance has to name the date requirement: a time-only
        # input_datetime is the other way this silently parses as None.
        assert "date and time" in found[0]["guidance"]

    def test_input_datetime_ready_by_is_accepted(self):
        issues = _validate_config_for_save(
            _ev_config(ha_ready_by_entity="input_datetime.zoe_charged_by")
        )
        assert _messages(issues, "ha_ready_by_entity") == []

    def test_absent_ready_by_is_not_flagged(self):
        issues = _validate_config_for_save(_ev_config())
        assert _messages(issues, "ha_ready_by_entity") == []

    def test_target_soc_accepts_numeric_domains(self):
        for entity in ("input_number.zoe_target_soc", "number.zoe_target", "sensor.zoe_target"):
            issues = _validate_config_for_save(_ev_config(ha_target_soc_entity=entity))
            assert _messages(issues, "ha_target_soc_entity") == [], entity

    def test_target_soc_rejects_datetime(self):
        issues = _validate_config_for_save(
            _ev_config(ha_target_soc_entity="input_datetime.zoe_target_soc")
        )
        found = _messages(issues, "ha_target_soc_entity may be invalid")
        assert len(found) == 1
        assert found[0]["severity"] == "warning"

    def test_goal_entity_warnings_never_block_a_save(self):
        """Warnings only — an error would lock the user out of the settings page."""
        issues = _validate_config_for_save(
            _ev_config(
                ha_ready_by_entity="input_number.zoe_charged_by",
                ha_target_soc_entity="input_datetime.zoe_target_soc",
            )
        )
        assert [i for i in issues if i["severity"] == "error"] == []


def _socket_config(ev_charger):
    return {
        "system": {
            "has_solar": False,
            "has_battery": True,
            "has_water_heater": False,
            "has_ev_charger": True,
        },
        "input_sensors": {"battery_soc": "sensor.batt"},
        "ev_chargers": [ev_charger],
    }


class TestMonitoredEntityReload:
    """Fix 1: a reload reports which entities newly became monitored."""

    BASE_CHARGER = {  # noqa: RUF012 - plain test data
        "id": "ev_charger_1",
        "enabled": True,
        "sensor": "sensor.ev_power",
        "plug_sensor": "binary_sensor.ev_plug",
    }

    def _client_with(self, monkeypatch, charger):
        """Build a client whose config.yaml reads as `charger`, mutable in place."""
        import backend.ha_socket as ha_socket

        current = {"cfg": _socket_config(charger)}
        monkeypatch.setattr(ha_socket, "load_yaml", lambda _path: current["cfg"])
        monkeypatch.setattr(
            ha_socket,
            "load_home_assistant_config",
            lambda: {"url": "http://test", "token": "t"},
        )
        return ha_socket.HAWebSocketClient(), current

    def test_reload_returns_newly_monitored_entities(self, monkeypatch):
        client, current = self._client_with(monkeypatch, self.BASE_CHARGER)
        assert "input_datetime.zoe_ready" not in client.monitored_entities

        # The user adds a ready-by entity in settings and saves.
        current["cfg"] = _socket_config(
            {**self.BASE_CHARGER, "ha_ready_by_entity": "input_datetime.zoe_ready"}
        )
        added = client.reload_monitored_entities()

        assert "input_datetime.zoe_ready" in added
        assert client.monitored_entities["input_datetime.zoe_ready"] == "ev_ready_by_0"
        # Entities that were already monitored are not reported as new.
        assert "sensor.ev_power" not in added

    def test_reload_with_no_changes_returns_empty(self, monkeypatch):
        client, _ = self._client_with(
            monkeypatch,
            {**self.BASE_CHARGER, "ha_ready_by_entity": "input_datetime.zoe_ready"},
        )
        assert "input_datetime.zoe_ready" in client.monitored_entities
        assert client.reload_monitored_entities() == set()

    @pytest.mark.asyncio
    async def test_seeding_reads_the_value_already_set_in_ha(self, monkeypatch):
        """The exact reported failure: the ready-by was set in HA *before* the
        config save, so no state_changed event was ever coming for it."""
        import backend.core.ha_client as ha_client_mod

        client, current = self._client_with(monkeypatch, self.BASE_CHARGER)

        current["cfg"] = _socket_config(
            {
                **self.BASE_CHARGER,
                "ha_ready_by_entity": "input_datetime.zoe_ready",
                "ha_target_soc_entity": "input_number.zoe_target",
            }
        )

        states = {
            "input_datetime.zoe_ready": {
                "entity_id": "input_datetime.zoe_ready",
                "state": "2026-09-16 06:00:00",
            },
            "input_number.zoe_target": {
                "entity_id": "input_number.zoe_target",
                "state": "95.0",
            },
        }
        fetched: list[str] = []

        async def fake_get_state(entity_id):
            fetched.append(entity_id)
            return states.get(entity_id)

        monkeypatch.setattr(ha_client_mod, "get_ha_entity_state", fake_get_state)

        synced: list[list[dict]] = []
        monkeypatch.setattr(
            type(client), "_sync_ev_schedules_on_startup", lambda _self, r: synced.append(r)
        )
        monkeypatch.setattr(type(client), "_handle_state_change", lambda *_: None)

        added = await client.reload_and_seed_entities()

        assert added == {"input_datetime.zoe_ready", "input_number.zoe_target"}
        # Both goal entities are fetched, so the sync sees HA's real values
        # instead of treating the absent one as "HA has nothing".
        assert sorted(fetched) == ["input_datetime.zoe_ready", "input_number.zoe_target"]
        assert len(synced) == 1
        assert {s["entity_id"] for s in synced[0]} == set(states)

    @pytest.mark.asyncio
    async def test_no_new_entities_skips_fetching_entirely(self, monkeypatch):
        import backend.core.ha_client as ha_client_mod

        client, _ = self._client_with(
            monkeypatch,
            {**self.BASE_CHARGER, "ha_ready_by_entity": "input_datetime.zoe_ready"},
        )

        async def fail_get_state(entity_id):
            raise AssertionError(f"should not fetch {entity_id}")

        monkeypatch.setattr(ha_client_mod, "get_ha_entity_state", fail_get_state)
        assert await client.reload_and_seed_entities() == set()


class TestIncompleteGoalIsReported:
    """Fix 3: a ready-by with no target SoC is announced, not dropped quietly."""

    @pytest.fixture(autouse=True)
    def _fresh_warning_memory(self, monkeypatch):
        monkeypatch.setattr("planner.pipeline._warned_incomplete_goals", set())

    def _merge(self, charger_state):
        from planner.pipeline import merge_ev_goals_from_state

        return merge_ev_goals_from_state(
            [{"id": "ev_charger_1", "battery_capacity_kwh": 22}],
            {"ev_charger_1": charger_state},
        )

    def test_ready_by_without_target_soc_logs_a_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="darkstar.planner"):
            merged = self._merge({"ready_by": "06:00", "repeat": "daily"})

        assert merged[0]["target_soc_percent"] is None
        assert merged[0]["ready_by"] is None  # still inert, but no longer silent
        assert "ready-by 06:00 is set but no target SoC" in caplog.text

    def test_warning_logged_once_per_goal_state(self, caplog):
        state = {"ready_by": "06:00", "repeat": "daily", "last_updated": "2026-09-26T08:00:00"}
        with caplog.at_level(logging.WARNING, logger="darkstar.planner"):
            for _ in range(3):
                self._merge(state)
            assert caplog.text.count("is set but no target SoC") == 1
            self._merge({**state, "ready_by": "07:00", "last_updated": "2026-09-26T09:00:00"})
        assert caplog.text.count("is set but no target SoC") == 2

    def test_no_goal_at_all_stays_quiet(self, caplog):
        with caplog.at_level(logging.WARNING, logger="darkstar.planner"):
            merged = self._merge({})

        assert merged[0]["ready_by"] is None
        assert "no target SoC" not in caplog.text

    def test_complete_goal_is_used(self, caplog):
        with caplog.at_level(logging.WARNING, logger="darkstar.planner"):
            merged = self._merge({"target_soc_percent": 95, "ready_by": "06:00", "repeat": "daily"})

        assert merged[0]["target_soc_percent"] == 95
        assert merged[0]["ready_by"] == "06:00"
        assert "no target SoC" not in caplog.text
