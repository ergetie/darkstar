"""The executor retry log and final error never hide an empty-message exception."""

import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest

from executor.actions import HACallError, _retry_with_backoff


@pytest.mark.asyncio
async def test_retry_log_names_timeout_type(caplog):
    operation = AsyncMock(side_effect=[asyncio.TimeoutError(), "ok"])
    with (
        patch("executor.actions.asyncio.sleep", new=AsyncMock()),
        caplog.at_level(logging.WARNING, logger="executor.actions"),
    ):
        assert await _retry_with_backoff(operation, max_retries=3) == "ok"

    lines = [r.getMessage() for r in caplog.records if "attempt 1/4" in r.getMessage()]
    assert len(lines) == 1
    assert "TimeoutError" in lines[0]
    assert "attempt 1/4): ." not in lines[0]
    assert "attempt 1/4): ;" not in lines[0]


@pytest.mark.asyncio
async def test_exhausted_error_carries_last_exception_description():
    operation = AsyncMock(side_effect=asyncio.TimeoutError())
    with patch("executor.actions.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(HACallError) as exc_info:
            await _retry_with_backoff(operation, max_retries=1)
    assert "TimeoutError" in str(exc_info.value)
    assert exc_info.value.exception_type == "TimeoutError"
    assert "after 2 attempts: TimeoutError" in exc_info.value.message
