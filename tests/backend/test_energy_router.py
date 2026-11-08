"""Tests for battery wear cost fields in energy router."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_store_mock(row_values):
    """Return a mock store whose AsyncSession yields a result row."""
    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, i: row_values[i]

    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    @asynccontextmanager
    async def _async_session():
        yield mock_session

    store = MagicMock()
    store.AsyncSession = _async_session
    return store


def _base_row(
    grid_imp=2.0,
    grid_exp=0.5,
    batt_chg=3.0,
    batt_dis=3.0,
    water=0.0,
    pv=1.0,
    load=2.5,
    ev=0.0,
    import_cost=4.0,
    export_rev=0.3,
    grid_charge_cost=1.0,
    self_cons=0.5,
    slot_count=24,
    ev_grid=0.0,
    ev_solar=0.0,
    ev_cost=0.0,
):
    return [
        grid_imp,
        grid_exp,
        batt_chg,
        batt_dis,
        water,
        pv,
        load,
        ev,
        import_cost,
        export_rev,
        grid_charge_cost,
        self_cons,
        slot_count,
        ev_grid,
        ev_solar,
        ev_cost,
    ]


@pytest.mark.asyncio
async def test_energy_range_includes_wear_fields_with_correct_values():
    """Response includes battery_wear_cost_sek and net_cost_incl_wear_sek matching the formula."""
    from backend.api.routers.energy import get_energy_range

    config = {
        "timezone": "Europe/Stockholm",
        "battery_economics": {"battery_cycle_cost_kwh": 0.2},
    }
    row = _base_row(batt_chg=4.0, batt_dis=4.0, import_cost=5.0, export_rev=1.0)
    store = _make_store_mock(row)

    with patch("backend.api.routers.energy.load_yaml", return_value=config):
        result = await get_energy_range(period="today", store=store)

    expected_wear = (4.0 + 4.0) * 0.2 * 0.5
    expected_net = 5.0 - 1.0
    expected_net_incl = expected_net + expected_wear

    assert "battery_wear_cost_sek" in result
    assert "net_cost_incl_wear_sek" in result
    assert result["battery_wear_cost_sek"] == round(expected_wear, 2)
    assert result["net_cost_incl_wear_sek"] == round(expected_net_incl, 2)
    assert result["net_cost_sek"] == round(expected_net, 2)


@pytest.mark.asyncio
async def test_energy_range_zero_battery_throughput():
    """Zero battery throughput → battery_wear_cost_sek=0 and net_cost_incl_wear_sek == net_cost_sek."""
    from backend.api.routers.energy import get_energy_range

    config = {
        "timezone": "Europe/Stockholm",
        "battery_economics": {"battery_cycle_cost_kwh": 0.2},
    }
    row = _base_row(batt_chg=0.0, batt_dis=0.0, import_cost=3.0, export_rev=0.5)
    store = _make_store_mock(row)

    with patch("backend.api.routers.energy.load_yaml", return_value=config):
        result = await get_energy_range(period="today", store=store)

    assert result["battery_wear_cost_sek"] == 0.0
    assert result["net_cost_incl_wear_sek"] == result["net_cost_sek"]


@pytest.mark.asyncio
async def test_energy_range_adds_prorated_fixed_fees_to_net_cost():
    """October 2026 with 510/384 kr fees and 25% VAT adds 678.26 kr to net and net incl. wear."""
    from backend.api.routers.energy import get_energy_range

    config = {
        "timezone": "Europe/Stockholm",
        "battery_economics": {"battery_cycle_cost_kwh": 0.2},
        "pricing": {
            "vat_percent": 25.0,
            "subscription_fee_sek_per_month": 510.0,
            "supplier_fee_sek_per_year": 384.0,
        },
    }
    row = _base_row(batt_chg=4.0, batt_dis=4.0, import_cost=100.0, export_rev=10.0)
    store = _make_store_mock(row)

    with patch("backend.api.routers.energy.load_yaml", return_value=config):
        result = await get_energy_range(
            period="custom", start_date="2026-10-01", end_date="2026-10-31", store=store
        )

    assert result["fixed_fees_sek"] == pytest.approx(678.26, abs=0.01)
    assert result["net_cost_sek"] == pytest.approx(90.0 + 678.26, abs=0.01)
    assert result["net_cost_incl_wear_sek"] == pytest.approx(90.0 + 678.26 + 0.8, abs=0.02)
    assert result["import_cost_sek"] == 100.0
    assert result["export_revenue_sek"] == 10.0


@pytest.mark.asyncio
async def test_energy_range_without_fee_config_has_zero_fixed_fees():
    from backend.api.routers.energy import get_energy_range

    store = _make_store_mock(_base_row(import_cost=5.0, export_rev=1.0))
    with patch(
        "backend.api.routers.energy.load_yaml", return_value={"timezone": "Europe/Stockholm"}
    ):
        result = await get_energy_range(period="today", store=store)
    assert result["fixed_fees_sek"] == 0.0
    assert result["net_cost_sek"] == 4.0
