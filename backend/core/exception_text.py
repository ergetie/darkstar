"""Readable, secret-free one-line descriptions of exceptions for log lines and error details."""

import re

_MAX_LENGTH = 300

_URL_RE = re.compile(r"\b(?:https?|wss?)://[^\s<>\"'`]+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:!?)]}"
_DISCORD_WEBHOOK_RE = re.compile(
    r"^(?P<scheme>https?)://(?:[^/@]*@)?(?P<host>(?:[\w-]+\.)?discord(?:app)?\.com)(?::\d+)?"
    r"/api(?:/v\d+)?/webhooks(?:/|$)",
    re.IGNORECASE,
)
_URL_PARTS_RE = re.compile(
    r"^(?P<scheme>[a-z]+)://(?:[^/?#@]*@)?(?P<host>[^/?#]*)(?P<rest>.*)$", re.IGNORECASE | re.DOTALL
)
_TOKEN_PARAM_RE = re.compile(
    r"\b(?P<key>access_token|api_key|token|key|password)(?P<sep>=)"
    r"(?P<quote>(?:\\*[\"'])?)[^\s&\"',;\\]+",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"\b(?P<prefix>bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE)


def _scrub_one_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    url = raw.rstrip(_TRAILING_PUNCTUATION)
    trailing = raw[len(url) :]

    webhook = _DISCORD_WEBHOOK_RE.match(url)
    if webhook:
        return (
            f"{webhook.group('scheme')}://{webhook.group('host')}/api/webhooks/<redacted>{trailing}"
        )

    parts = _URL_PARTS_RE.match(url)
    if parts is None:
        return raw
    has_userinfo = "@" in url.split("://", 1)[1].split("/", 1)[0].split("?", 1)[0]
    rest = parts.group("rest")
    if rest in ("", "/") and not has_userinfo:
        return raw
    return f"{parts.group('scheme')}://{parts.group('host')}/<redacted>{trailing}"


def scrub_urls(text: str) -> str:
    """Reduce every URL in ``text`` so path, query, fragment and credentials are removed.

    Discord webhook URLs become ``https://discord.com/api/webhooks/<redacted>``; other
    URLs with anything beyond a host become ``scheme://host[:port]/<redacted>``.
    Host-only URLs are kept so a Home Assistant address stays diagnosable.
    """
    return _URL_RE.sub(_scrub_one_url, text)


def mask_secret_params(text: str) -> str:
    """Mask ``token=``, ``api_key=``, ``key=``, ``access_token=``, ``password=`` and bearer values."""
    text = _TOKEN_PARAM_RE.sub(
        lambda m: f"{m.group('key')}{m.group('sep')}{m.group('quote')}<redacted>", text
    )
    return _BEARER_RE.sub(lambda m: f"{m.group('prefix')}<redacted>", text)


def describe_exception(exc: BaseException, max_length: int = _MAX_LENGTH) -> str:
    """Return ``TypeName: text`` for an exception, never an empty description.

    Many timeouts (``httpx.ReadTimeout``, ``asyncio.TimeoutError``) have an empty
    string, which turns a plain ``"%s", exc`` log into a blank line. When the text
    is empty the exception's ``repr`` is used instead, prefixed with the type name
    if the ``repr`` does not already start with it. URLs and token-like values are
    scrubbed before the result is capped at ``max_length`` characters, so a secret
    webhook URL or a huge response body cannot reach a log.
    """
    name = type(exc).__name__
    text = str(exc).strip()
    if text:
        description = f"{name}: {text}"
    else:
        shown = repr(exc)
        description = shown if shown.startswith(name) else f"{name} {shown}"
    description = mask_secret_params(scrub_urls(description))
    if len(description) > max_length:
        description = description[: max_length - 3] + "..."
    return description
