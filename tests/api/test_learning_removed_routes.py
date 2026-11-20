"""Endpoints that served fabricated or never-written data stay removed."""

import pytest

from tests.api.test_api_learning_status import client  # noqa: F401  (fixture)


@pytest.mark.parametrize("path", ["/api/learning/loops", "/api/learning/daily_metrics"])
def test_removed_learning_routes_return_404(client, path):  # noqa: F811
    assert client.get(path).status_code == 404
