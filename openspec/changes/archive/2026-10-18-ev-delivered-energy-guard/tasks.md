## 1. Recorder

- [x] 1.1 Add `energy_added_reset_threshold_kwh` (default 0.5) to `config.default.yaml` (near :162) and a range entry (0.0-5.0 kWh) in `_EV_LOSS_RANGES` (backend/api/routers/config.py:726); read it in `backend/recorder.py` per charger with default 0.5
- [x] 1.2 Rewrite `car_energy_from_added_sensor` in `backend/recorder.py`: reset only when new value <= threshold; else contribute 0 and rebase
- [x] 1.3 In `_ev_car_energy`, cap sensor energy by wallbox kWh + tolerance; 0 when wallbox ~0
- [x] 1.4 Zero `ev_charger_car_energy` where rejected aggregates zero `ev_charger_energy` (~line 583)

## 2. Planner

- [x] 2.1 Cap per-slot car energy at `energy_kwh + tolerance` in `_ev_delivered_today_kwh`
- [x] 2.2 Keep `required_kwh` semantics unchanged; no goal-start SoC, no schema change

## 3. Frontend

- [x] 3.1 Base `computeProgressPercent` and the bar in `EVChargingCard.tsx` on `soc / target_soc` (clamped 0-100) for chargers with SoC; for chargers without a SoC sensor use delivered / (delivered + remaining required) (clamped 0-100); hide only when neither is available
- [x] 3.2 Make "Delivered Today" informational; replace "Target X kWh (N% of goal)" with SoC text; fix COMPLETE state
- [x] 3.3 No api.ts change: `soc_percent` and `target_soc_percent` already exist (api.ts:1317,1323); chargers without SoC keep the bar via the delivered/required formula

## 4. Tests

- [x] 4.1 Recorder tests using the torleif fixture in design.md (drift 22.47...21.92, wallbox 7.5e-05): car energy 0 per slot; cap holds for the 11:00/14:00/14:45 rows
- [x] 4.2 Tests for genuine reset (24.8 to 0 to 0.6), non-zero drop ignored, wallbox cap, rejected aggregate zeroing
- [x] 4.3 Pipeline test: delivered today stays ~0 for the idle sequence including legacy bad rows
- [x] 4.4 Frontend tests for progress percent (22 kWh delivered, SoC below target; complete state; no-SoC charger shows delivered/required percent)
- [x] 4.5 Run `./scripts/lint.sh` and the affected tests
