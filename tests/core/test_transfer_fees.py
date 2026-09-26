"""Tests for time-of-use transfer fee resolution and its price consumers."""

import logging
from datetime import datetime, timedelta

import pytest
import pytz

from backend.core.prices import (
    _process_nordpool_data,
    calculate_import_export_prices,
    resolve_transfer_fee,
)
from ml.price_forecast import derive_consumer_prices
from planner.strategy.ev_deferral import price_post_horizon_slots

TZ = pytz.timezone("Europe/Stockholm")
WINTER_WEEKDAY_RULE = {
    "months": [11, 12, 1, 2, 3],
    "weekdays": [0, 1, 2, 3, 4],
    "hours": {"start": 6, "end": 22},
    "fee_sek": 0.76,
}


def _config(mode="time_of_use", rules=None, holidays=False):
    pricing = {
        "vat_percent": 25.0,
        "grid_transfer_fee_sek": 0.25,
        "energy_tax_sek": 0.44,
        "transfer_fee_mode": mode,
        "holidays_as_weekend": holidays,
        "transfer_fee_rules": [WINTER_WEEKDAY_RULE] if rules is None else rules,
    }
    return {"timezone": "Europe/Stockholm", "pricing": pricing}


def _local(*args):
    return TZ.localize(datetime(*args))


def test_flat_parity_with_old_formula_without_new_keys():
    config = {"pricing": {"vat_percent": 25.0, "grid_transfer_fee_sek": 0.25, "energy_tax_sek": 0.44}}
    expected = (0.5 + 0.25 + 0.44) * 1.25
    for slot in (None, _local(2026, 12, 1, 10, 0)):
        imp, exp = calculate_import_export_prices(500.0, config, slot)
        assert imp == pytest.approx(expected)
        assert exp == pytest.approx(0.5)


def test_flat_mode_ignores_rules():
    config = _config(mode="flat")
    assert resolve_transfer_fee(_local(2026, 12, 1, 10, 0), config["pricing"]) == 0.25


def test_no_slot_start_uses_flat_fee_in_tou_mode():
    assert resolve_transfer_fee(None, _config()["pricing"]) == 0.25


@pytest.mark.parametrize(
    ("slot", "fee"),
    [
        (_local(2026, 12, 1, 10, 0), 0.76),  # winter weekday daytime
        (_local(2026, 12, 1, 23, 0), 0.25),  # no rule matches -> flat
        (_local(2026, 12, 1, 21, 45), 0.76),
        (_local(2026, 12, 1, 22, 0), 0.25),
        (_local(2026, 12, 5, 10, 0), 0.25),  # Saturday
        (_local(2026, 7, 7, 10, 0), 0.25),  # summer
    ],
)
def test_tou_per_slot_fee(slot, fee):
    assert resolve_transfer_fee(slot, _config()["pricing"], TZ) == pytest.approx(fee)


def test_utc_slot_is_matched_in_local_time():
    # 2026-12-01 05:30 UTC == 06:30 Stockholm (CET)
    slot = datetime(2026, 12, 1, 5, 30, tzinfo=pytz.UTC)
    assert resolve_transfer_fee(slot, _config()["pricing"], "Europe/Stockholm") == 0.76


def test_first_match_wins():
    rules = [{"fee_sek": 0.9, "hours": {"start": 8, "end": 12}}, {"fee_sek": 0.5}]
    pricing = _config(rules=rules)["pricing"]
    assert resolve_transfer_fee(_local(2026, 5, 5, 9, 0), pricing) == 0.9
    assert resolve_transfer_fee(_local(2026, 5, 5, 13, 0), pricing) == 0.5


def test_holiday_toggle():
    slot = _local(2026, 12, 25, 10, 0)  # Friday, Juldagen
    assert resolve_transfer_fee(slot, _config(holidays=False)["pricing"]) == 0.76
    assert resolve_transfer_fee(slot, _config(holidays=True)["pricing"]) == 0.25


