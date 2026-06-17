import logging
from pythonjsonlogger import json as jsonlogger
from backend.core.logging import EmojiFormatter, RingBufferHandler


def test_emoji_formatter_warning():
    """Verify that WARNING logs get the ⚠️ emoji prepended."""
    formatter = EmojiFormatter("%(levelname)s: %(message)s")
    record = logging.LogRecord(
        name="test",
        level=logging.WARNING,
        pathname="test.py",
        lineno=1,
        msg="This is a warning",
        args=(),
        exc_info=None,
    )
    # Populates record.message
    formatter.format(record)
    result = formatter.format(record)
    assert result == "⚠️ WARNING: This is a warning"


def test_emoji_formatter_error():
    """Verify that ERROR logs get the 🚨 emoji prepended."""
    formatter = EmojiFormatter("%(levelname)s: %(message)s")
    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname="test.py",
        lineno=1,
        msg="This is an error",
        args=(),
        exc_info=None,
    )
    formatter.format(record)
    result = formatter.format(record)
    assert result == "🚨 ERROR: This is an error"


def test_emoji_formatter_critical():
    """Verify that CRITICAL logs get the 🚨 emoji prepended."""
    formatter = EmojiFormatter("%(levelname)s: %(message)s")
    record = logging.LogRecord(
        name="test",
        level=logging.CRITICAL,
        pathname="test.py",
        lineno=1,
        msg="This is critical",
        args=(),
        exc_info=None,
    )
    formatter.format(record)
    result = formatter.format(record)
    assert result == "🚨 CRITICAL: This is critical"


def test_emoji_formatter_info_debug():
    """Verify that INFO and DEBUG logs do not get any emoji prepended."""
    formatter = EmojiFormatter("%(levelname)s: %(message)s")

    # INFO
    record_info = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="This is info",
        args=(),
        exc_info=None,
    )
    formatter.format(record_info)
    assert formatter.format(record_info) == "INFO: This is info"

    # DEBUG
    record_debug = logging.LogRecord(
        name="test",
        level=logging.DEBUG,
        pathname="test.py",
        lineno=1,
        msg="This is debug",
        args=(),
        exc_info=None,
    )
    formatter.format(record_debug)
    assert formatter.format(record_debug) == "DEBUG: This is debug"


def test_emoji_formatter_no_duplicate_warning():
    """Verify that warning logs already starting with ⚠️ are not duplicated."""
    formatter = EmojiFormatter("%(levelname)s: %(message)s")
    record = logging.LogRecord(
        name="test",
        level=logging.WARNING,
        pathname="test.py",
        lineno=1,
        msg="⚠️ This is already prefixed",
        args=(),
        exc_info=None,
    )
    formatter.format(record)
    result = formatter.format(record)
    assert result == "WARNING: ⚠️ This is already prefixed"


def test_emoji_formatter_no_duplicate_error():
    """Verify that error logs already starting with ❌/🚨 are not duplicated."""
    formatter = EmojiFormatter("%(levelname)s: %(message)s")

    # With ❌
    record_cross = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname="test.py",
        lineno=1,
        msg="❌ This is already prefixed",
        args=(),
        exc_info=None,
    )
    formatter.format(record_cross)
    assert formatter.format(record_cross) == "ERROR: ❌ This is already prefixed"

    # With 🚨
    record_siren = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname="test.py",
        lineno=1,
        msg="🚨 This is already prefixed",
        args=(),
        exc_info=None,
    )
    formatter.format(record_siren)
    assert formatter.format(record_siren) == "ERROR: 🚨 This is already prefixed"


def test_json_file_handler_has_no_injected_emoji():
    """Verify that the JSON file formatter does not inject emoji prefixes."""
    formatter = jsonlogger.JsonFormatter("%(levelname)s %(message)s")
    record = logging.LogRecord(
        name="test",
        level=logging.WARNING,
        pathname="test.py",
        lineno=1,
        msg="A plain warning",
        args=(),
        exc_info=None,
    )
    formatter.format(record)
    result = formatter.format(record)
    assert "⚠️" not in result
    assert "🚨" not in result


def test_ring_buffer_warning_gets_emoji():
    """Verify that the ring buffer handler emits entries with the emoji prefix."""
    handler = RingBufferHandler(maxlen=10)
    handler.setFormatter(EmojiFormatter("%(levelname)s: %(message)s"))
    record = logging.LogRecord(
        name="test",
        level=logging.WARNING,
        pathname="test.py",
        lineno=1,
        msg="A buffered warning",
        args=(),
        exc_info=None,
    )
    handler.emit(record)
    logs = handler.get_logs()
    assert logs[-1]["message"].startswith("⚠️")
