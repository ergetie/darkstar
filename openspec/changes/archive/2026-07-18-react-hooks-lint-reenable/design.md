# Design: react-hooks-lint-reenable

## Context

`eslint-plugin-react-hooks` 7.1.1 added 4 rules to its `recommended` set; they were disabled in `frontend/eslint.config.js` during dependency-upgrade-pass to keep that change version-bump-only. A fresh run (2026-07-18) with the rules forced on shows 25 findings in 15 files: 15× `set-state-in-effect`, 7× `static-components`, 2× `purity`, 1× `immutability`. Every site was individually investigated before this design; the fix pattern per site is pre-decided below.

**Post-implementation correction (2026-07-18):** two items below did not survive contact with the actual linter and were revised during implementation — both are called out inline where they occur. (1) The original triage undercounted `set-state-in-effect` as 14; an extra mount-fetch finding in `aurora/ModelTrainingCard.tsx` was missed and is folded into D1 class 3 below. (2) The `purity` fix prescribed for `Debug.tsx` — reading `Date.now()` directly inside `useMemo` — does not actually clear the rule (`useMemo` bodies run during render, same as the component body; only `useEffect` callbacks and lazy `useState` initializers are exempt). See D1 class 2 for the fix actually used.

## Goals / Non-Goals

**Goals:**

- All 4 rules re-enabled at recommended severity; `npx eslint .` reports zero findings.
- No intended behavior change anywhere — this is lint-debt cleanup, not a UX change.
- Every suppression that remains (see Decision 3) carries a justification comment at the site.

**Non-Goals:**

- Introducing a data-fetching library (React Query etc.) to make fetch effects idiomatic — far out of scope.
- Fixing unrelated pre-existing bugs noticed nearby (e.g. the `data-index` comment in `ui/Select.tsx:259`).
- Behavior *improvements* beyond what a fix pattern inherently gives (one deliberate exception: the boost countdown, Decision 4).

## Decisions

### D1: Findings are fixed by class, not ad hoc

The 25 findings fall into four classes, each with one fix pattern:

1. **`static-components` (7)** — components defined inside render:
   - `SystemHealthCard.StatusIcon`: pure prop-taking component → **hoist to module scope** (fixes 4 findings, zero plumbing).
   - `CommandBar.CompactRiskPills/CompactWaterPills/OverrideButtons`: capture many closure bindings → **convert to plain JSX expressions** (`const riskPills = (<div>…</div>)` rendered as `{riskPills}`). No new component identity, no prop-plumbing risk. Chosen over module-scope extraction because forwarding ~10 closure values as props is the error-prone path; none of the three hold internal state, so inlining is behavior-neutral.

2. **`purity` (2)** — `Date.now()` during render:
   - `Debug.tsx`: **as implemented**, seed a `now` state via a lazy `useState(() => Date.now())` initializer, refreshed every 60s by an interval inside a `useEffect`, and read `now` (not `Date.now()`) in the `useMemo` that filters logs by time range. (Originally prescribed: wrap the filtering in `useMemo` with `Date.now()` read directly inside the memo callback — this does not clear the rule, since `useMemo` bodies execute during render just like the component body; only `useEffect` callback bodies and lazy `useState` initializers are exempt from the impure-call check. Verified by testing before revising.) Filtering stays effectively live at 60s granularity, which is enough for hour-scale time-range buckets.
   - `CommandBar.tsx` boost countdown: see D4.

