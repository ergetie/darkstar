"""Readable one-line descriptions of exceptions for log lines and error details."""

_MAX_LENGTH = 300


def describe_exception(exc: BaseException, max_length: int = _MAX_LENGTH) -> str:
    """Return ``TypeName: text`` for an exception, never an empty description.

    Many timeouts (``httpx.ReadTimeout``, ``asyncio.TimeoutError``) have an empty
    string, which turns a plain ``"%s", exc`` log into a blank line. When the text
    is empty the exception's ``repr`` is used instead, prefixed with the type name
    if the ``repr`` does not already start with it. The result is capped at
    ``max_length`` characters so a huge response body cannot flood a log.
    """
    name = type(exc).__name__
    text = str(exc).strip()
    if text:
        description = f"{name}: {text}"
    else:
        shown = repr(exc)
        description = shown if shown.startswith(name) else f"{name} {shown}"
    if len(description) > max_length:
        description = description[: max_length - 3] + "..."
    return description
