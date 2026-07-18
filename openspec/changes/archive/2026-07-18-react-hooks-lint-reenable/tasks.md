# Tasks: react-hooks-lint-reenable

Line numbers are from the 2026-07-18 lint run and may drift a few lines — locate by the described code, not the number.

## 1. Mechanical fixes (static-components, immutability, purity)

- [x] 1.1 `src/components/SystemHealthCard.tsx`: move the `StatusIcon` component definition (~lines 42-50, takes only a `status` prop) from inside `SystemHealthCard` to module scope above it — no other edits (clears the 4 findings at ~75/91/116/139)
- [x] 1.2 `src/components/CommandBar.tsx`: convert the three nested components `CompactRiskPills` (~line 249), `CompactWaterPills` (~line 282), and `OverrideButtons` (~line 315) from function components into plain JSX expressions (`const riskPills = (<div>…</div>)` etc.), and replace their `<CompactRiskPills />`-style usages (~lines 506-509) with `{riskPills}`-style renders in the exact same positions — do NOT extract to module scope, do NOT change any of the JSX inside them
- [x] 1.3 `src/components/aurora/ModelTrainingCard.tsx`: move the `const fetchData = async () => {…}` declaration (~line 32) above the `useSocket('training_progress', …)` call (~line 22) that references it — plain reorder, no `useCallback` wrapping. **Deviation:** this file also had an undocumented 25th finding (mount `fetchData()` call in the `useEffect` at ~line 50) not listed anywhere in this task or in design.md's 24-finding tally; fixed with the same justified-suppression pattern as section 4 (IO-lifecycle mount fetch)
- [x] 1.4 `src/pages/Debug.tsx`: in `LogPanel` (component is actually named `LogsView`), wrap the `filteredLogs` computation (level filter + time-range filter, ~lines 53-64) in `useMemo` keyed `[logs, levelFilter, timeRange]`. **Deviation:** reading `Date.now()` directly inside the `useMemo` callback, as literally prescribed, still trips `purity` (useMemo bodies run during render, unlike `useEffect`) — verified by test. Fixed instead with a `now` state seeded via a lazy `useState` initializer and refreshed by a 60s-interval effect (mirrors the D4 pattern), added to the memo's deps

## 2. Combobox highlight resets (shared pattern, D2)

- [x] 2.1 `src/components/EntitySelect.tsx`: delete the `useEffect(() => setHighlightIndex(0), [filtered.length])` (~lines 74-76) and instead call `setHighlightIndex(0)` in the search input's `onChange` handler
- [x] 2.2 `src/components/ServiceSelect.tsx`: same replacement for the identical effect at ~line 80
- [x] 2.3 `src/components/ui/Select.tsx`: same replacement for the effect at ~lines 87-89, which also depends on `open` — additionally call `setHighlightIndex(0)` in every code path that toggles `open` (trigger `onClick` AND the keyboard-open paths in `handleKeyDown`)

## 3. Derived-state fixes (set-state-in-effect, genuinely restructured)

- [x] 3.1 `src/pages/Dashboard.tsx`: delete the `plannerMeta` state (line ~134) and its mirror effect (~lines 489-491), and pass `plannerLocalMeta` directly at the two usage sites (~lines 746, 803) — verified 2026-07-18 that the mirror effect is `plannerMeta`'s only writer
- [x] 3.2 `src/components/ChartCard.tsx`: remove the `setSelectedIndex(null)` call from the `[isMobile]` effect (~line 1340); derive `const effectiveSelectedIndex = isMobile ? selectedIndex : null` during render and use it in place of raw `selectedIndex` in BOTH the `[selectedIndex]` band-redraw effect (~lines 1308-1319, switching its dependency to `effectiveSelectedIndex`) and any other consumer of the selection, so the band still repaints (to cleared) on the mobile→desktop transition
- [x] 3.3 `src/components/PlannerErrorDetails.tsx`: in `useRetryCountdown`, replace the synchronous `setRemaining(initialVal)` re-seed inside the `[retryInS]` effect (~line 48) with the render-time reset pattern (track `prevRetryInS` in state; when `retryInS !== prevRetryInS` during render, set both `prevRetryInS` and `remaining`); the 1s `setInterval` and its cleanup stay in the effect unchanged
- [x] 3.4 `src/pages/settings/components/ProfileSetupHelper.tsx`: remove the synchronous `setSuggestions(null)` early-return branch (~line 37) from the `[profileName]` effect; make the "empty/`generic` profile ⇒ no suggestions" case render-derived (short-circuit rendering), ensuring stale suggestions from a previously selected profile are still cleared when switching back to generic (derived `displaySuggestions = isGeneric ? null : suggestions`, used everywhere `suggestions` was read)
- [x] 3.5 `src/components/ServiceSelect.tsx`: move the lazy services fetch out of the `[open, services.length, loading]` effect (~lines 37-51) into a `loadServices` function invoked from BOTH the trigger's `onClick` and the keyboard-open paths (`ArrowDown`/`Enter` in `handleKeyDown`), preserving the exact fetch-once guard (only when `services.length === 0 && !loading`), then delete the effect
- [x] 3.6 `src/components/CommandBar.tsx`: replace the render-time `Date.now()` boost countdown IIFE (~lines 215-219) with a `now` state driven by a 1-second `setInterval` inside a `useEffect` that is active ONLY while a water boost is active (`waterBoostActive` with a future `expires_at`), cleared on unmount and on expiry; compute `boostCountdown` from `now`. `now` is seeded via a lazy `useState(() => Date.now())` initializer (exempt from the purity check) rather than a synchronous `setState` call in the effect body (which itself trips `set-state-in-effect`, verified by test). Deliberate behavior change per D4: countdown now ticks every second instead of only on incidental re-renders