3. **`set-state-in-effect` (15)** — splits into two sub-groups (this is the load-bearing decision):
   - **Derived-state effects (7 findings)** — state mirrored/reset from other values: genuinely fixed via derive-during-render, reset-in-event-handler, or state deletion (per-site prescriptions in tasks.md). Includes deleting `Dashboard.plannerMeta` outright — verified its only writer is the mirror effect.
   - **IO-lifecycle and high-sensitivity effects (8 findings)** — mount/dependency-driven fetch effects (`Aurora.tsx:93,149`, `Dashboard.tsx:508`, `Executor.tsx:473`, `useSettingsForm.ts:111`, `aurora/ModelTrainingCard.tsx:51`) and two effects guarding user-editable form state with deliberate, commented edit/refresh guards (`EVChargingCard.tsx:143`, `useSettingsForm.ts:118`): **keep the effect and add a targeted `// eslint-disable-next-line react-hooks/set-state-in-effect` with a one-line justification**. Rationale: the fetch effects perform side-effectful IO that cannot be derived during render, and restructuring them buys nothing but risk; the two form-state effects carry the highest behavior-change risk in the whole change (optimistic-save flash-back, edit-wipe) and their guards exist for documented reasons. Config-level `'off'` is banned by the spec delta; site-level suppression with justification is the honest boundary. (`aurora/ModelTrainingCard.tsx:51` was missed in the original triage — see Context note above — and folded into this group since it's the same IO-lifecycle mount-fetch shape as the others.)

4. **`immutability` (1)** — `ModelTrainingCard.fetchData` referenced above its declaration: **move the declaration above the `useSocket` call**. Pure reorder; not wrapping in `useCallback` (avoids perturbing the socket subscription and 5s polling deps).

### D2: The three combobox highlight-resets get one shared pattern

`EntitySelect.tsx:75`, `ServiceSelect.tsx:80`, `ui/Select.tsx:88` are the identical `useEffect(() => setHighlightIndex(0), [filtered.length])` pattern. Fix all three the same way: reset `highlightIndex` in the search input's `onChange` handler (and in the open/close toggle paths for `ui/Select`, whose effect also depends on `open`). Chosen over clamp-during-render because the handler reset also covers the "new search, same result count" case the current effect misses — strictly equal-or-better behavior.

### D3: Rules flip on in config only after all sites are clean

The 4 `'off'` overrides and their explanatory comment are removed from `eslint.config.js` as the last code step, then lint runs as the gate. During implementation, findings are re-checked with the same wrapper-config technique used in the investigation (temp config forcing the rules on) so progress is measurable without breaking `ci_local.sh` mid-change.

### D4: The boost countdown becomes a real ticking countdown

`CommandBar.tsx:217` computes remaining boost seconds from `Date.now()` during render — today it only advances when something else re-renders the Dashboard. The purity fix (a 1-second interval updating a `now` state, active **only while a boost is active**, cleared on unmount/expiry) makes it tick smoothly. This is the one deliberate behavior change: an erratically-updating countdown becomes a correct one. Called out so verification checks it explicitly.

## Risks / Trade-offs

- **[ChartCard mobile selection band]** Deriving `effectiveSelectedIndex = isMobile ? selectedIndex : null` must still trigger the imperative Chart.js redraw on the desktop transition, or a stale band lingers → route the derived value through the existing `[selectedIndex]` redraw effect's dependencies; verify by crossing the mobile/desktop breakpoint with a slot selected.
- **[Inline suppressions read as unfinished work]** 8 of 25 findings end as justified suppressions rather than rewrites → each carries a one-line why; design records the split. If the user wants zero suppressions, the two form-state sites need their own carefully-verified change (flagged as open question).
- **[Shared components touched]** `ui/Select`, `EntitySelect`, `ServiceSelect`, `ChartCard`, `CommandBar` render on multiple pages → per backlog rules, visual verification covers every page rendering them (Dashboard, Settings, Aurora, Executor, Debug, StartupWizard overlay, DesignSystem), not just the "obvious" ones.
- **[CommandBar inlining]** Converting the three nested components to JSX expressions is mechanical, but they're currently instantiated inside conditional layouts → keep the render positions identical; verify pills/override buttons render and fire handlers.

## Open Questions

_None. User approved (2026-07-18): (1) the suppress-with-justification boundary for the IO/high-sensitivity sites (7 at design time, 8 after the `aurora/ModelTrainingCard.tsx` finding surfaced during implementation) — no follow-up restructure of the two form-state effects wanted; (2) the D4 boost-countdown behavior improvement._
