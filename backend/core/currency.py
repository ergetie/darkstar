"""Currency helpers for user-facing backend messages.

Amounts throughout Darkstar are in the configured currency (`nordpool.currency`);
the legacy `_sek` key suffix is kept for compatibility and does not mean SEK.
"""

import re
from collections.abc import Mapping
from typing import Any, cast

# Equals the shipped `nordpool.currency` default in config.default.yaml.
DEFAULT_CURRENCY_CODE = "SEK"

_ISO_CODE = re.compile(r"^[A-Z]{3}$")


def get_currency_code(config: Mapping[str, Any] | None) -> str:
    """Return the configured ISO 4217 code, uppercased.

    Falls back to DEFAULT_CURRENCY_CODE when the key is missing, empty or not a
    three-letter code.
    """
    nordpool: Any = (config or {}).get("nordpool")
    raw: Any = (
        cast("Mapping[str, Any]", nordpool).get("currency")
        if isinstance(nordpool, Mapping)
        else None
    )
    if not isinstance(raw, str):
        return DEFAULT_CURRENCY_CODE
    code = raw.strip().upper()
    return code if _ISO_CODE.fullmatch(code) else DEFAULT_CURRENCY_CODE


def price_unit(config: Mapping[str, Any] | None) -> str:
    """Return the price unit label, e.g. "EUR/kWh"."""
    return f"{get_currency_code(config)}/kWh"
