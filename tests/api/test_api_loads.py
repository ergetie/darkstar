from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.api.routers.config import get_config


def test_api_loads_debug():
    # Mock config to avoid loading real yaml
    mock_config = {
        "deferrable_loads": [{"id": "wh", "sensor_key": "sensor.wh"}],
        "input_sensors": {},
    }

    # Use a simpler app for testing router integration
    from fastapi import FastAPI

    from backend.api.routers.loads import router as loads_router

    app = FastAPI()
    app.include_router(loads_router)

    # Override config dependency
    app.dependency_overrides[get_config] = lambda: mock_config

    client = TestClient(app)

    with patch(
        "backend.loads.service.get_ha_sensor_kw_normalized", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = 1.0  # 1.0 kW directly (unit-aware)

        response = client.get("/api/loads/debug")
        assert response.status_code == 200
        data = response.json()

        assert data["controllable_total_kw"] == 1.0
        assert len(data["loads"]) == 1
        assert data["loads"][0]["id"] == "wh"
        assert data["quality_metrics"]["sensor_health"]["wh"] is True


if __name__ == "__main__":
    # Run simple test manually
    test_api_loads_debug()
