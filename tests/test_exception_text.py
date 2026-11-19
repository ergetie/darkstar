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


@pytest.mark.parametrize(
    ("message", "expected", "absent"),
    [
        (
            "404 for https://discord.com/api/webhooks/123/SECRET",
            "404 for https://discord.com/api/webhooks/<redacted>",
            ["SECRET", "123"],
        ),
        (
            "bad https://ha.local:8123/api/x?access_token=abc",
            "bad https://ha.local:8123/<redacted>",
            ["abc", "access_token", "/api/x"],
        ),
        (
            "failed https://user:pw@ha.local:8123",
            "failed https://ha.local:8123/<redacted>",
            ["user", "pw"],
        ),
        (
            "see (https://ha.local/api/states/x).",
            "see (https://ha.local/<redacted>).",
            ["states"],
        ),
        (
            "a https://one.local/p1 b https://two.local:9/p2?q=1 c",
            "a https://one.local/<redacted> b https://two.local:9/<redacted> c",
            ["p1", "p2", "q=1"],
        ),
        ("http://homeassistant.local:8123", "http://homeassistant.local:8123", []),
        ("http://homeassistant.local:8123/", "http://homeassistant.local:8123/", []),
        ("just text, no url", "just text, no url", []),
    ],
)
def test_urls_are_scrubbed(message, expected, absent):
    description = describe_exception(RuntimeError(message))
    assert description == f"RuntimeError: {expected}"
    for secret in absent:
        assert secret not in description


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("token=abc123 failed", "token=<redacted> failed"),
        ("api_key=XYZ&x=1", "api_key=<redacted>&x=1"),
        ("key=k1 and password=hunter2", "key=<redacted> and password=<redacted>"),
        ("access_token=tok", "access_token=<redacted>"),
        ("Authorization: Bearer abc.DEF-123", "Authorization: Bearer <redacted>"),
        ("monkey patch, no secrets", "monkey patch, no secrets"),
    ],
)
def test_token_patterns_are_masked_outside_urls(message, expected):
    assert describe_exception(RuntimeError(message)) == f"RuntimeError: {expected}"


def test_scrub_happens_before_truncation():
    secret = "S3CRET"
    description = describe_exception(RuntimeError("x" * 280 + f" https://h.io/{secret}"))
    assert secret not in description
