from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.api.routers.water import WaterBoostRequest, cancel_water_boost, set_water_boost


@pytest.mark.asyncio
async def test_set_water_boost_rejects_unknown_heater_ids():
    executor = MagicMock()
    executor.set_water_boost.return_value = {
        "success": False,
        "error": "Unknown water heater id",
        "unknown_heater_ids": ["missing"],
    }

    with (
        patch("backend.api.routers.executor.get_executor_instance", return_value=executor),
        pytest.raises(HTTPException) as exc_info,
    ):
        await set_water_boost(WaterBoostRequest(heater_ids=["missing"]))

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_cancel_water_boost_rejects_unknown_heater_ids():
    executor = MagicMock()
    executor.clear_water_boost.return_value = {
        "success": False,
        "error": "Unknown water heater id",
        "unknown_heater_ids": ["missing"],
    }

    with (
        patch("backend.api.routers.executor.get_executor_instance", return_value=executor),
        pytest.raises(HTTPException) as exc_info,
    ):
        await cancel_water_boost(WaterBoostRequest(heater_ids=["missing"]))

    assert exc_info.value.status_code == 400
