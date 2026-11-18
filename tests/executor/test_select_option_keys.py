"""Select options and enum states: display texts vs translation keys.

fronius_modbus (and other integrations) moved from English display texts such as
"Charge from Grid" to translation keys such as "charge_from_grid". Profiles written
against either spelling must keep writing and verifying correctly.
"""

from unittest.mock import AsyncMock

import pytest

from executor.actions import (
    ActionDispatcher,
    HAClient,
    option_key,
    option_values_match,
    resolve_select_option,
)
from executor.config import ExecutorConfig
from executor.engine import _values_equal

NEW_FRONIUS_OPTIONS = [
    "auto",
    "pv_charge_limit",
    "discharge_limit",
    "pv_charge_and_discharge_limit",
    "charge_from_grid",
    "discharge_to_grid",
    "block_discharging",
    "block_charging",
]
OLD_FRONIUS_OPTIONS = [
    "Auto",
    "PV Charge Limit",
    "Discharge Limit",
    "PV Charge and Discharge Limit",
    "Charge from Grid",
    "Discharge to Grid",
    "Block Discharging",
    "Block Charging",
]


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("Auto", "auto"),
        ("Charge from Grid", "charge_from_grid"),
        ("Block Discharging", "block_discharging"),
        ("Power reduction,Constant power factor", "power_reduction_constant_power_factor"),
        ("  On grid operating ", "on_grid_operating"),
        ("charge_from_grid", "charge_from_grid"),
        ("Force_3", "force_3"),
    ],
)
def test_option_key_follows_translation_key_rule(text, key):
    assert option_key(text) == key


@pytest.mark.parametrize(
    ("requested", "options", "expected"),
    [
        # Old profile text against the new integration.
        ("Charge from Grid", NEW_FRONIUS_OPTIONS, "charge_from_grid"),
        ("Auto", NEW_FRONIUS_OPTIONS, "auto"),
        ("Block Discharging", NEW_FRONIUS_OPTIONS, "block_discharging"),
        ("Discharge to Grid", NEW_FRONIUS_OPTIONS, "discharge_to_grid"),
        # New key against the old integration.
        ("charge_from_grid", OLD_FRONIUS_OPTIONS, "Charge from Grid"),
        # Exact matches are untouched.
        ("Auto", OLD_FRONIUS_OPTIONS, "Auto"),
        ("auto", NEW_FRONIUS_OPTIONS, "auto"),
    ],
)
def test_resolve_select_option_uses_entity_spelling(requested, options, expected):
    assert resolve_select_option(requested, options) == expected


def test_resolve_select_option_leaves_unknown_ambiguous_or_missing_options_alone():
    assert resolve_select_option("Turbo", NEW_FRONIUS_OPTIONS) == "Turbo"
    assert resolve_select_option("Auto", ["auto", "AUTO"]) == "Auto"
    assert resolve_select_option("Auto", None) == "Auto"
    assert resolve_select_option("---", ["___"]) == "---"


@pytest.mark.parametrize(
    ("current", "target", "expected"),
    [
        ("charge_from_grid", "Charge from Grid", True),
        ("Charge from Grid", "charge_from_grid", True),
        ("auto", "Auto", True),
        ("block_discharging", "Block Charging", False),
        ("auto", "Block Discharging", False),
        ("--", "__", False),
        (None, "Auto", False),
    ],
)
def test_state_comparisons_accept_both_spellings(current, target, expected):
    assert option_values_match(current, target) is expected
    assert _values_equal(current, target) is expected
    dispatcher = ActionDispatcher(AsyncMock(), ExecutorConfig())
    assert dispatcher._values_match(current, target) is expected


@pytest.mark.asyncio
async def test_set_select_option_writes_the_entitys_own_option():
    client = HAClient("http://ha.local:8123", "token")
    client.get_state = AsyncMock(
        return_value={"state": "auto", "attributes": {"options": NEW_FRONIUS_OPTIONS}}
    )
    client.call_service = AsyncMock(return_value=True)

    assert await client.set_select_option("select.storage_control_mode", "Charge from Grid")

    client.call_service.assert_awaited_once_with(
        "select",
        "select_option",
        "select.storage_control_mode",
        {"option": "charge_from_grid"},
    )


@pytest.mark.asyncio
async def test_set_select_option_falls_back_to_requested_option_without_state():
    client = HAClient("http://ha.local:8123", "token")
    client.get_state = AsyncMock(return_value=None)
    client.call_service = AsyncMock(return_value=True)

    assert await client.set_select_option("select.storage_control_mode", "Auto")

    client.call_service.assert_awaited_once_with(
        "select", "select_option", "select.storage_control_mode", {"option": "Auto"}
    )
