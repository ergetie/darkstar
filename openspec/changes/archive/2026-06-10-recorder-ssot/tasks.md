## 1. Time-weighted integration (shared primitive — do first)

- [x] 1.1 Rewrite the power-to-energy helper in `backend/core/ha_client.py:235-237` to step-integrate `Σ powerᵢ·Δtᵢ` over each sample's `last_changed`, zero-order hold, clipped to `[start, end]` (replaces `mean × duration`)
- [x] 1.2 Handle the at-start state held from before the window, and hold the previous valid power across excluded `unknown`/`unavailable`/non-numeric samples
- [x] 1.3 Preserve the existing contract: unit-normalize W→kW, return `None` on empty/failed history, 10–15 s timeout, no internal retries
- [x] 1.4 Unit tests for 1.1–1.3 covering the spec scenarios (irregular updates, single held sample, pre-window clip, empty, failure, unit normalization, excluded states)

## 2. Slot alignment to the completed window

- [x] 2.1 Change `backend/recorder.py:209-214` to label the row `slot_start = floor(now) − 15 min`, derived from the wall clock (not an iteration counter)
- [x] 2.2 Compute every field (load/PV/grid deltas + EV/water integration) over the single `[slot_start, slot_start+15min]` window
- [x] 2.3 Reorder the `backend/services/recorder_service.py:155→160` loop so the boundary wake records the just-finished slot
- [x] 2.4 Tests: steady-state wake records the finished slot; all fields align to one window; late/skipped wake still labels correctly

## 3. Disaggregate controllable loads in every writer

- [x] 3.1 Add EV/water sensor fetching to the backfill mapping (`backend/learning/backfill.py:139-145`) so gap slots retrieve controllable-load history
- [x] 3.2 Subtract integrated EV/water energy from total load before writing `load_kwh` in `backend/learning/engine.py:238-244`, mirroring the live path; clamp to `0.0`
- [x] 3.3 Confirm the live recorder subtraction (`backend/recorder.py:500-511`) now consumes the slot-aligned integrated EV/water from steps 1–2 (not the old snapshot)
- [x] 3.4 Tests: backfill stores base load (not total); live and backfill produce the same `load_kwh` meaning for an equivalent slot; negative clamp

## 4. Correctable energy storage

- [x] 4.1 Replace the `excluded.X > 0` overwrite guard in `backend/learning/store.py:166-189` with presence-based logic: authoritative live writes overwrite (incl. lower values and true zeros); "no measurement" keeps the existing value
- [x] 4.2 Mark backfill writes non-authoritative so they only fill columns with no authoritative value and never overwrite a live-recorded one
- [x] 4.3 Tests: downward correction applied; true zero stored; backfill does not wipe an authoritative value; missing metric keeps existing value

## 5. Canonical column ownership (OQ7)

- [x] 5.1 Add a short ownership table/docstring to `backend/recorder.py` documenting per-column owners (recorder = energy/price incl. `load_kwh`=base; executor = `executed_action`)
- [x] 5.2 Verify the executor write (`executor/history.py:155`) touches only `executed_action` and no energy/price column; add a regression test asserting recorder columns are untouched by the executor UPDATE

## 6. Verification

- [x] 6.1 Run the full test suite; confirm no regressions against the Phase 0 baseline (1051 passing)
- [x] 6.2 Manually trace one recorded slot end-to-end (live + a backfilled gap) confirming alignment, integration, base-load isolation, and a correction round-trip
- [x] 6.3 `openspec validate recorder-ssot` and update the stabilization-review findings ledger note if scope shifts during implementation
