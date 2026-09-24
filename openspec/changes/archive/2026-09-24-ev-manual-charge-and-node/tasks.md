## 1. Executor: manual charge state

- [x] 1.1 Add `soc_sensor`, `plug_sensor` to `EVChargerDeviceConfig` (executor/config.py) and parse them from YAML; tests in test_ev_config / test_ev_charger_validation
- [x] 1.2 Add `ManualCharge` dataclass and `_ev_manual_charge` dict with `set_ev_manual_charge`, `clear_ev_manual_charge`, `get_ev_manual_charge_status` in executor/engine.py (validation per spec, websocket emit `ev_manual_charge_updated`)
- [x] 1.3 Persist/restore manual charges via `update_ev_state` under a separate `manual_charge` key; load at executor startup; goal fields untouched
- [x] 1.4 Unit tests: set/clear/status, validation errors, persistence round-trip, goal unchanged

## 2. Executor: control integration

- [x] 2.1 `_charger_should_be_on` returns True for chargers with active manual charge
- [x] 2.2 `_run_load_balancer` / `_control_ev_charger_current`: planner target = manual `current_a` or `max_current_a`; exclude charger from surplus targeting while manual is active
- [x] 2.3 Verify shed, `force_stop` and `skip_writes` still take precedence (no code change expected; add tests)
- [x] 2.4 Per-tick end detection: read SoC/plug for manual chargers; end on SoC ≥ target, unplugged, 24 h timeout; keep charging on unavailable SoC; request rate-limited replan on end
- [x] 2.5 Tests (new tests/executor/test_ev_manual_charge.py): binary on with 0 kW plan, current at max / user amps, balancer throttle keeps manual active, shed binary, other charger unaffected, each end condition, replan requested

## 3. Backend API and live data

- [x] 3.1 `POST` / `DELETE /api/ev/chargers/{id}/manual-charge` in backend/api/routers/ev.py with spec validation (type from config)
- [x] 3.2 Add `manual_charge` to `GET /api/ev/chargers` response model
- [x] 3.3 Add charger `id` to live `ev_chargers[]` entries in backend/ha_socket.py and backend/api/routers/system.py
- [x] 3.4 Update route snapshot test; API tests for endpoints and validation

## 3b. Executor: house Top Up ends at target

- [x] 3b.1 `set_quick_action('force_charge')`: skip duration list, 24 h safety expiry, validate `min_soc_percent ≤ target ≤ 100` and current SoC < target (router returns 400 with message)
- [x] 3b.2 Tick: clear `force_charge` when `current_soc_percent >= target_soc` and follow schedule
- [x] 3b.3 Tests in tests/executor/test_executor_engine.py: ends at target, still active past 60 min, 24 h timeout, rejections; adjust existing duration test for force_charge

## 4. Frontend: shared stepper and Top Up

- [x] 4.1 Create `SocStepper` component (±15, clamp, tap-to-type, Enter/blur/Esc) with design tokens; unit tests
- [x] 4.2 Add stepper to `/design-system` showcase and any new classes to index.css `@layer components`
- [x] 4.3 Replace Top Up fixed list in CommandBar.tsx with `SocStepper` (range `min_soc_percent`–100 from config); show API rejection message in toast

## 5. Frontend: EV manual charge UI

- [x] 5.1 Add `Api.ev.manualCharge.start/stop` and types in lib/api.ts; subscribe to `ev_manual_charge_updated`
- [x] 5.2 CommandBar EV Charge control: shown when a controllable charger is plugged; selector only for >1; collapsed amps toggle for current-type only; STOP when active
- [x] 5.3 EVChargingCard: "Manual charge → X% · Stop" line when active
- [x] 5.4 Component tests for CommandBar EV control (single/multi/binary/none plugged) and card line

## 6. Frontend: power-flow EV node

- [x] 6.1 Pure function `deriveEvNodeView(evChargers, chargerStatuses)` → icon (Zap/Plug/Unplug), text, muted; tests for every spec scenario incl. multi-charger
- [x] 6.2 Use it in PowerFlowCard.tsx node rendering; pass charger status (target, manual) from Dashboard; remove dead `ev_soc` from Dashboard livePower and `evSoc` prop
- [x] 6.3 Align PowerFlowRegistry.ts EV accessors with the new function (or remove the unused accessors) and update its tests

## 7. Verification

- [x] 7.1 `./scripts/lint.sh` passes (backend + frontend)
- [x] 7.2 Manual check in dev UI: single charger node states, Top Up stepper, EV start/stop with binary and current charger configs
