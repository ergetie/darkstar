from typing import Any

import pytest

from backend.core.currency import DEFAULT_CURRENCY_CODE, get_currency_code, price_unit


def test_configured_code() -> None:
    assert get_currency_code({"nordpool": {"currency": "EUR"}}) == "EUR"
    assert price_unit({"nordpool": {"currency": "EUR"}}) == "EUR/kWh"


def test_lowercase_is_uppercased() -> None:
    assert get_currency_code({"nordpool": {"currency": " nok "}}) == "NOK"


@pytest.mark.parametrize(
    "config",
    [
        None,
        {},
        {"nordpool": None},
        {"nordpool": {}},
        {"nordpool": {"currency": ""}},
        {"nordpool": {"currency": None}},
        {"nordpool": {"currency": 5}},
        {"nordpool": {"currency": "EURO"}},
        {"nordpool": {"currency": "E1R"}},
    ],
)
def test_missing_or_invalid_falls_back(config: dict[str, Any] | None) -> None:
    assert get_currency_code(config) == DEFAULT_CURRENCY_CODE == "SEK"
    assert price_unit(config) == "SEK/kWh"
