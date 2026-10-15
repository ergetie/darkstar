# Tasks

## 1. Solver: away car does not block the battery

- [x] 1.1 Add a failing regression test in `tests/planner/test_kepler_ev_assumed_plugged_discharge.py`: one assumed-plugged charger with a goal, expensive prices, charged battery; assert discharge > 0 in the planned EV slots and the house battery plan matches the run without the charger apart from EV grid import; verify it fails on current code
- [x] 1.2 In `planner/solver/kepler.py`, build the `any_ev_charging` linking and discharge block from live-plugged chargers only and skip both when none are plugged (D3); keep the grid-only EV constraint for all chargers; verify 1.1 passes
- [x] 1.3 Add tests: plugged-in charger still blocks; plugged + assumed-plugged mix blocks only in the plugged charger's slots; charger without a plug sensor still blocks; only-assumed input adds no EV discharge constraint; verify with `tests/planner` passing

## 2. EV card

- [x] 2.1 In `frontend/src/components/EVChargingCard.tsx`, split the goal view and the edit form into header, scrollable body and non-shrinking action footer (D4); keep `overflow-hidden` only on the outer card; verify with a TypeScript check
- [x] 2.2 Update the awaiting-plug-in text to state the battery is unaffected while away (D5); verify with the existing assumed-plugged rendering test updated
- [x] 2.3 Add tests in `frontend/src/components/EVChargingCard.test.tsx`: action buttons and Save/Cancel render in a footer outside the scrollable body; verify the EVChargingCard tests pass

## 3. Integration check

- [x] 3.1 Run the dev app at desktop width (≥1024 px) with one charger showing every optional block, with two chargers, and at mobile width; verify buttons are always visible, the body scrolls, and the dashboard row height is unchanged
- [x] 3.2 Run `./scripts/lint.sh` and the planner, executor and frontend test suites; verify all pass
