## 1. Attribution query

- [x] 1.1 In `backend/api/routers/energy.py`, replace the per-slot EV expressions with `pv_surplus = max(0, pv − load − water)`, `ev_solar = min(ev, pv_surplus)`, `ev_grid = ev − ev_solar` (null-safe via coalesce).
- [x] 1.2 Compute the EV cost expression as `min(ev_grid, max(0, import)) × import_price` and update the explanatory comment above the expressions.
- [x] 1.3 Confirm `ev_solar_share` and the zero-fallback response are unchanged and still consistent with the new sums.

## 2. Tests

- [x] 2.1 Rewrite `tests/api/test_energy_ev_cost.py` cases to the new scenarios: night all grid, night with under-recorded import (PV 0 → solar 0), midday full solar, partial surplus, load above PV, no EV energy, null inputs.
- [x] 2.2 Add a case asserting `ev_cost_sek ≤ import_cost_sek` when `ev_grid_kwh` exceeds `import_kwh`.
- [x] 2.3 Check `tests/backend/test_energy_router.py` for assertions on the old split and update them.

## 3. Verification

- [x] 3.1 Run `UV_NO_SYNC=1 uv run python -m pytest tests/api/test_energy_ev_cost.py tests/backend/test_energy_router.py -v`, then `./scripts/lint.sh`.
- [x] 3.2 Read-only check against production data: for 2026-10-01 the night slots 00:15 and 01:30 report `ev_solar_kwh = 0`, and no slot with `pv_kwh = 0` reports solar.
  - Checked 2026-10-03 (prod DB opened `mode=ro`). 00:15: ev 1.654, import 1.507, pv 0 → old solar 0.147, new solar 0, grid 1.654, cost 3.79 SEK. 01:30: ev 1.649, import 1.042, pv 0 → old solar 0.607, new solar 0, grid 1.649, cost 2.54 SEK. All 96 slots: 0 slots with pv = 0 report solar.
