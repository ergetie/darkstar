"""Fixed fees (grid subscription, supplier yearly fee) prorated per local calendar day."""

import calendar
from datetime import date, timedelta
from typing import Any, cast


def _non_negative(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return max(0.0, float(value))


def fixed_fees_for_range(start_date: date, end_date: date, config: dict[str, Any]) -> float:
    """
    Total fixed fees in SEK incl. VAT for the inclusive local date range.

    The grid monthly fee (``pricing.subscription_fee_sek_per_month``) is charged as
    monthly / days_in_month per calendar day and the supplier yearly fee
    (``pricing.supplier_fee_sek_per_year``) as yearly / days_in_year per calendar day,
    both excl. VAT, then VAT is applied. Every calendar day of the range counts in
    full, whether or not slot data exists (a DST day is one day, today is a full day).
    """
    pricing: Any = config.get("pricing")
    pricing_cfg = cast("dict[str, Any]", pricing) if isinstance(pricing, dict) else {}
    monthly = _non_negative(pricing_cfg.get("subscription_fee_sek_per_month"))
    yearly = _non_negative(pricing_cfg.get("supplier_fee_sek_per_year"))
    if end_date < start_date or (monthly == 0.0 and yearly == 0.0):
        return 0.0
    vat_percent = _non_negative(pricing_cfg.get("vat_percent", 25.0))

    total_excl_vat = 0.0
    day = start_date
    while day <= end_date:
        days_in_month = calendar.monthrange(day.year, day.month)[1]
        days_in_year = 366 if calendar.isleap(day.year) else 365
        total_excl_vat += monthly / days_in_month + yearly / days_in_year
        day += timedelta(days=1)
    return total_excl_vat * (1 + vat_percent / 100.0)
