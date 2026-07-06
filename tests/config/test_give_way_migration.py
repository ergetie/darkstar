"""load-balancing-completion 1.4: give_way_order migration + self-healing tests."""

import logging

from backend.config_migration import _migrate_give_way_order
from executor.config import (
    BalancedLoadConfig,
    BalancedLoadType,
    GiveWayOrderEntry,
    LoadBalancingConfig,
    heal_give_way_order,
)

logging.basicConfig(level=logging.INFO)


def make_config(**overrides):
    config = {
        "ev_chargers": [
            {"id": "ev_a", "type": "current"},
            {"id": "ev_b", "type": "current"},
            {"id": "ev_binary", "type": "binary"},
        ],
        "load_balancing": {
            "enabled": True,
            "charger_priority": {"ev_a": 1, "ev_b": 2},
            "loads": [
                {"device_type": "water_heater", "device_id": "wh", "phases": [2], "priority": 2},
                {"device_type": "custom_entity", "device_id": "pump", "phases": [1], "priority": 1},
            ],
        },
    }
    config.update(overrides)
    return config


class TestGiveWayMigration:
    def test_both_old_fields_build_full_order(self):
        config = make_config()
        result, changed = _migrate_give_way_order(config)
        assert changed
        lb = result["load_balancing"]
        assert lb["give_way_order"] == [
            {"kind": "charger", "id": "ev_a"},
            {"kind": "charger", "id": "ev_b"},
            {"kind": "shed", "id": "pump"},  # old priority 1 gives way first
            {"kind": "shed", "id": "wh"},
        ]
        assert "charger_priority" not in lb
        assert all("priority" not in load for load in lb["loads"])

    def test_charger_priority_overrides_position(self):
        config = make_config()
        config["load_balancing"]["charger_priority"] = {"ev_b": 1, "ev_a": 2}
        result, _ = _migrate_give_way_order(config)
        order = result["load_balancing"]["give_way_order"]
        assert [e["id"] for e in order if e["kind"] == "charger"] == ["ev_b", "ev_a"]

    def test_only_charger_priority_set(self):
        config = make_config()
        for load in config["load_balancing"]["loads"]:
            del load["priority"]
        result, changed = _migrate_give_way_order(config)
        assert changed
        order = result["load_balancing"]["give_way_order"]
        # Loads without priority keep their list order after the chargers
        assert [e["id"] for e in order] == ["ev_a", "ev_b", "wh", "pump"]
        assert "charger_priority" not in result["load_balancing"]

    def test_only_load_priority_set(self):
        config = make_config()
        del config["load_balancing"]["charger_priority"]
        result, changed = _migrate_give_way_order(config)
        assert changed
        order = result["load_balancing"]["give_way_order"]
        # Chargers fall back to ev_chargers[] position
        assert [e["id"] for e in order] == ["ev_a", "ev_b", "pump", "wh"]
        assert all("priority" not in load for load in result["load_balancing"]["loads"])

    def test_priority_ties_keep_original_order(self):
        config = make_config()
        for load in config["load_balancing"]["loads"]:
            load["priority"] = 1
        config["load_balancing"]["charger_priority"] = {"ev_a": 1, "ev_b": 1}
        result, _ = _migrate_give_way_order(config)
        order = result["load_balancing"]["give_way_order"]
        assert [e["id"] for e in order] == ["ev_a", "ev_b", "wh", "pump"]

    def test_charger_priority_referencing_missing_device_is_dropped(self):
        config = make_config()
        config["load_balancing"]["charger_priority"]["ghost"] = 0
        result, _ = _migrate_give_way_order(config)
        order = result["load_balancing"]["give_way_order"]
        assert "ghost" not in [e["id"] for e in order]
        # Real chargers still ordered by their priorities
        assert [e["id"] for e in order if e["kind"] == "charger"] == ["ev_a", "ev_b"]

    def test_binary_charger_never_becomes_charger_entry(self):
        config = make_config()
        result, _ = _migrate_give_way_order(config)
        order = result["load_balancing"]["give_way_order"]
        assert "ev_binary" not in [e["id"] for e in order if e["kind"] == "charger"]

    def test_idempotent_second_run_is_a_noop(self):
        config = make_config()
        result, changed = _migrate_give_way_order(config)
        assert changed
        again, changed_again = _migrate_give_way_order(result)
        assert not changed_again
        assert again["load_balancing"]["give_way_order"] == result["load_balancing"]["give_way_order"]

    def test_existing_give_way_order_is_preserved(self):
        """Old keys present alongside give_way_order: keys dropped, order kept."""
        config = make_config()
        existing = [{"kind": "shed", "id": "wh"}, {"kind": "charger", "id": "ev_a"}]
        config["load_balancing"]["give_way_order"] = list(existing)
        result, changed = _migrate_give_way_order(config)
        assert changed  # old keys removed
        assert result["load_balancing"]["give_way_order"] == existing
        assert "charger_priority" not in result["load_balancing"]

    def test_no_load_balancing_section_is_a_noop(self):
        result, changed = _migrate_give_way_order({"ev_chargers": []})
        assert not changed
        assert "load_balancing" not in result


