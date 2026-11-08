"""Fixed fee proration (grid monthly + supplier yearly, excl. VAT, VAT applied)."""

from datetime import date

import pytest

from backend.core.fixed_fees import fixed_fees_for_range

CFG = {
    "pricing": {
        "vat_percent": 25.0,
        "subscription_fee_sek_per_month": 510.0,
        "supplier_fee_sek_per_year": 384.0,
    }
}


def test_october_2026_matches_bill() -> None:
    fees = fixed_fees_for_range(date(2026, 10, 1), date(2026, 10, 31), CFG)
    assert fees == pytest.approx(678.26, abs=0.01)


def test_single_day_is_full_day_fee() -> None:
    fees = fixed_fees_for_range(date(2026, 10, 5), date(2026, 10, 5), CFG)
    assert fees == pytest.approx((510 / 31 + 384 / 365) * 1.25)


def test_month_boundary_uses_each_months_length() -> None:
    fees = fixed_fees_for_range(date(2026, 2, 28), date(2026, 3, 1), CFG)
    expected = (510 / 28 + 510 / 31 + 2 * 384 / 365) * 1.25
    assert fees == pytest.approx(expected)


def test_leap_year_length() -> None:
    fees = fixed_fees_for_range(date(2028, 2, 29), date(2028, 2, 29), CFG)
    assert fees == pytest.approx((510 / 29 + 384 / 366) * 1.25)


def test_dst_days_count_once() -> None:
    # 2026-10-25 is the autumn DST change (25 h), 2026-03-29 the spring change (23 h).
    one = fixed_fees_for_range(date(2026, 10, 24), date(2026, 10, 24), CFG)
    dst = fixed_fees_for_range(date(2026, 10, 25), date(2026, 10, 25), CFG)
    assert dst == pytest.approx(one)


@pytest.mark.parametrize(
    "config",
    [{}, {"pricing": None}, {"pricing": {}}, {"pricing": {"subscription_fee_sek_per_month": -5}}],
)
def test_missing_or_invalid_fees_are_zero(config: dict) -> None:
    assert fixed_fees_for_range(date(2026, 10, 1), date(2026, 10, 31), config) == 0.0


def test_inverted_range_is_zero() -> None:
    assert fixed_fees_for_range(date(2026, 10, 5), date(2026, 10, 4), CFG) == 0.0
