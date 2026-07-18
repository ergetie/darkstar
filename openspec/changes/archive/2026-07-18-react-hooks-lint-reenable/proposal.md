# Proposal: react-hooks-lint-reenable

## Why

During dependency-upgrade-pass (2026-07), `eslint-plugin-react-hooks` 7.0.1 → 7.1.1 added 4 new rules to its `recommended` set. They flagged pre-existing findings in our code; fixing them meant restructuring effects/components, which was out of scope for a version-bump-only change, so the 4 rules were disabled in `frontend/eslint.config.js` with a follow-up note. This change is that follow-up: fix the findings properly and re-enable the rules, restoring the full recommended rule set as the lint baseline.

A fresh lint run (2026-07-18) with the 4 rules forced on shows **25 findings across 15 files** (the backlog's "22 across 13" is stale — code has moved since the upgrade): 15× `set-state-in-effect`, 7× `static-components`, 2× `purity` (both `Date.now` during render), 1× `immutability`. (The original triage undercounted `set-state-in-effect` as 14 — an additional mount-fetch finding in `aurora/ModelTrainingCard.tsx` surfaced during implementation; see design.md D1.)

## What Changes

- Fix all 25 findings across 15 frontend files by restructuring the affected effects/components (derive-during-render instead of effect+setState, hoist render-defined components to module scope, move impure `Date.now` calls out of render, fix declaration order). Exact per-site fix patterns are decided in design.md — no behavior changes intended; where a genuine behavior-affecting restructure is unavoidable it is called out explicitly in tasks.
- Remove the 4 `'off'` overrides (`react-hooks/set-state-in-effect`, `static-components`, `purity`, `immutability`) and their explanatory comment from `frontend/eslint.config.js`, re-enabling them at their `recommended` severity.
- Delete the corresponding backlog item from `docs/BACKLOG.md` (per backlog workflow rules, at change-creation time).

## Capabilities

### New Capabilities

_None — this is lint-debt cleanup of existing UI code; no new user-facing capability._

### Modified Capabilities

- `ci-quality-gate`: add a requirement that the frontend ESLint config runs the full `eslint-plugin-react-hooks` recommended rule set with no rules disabled, so future hook-safety regressions are caught at lint time.

## Impact

- **Code:** 15 frontend files (components: ChartCard, CommandBar, EVChargingCard, EntitySelect, PlannerErrorDetails, ServiceSelect, SystemHealthCard, aurora/ModelTrainingCard, ui/Select; pages: Aurora, Dashboard, Debug, Executor; settings: useSettingsForm, ProfileSetupHelper) plus `frontend/eslint.config.js` and `docs/BACKLOG.md`.
- **Risk:** restructuring effects/components can change render behavior. Several touched files are shared UI (`ui/Select`, `EntitySelect`, `ServiceSelect`, `ChartCard`, `CommandBar`) — per backlog verification rules, every page rendering shared touched code SHALL be visually checked, not just the pages the change is "about".
- **No backend, API, or dependency changes.**
