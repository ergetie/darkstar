## 1. Remove the duplicate recorder

- [x] 1.1 In `scripts/docker-entrypoint.sh`, remove the initial standalone recorder launch (`python -m backend.recorder 2>&1 | … &` around line 129) and its `log "Starting Recorder…"` / `log "Recorder started (PID …)"` lines.
- [x] 1.2 Remove the recorder auto-restart block from the monitor loop (the `if ! kill -0 "$RECORDER_PID" … python -m backend.recorder … fi` around line 160).
- [x] 1.3 Remove the now-unused `RECORDER_PID` variable and its `cleanup()` kill handling, so the script tracks only `API_PID`.
- [x] 1.4 Verify the edited entrypoint still starts uvicorn (`backend.main:app`) exactly once and that no reference to `backend.recorder` remains: `grep -n "backend.recorder" scripts/docker-entrypoint.sh` returns nothing.

## 2. Regression coverage

- [x] 2.1 Add a test asserting `scripts/docker-entrypoint.sh` contains no `python -m backend.recorder` invocation (guards against silent reintroduction).
- [x] 2.2 Add/confirm a single-writer invariant test: simulate two recorder cycles sharing one `RecorderStateStore` (`data/recorder_state.json`) on the same slot and assert the second cycle's zero delta does not become the stored value when only one recorder is intended — i.e., document/lock the expectation that exactly one recorder runs. Reference the `Single Live Recorder Instance` spec scenarios.
- [x] 2.3 Run the test suite for the recorder area (e.g. `tests/backend/test_recorder_deltas.py` and any entrypoint test) and confirm green.

## 3. Build, deploy, and verify live recording

- [x] 3.1 Confirm which Dockerfile builds the running server image (the server currently uses `scripts/docker-entrypoint.sh`, confirmed by the `[RECORDER]` log prefix); ensure the edit lands in the entrypoint that actually runs.
- [ ] 3.2 Build and deploy the updated image.
- [ ] 3.3 Confirm logs show only the in-process recorder (`INFO: recorder - Recording observation …`) and **no** `[RECORDER]` lines, and that each slot is recorded exactly once.
- [ ] 3.4 Confirm newly recorded slots store non-zero PV/load/import/export when the system is actually producing/consuming.

## 4. Heal the corrupted data range (one-time operational step)

- [x] 4.1 Resolve the open question: confirm whether `bin/backfill_ha.py` should subtract EV/water so healed `load_kwh` matches the live base-load meaning; adjust the tool or range if needed.
- [ ] 4.2 Run `bin/backfill_ha.py 2026-06-14 <today>` once against the production DB (after the entrypoint fix is live so the recorder no longer re-zeros) to re-fetch HA history and overwrite the zeroed rows.
- [ ] 4.3 Verify `slot_observations` for `2026-06-14 → present` now has restored PV/load/import/export, and that the Energy Resources and Grid & Financial cards show today/yesterday correctly.
- [ ] 4.4 Confirm the next nightly ML retrain consumes the healed data (no recent all-zero days in the training window).
