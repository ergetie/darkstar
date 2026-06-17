## 1. Emoji formatter

- [x] 1.1 In `backend/core/logging.py`, add an `EmojiFormatter(logging.Formatter)` subclass that overrides `format()`: call `super().format(record)`, then prepend an emoji based on `record.levelno` (`WARNING → ⚠️`, `ERROR`/`CRITICAL → 🚨`, otherwise no change).
- [x] 1.2 Add a helper that detects whether the formatted message already begins (first non-whitespace char) with an emoji, covering the emojis in use (⚠️ ❌ ✅ 🚀 💾 🔌 🔗 📍 🚨) plus the general emoji code-point ranges; skip prefixing when one is present.
- [x] 1.3 Ensure no emoji is added for `INFO`/`DEBUG` records.

## 2. Wire into handlers

- [x] 2.1 Replace the console handler's formatter with `EmojiFormatter` using the existing format string `"%(levelname)s:\t%(name)s - %(message)s"`.
- [x] 2.2 Set the same `EmojiFormatter` instance on the ring-buffer handler (currently `_ring_buffer_handler.setFormatter(console_formatter)`).
- [x] 2.3 Confirm the JSON file handler still uses `jsonlogger.JsonFormatter` (unchanged — no emoji injection).

## 3. Clean up hand-typed emoji prefixes

- [x] 3.1 Strip leading emoji prefixes from `logger.warning(...)`/`logger.error(...)` messages in `backend/main.py`.
- [x] 3.2 Same cleanup in `backend/health.py`.
- [x] 3.3 Same cleanup in `backend/ha_socket.py`.
- [x] 3.4 Same cleanup in `backend/config_migration.py`.
- [x] 3.5 Same cleanup in `ml/forward.py`.
- [x] 3.6 Leave INFO-level startup emojis (🚀 ✅ 💾) intact — the no-duplicate guard preserves them.

## 4. Verify

- [x] 4.1 Emit test WARNING and ERROR records (plain message) and confirm console + ring-buffer lines start with `⚠️` / `🚨`.
- [x] 4.2 Emit a WARNING whose message already starts with `⚠️` (e.g. the `SLOW TICK` line) and confirm exactly one emoji appears (no duplication).
- [x] 4.3 Confirm a record written to the JSON file handler has no injected emoji in its `message` field.
- [x] 4.4 Confirm INFO/DEBUG console lines are unchanged.
