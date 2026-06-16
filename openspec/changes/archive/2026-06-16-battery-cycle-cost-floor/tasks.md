## 1. Decouple Reflex from the cycle cost

- [x] 1.1 Remove the `analyze_roi` method from `backend/learning/reflex.py`
- [x] 1.2 Remove its call from the Reflex orchestration/run method (keep safety, confidence, capacity analyzers intact)
- [x] 1.3 Remove the `battery_economics.battery_cycle_cost_kwh` entries from `BOUNDS` and `MAX_DAILY_CHANGE`
- [x] 1.4 Update the `reflex_enabled` comment in `config.yaml` and `config.default.yaml` to drop "battery cost" from the tuned-parameters list
- [x] 1.5 Check `get_arbitrage_stats` call sites; remove it if orphaned after 1.1, otherwise leave it
- [x] 1.6 Add/adjust a test asserting a Reflex run never proposes or applies a change to `battery_economics.battery_cycle_cost_kwh`

## 2. Enforce the cycle cost as a hard floor (solver adapter, SSOT)

- [x] 2.1 In `planner/solver/adapter.py`, at the single point where `wear_cost_sek_per_kwh` is finalized, apply `max(battery_cycle_cost_kwh, resolved_value)`
- [x] 2.2 Ensure the configured cycle cost is read from `battery_economics.battery_cycle_cost_kwh` for the floor regardless of override source
- [x] 2.3 Add a test: StrategyEngine override of 0.0 (high spread) → solver receives the configured cycle cost
- [x] 2.4 Add a test: StrategyEngine override above the floor (e.g. 1.0) → solver receives the override unchanged
- [x] 2.5 Add a test asserting no code path delivers a solver wear cost below the configured cycle cost

## 3. Compute battery wear cost in the energy endpoint

- [x] 3.1 In `backend/api/routers/energy.py`, compute `battery_wear_cost_sek = (battery_charge_kwh + battery_discharge_kwh) * battery_cycle_cost_kwh * 0.5` using the config value
- [x] 3.2 Compute `net_cost_incl_wear_sek = net_cost_sek + battery_wear_cost_sek`; leave `net_cost_sek` unchanged
- [x] 3.3 Add both fields to the `/api/energy/today` and `/api/energy/range` responses (including the zero-data fallback path)
- [x] 3.4 Add a test: response includes both fields and the values match the formula
- [x] 3.5 Add a test: zero battery throughput → `battery_wear_cost_sek = 0.0` and `net_cost_incl_wear_sek == net_cost_sek`

## 4. Surface battery wear on the Grid & Financial card

- [x] 4.1 In `frontend/src/components/CommandDomains.tsx` (GridDomain), map the new `battery_wear_cost_sek` / `net_cost_incl_wear_sek` fields through the data layer
- [x] 4.2 Add a distinct secondary "incl. battery wear" line beneath the headline Net, using `net_cost_incl_wear_sek` with the existing sign/color convention
- [x] 4.3 Add a "Battery Wear" row to the financial breakdown section, consistent with the existing rows
- [x] 4.4 Confirm the headline Net still renders `net_cost_sek` unchanged

## 5. Verify end-to-end

- [ ] 5.1 Run a plan on a high-spread day and confirm the solver wear cost is floored at the cycle cost (battery not treated as free) — adapter code path runs live, but the high-spread clamp value was not runtime-isolatable (no log/endpoint exposes resolved wear cost); covered by code + adapter tests only
- [x] 5.2 Confirm the energy endpoint returns correct wear values for today/yesterday/week/month
- [x] 5.3 Confirm the card shows the secondary net-incl-wear line and the Battery Wear row, headline unchanged
- [x] 5.4 Run a Reflex run and confirm `battery_cycle_cost_kwh` in config is untouched
- [x] 5.5 Run the lint/type/test suite (quality gate) and fix any regressions
