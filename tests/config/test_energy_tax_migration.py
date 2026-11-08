"""Config migration of the old energy tax default (0.439 -> 0.36)."""

from pathlib import Path

import pytest
import yaml

from backend.config_migration import _migrate_config, _migrate_energy_tax

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = str(REPO_ROOT / "config.default.yaml")


def test_old_default_replaced() -> None:
    cfg, changed = _migrate_energy_tax({"pricing": {"energy_tax_sek": 0.439}})
    assert changed is True
    assert cfg["pricing"]["energy_tax_sek"] == 0.36


@pytest.mark.parametrize("value", [0.45, 0.36, 0, True, "0.439", None])
def test_other_values_untouched(value: object) -> None:
    cfg, changed = _migrate_energy_tax({"pricing": {"energy_tax_sek": value}})
    assert changed is False
    assert cfg["pricing"]["energy_tax_sek"] == value


def test_missing_key_or_section_untouched() -> None:
    assert _migrate_energy_tax({"pricing": {}})[1] is False
    assert _migrate_energy_tax({})[1] is False
    assert _migrate_energy_tax({"pricing": None})[1] is False


def _write(tmp_path: Path, pricing: dict) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"pricing": pricing}), encoding="utf-8")
    return path


def test_full_migration_rewrites_and_fills_new_keys(tmp_path: Path) -> None:
    path = _write(tmp_path, {"energy_tax_sek": 0.439})
    _migrate_config(str(path), DEFAULT_PATH, False)
    pricing = yaml.safe_load(path.read_text())["pricing"]
    assert pricing["energy_tax_sek"] == 0.36
    assert pricing["supplier_fee_sek_per_year"] == 0
    assert pricing["supplier_markup_sek_kwh"] == 0
    assert pricing["subscription_fee_sek_per_month"] == 0


def test_full_migration_keeps_custom_value(tmp_path: Path) -> None:
    path = _write(tmp_path, {"energy_tax_sek": 0.45})
    _migrate_config(str(path), DEFAULT_PATH, False)
    assert yaml.safe_load(path.read_text())["pricing"]["energy_tax_sek"] == 0.45
