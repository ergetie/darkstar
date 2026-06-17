## Context

Logging is configured centrally in `backend/core/logging.py` via `setup_logging()`. There are three handlers on the root logger:

1. **Console** (`StreamHandler`) — uses `console_formatter = logging.Formatter("%(levelname)s:\t%(name)s - %(message)s")`.
2. **JSON file** (`TimedRotatingFileHandler` + `pythonjsonlogger`) — structured, daily rotation, carries `levelname` as a field.
3. **UI ring buffer** (`RingBufferHandler`) — reuses the same `console_formatter` instance for the messages the dashboard polls.

Emojis today are hand-typed into ~35 of ~355 `warning`/`error` message strings; the other ~90% are plain. Startup INFO lines also hand-type emojis (🚀 ✅ 💾). The goal is consistent, level-based emoji prefixing without touching every call site and without polluting the JSON logs.

## Goals / Non-Goals

**Goals:**
- One central place that prefixes `⚠️` for WARNING and `🚨` for ERROR/CRITICAL on console + UI output.
- Idempotent: never produce a double emoji on messages that already start with one.
- JSON file logs unchanged.
- Remove the now-redundant hand-typed emojis from warning/error messages.

**Non-Goals:**
- Changing log levels, handlers, rotation, or the noisy-library suppression config.
- Adding emojis to INFO/DEBUG (startup INFO lines keep their existing hand-typed emojis via the no-duplicate guard).
- Changing the JSON file format or the ring buffer's stored structure.

## Decisions

### Decision: Subclass `logging.Formatter` rather than edit call sites
Create an `EmojiFormatter(logging.Formatter)` that overrides `format()`: compute the base string via `super().format(record)`, then prepend the level emoji unless an emoji is already present. Wire it into the console handler and set it on the ring-buffer handler (replacing the shared `console_formatter`).

- **Why:** One change covers all ~355 sites and any future ones. Editing call sites individually is error-prone and doesn't help new code.
- **Alternative considered:** A `logging.Filter` that mutates `record.msg`. Rejected — a filter runs once and would also affect the JSON handler (filters attach to logger/handler and mutate shared record state), risking emoji leakage into structured logs. Formatting is the correct layer because each handler formats independently.

### Decision: Emoji mapping by `record.levelno`
`WARNING → ⚠️`, `ERROR` and `CRITICAL → 🚨`, everything else → no prefix. Use `levelno` thresholds/constants, not string matching on `levelname`.

### Decision: "Already has emoji" guard
Before prefixing, check whether the formatted message's first non-whitespace character is already an emoji. Implementation: test the leading character(s) against a small set/range of emoji code points (covers the emojis actually in use — ⚠️ ❌ ✅ 🚀 💾 🔌 🔗 📍 🚨 — and the general Unicode emoji ranges). If present, return the string unchanged.

- **Why:** Preserves the ~35 existing hand-typed warning/error emojis and startup lines during/after the cleanup, and is safe if cleanup is partial.
- **Alternative considered:** Skip the guard and rely solely on cleanup removing every hand-typed emoji. Rejected — fragile (one missed site = double emoji) and startup INFO emojis would still need protection.

### Decision: Prefix placement
Prepend the emoji before the whole formatted line (i.e. `"⚠️ " + base`), so it leads the rendered output the operator scans. The `levelname/name - message` structure is preserved after the emoji.

### Decision: Cleanup of hand-typed emojis
Strip leading emoji prefixes from the ~35 `logger.warning(...)`/`logger.error(...)` message strings so they render uniformly via the formatter. The no-duplicate guard means this cleanup is non-breaking and can be done in the same change.

## Risks / Trade-offs

- **Emoji detection misclassifies a message that legitimately starts with a non-emoji symbol** → Keep the detection scoped to actual emoji code-point ranges (not arbitrary punctuation); default to "no emoji present → add prefix", which is the safe/expected behavior.
- **Terminals or log scrapers that dislike multibyte glyphs** → Console already emits emojis today (startup lines), and the JSON file handler — the machine-readable sink — is explicitly excluded, so scraping is unaffected.
- **Ring buffer stores the formatted string** → It already does (`self.format(record)`), so the UI simply gains the prefix with no structural change.
- **Width of ⚠️/🚨 (variation selectors)** → Cosmetic only; matches the existing `⚠️ SLOW TICK` line already in production.

## Migration Plan

No data or config migration. Ship the formatter + call-site cleanup together; effect is immediate on next restart. Rollback = revert the commit (no persisted state, no schema).
