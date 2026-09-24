## 1. Shared helper

- [x] 1.1 Add `backend/core/ha_timestamps.py` with `reading_timestamp(state)` (`last_reported` → `last_updated` → `last_changed`, skip unparseable, naive → UTC, `None` if nothing usable)
- [x] 1.2 Unit tests: each fallback step, unparseable value skipped, naive → UTC, empty/None state

## 2. Load balancer phase readings

- [x] 2.1 `executor/engine.py`: use `reading_timestamp` for phase power/current and phase voltage timestamps; remove `_parse_ha_timestamp` if no longer used
- [x] 2.2 Tests: steady value with fresh `last_reported` is not stale (no stale_fallback/notification); old `last_reported` is stale; state without `last_reported` falls back to `last_updated`; stale voltage (by `last_reported`) still marks phase stale
- [x] 2.3 Update existing load-balancer/engine test fixtures only where they assert the old timestamp source

## 3. SoC staleness wiring

- [x] 3.1 `backend/core/ha_client.py`: factor state→float parsing so `get_ha_sensor_float` and `get_initial_state` share it; in `get_initial_state` fetch the SoC full state once and set `initial_state["soc_timestamp"]` (ISO, tz-aware) when available; keep `HA_UNAVAILABLE` behaviour identical
- [x] 3.2 Tests: `soc_timestamp` populated from `last_reported`; omitted when no timestamp; 45-min-old SoC → `DATA_STALE` warning, planner continues; steady SoC with fresh `last_reported` → no warning

## 4. Verify

- [x] 4.1 `rg` confirms no remaining live-freshness consumer uses `last_updated`/`last_changed` directly (history consumers intentionally untouched)
- [x] 4.2 `./scripts/lint.sh` passes and full test suite green