## 4. Justified inline suppressions (set-state-in-effect, D1 class 3b)

Each suppression is a `// eslint-disable-next-line react-hooks/set-state-in-effect` directly above the flagged line with a one-line reason. No other code changes at these sites.

- [x] 4.1 `src/pages/Aurora.tsx`: suppress at the mount data-fetch effect (~line 93) and the price-forecast lazy-fetch effect (~line 149) — reason: IO-lifecycle fetch effects; loading flags are fetch state, not derivable
- [x] 4.2 `src/pages/Dashboard.tsx`: suppress at the mount `fetchAllData()` effect (~line 508) — reason: initial IO fetch, participates in socket-reconnect refetch
- [x] 4.3 `src/pages/Executor.tsx`: suppress at the `setLoading(true)` in the mount+30s-polling effect (~line 473) — reason: initial-load spinner must NOT move into `fetchAll` (would flash on every background poll)
- [x] 4.4 `src/pages/settings/hooks/useSettingsForm.ts`: suppress at the mount `reload()`/`reloadEntities()` effect (~line 111) and the form-rebuild effect (~line 118) — reasons: IO fetch; and user-editable form state whose rebuild-on-`fields`-change guards against edit-wipe (render-derivation would lose in-progress edits)
- [x] 4.5 `src/components/EVChargingCard.tsx`: suppress at the charger→form sync effect (~line 143) — reason: deliberate `!isEditing && !pendingRefresh` guards (documented in surrounding comments) prevent optimistic-save flash-back; effect must re-run when `pendingRefresh` clears, which render-reset-on-prop-change cannot express

## 5. Re-enable rules and gate

- [x] 5.1 `frontend/eslint.config.js`: delete the four `'off'` overrides (`react-hooks/set-state-in-effect`, `static-components`, `purity`, `immutability`) and the dependency-upgrade-pass explanatory comment block above them
- [x] 5.2 Run `npx eslint .` in `frontend/` — zero findings (warnings from pre-existing `warn`-level rules unaffected by this change are acceptable only if they existed before; no new ones). Verified with `--report-unused-disable-directives --max-warnings 0` (the project's actual `pnpm lint` script): clean.
- [x] 5.3 Run the frontend typecheck and test suite (`ci_local.sh` frontend portion or equivalent) — no regressions. `tsc --noEmit`: clean. `vitest run`: 31 files / 183 tests passed. `vite build`: succeeded.
- [x] 5.4 Delete the backlog item from `docs/BACKLOG.md` — done at change-creation time (2026-07-18), per backlog workflow rules

## 6. Visual verification (shared code — every page that renders touched components)

Verified manually by the user directly in the browser against the running dev server (this is a live system with `system_id: "prod"` and real solar/battery/water-heater/EV-charger hardware — the agent implementing this change did not click the hardware-actuating controls itself; the user exercised those and confirmed the rest of the checklist by eye).

- [x] 6.1 **Dashboard** (`/`): CommandBar renders; risk pills, water pills, and override buttons all present and clickable; start a water boost and confirm the countdown ticks down once per second and disappears at expiry; EV charging card — edit a goal, save, confirm no flash-back to stale values, then trigger an external charger update while NOT editing and confirm the form updates; charts render and planner metadata (plannerMeta consumers at the two usage sites) displays as before
- [x] 6.2 **ChartCard breakpoint** (Dashboard or DesignSystem): on mobile width, tap a slot to show the selection band, then widen past the desktop breakpoint — band clears, no lingering band, no console errors
- [x] 6.3 **Settings** (`/settings`): form fields populate from config; type in an EntitySelect and a ServiceSelect — highlight resets to the first item as you type; ServiceSelect lazy-loads its service list exactly once on first open via mouse click AND via keyboard (ArrowDown/Enter); grouped searchable `ui/Select` (e.g. in SettingsField) resets highlight on open and on search; make an edit, cause an unrelated re-render, confirm the edit survives; switch inverter profile from generic to a specific profile (helper appears) and back to generic (helper disappears, no stale suggestions)
- [x] 6.4 **Aurora** (`/aurora`): page loads with all cards; the four SystemHealthCard status icons render with correct colors; switch chart mode to price — forecast loads once, no refetch loop; ModelTrainingCard still refreshes on training completion
- [x] 6.5 **Executor** (`/executor`): initial spinner shows once, data loads, background 30s polling does not flash the spinner
- [x] 6.6 **Debug** (`/debug`): time-range pills (1h/6h/24h) filter logs correctly in live mode
- [x] 6.7 **Global + StartupWizard**: trigger/inspect the SystemAlert planner-error modal if reproducible — retry countdown displays and resets when a new retry value arrives (if not reproducible, verify `useRetryCountdown` via the component's tests or a temporary story); confirm the StartupWizard overlay's EntitySelect still works (highlight reset while typing)
