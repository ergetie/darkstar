"""Explicit participation survives legacy migration, saves and reloads."""

import copy

import pytest
import yaml

from executor.config import effective_load_balancing_selection, load_executor_config


def legacy_config():
    return {
        "system": {"has_battery": False, "grid": {"main_fuse_a": 20}},
        "ev_chargers": [{"id": "car", "type": "current", "enabled": True}],
        "load_balancing": {
            "enabled": True,
            "loads": [{"device_type": "custom_entity", "device_id": "pump", "phases": [1]}],
            "give_way_order": [],
        },
    }


def test_effective_legacy_selection_preserves_auto_participation_without_mutation():
    config = legacy_config()
    before = copy.deepcopy(config)
    result = effective_load_balancing_selection(config)
    assert result["auto_include_devices"] is False
    assert result["give_way_order"] == [
        {"kind": "charger", "id": "car"},
        {"kind": "shed", "id": "pump"},
    ]
    assert config == before


@pytest.mark.parametrize("order", [[], [{"kind": "charger", "id": "car"}]])
def test_explicit_selection_is_preserved_on_load_and_repeated_heal(tmp_path, order):
    from executor.config import heal_give_way_order

    config = legacy_config()
    config["load_balancing"].update(auto_include_devices=False, give_way_order=order)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    for _ in range(2):
        loaded = load_executor_config(str(path)).load_balancing
        heal_give_way_order(loaded, ["car"], battery_available=True)
        assert [{"kind": e.kind, "id": e.id} for e in loaded.give_way_order] == order
        assert effective_load_balancing_selection(config)["give_way_order"] == order


def test_selection_migration_materializes_legacy_order_and_is_idempotent(tmp_path):
    from backend.config_migration import _migrate_config

    config = legacy_config()
    template = copy.deepcopy(config)
    template["load_balancing"]["auto_include_devices"] = False
    path = tmp_path / "config.yaml"
    default_path = tmp_path / "default.yaml"
    path.write_text(yaml.safe_dump(config))
    default_path.write_text(yaml.safe_dump(template))
    _migrate_config(str(path), str(default_path), False)
    migrated = yaml.safe_load(path.read_text())
    assert migrated["load_balancing"]["auto_include_devices"] is False
    assert migrated["load_balancing"]["give_way_order"][0] == {"kind": "charger", "id": "car"}
    before = path.read_bytes()
    _migrate_config(str(path), str(default_path), False)
    assert path.read_bytes() == before


@pytest.mark.parametrize("protected,expected", [(None, 20), (16, 16)])
def test_protected_rating_is_separate_from_planner_grid_limit(tmp_path, protected, expected):
    from planner.solver.adapter import resolve_max_phase_import_kw

    config = legacy_config()
    config["load_balancing"]["protected_fuse_a"] = protected
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    assert load_executor_config(str(path)).load_balancing.main_fuse_a == expected
    assert effective_load_balancing_selection(config)["protected_fuse_a"] == expected
    assert resolve_max_phase_import_kw(config) == pytest.approx(20 * 0.85 * 230 / 1000)
    assert config["system"]["grid"]["main_fuse_a"] == 20


@pytest.mark.parametrize("rating", [0, 126, -1, True, "16", 16.5, float("inf")])
def test_invalid_protected_rating_is_rejected(rating):
    from backend.api.routers.config import _validate_graceful_degradation_ranges

    issues = _validate_graceful_degradation_ranges({"protected_fuse_a": rating})
    assert any("protected_fuse_a" in issue["message"] for issue in issues)


def test_remove_and_readd_does_not_resurrect_device_limits_or_pending_grants():
    from datetime import datetime

    from executor.config import GiveWayOrderEntry, LoadBalancingConfig
    from executor.load_balancer import LoadBalancer

    now = datetime(2026, 10, 21)
    entries = [GiveWayOrderEntry("charger", "car"), GiveWayOrderEntry("battery", "battery")]
    lb = LoadBalancer(
        LoadBalancingConfig(main_fuse_a=20, auto_include_devices=False, give_way_order=entries)
    )
    lb._ev_paused_at["car"] = now
    lb._ev_reduced_at["car"] = now
    lb._battery_paused_at = now
    lb._battery_reduced_at = now
    lb._ledger.grant("charger:car", {1: 5}, 5, 0, now)
    lb._ledger.grant("battery", {1: 5}, 5, 0, now)
    lb._awaiting[1] = now
    lb._fuse_model.relief_needed(1, 100, now, False)
    heat = lb._fuse_model.heat(1)
    lb.configure(LoadBalancingConfig(main_fuse_a=20, auto_include_devices=False), 15)
    lb.configure(
        LoadBalancingConfig(main_fuse_a=20, auto_include_devices=False, give_way_order=entries), 15
    )
    assert lb._ev_paused_at == {}
    assert lb._ev_reduced_at == {}
    assert lb._battery_paused_at is None
    assert lb._battery_reduced_at is None
    assert lb._ledger.pending_a(1) == 0
    assert lb._awaiting == {}
    assert lb._fuse_model.heat(1) == heat


def test_enabled_empty_selection_is_valid_without_configured_devices():
    from backend.api.routers.config import _validate_config_for_save

    config = legacy_config()
    config["ev_chargers"] = []
    config["load_balancing"].update(auto_include_devices=False, give_way_order=[], loads=[])
    config["input_sensors"] = {
        f"grid_current_l{phase}": f"sensor.phase_{phase}" for phase in (1, 2, 3)
    }
    issues = _validate_config_for_save(config)
    assert not any("loads is empty" in issue["message"] for issue in issues)
