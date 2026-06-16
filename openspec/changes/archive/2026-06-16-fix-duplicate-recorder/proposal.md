## Why

Two recorder instances run concurrently in the deployed (root `Dockerfile`) container — a standalone `python -m backend.recorder` launched by `scripts/docker-entrypoint.sh` **and** the in-process `RecorderService` started by `backend/main.py`. They share one meter-state file (`data/recorder_state.json`) and both upsert the same `slot_observations` row keyed on `slot_start`. The first to wake computes the real cumulative-meter delta and advances the shared state; the second wakes ~5 s later (`recorder_service.py` sleeps 5 s post-boundary), reads the already-advanced state, computes a **zero** delta, and — because it commits last — overwrites the real values with `0.0`. This was harmless until the `2026-06-10-recorder-ssot` change (deployed 2026-06-13) replaced the "first positive write wins" UPSERT guard with authoritative last-writer-wins to allow legitimate zeros and corrections; that unmasked the duplicate as a data-destroying race. Result: all PV/load/import/export energy in `slot_observations` reads `0.0` from 2026-06-14 onward (prices and SoC unaffected), so today/yesterday energy and Grid & Financial cards are blank while the 7-day card still shows the pre-06-14 data.

## What Changes

- **Remove the standalone recorder launch** from `scripts/docker-entrypoint.sh` (the initial launch on line ~129, the auto-restart block on line ~160, and the `RECORDER_PID` tracking/monitoring), so the in-process `RecorderService` becomes the **single** recorder — matching what the HA add-on entrypoint (`darkstar/run.sh`, `darkstar-dev/run.sh`) already does (uvicorn only). **BREAKING** for the root-`Dockerfile` runtime topology only (no API/data-format change).
- **Add a spec requirement** that exactly one recorder instance writes live observations, and that the deployment MUST NOT launch a second concurrent recorder.
- **Add regression coverage** that asserts the entrypoint launches no standalone recorder and that two concurrent recorders cannot silently zero out real data (single-writer invariant).
- **Heal the corrupted range operationally** (not committed fix code): run the existing `bin/backfill_ha.py 2026-06-14 <today>` repair tool once to re-fetch HA history and overwrite the zeroed rows. This is documented as a runbook step, consistent with the repo's existing `bin/`/`scripts/` repair tooling (`fix_load_gaps.py`, `repair_soc.py`, etc.); nothing one-time is added to the application path.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `energy-recording`: add a requirement that exactly one live recorder instance writes `slot_observations`, and that the deployment runtime SHALL NOT start a second concurrent recorder. This closes the gap that, combined with the existing Correctable Energy Storage (authoritative last-writer-wins) requirement, allowed a duplicate recorder to overwrite real measurements with zeros.

## Impact

- **Code:** `scripts/docker-entrypoint.sh` (remove standalone recorder launch + restart + PID monitoring). No change to `backend/recorder.py`, `backend/services/recorder_service.py`, `backend/main.py`, or `backend/learning/store.py` — the recording/storage logic is correct for a single writer.
- **Tests:** new regression test(s) asserting the entrypoint starts no `python -m backend.recorder`, and a single-writer invariant guard.
- **Data:** historical `slot_observations` rows for 2026-06-14 → present are zeroed and require the one-time operational backfill to restore PV/load/import/export. No schema or migration change.
- **Downstream consumers:** ML training (`ml/train.py`) uses 30-day-half-life recency weighting and retrains nightly, so the recent zeros are currently biasing PV/load forecasts downward; healing the range before the next nightly retrain removes the bias. Existing models recover on subsequent retrains once data is correct.
- **Build/deploy:** the fix targets the root-`Dockerfile` entrypoint actually running on the server (confirmed via the `[RECORDER]` log prefix). The add-on entrypoints are already single-recorder. Verify at deploy time which Dockerfile builds the running image so the edit lands where it runs.
- **Operational caveat:** `bin/backfill_ha.py` writes raw `load_kwh` via direct `UPDATE` and does not re-subtract EV/water (the live recorder isolates base load). Acceptable for a short heal, but confirm/adjust before running so healed rows match the base-load meaning of live rows.
