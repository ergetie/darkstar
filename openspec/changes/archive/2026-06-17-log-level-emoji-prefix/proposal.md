## Why

Startup logs use emojis (🚀 ✅ 💾) so operators can scan them at a glance, but warnings and errors during normal running are mostly plain text. Only ~35 of ~355 `warning`/`error` call sites include an emoji, so the important lines (the ones an operator needs to spot fast) are the hardest to pick out of the log stream.

## What Changes

- Add a custom logging `Formatter` in `backend/core/logging.py` that automatically prepends a level-based emoji to every log record: `WARNING → ⚠️`, `ERROR`/`CRITICAL → 🚨`. `INFO`/`DEBUG` are unchanged.
- Guard against double prefixing: if a message already starts with an emoji (e.g. the ~35 existing `⚠️`/`❌` messages, or startup lines), the formatter does not add another.
- Apply the formatter to the **console** handler and the **UI ring-buffer** handler (both already share one formatter instance), so the dashboard log viewer also gets the prefixes.
- Leave the **JSON file handler** untouched — it already records `levelname` as a structured field, so injecting emojis there would only pollute machine-readable logs.
- Clean up the ~35 hand-typed emoji prefixes from individual `warning`/`error` message strings so they flow through the formatter instead (the double-prefix guard makes this safe to do incrementally, but the cleanup keeps messages consistent).

## Capabilities

### New Capabilities
- `log-level-emoji-prefix`: Automatic, level-based emoji prefixing of log records at the formatter layer, with a guard that avoids duplicating an emoji already present in the message.

### Modified Capabilities
<!-- None: no existing spec's requirements change. -->

## Impact

- **Code**: `backend/core/logging.py` (new `Formatter` subclass, wired into console + ring-buffer handlers). Cleanup edits across ~35 `logger.warning(...)`/`logger.error(...)` call sites that currently hand-type an emoji.
- **Behavior**: Console output and the UI log viewer gain a leading emoji on warning/error lines. JSON file logs are unchanged.
- **No** dependencies, APIs, schema, or config changes. Cosmetic/observability only.
