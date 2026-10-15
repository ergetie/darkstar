## Context

**Solver.** `planner/solver/kepler.py` builds `plugged_chargers` from chargers that are `plugged_in or assumed_plugged` (~line 157). The `any_ev_charging[t]` linking and the Big-M discharge block (~lines 491-499) iterate that list, so an assumed-plugged slot forces `discharge[t] = 0`. The executor gate (`_gate_ev_plan_on_plug_state`, `executor/engine.py`) zeroes only the EV kW, keep-on and surplus fields; the slot's battery plan stays. A hold slot gets `soc_target` = entry SoC (`planner/output/soc_target.py`), and `executor/controller.py` then holds the battery whenever live SoC ≤ target.

**Card.** On desktop the charger list in `CommandDomains.tsx` is `lg:absolute lg:inset-0 overflow-y-auto`, so it takes the cell height without driving the row height. A single charger card gets `flex-1` and has `overflow-hidden` (`EVChargingCard.tsx`). A flex item with `overflow` other than `visible` has an automatic minimum height of 0, so the card shrinks to the list height and clips its content; the list has nothing left to scroll, and the bottom action row (`mt-auto`) is hidden first.

## Goals / Non-Goals

**Goals:**
- An away car never stops the house battery from discharging, in the plan or at runtime.
- The user can always reach the goal buttons and understands that an away car's plan costs nothing.
- Plugged-in behaviour and the existing layout contract (single card fills the cell, row height unchanged, several cards scroll in the list) are unchanged.

**Non-Goals:**
- Clearing or pausing goals on unplug (decided: keep goals).
- Executor changes; fixing the plan removes the cause.
- Button size or card content redesign.

## Decisions

**D1. Fix the block in the solver.** Exclude assumed-plugged chargers from the `any_ev_charging` linking. The plan then contains the battery discharge the house needs, and `soc_target`, chart and savings stay consistent.
- Alternative: executor overrides hold slots caused by an assumed-plugged EV. Rejected: the executor cannot tell why a slot is hold, and the shown plan would still be wrong.

**D2. Keep the grid-only EV constraint for assumed-plugged chargers.** `ev_energy <= grid_import + pv` stays, so the preview never funds the EV from the battery.

**D3. No `any_ev_charging` variable when no charger is live-plugged.** Same as the existing "EV disabled users are unaffected" rule.

**D4. Card: header, scrollable body, fixed action footer.** The body gets `min-h-0 flex-1 overflow-y-auto` with the design system's `custom-scrollbar`; the actions row is a non-shrinking footer. Same structure for the edit-goal form (Save/Cancel). `overflow-hidden` stays only on the outer card for rounded corners.
- Alternative: remove `overflow-hidden` so the card grows and the list scrolls. Rejected: with one charger the buttons would still sit below the fold.
- Alternative: buttons in the header. Rejected: breaks the "actions at the bottom" contract.

**D5. Wording.** Awaiting-plug-in text: "Planned from HH:MM — plug in the car. No effect on the house battery while away." (shortened form when no start time). Follows the design system's text tokens.

## Risks / Trade-offs

- [Preview slightly optimistic: once plugged in, those slots block discharge and cost a bit more] → The plug-in replan recomputes immediately.
- [Charger without a plug sensor] → Treated as plugged (`ev-live-state`), never assumed-plugged, so it keeps the block. Covered by a test.
- [jsdom cannot measure layout] → Unit tests assert structure; a visual check at desktop width is part of the tasks.