def make_lb(order, loads=None) -> LoadBalancingConfig:
    return LoadBalancingConfig(
        enabled=True,
        main_fuse_a=20,
        loads=loads if loads is not None else [],
        give_way_order=order,
    )


def shed_load(device_id: str) -> BalancedLoadConfig:
    return BalancedLoadConfig(
        device_type=BalancedLoadType.WATER_HEATER, device_id=device_id, phases=[2]
    )


class TestGiveWayOrderSelfHealing:
    def test_new_charger_appended_after_last_charger_entry(self):
        lb = make_lb(
            [
                GiveWayOrderEntry("charger", "ev_a"),
                GiveWayOrderEntry("shed", "wh"),
            ],
            loads=[shed_load("wh")],
        )
        heal_give_way_order(lb, ["ev_a", "ev_new"])
        assert [(e.kind, e.id) for e in lb.give_way_order] == [
            ("charger", "ev_a"),
            ("charger", "ev_new"),
            ("shed", "wh"),
        ]

    def test_charger_appended_at_top_when_no_charger_entries(self):
        lb = make_lb([GiveWayOrderEntry("shed", "wh")], loads=[shed_load("wh")])
        heal_give_way_order(lb, ["ev_a"])
        assert [(e.kind, e.id) for e in lb.give_way_order] == [
            ("charger", "ev_a"),
            ("shed", "wh"),
        ]

    def test_retyped_charger_dropped(self):
        """A charger switched back to type: binary drops out of the order."""
        lb = make_lb(
            [
                GiveWayOrderEntry("charger", "ev_a"),
                GiveWayOrderEntry("charger", "ev_retyped"),
            ]
        )
        heal_give_way_order(lb, ["ev_a"])
        assert [(e.kind, e.id) for e in lb.give_way_order] == [("charger", "ev_a")]

    def test_missing_shed_appended_at_end(self):
        lb = make_lb(
            [GiveWayOrderEntry("charger", "ev_a")],
            loads=[shed_load("wh"), shed_load("pump")],
        )
        heal_give_way_order(lb, ["ev_a"])
        assert [(e.kind, e.id) for e in lb.give_way_order] == [
            ("charger", "ev_a"),
            ("shed", "wh"),
            ("shed", "pump"),
        ]

    def test_dangling_shed_reference_dropped(self):
        lb = make_lb(
            [GiveWayOrderEntry("shed", "gone"), GiveWayOrderEntry("shed", "wh")],
            loads=[shed_load("wh")],
        )
        heal_give_way_order(lb, [])
        assert [(e.kind, e.id) for e in lb.give_way_order] == [("shed", "wh")]

    def test_complete_order_is_untouched(self):
        order = [
            GiveWayOrderEntry("shed", "wh"),
            GiveWayOrderEntry("charger", "ev_a"),
        ]
        lb = make_lb(list(order), loads=[shed_load("wh")])
        heal_give_way_order(lb, ["ev_a"])
        assert lb.give_way_order == order
