## 1. Invariant monitor thresholds (backend/monitors.py)

- [x] 1.1 Change `COMMAND_SUCCESS_MIN` from `0.99` to `0.95` and update the constant's doc comment (lines ~30 and ~65) to reflect the new rationale (tolerates ~72 failed one-minute ticks per 24 h)
- [x] 1.2 Delete the hardcoded `PV_FORECAST_CEILING_KWH = 7.11 * 0.25` constant and compute the ceiling inside `_eval_forecast_sanity` as `sum(array.kwp for system.solar_arrays) * 0.25`, read from `self._config`
- [x] 1.3 In `_eval_forecast_sanity`, return `skipped` with reason "no solar arrays configured" when the arrays list is missing/empty or summed kWp ≤ 0
- [x] 1.4 Update/add monitor unit tests: 14.94 kWp system passes at 2.781 kWh/slot; 7.11 kWp system violates above 1.778; no-arrays config skips; 18/1321 failed ticks passes at 95 %; sustained failure (e.g. 10 %) still violates

## 2. Load-history delta guard (backend/core/ha_client.py)

- [x] 2.1 In `get_load_profile_from_ha`, read `recorder.max_meter_delta_kwh` from config (default 50.0) and skip any interval whose `energy_delta` exceeds it (advance `prev_state`/`prev_time` normally so subsequent deltas stay correct); count skipped deltas and track the largest
- [x] 2.2 After the state loop, log one WARNING with the skip count and largest skipped delta when any were skipped; keep the existing 500 kWh/day backstop unchanged
- [x] 2.3 Add unit tests: history with nightly 0→lifetime jumps yields a plausible profile without the demo fallback; clean history is byte-identical to pre-guard output; skip warning is logged once

## 3. Honest degraded messaging (backend/core/ha_client.py)

- [x] 3.1 Pass a discard reason into the demo-fallback path (or set it before calling `get_dummy_load_profile`) so the fallback knows whether a sensor was configured and why its data was rejected
- [x] 3.2 When a sensor is configured but its data was discarded, log and set `set_load_forecast_status("degraded", "demo")` detail text that names the sensor and says the data was discarded as implausible — not "configure your sensor"; keep the existing message when no sensor is configured
- [x] 3.3 Add unit tests for both message variants (configured-but-discarded vs not-configured)

## 4. Null inverter profile fallback (executor/profiles.py)

- [x] 4.1 In `get_profile_from_config`, resolve the profile name with `system_config.get("inverter_profile") or "generic"` so null/empty goes straight to `generic` with a single INFO log and no `profiles/None.yaml` attempt or ERROR log
- [x] 4.2 Add unit tests: `inverter_profile: null` loads generic with no ERROR-level record; a misspelled name still logs WARNING and falls back to generic

## 5. Banner snooze (frontend)

- [x] 5.1 In `SystemAlert.tsx`, add a snooze helper: store `{[key]: expiryTimestamp}` in `localStorage` keyed by `issue.code || issue.category` with a 24 h window, and filter snoozed, unexpired issues out of the rendered list
- [x] 5.2 Render the ✕ (snooze) button on both critical and warning banners, wired to the snooze helper (remove dependence on the never-passed `onDismiss` prop)
- [x] 5.3 Show a compact "N snoozed" chip whenever snoozed issues exist; clicking it clears their snooze entries so the banners reappear
- [x] 5.4 Update `SystemAlert` tests (or add them): snoozing hides only the snoozed issue; expired snooze re-renders the banner; message-number changes don't defeat the snooze; the snoozed chip restores banners

## 6. Verification

- [x] 6.1 Run backend tests (monitors, ha_client, profiles) and frontend tests; run linters
- [x] 6.2 Manual sanity check with the beta tester's config values: forecast ceiling computes to 3.735 kWh/slot for 14.94 kWp; simulated 19,609 kWh jump history produces a real profile, not demo
