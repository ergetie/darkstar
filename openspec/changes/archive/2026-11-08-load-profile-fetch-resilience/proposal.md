# Proposal

## Why

`get_load_profile_from_ha` builds the 7-day load profile from seven one-day history requests. A single request that fails (12 s timeout during a Home Assistant stall) throws the whole profile away and returns the flat 0.5 kWh demo profile, and the health banner says "Load forecast using demo data". Prod logged this on 2026-11-05 at 12:15, 13:24, 15:00 and 23:00, and again on 2026-11-06 (02:06, 02:07, 04:46, 06:30, 08:44, 22:05) and 2026-11-07 (02:05, 02:06). A normal day request takes about 3 s, so a short retry would have succeeded. Every such failure is logged with an empty message (`get_power_history_batch(1 entities): `), and the executor's retry log is blank for the same reason (`HA API call failed (attempt 1/4): .`, 320 lines on 2026-11-05), so the cause (a timeout) is invisible.

## What Changes

- History chunk requests used for the load profile get a bounded retry on transient errors and a timeout sized for a loaded Home Assistant, inside an overall deadline. The default behaviour of `get_power_history_batch` for other callers (recorder, water progress, backfill) is unchanged.
- If some day chunks still fail, the profile is built from the days that succeeded when enough days did (per-slot coverage averaging over the days fetched, see `energy-recording`). Below that threshold, the last good profile is used.
- The last good load profile is kept in memory and persisted (atomic JSON file under `data/`), and reused on a transient fetch failure up to a maximum age. Only after that does the demo or synthetic profile apply.
- A short-lived in-process failure memo: after a build ends in transient failure, later calls within a cooldown skip fetching and go straight to the fallback chain, and concurrent calls share one in-flight build. During an outage this costs at most one deadline per cooldown window instead of one per call (`get_load_profile_from_ha` is called twice per planner run and by two API routes).
- Health and banner messaging stays truthful: reusing a stored profile or a partial window is reported as such (not as "demo data"), and the status clears when a full live fetch succeeds.
- Failure logs always include the exception type and a non-empty description, in the history fetch, the executor retry log and the final executor failure error.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `load-history-sanitization`: adds requirements for retry and timeout of load-profile history requests, partial-window use, last-good profile reuse with maximum age and persistence, a failure cooldown with shared in-flight builds, and truthful fallback status.
- `async-http-client`: adds a requirement that Home Assistant request failures are logged with their exception type and never with an empty message.

## Impact

- `backend/core/ha_client.py` (`get_power_history_batch`, `get_load_profile_from_ha`, `get_dummy_load_profile` callers), `backend/health.py` (new reasons and clear path, banner text), `backend/core/open_meteo_retry.py` (reuse and a parametrised retry helper), `executor/actions.py` (`_retry_with_backoff` log and `HACallError`), `backend/api/routers/debug.py` (explicit refresh), `.gitignore` (new runtime file), tests under `tests/backend/`.
- New runtime file `data/load_profile_last_good.json` (not committed). No config key, schema or dependency change.
