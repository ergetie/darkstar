# Proposal: backlog-quick-wins

## Why

Five small, independent fix/cleanup items have accumulated in the backlog: a dead broken API endpoint (plus the dead frontend pages that once called it), a dev-script timezone bug, five spec files failing `openspec validate --specs`, sequential HA reads that triple EV endpoint latency, and oversized HA history fetches. Each is low-risk and well-understood; batching them clears the backlog's quick-win tier in one change.

## What Changes

- **Delete the dead `/api/simulate` endpoint** (`backend/api/routers/schedule.py`) instead of fixing its `'dict' object has no attribute 'iterrows'` bug. Nothing live calls it — its only callers are unrouted archived pages. Also delete its single-consumer module `planner/simulation.py`, its tests (`tests/planner/test_simulation.py`), the `simulate` client function in `frontend/src/lib/api.ts`, and update the route snapshot/smoke tests. **BREAKING** (API removal — but verified dead).
- **Delete the three dead archived frontend pages** `frontend/src/pages/archive/{Planning,Lab,Learning}.tsx` (unrouted, imported by nothing; user approved all three).
- **Fix `scripts/insert_mock_price_forecasts.py`** to emit timezone-aware `slot_start` (and `issue_timestamp`) via `.isoformat()` so mock data joins correctly with `slot_observations`.
- **Fix the 5 spec files failing validation** (`startup-wizard`, `sensor-configuration`, `aurora-corrector`, `executor`, `planner`): add missing SHALL/MUST wording and `#### Scenario:` blocks documenting existing implemented behavior. Documentation-format fixes only — no behavior changes.
- **Parallelize per-charger HA reads** in `GET /api/ev/chargers` (`asyncio.gather` over the plug/SoC/power reads per charger, and across chargers) to cut dashboard EV tab latency.
- **Slim HA history fetches** in `backend/api/routers/ha.py` (`_fetch_ha_history_avg`) and `backend/core/ha_client.py` (`get_load_profile_from_ha`) via `minimal_response`/`no_attributes` request flags, with before/after validation that averaging results are unchanged. The learning backfill and energy-integration fetches are deliberately left at full detail.

(The five handled items were already removed from `docs/BACKLOG.md` at change-creation time, per the user's workflow rule.)

## Capabilities

### New Capabilities

(none — all items fix or clean up existing behavior)

### Modified Capabilities

- `planner`: remove the "Simulation SoC projection" requirement — the `/api/simulate` endpoint it governs is deleted.
- `router-structure`: remove `POST /api/simulate` from the route-preservation requirement and drop the "Schedule simulation lives in schedule.py" scenario.

(The 5 validation-failure spec files are edited directly as documentation-format fixes — SHALL wording and scenarios describing already-implemented behavior — not via delta specs, since no requirement's meaning changes.)

## Impact

- **Backend:** `backend/api/routers/schedule.py` (endpoint removed), `backend/api/routers/ev.py` (parallelized reads), `backend/api/routers/ha.py` + `backend/core/ha_client.py` (fetch flags), `planner/simulation.py` (deleted).
- **Frontend:** `frontend/src/lib/api.ts` (simulate function removed), `frontend/src/pages/archive/` (3 files deleted). No live UI behavior changes.
- **Tests:** `tests/planner/test_simulation.py` deleted; `tests/api/test_route_snapshot.py` and `tests/api/test_endpoint_smoke.py` updated; possible new/adjusted tests for EV endpoint parallelism and HA averaging equivalence.
- **Specs:** 5 spec files reformatted to pass validation; 2 delta specs (planner, router-structure).
- **No config, DB, or HA-integration surface changes.** External API surface shrinks by one dead endpoint.
