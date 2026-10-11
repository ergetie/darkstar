## Why

Users cannot tell how good Darkstar's battery decisions are. A Wolta-style score answers that: compare each finished day with the best battery plan possible in hindsight. The 2026-10-11 investigation on the maintainer's production data proved the method: on clean days Darkstar reached ~81 % of the hindsight optimum (≈5.6 SEK/day missed), the result is insensitive to small model details (<2 SEK over 22 days), and earlier apparent large gaps were data bugs and a disconnected battery module, not planning.

## What Changes

- Every night, for each finished local day with clean recorded data, solve one 00:00–24:00 battery-only hindsight plan with Kepler on the recorded load, PV and prices, ending at the same stored energy as reality.
- Price Darkstar's actual battery moves and the hindsight plan with the same model, plus a no-battery baseline, and store per day: actual cost, optimal cost, no-battery cost, missed SEK and score.
- Only score days whose every slot was recorded with per-value provenance from power history; others are excluded with a reason.
- Check the configured battery capacity against the capacity implied by recorded flows and SoC; on mismatch, exclude the day with a clear reason instead of scoring it wrongly.
- Add a read-only API and a small Finance card: score and missed SEK for the selected period, with days scored/excluded.

## Capabilities

### New Capabilities

- `daily-battery-benchmark`: nightly hindsight benchmark, day eligibility, capacity check, stored results, API and Finance card.

### Modified Capabilities

None. Recorder, live planner and executor behavior are unchanged.

## Impact

- Planner: a benchmark entry point reusing Kepler with policy penalties off and benchmark-only constraints; live planning unchanged.
- Backend: a small nightly service, results in `system_state` via `LearningStore`, one endpoint in `backend/api/routers/energy.py`.
- Frontend: one Finance card.
- No schema migration, no new dependency, no HA calls.
- Non-goals: rolling forecast replay, cause attribution (forecast vs execution), historical import from HA statistics, partial-discharge or taper modelling, payback figures.