def test_invalid_rule_is_skipped_with_warning(caplog):
    rules = [{"hours": {"start": 8, "end": 8}, "fee_sek": 9.0}, {"fee_sek": -1}, WINTER_WEEKDAY_RULE]
    pricing = _config(rules=rules)["pricing"]
    with caplog.at_level(logging.WARNING, logger="darkstar.core.prices"):
        fee = resolve_transfer_fee(_local(2026, 12, 2, 10, 0), pricing)
    assert fee == 0.76
    assert "transfer_fee_rules[0]" in caplog.text
    assert "transfer_fee_rules[1]" in caplog.text


def test_nordpool_processing_uses_slot_fee():
    config = _config()
    start = _local(2026, 12, 1, 21, 45)
    entries = [
        {"start": start + timedelta(minutes=15 * i), "end": start + timedelta(minutes=15 * (i + 1)), "value": 1000.0}
        for i in range(2)
    ]
    result = _process_nordpool_data(entries, config)
    assert result[0]["import_price_sek_kwh"] == pytest.approx((1.0 + 0.76 + 0.44) * 1.25)
    assert result[1]["import_price_sek_kwh"] == pytest.approx((1.0 + 0.25 + 0.44) * 1.25)


def test_forecast_slots_include_window_fee():
    config = _config()
    result = derive_consumer_prices(0.1, 0.2, 0.3, config, slot_start="2026-12-01T10:00:00+01:00")
    assert result["import_p10"] == pytest.approx((0.1 + 0.76 + 0.44) * 1.25)
    assert result["import_p50"] == pytest.approx((0.2 + 0.76 + 0.44) * 1.25)
    assert result["import_p90"] == pytest.approx((0.3 + 0.76 + 0.44) * 1.25)
    flat = derive_consumer_prices(0.1, 0.2, 0.3, config)
    assert flat["import_p50"] == pytest.approx((0.2 + 0.25 + 0.44) * 1.25)


def test_ev_post_horizon_slots_use_slot_fee():
    config = _config()
    peak = _local(2026, 12, 1, 10, 0)
    night = _local(2026, 12, 1, 23, 0)
    slots, _ = price_post_horizon_slots(
        [(peak, 0.25), (night, 0.25)], {}, {peak: 0.3, night: 0.3}, config, 0.0, None, 9.9
    )
    assert slots[0].price == pytest.approx((0.3 + 0.76 + 0.44) * 1.25)
    assert slots[1].price == pytest.approx((0.3 + 0.25 + 0.44) * 1.25)


@pytest.mark.parametrize(("pricing_change", "invalidated"), [(True, True), (False, False)])
def test_config_save_invalidates_price_cache_on_pricing_change(
    tmp_path, monkeypatch, pricing_change, invalidated
):
    import asyncio
    import shutil
    from pathlib import Path
    from unittest.mock import patch

    from backend.api.routers.config import save_config
    from backend.core.cache import cache_sync
    from backend.core.prices import NORDPOOL_CACHE_KEY

    repo = Path(__file__).resolve().parents[2]
    shutil.copy(repo / "config.default.yaml", tmp_path / "config.default.yaml")
    shutil.copy(repo / "config.default.yaml", tmp_path / "config.yaml")
    monkeypatch.chdir(tmp_path)

    payload = {"system": {"has_battery": False}}
    if pricing_change:
        payload["pricing"] = {"transfer_fee_mode": "time_of_use", "transfer_fee_rules": [WINTER_WEEKDAY_RULE]}

    cache_sync.set(NORDPOOL_CACHE_KEY, [{"stale": True}], ttl_seconds=3600.0)
    try:
        with patch("backend.api.routers.config.get_executor_instance", return_value=None):
            result = asyncio.run(save_config(payload))
        assert result["status"] == "success"
        assert (cache_sync.get(NORDPOOL_CACHE_KEY) is None) is invalidated
        import yaml

        saved = yaml.safe_load((tmp_path / "config.yaml").read_text())["pricing"]
        if pricing_change:
            assert saved["transfer_fee_mode"] == "time_of_use"
            assert saved["transfer_fee_rules"] == [WINTER_WEEKDAY_RULE]
        else:
            assert saved["transfer_fee_mode"] == "flat"
            assert saved["transfer_fee_rules"] == []
    finally:
        cache_sync.invalidate(NORDPOOL_CACHE_KEY)
