"""Backfill scripts price slots through the shared price function (no network)."""

import importlib.util
from datetime import datetime
from pathlib import Path

import pytest
import pytz

from backend.core.prices import calculate_import_export_prices

BIN = Path(__file__).resolve().parents[2] / "bin"
TZ = pytz.timezone("Europe/Stockholm")

CONFIG = {
    "timezone": "Europe/Stockholm",
    "pricing": {
        "vat_percent": 25.0,
        "grid_transfer_fee_sek": 0.25,
        "energy_tax_sek": 0.36,
        "supplier_markup_sek_kwh": 0.1132,
        "transfer_fee_mode": "time_of_use",
        "transfer_fee_rules": [{"hours": {"start": 6, "end": 22}, "fee_sek": 0.76}],
    },
}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("hour", "fee"), [(12, 0.76), (2, 0.25)])
def test_vattenfall_uses_shared_formula_with_time_of_use(hour: int, fee: float) -> None:
    module = _load("backfill_vattenfall")
    slot = TZ.localize(datetime(2026, 10, 14, hour))
    imp, exp = module.calculate_final_prices(50.0, CONFIG, slot)  # 50 ore/kWh = 0.50 SEK/kWh
    expected_imp, expected_exp = calculate_import_export_prices(500.0, CONFIG, slot)
    assert imp == pytest.approx(round(expected_imp, 4))
    assert exp == pytest.approx(0.5)
    assert expected_exp == pytest.approx(0.5)
    assert imp == pytest.approx((0.5 + fee + 0.36 + 0.1132) * 1.25, abs=1e-4)


def test_backfill_scripts_have_no_hardcoded_tax_formula() -> None:
    for name in ("backfill_prices", "backfill_vattenfall"):
        source = (BIN / f"{name}.py").read_text(encoding="utf-8")
        assert "0.439" not in source
        assert "calculate_import_export_prices" in source
