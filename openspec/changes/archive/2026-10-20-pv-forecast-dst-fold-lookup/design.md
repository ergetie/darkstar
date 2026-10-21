# Design

## Context

Two key types meet in the PV slot mapping: fixed-offset python `datetime` keys from `open_meteo_solar_forecast` (`estimate.watts`, one offset for the whole range) and price slot `start_time` values that may be pandas `Timestamp`s (from `ml/forward.py` `dst_safe_date_range`) or pytz datetimes. Python datetime hashing ignores `fold` for inter-zone comparison inconsistently, and pandas Timestamp hashing in a fold differs from the equal-instant datetime, so `in dict` is not a reliable instant match. Daily totals in `_get_forecast_data_async` iterate the keys and convert with `astimezone(local_tz)`, which is instant-correct and unaffected. `_estimate_from_same_time_of_day` keys by local wall-clock `time()`, which is intentional (time-of-day profile) and out of scope.

## Goals / Non-Goals

**Goals:**
- Live, stored-baseline and DB-fallback exact-slot lookups match by UTC instant for any aware datetime type, including DST fold and spring-forward gaps.
- Banner and errors clear when Open-Meteo returns complete data.

**Non-Goals:**
- Changing fallback/estimation semantics, daily total logic, or `dst_safe_date_range`.
- Changing how slots are generated in `ml/forward.py`.

## Decisions

- **Canonical key = int Unix seconds of the 15-min-floored UTC instant.** A small helper (e.g. `_slot_key(ts) -> int`) converts any aware datetime/Timestamp: `int(ts.timestamp())` floored to 900 s; naive values are treated as UTC (matching the existing daily-total convention). Integers have no fold/tz/type hashing ambiguity. Alternative (UTC python datetimes via `astimezone(UTC)` + `to_pydatetime()`) works too but still relies on type conversion at every call site; ints are simpler and cheaper.
- **Flooring on the instant, not wall clock.** Replaces `slot_time.replace(minute=...)`, which operated in local wall time and could also carry fold quirks. Equivalent for all whole-hour/quarter-hour offsets in use.
- **Build a key index once** (`{_slot_key(k): watts}`) so mapping stays O(slots), preserving the "Efficient Live PV Slot Mapping" performance requirement.
- **Stored fallback `by_slot`** keyed with the same helper; `slot_times` remain local datetimes for date/time-of-day use.
- **DB forecast fallback `build_db_forecast_for_slots`**: its `indexed` dict (pytz local keys) is looked up with `slot.astimezone(local_tz)`; verified that a fold=1 pandas Timestamp misses this lookup, so it uses the same helper.
- **Verified unaffected (no change):** the per-array sum in `_fetch_forecast` (all keys come from the same library response with one fixed offset), the daily-total loop (iterates its own keys), and `ml/forward.py` (only pandas `merge`, which matches on int64 UTC values, no dict lookups on slot times).

## Risks / Trade-offs

- [Non-quarter-hour offsets] Flooring on Unix seconds assumes zone offsets are multiples of 15 min → true for all supported configured zones; documented in the helper.
- [Hidden callers relying on datetime keys] Index is local to the function; no external contract changes.
