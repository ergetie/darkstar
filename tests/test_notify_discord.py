"""Discord webhook failures never log the secret webhook URL."""

import logging

import pytest
import requests

from backend.notify import _send_discord_notification


@pytest.fixture(autouse=True)
def _capturable_logger(monkeypatch):
    """Other tests may reconfigure logging; make this logger reach caplog regardless."""
    notify_logger = logging.getLogger("backend.notify")
    monkeypatch.setattr(notify_logger, "propagate", True)
    monkeypatch.setattr(notify_logger, "disabled", False)


FAKE_URL = "https://discord.com/api/webhooks/123456/FAKE-SECRET-TOKEN"


class _Response:
    status_code = 404

    def raise_for_status(self):
        raise requests.HTTPError(f"404 Client Error: Not Found for url: {FAKE_URL}", response=self)


def test_http_error_logs_class_and_status_only(monkeypatch, caplog):
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Response())
    with caplog.at_level(logging.WARNING, logger="backend.notify"):
        assert _send_discord_notification(FAKE_URL, "t", "m") is False

    assert "FAKE-SECRET-TOKEN" not in caplog.text
    assert "discord.com" not in caplog.text
    assert [r.getMessage() for r in caplog.records] == [
        "Discord notification failed: HTTPError status=404"
    ]


def test_connection_error_without_response_logs_no_url(monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise requests.ConnectionError(f"Max retries exceeded with url: {FAKE_URL}")

    monkeypatch.setattr(requests, "post", boom)
    with caplog.at_level(logging.WARNING, logger="backend.notify"):
        assert _send_discord_notification(FAKE_URL, "t", "m") is False

    assert "FAKE-SECRET-TOKEN" not in caplog.text
    assert "Discord notification failed: ConnectionError status=n/a" in caplog.text
