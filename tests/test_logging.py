import logging
from collections.abc import Iterator
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest
from pythonjsonlogger import json as jsonlogger

from backend.core.logging import EmojiFormatter, RingBufferHandler, setup_logging


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


@pytest.fixture
def file_handler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[RotatingFileHandler]:
    """Run setup_logging in a temp working dir and yield the file handler it installs."""
    root = logging.getLogger()
    before_handlers = list(root.handlers)
    before_level = root.level
    monkeypatch.chdir(tmp_path)
    setup_logging()
    added = [h for h in root.handlers if h not in before_handlers]
    handler = next(h for h in added if isinstance(h, RotatingFileHandler))
    yield handler
    for h in added:
        root.removeHandler(h)
    handler.close()
    root.setLevel(before_level)


def test_file_handler_is_size_rotating(file_handler: RotatingFileHandler):
    assert type(file_handler) is RotatingFileHandler
    assert file_handler.maxBytes == 10 * 1024 * 1024
    assert file_handler.backupCount == 5
    assert file_handler.encoding == "utf-8"
    assert file_handler.mode == "a"


def test_file_handler_rolls_over_to_numbered_backup(
    file_handler: RotatingFileHandler, tmp_path: Path
):
    def record(msg: str) -> logging.LogRecord:
        return logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg=msg,
            args=(),
            exc_info=None,
        )

    # Start with a non-empty file: Python < 3.12.3 also rolls over an empty
    # file, so an oversized first record would behave differently by version.
    file_handler.emit(record("small"))
    file_handler.emit(record("x" * (file_handler.maxBytes + 1)))  # rolls over first

    log_dir = tmp_path / "data"
    assert (log_dir / "darkstar.log.1").is_file()
    assert (log_dir / "darkstar.log.1").stat().st_size < file_handler.maxBytes
    assert not (log_dir / "darkstar.log.2").exists()
    assert (log_dir / "darkstar.log").stat().st_size > file_handler.maxBytes
