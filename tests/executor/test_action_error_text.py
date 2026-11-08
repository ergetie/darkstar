"""Executor action failure logs never hide an empty-message exception."""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from executor.actions import ActionDispatcher, HACallError, _retry_with_backoff


def _dispatcher(ha: MagicMock) -> ActionDispatcher:
    return ActionDispatcher(ha_client=ha, config=MagicMock(), shadow_mode=False)


def _only(caplog, text: str) -> str:
    lines = [r.getMessage() for r in caplog.records if text in r.getMessage()]
    assert len(lines) == 1, caplog.text
    return lines[0]


@pytest.mark.asyncio
async def test_write_failure_names_exception_type(caplog):
    async def fail(*_args, **_kwargs):
        await _retry_with_backoff(AsyncMock(side_effect=asyncio.TimeoutError()), max_retries=0)

    ha = MagicMock()
    ha.get_state = AsyncMock(return_value={"state": "6", "attributes": {}})
    ha.set_number = AsyncMock(side_effect=fail)
    with caplog.at_level(logging.ERROR, logger="executor.actions"):
        assert await _dispatcher(ha)._write_entity("number.x", 10, "number") is False

    line = _only(caplog, "Failed to write to number.x")
    assert "HACallError" in line
    assert "TimeoutError" in line


@pytest.mark.asyncio
async def test_write_failure_with_empty_hacallerror_text_is_not_blank(caplog):
    ha = MagicMock()
    ha.get_state = AsyncMock(return_value={"state": "6", "attributes": {}})
    ha.set_number = AsyncMock(side_effect=HACallError(""))
    with caplog.at_level(logging.ERROR, logger="executor.actions"):
        await _dispatcher(ha)._write_entity("number.x", 10, "number")

    assert "HACallError" in _only(caplog, "Failed to write to number.x")


@pytest.mark.asyncio
async def test_notification_failure_names_timeout(caplog):
    ha = MagicMock()
    ha.send_notification = AsyncMock(side_effect=asyncio.TimeoutError())
    with caplog.at_level(logging.WARNING, logger="executor.actions"):
        await _dispatcher(ha)._send_notification("hi")

    assert "TimeoutError" in _only(caplog, "Failed to send notification")


@pytest.mark.asyncio
async def test_balancer_ha_notification_failure_names_timeout(caplog):
    ha = MagicMock()
    ha.send_notification = AsyncMock(side_effect=asyncio.TimeoutError())
    with (
        patch("backend.core.secrets.load_notifications_config", return_value={}),
        caplog.at_level(logging.WARNING, logger="executor.actions"),
    ):
        await _dispatcher(ha).notify_balancer_intervention("hi")

    assert "TimeoutError" in _only(caplog, "Balancer HA notification failed")


@pytest.mark.asyncio
async def test_balancer_discord_fallback_failure_names_timeout(caplog):
    ha = MagicMock()
    ha.send_notification = AsyncMock(return_value=False)
    with (
        patch(
            "backend.core.secrets.load_notifications_config",
            return_value={"discord_webhook_url": "https://example.invalid/hook"},
        ),
        patch("backend.notify.send_critical_notification", side_effect=asyncio.TimeoutError()),
        caplog.at_level(logging.WARNING, logger="executor.actions"),
    ):
        await _dispatcher(ha).notify_balancer_intervention("hi")

    assert "TimeoutError" in _only(caplog, "Balancer Discord fallback failed")
