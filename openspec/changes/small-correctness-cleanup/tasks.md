> Each group is one independent finding and is independently revertable. Order is low-risk → behavior-affecting; verification last.

## 1. #8 — EV charge current uses nominal voltage

- [ ] 1.1 In `executor/controller.py:320`, change the kW→A conversion to divide by `self.config.nominal_voltage_v` instead of `self.config.min_voltage_v`
- [ ] 1.2 Confirm `min_voltage_v` is still used only for safety/limit checks, not the conversion
- [ ] 1.3 Add/extend a unit test asserting `(P × 1000) / nominal_voltage_v` for a representative slot, and that the current limit clamp still applies

## 2. #24 — Deliver the boost-cancellation notification

- [ ] 2.1 In `executor/engine.py:1179-1182`, `await` the `self.dispatcher._send_notification(...)` call (or wrap in `create_task`), matching the awaited call sites at `engine.py:1237` / `actions.py:1213`
- [ ] 2.2 Add a test asserting the notification is sent when a boost is cancelled below `min_soc + 10%`, with no un-awaited-coroutine warning

## 3. #13 — Log WebSocket broadcast failures

- [ ] 3.1 In `executor/engine.py:1439-1444` and `:1527-1532`, replace the bare `except Exception: pass` around `ws_manager.emit_sync(...)` with a `logger.debug`/`warning` on failure; narrow the except if practical
- [ ] 3.2 Confirm the error/status record is still appended to `recent_errors` before the emit (no reordering)
- [ ] 3.3 Add a test that a raising WS manager logs and the record remains persisted

## 4. #21 — Remove the dead/broken force_export quick action

- [ ] 4.1 Remove the `force_export` override branch in `executor/controller.py:178-179` (the hardcoded `export_power_w=0.0`)
- [ ] 4.2 Remove the engine handler/trigger in `executor/engine.py:1140-1141` and the dispatch at `:482`
- [ ] 4.3 Remove the `force_export` override type/enum and any now-dead references; confirm `force_charge` ("Top Up") path is untouched
- [ ] 4.4 Grep the repo (incl. frontend) to confirm no remaining caller; update/remove any test referencing `force_export`

## 5. #20 — Report plan cost at the effective export price

- [ ] 5.1 In the cost recompute (`planner/solver/kepler.py:751-752`), value exported energy at `export_price − export_threshold` (the effective price used by the objective at `:473-476`) instead of raw `s.export_price_sek_kwh`
- [ ] 5.2 Add a test: with a non-zero export threshold the reported `total_cost_sek` equals the objective value; with threshold 0 the reported cost is unchanged; the chosen schedule never changes

## 6. #12 + #14 (simulation) — Accurate simulation SoC projection

- [ ] 6.1 In `planner/simulation.py`, feed the SoC projection total battery charge (`battery_charge_kw`) instead of the grid-only `charge_kw` (adapter field at `adapter.py:555`); rename or document the grid-only field to avoid the collision
- [ ] 6.2 Apply the parsed-but-discarded `min_soc_percent`/`max_soc_percent` (`simulation.py:30-31`) as the clamp band, replacing the `[0, capacity]`-only clamp at `:62`
- [ ] 6.3 Update/extend the `/api/simulate` test(s) to assert PV-sourced charge raises projected SoC and the curve stays within the configured band

## 7. #19 + #14 (non-simulation) — Comment & dead-code cleanup (no behavior change)

- [ ] 7.1 `planner/solver/kepler.py:484-487` — fix the stale terminal-value comment; `:510-528` — remove the duplicated "BIDIRECTIONAL" comment and the duplicate `target_soc_kwh` assignment (keep one)
- [ ] 7.2 `planner/output/soc_target.py:73` — remove the discarded `float(battery_config.get("capacity_kwh", 34.2))` read
- [ ] 7.3 `executor/actions.py:787` — remove the unreachable `if entity is None:` branch (guarded out at `:776`)
- [ ] 7.4 `backend/ha_socket.py:687` — remove the redundant trailing `pass`
- [ ] 7.5 Confirm no behavior change (tests still green; these are removals/comment edits only)

## 8. Verification

- [ ] 8.1 Run the full test suite (`uv run python -m pytest`) — expect the Phase 0 baseline (1051) plus the new tests, 0 failures
- [ ] 8.2 Run `pyright` (strict) over the touched modules — no new type errors
- [ ] 8.3 `openspec validate small-correctness-cleanup` passes
