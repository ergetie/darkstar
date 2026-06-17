import logging
import os
from collections import deque
from datetime import UTC, datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

from pythonjsonlogger import json as jsonlogger


# Ring Buffer for real-time logs in UI
class RingBufferHandler(logging.Handler):
    """In-memory ring buffer for log entries that the UI can poll."""

    def __init__(self, maxlen: int = 1000) -> None:
        super().__init__()
        self._buffer: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            timestamp = datetime.fromtimestamp(record.created, tz=UTC)
        except Exception:
            timestamp = datetime.now(UTC)
        entry = {
            "timestamp": timestamp.isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": self.format(record),
        }
        self._buffer.append(entry)

    def get_logs(self) -> list[dict[str, Any]]:
        return list(self._buffer)


class EmojiFormatter(logging.Formatter):
    """Logging formatter that prepends level-based emojis to log records."""

    def _starts_with_emoji(self, s: str) -> bool:
        if not s:
            return False
        s_stripped = s.lstrip()
        if not s_stripped:
            return False
        first_char = s_stripped[0]
        cp = ord(first_char)
        # Check code point ranges for common emojis and symbols
        return (0x2600 <= cp <= 0x27BF) or (0x2300 <= cp <= 0x23FF) or (0x1F000 <= cp <= 0x1FBF9)

    def format(self, record: logging.LogRecord) -> str:
        # Get standard formatted message/record line
        formatted = super().format(record)

        # Only WARNING and above get an emoji prefix
        if record.levelno < logging.WARNING:
            return formatted

        # Check if the message already starts with an emoji
        msg = record.message if hasattr(record, "message") else record.getMessage()
        if self._starts_with_emoji(msg):
            return formatted

        # Prepend the level-based emoji
        if record.levelno == logging.WARNING:
            return "⚠️ " + formatted
        elif record.levelno >= logging.ERROR:
            return "🚨 " + formatted

        return formatted


# Global instances
_ring_buffer_handler = RingBufferHandler(maxlen=1000)


def setup_logging():
    """Configure centralized logging with JSON file rotation and Ring Buffer."""
    log_level_str = os.environ.get("LOG_LEVEL", "INFO").upper()
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if log_level_str not in valid_levels:
        log_level_str = "INFO"

    log_level = getattr(logging, log_level_str)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # 1. Console Handler (Simple format)
    console_handler = logging.StreamHandler()
    console_formatter = EmojiFormatter("%(levelname)s:\t%(name)s - %(message)s")
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # 2. File Handler (JSON, Timed Rotation)
    log_dir = Path.cwd() / "data"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "darkstar.log"

    file_handler = TimedRotatingFileHandler(
        log_file, when="midnight", interval=1, backupCount=7, encoding="utf-8"
    )

    # Custom JSON Formatter
    json_formatter = jsonlogger.JsonFormatter(  # type: ignore[no-untyped-call]
        "%(asctime)s %(levelname)s %(name)s %(message)s %(module)s %(lineno)d"
    )
    file_handler.setFormatter(json_formatter)
    root_logger.addHandler(file_handler)

    # 3. Ring Buffer Handler (for UI)
    _ring_buffer_handler.setFormatter(console_formatter)
    root_logger.addHandler(_ring_buffer_handler)

    # Explicitly set darkstar loggers
    logging.getLogger("darkstar").setLevel(log_level)

    # Silence noisy library loggers (Rev ARC13)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("websockets.client").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # Silence repetitive API data loading (Rev DX2)
    logging.getLogger("darkstar.api").setLevel(logging.WARNING)


def get_ring_buffer() -> RingBufferHandler:
    """Return the global ring buffer handler instance."""
    return _ring_buffer_handler
