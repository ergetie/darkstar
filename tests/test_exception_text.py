"""describe_exception never yields an empty description (load-profile-fetch-resilience)."""

import asyncio

import aiohttp
import httpx
import pytest

from backend.core.exception_text import describe_exception


@pytest.mark.parametrize(
    ("exc", "name"),
    [
        (httpx.ReadTimeout(""), "ReadTimeout"),
        (asyncio.TimeoutError(), "TimeoutError"),
        (aiohttp.ServerTimeoutError(), "ServerTimeoutError"),
    ],
)
def test_empty_text_names_the_type(exc, name):
    description = describe_exception(exc)
    assert description.startswith(name)
    assert description.strip() != name + ":"
    assert not description.endswith((":", "."))


def test_text_is_kept_with_type():
    assert (
        describe_exception(httpx.ConnectError("All connection attempts failed"))
        == "ConnectError: All connection attempts failed"
    )


def test_very_long_message_is_capped():
    description = describe_exception(RuntimeError("x" * 5000))
    assert len(description) == 300
    assert description.startswith("RuntimeError: xxx")
    assert description.endswith("...")
